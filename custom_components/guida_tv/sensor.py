"""Entità sensore della Guida TV.

Riferimenti alla specifica (SPEC.md §6 Entità):
- sensor.guida_tv_canali: stato = numero canali; attributo channels = lista
  {number, name, slug, logo, category} ordinata per numero.
- un sensore per canale: stato = titolo in onda ora; attributi = numero, logo,
  inizio, fine, avanzamento %, immagine, genere, programma successivo. Si aggiorna
  al cambio programma senza polling.
- sensore diagnostico: stato/errori dell'ultimo aggiornamento.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL, EntityCategory, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CATEGORY,
    ATTR_CHANNEL_COUNT,
    ATTR_CHANNELS,
    ATTR_DESCRIPTION,
    ATTR_ERRORS,
    ATTR_GENRE,
    ATTR_IMAGE,
    ATTR_LAST_UPDATE,
    ATTR_LOGO,
    ATTR_LOGO_LOCAL,
    ATTR_NEXT_START,
    ATTR_NEXT_TITLE,
    ATTR_NUMBER,
    ATTR_PROGRAM_COUNT,
    ATTR_PROGRESS,
    ATTR_START,
    ATTR_STOP,
    DOMAIN,
    UNIQUE_ID_PREFIX,
)
from .coordinator import GuidaTvCoordinator
from .scraper import sanitize_slug, sort_channels

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crea le entità sensore; i sensori per-canale sono sincronizzati dinamicamente.

    I sensori riepilogativo e diagnostico esistono sempre. I sensori per-canale
    dipendono dalla selezione dell'utente (SPEC: solo i canali scelti in
    setup/reconfigure) e dai canali scaricati: vengono aggiunti quando compaiono
    e RIMOSSI (entità + device) quando un canale viene deselezionato o non è più
    disponibile. La sincronizzazione avviene a ogni update del coordinator.
    """
    coordinator: GuidaTvCoordinator = entry.runtime_data

    async_add_entities(
        [
            GuidaTvChannelsSensor(coordinator),
            GuidaTvDiagnosticSensor(coordinator),
        ]
    )

    # Slug (originali) aggiunti in QUESTA sessione, per evitare ricreazioni
    # ripetute a ogni update; la rimozione invece ispeziona sempre il registro
    # (non solo questo set), così funziona anche subito dopo un reload, quando
    # known_slugs riparte vuoto ma il registro conserva le entità precedenti.
    known_slugs: set[str] = set()

    @callback
    def _remove_stale_channels(current_safe_slugs: set[str]) -> None:
        """Rimuove entità e device dei canali non più selezionati/disponibili.

        Ispeziona il registro (non known_slugs) confrontando lo slug sanitizzato
        estratto dall'unique_id con quelli attualmente attesi (SPEC: deselezione
        = rimozione pulita, non semplice sospensione dell'aggiornamento).
        """
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)
        prefix = f"{UNIQUE_ID_PREFIX}_"
        reserved = {"channels", "diagnostic"}

        for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            if reg_entry.domain != Platform.SENSOR or reg_entry.platform != DOMAIN:
                continue
            if not reg_entry.unique_id.startswith(prefix):
                continue
            safe_slug = reg_entry.unique_id[len(prefix):]
            if safe_slug in reserved or safe_slug in current_safe_slugs:
                continue

            _LOGGER.info("Rimuovo sensore canale non più selezionato: %s", reg_entry.entity_id)
            ent_reg.async_remove(reg_entry.entity_id)
            if reg_entry.device_id:
                # Rimuovi il device solo se non gli restano altre entità
                remaining = er.async_entries_for_device(
                    ent_reg, reg_entry.device_id, include_disabled_entities=True
                )
                if not remaining:
                    dev_reg.async_remove_device(reg_entry.device_id)

    @callback
    def _sync_channels() -> None:
        """Aggiunge i sensori mancanti e rimuove quelli non più selezionati.

        La costruzione di ogni sensore è isolata: se un canale genera un errore
        (es. dato inatteso), viene loggato e saltato senza compromettere gli altri
        né annullare l'intero lotto.
        """
        available = coordinator.data.get("channels", []) if coordinator.data else []
        _LOGGER.debug(
            "Sync canali: %d canali disponibili, %d già noti in sessione",
            len(available),
            len(known_slugs),
        )
        current_safe_slugs: set[str] = set()
        new_entities: list[SensorEntity] = []
        for channel in available:
            slug = channel.get("slug")
            if not slug:
                continue
            current_safe_slugs.add(sanitize_slug(slug))
            if slug in known_slugs:
                continue
            try:
                entity = GuidaTvChannelSensor(coordinator, channel)
            except Exception:  # noqa: BLE001 - un canale non deve bloccare gli altri
                _LOGGER.exception("Creazione sensore fallita per il canale %s", slug)
                continue
            known_slugs.add(slug)
            new_entities.append(entity)
        if new_entities:
            _LOGGER.info("Aggiunti %d nuovi sensori canale", len(new_entities))
            async_add_entities(new_entities)

        _remove_stale_channels(current_safe_slugs)

    # Sincronizza subito con quanto già disponibile (da cache), poi a ogni refresh
    _sync_channels()
    entry.async_on_unload(coordinator.async_add_listener(_sync_channels))


def _parse_iso(value: str | None) -> datetime | None:
    """Converte una stringa ISO 8601 in datetime aware, o None."""
    if not value:
        return None
    try:
        return dt_util.parse_datetime(value)
    except (ValueError, TypeError):
        return None


class GuidaTvChannelsSensor(CoordinatorEntity[GuidaTvCoordinator], SensorEntity):
    """Sensore riepilogativo: lista canali per Astrion (SPEC §6)."""

    _attr_has_entity_name = True
    # L'attributo `channels` (148 voci) supera il limite del recorder (16 KB):
    # non registriamo gli attributi di questo sensore nel DB (restano live).
    # La lista completa è comunque disponibile via servizio guida_tv.get_channels.
    _unrecorded_attributes = frozenset({MATCH_ALL})
    # Nome inglese fisso per ID entità stabile (learnings: evitare translation_key
    # sul nome per non generare ID dipendenti dalla lingua alla registrazione).
    _attr_name = "Channels"
    _attr_icon = "mdi:format-list-numbered"

    def __init__(self, coordinator: GuidaTvCoordinator) -> None:
        """Inizializza il sensore lista canali."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{UNIQUE_ID_PREFIX}_channels"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "hub")},
            name="Guida TV",
            manufacturer="guidatv.org",
            entry_type=None,
        )

    @property
    def native_value(self) -> int:
        """Stato = numero di canali."""
        return len(self.coordinator.data.get("channels", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Lista canali ordinata per numero, pronta per la dashboard (SPEC §6)."""
        ordered = sort_channels(self.coordinator.data.get("channels", []))
        return {
            ATTR_CHANNELS: [
                {
                    ATTR_NUMBER: c.get("number"),
                    "name": c.get("name"),
                    "slug": c.get("slug"),
                    ATTR_LOGO: c.get("logo"),
                    ATTR_LOGO_LOCAL: c.get("logo_local"),
                    ATTR_CATEGORY: c.get("category"),
                }
                for c in ordered
            ]
        }


class GuidaTvChannelSensor(CoordinatorEntity[GuidaTvCoordinator], SensorEntity):
    """Sensore "in onda ora" per un singolo canale (SPEC §6).

    Si aggiorna in due modi:
    - quando il coordinator riscarica la guida (CoordinatorEntity);
    - a fine programma, tramite un timer puntuale che ne forza il ricalcolo,
      così lo stato cambia al cambio programma senza polling.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: GuidaTvCoordinator, channel: dict[str, Any]) -> None:
        """Inizializza il sensore in-onda di un canale."""
        super().__init__(coordinator)
        # Slug originale: usato per cercare i programmi nei dati del coordinator.
        self._slug = channel["slug"]
        # Slug sanitizzato: base di unique_id ed entity_id (deve essere valido).
        safe_slug = sanitize_slug(self._slug)
        self._attr_name = channel.get("name") or self._slug
        self._attr_unique_id = f"{UNIQUE_ID_PREFIX}_{safe_slug}"
        self._attr_icon = "mdi:television-classic"
        self._unsub_timer = None
        self._attr_device_info = DeviceInfo(
            # identifiers deve essere stabile e sicuro: usa lo slug sanitizzato
            identifiers={(DOMAIN, safe_slug)},
            name=self._attr_name,
            manufacturer="guidatv.org",
            model=channel.get("category"),
            via_device=(DOMAIN, "hub"),
        )

    # -- Calcolo del programma corrente/successivo ---------------------------
    def _current_and_next(
        self,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Trova (programma in onda ora, programma successivo) per questo canale."""
        now = dt_util.utcnow()
        progs = self.coordinator.data.get("programs", {}).get(self._slug, [])
        current = None
        nxt = None
        for prog in progs:
            start = _parse_iso(prog.get("start"))
            stop = _parse_iso(prog.get("stop"))
            if start is None:
                continue
            if stop is not None and start <= now < stop:
                current = prog
            elif start > now and nxt is None:
                nxt = prog
        return current, nxt

    @property
    def native_value(self) -> str | None:
        """Stato = titolo del programma in onda (None se sconosciuto)."""
        current, _ = self._current_and_next()
        return current.get("title") if current else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributi ricchi per la dashboard (SPEC §6)."""
        current, nxt = self._current_and_next()
        channel = next(
            (
                c
                for c in self.coordinator.data.get("channels", [])
                if c["slug"] == self._slug
            ),
            {},
        )
        attrs: dict[str, Any] = {
            ATTR_NUMBER: channel.get("number"),
            ATTR_LOGO: channel.get("logo"),
            ATTR_LOGO_LOCAL: channel.get("logo_local"),
            ATTR_CATEGORY: channel.get("category"),
        }
        if current:
            start = _parse_iso(current.get("start"))
            stop = _parse_iso(current.get("stop"))
            progress = None
            if start and stop and stop > start:
                now = dt_util.utcnow()
                pct = (now - start) / (stop - start) * 100
                progress = round(max(0.0, min(100.0, pct)), 1)
            attrs.update(
                {
                    ATTR_START: current.get("start"),
                    ATTR_STOP: current.get("stop"),
                    ATTR_PROGRESS: progress,
                    ATTR_IMAGE: current.get("image"),
                    ATTR_GENRE: current.get("genre"),
                    ATTR_DESCRIPTION: current.get("description"),
                }
            )
        if nxt:
            attrs[ATTR_NEXT_TITLE] = nxt.get("title")
            attrs[ATTR_NEXT_START] = nxt.get("start")
        return attrs

    # -- Aggiornamento al cambio programma (senza polling) -------------------
    @callback
    def _schedule_next_change(self) -> None:
        """Programma un risveglio a fine del programma corrente."""
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

        current, nxt = self._current_and_next()
        # Prossimo istante di cambio: fine del corrente o inizio del successivo
        target = None
        if current:
            target = _parse_iso(current.get("stop"))
        elif nxt:
            target = _parse_iso(nxt.get("start"))

        if target is not None and target > dt_util.utcnow():
            self._unsub_timer = async_track_point_in_time(
                self.hass, self._handle_program_change, target
            )
            _LOGGER.debug("Canale %s: prossimo cambio programma alle %s", self._slug, target)

    @callback
    def _handle_program_change(self, now: datetime) -> None:
        """A fine programma: aggiorna lo stato e riprogramma il prossimo cambio."""
        self._unsub_timer = None
        self.async_write_ha_state()
        self._schedule_next_change()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Alla riscrittura della guida, aggiorna e riprogramma il timer."""
        self.async_write_ha_state()
        self._schedule_next_change()

    async def async_added_to_hass(self) -> None:
        """All'aggiunta, avvia il timer di cambio programma."""
        await super().async_added_to_hass()
        self._schedule_next_change()

    async def async_will_remove_from_hass(self) -> None:
        """Alla rimozione, annulla il timer."""
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None
        await super().async_will_remove_from_hass()


class GuidaTvDiagnosticSensor(CoordinatorEntity[GuidaTvCoordinator], SensorEntity):
    """Sensore diagnostico: esito dell'ultimo aggiornamento (SPEC §6, §7)."""

    _attr_has_entity_name = True
    _attr_name = "Last update"
    _attr_icon = "mdi:update"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GuidaTvCoordinator) -> None:
        """Inizializza il sensore diagnostico."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{UNIQUE_ID_PREFIX}_diagnostic"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, "hub")})

    @property
    def native_value(self) -> str:
        """Stato = 'ok' o 'errori' a seconda dell'ultimo scrape."""
        errors = self.coordinator.data.get("errors", [])
        return "errori" if errors else "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributi diagnostici: ultimo aggiornamento, conteggi, errori."""
        data = self.coordinator.data
        return {
            ATTR_LAST_UPDATE: data.get("last_update"),
            ATTR_CHANNEL_COUNT: len(data.get("channels", [])),
            ATTR_PROGRAM_COUNT: sum(
                len(v) for v in data.get("programs", {}).values()
            ),
            ATTR_ERRORS: data.get("errors", []),
        }
