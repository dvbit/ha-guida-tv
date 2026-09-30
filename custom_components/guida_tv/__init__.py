"""Integrazione Guida TV per Home Assistant.

Porta in Home Assistant la lista canali (nome + numerazione, DTT e Sky) e la
programmazione (da ieri a dopodomani) di guidatv.org, per alimentare dashboard
esterne come Astrion.

Riferimenti alla specifica: vedi SPEC.md incluso nel repository.
"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CHANNEL,
    ATTR_DATE,
    ATTR_TIME_FROM,
    ATTR_TIME_TO,
    DOMAIN,
    SERVICE_GET_CHANNELS,
    SERVICE_GET_SCHEDULE,
    SERVICE_REFRESH,
)
from .coordinator import GuidaTvCoordinator
from .scraper import sort_channels

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Schema del servizio get_schedule (SPEC §5)
_GET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CHANNEL): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_DATE): cv.string,       # "YYYY-MM-DD" o "oggi"/"domani"...
        vol.Optional(ATTR_TIME_FROM): cv.string,  # "HH:MM"
        vol.Optional(ATTR_TIME_TO): cv.string,    # "HH:MM"
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura l'integrazione da una config entry."""
    coordinator = GuidaTvCoordinator(hass, entry)

    # Carica la cache e programma il refresh giornaliero (SPEC §4, §8)
    await coordinator.async_prepare()
    # Primo refresh bloccante solo se non c'è cache (serve popolare i canali per
    # creare i sensori). Con cache presente il refresh parte DOPO il setup delle
    # piattaforme, così il listener che aggiunge i sensori canale è già registrato.
    if not coordinator.data.get("channels"):
        await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Ora che sensor.py ha registrato il listener, aggiorna in background se
    # avevamo già una cache (per intercettare canali nuovi/rimossi).
    if coordinator.data.get("channels"):
        hass.async_create_task(coordinator.async_request_refresh())

    _register_services(hass)

    # Ricarica l'integrazione quando cambiano le opzioni (SPEC §5 config da UI)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    _LOGGER.info("Integrazione Guida TV configurata")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Scarica una config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: GuidaTvCoordinator = entry.runtime_data
        await coordinator.async_shutdown()
        # Rimuovi i servizi solo se non restano altre entry
        if not hass.config_entries.async_loaded_entries(DOMAIN):
            hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
            hass.services.async_remove(DOMAIN, SERVICE_GET_SCHEDULE)
            hass.services.async_remove(DOMAIN, SERVICE_GET_CHANNELS)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ricarica l'entry al cambio opzioni (SPEC §5)."""
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    """Registra i servizi refresh e get_schedule (SPEC §5)."""

    async def _handle_refresh(call: ServiceCall) -> None:
        """Forza un refresh immediato di tutte le entry."""
        _LOGGER.info("Servizio guida_tv.refresh invocato")
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            coordinator: GuidaTvCoordinator = entry.runtime_data
            await coordinator.async_request_refresh()

    async def _handle_get_schedule(call: ServiceCall) -> ServiceResponse:
        """Restituisce la programmazione filtrata, riusabile da Astrion (SPEC §5).

        Filtri opzionali: channel (slug o lista), date, time_from, time_to.
        """
        channels_filter = call.data.get(ATTR_CHANNEL)
        date_filter = _resolve_date(call.data.get(ATTR_DATE))
        time_from = call.data.get(ATTR_TIME_FROM)
        time_to = call.data.get(ATTR_TIME_TO)

        result: dict[str, list[dict]] = {}
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            coordinator: GuidaTvCoordinator = entry.runtime_data
            programs = coordinator.data.get("programs", {})
            channels = {c["slug"]: c for c in coordinator.data.get("channels", [])}

            for slug, progs in programs.items():
                if channels_filter and slug not in channels_filter:
                    continue
                filtered = [
                    p
                    for p in progs
                    if _match_filters(p, date_filter, time_from, time_to)
                ]
                if filtered:
                    result[slug] = {
                        "channel": channels.get(slug, {}),
                        "programs": filtered,
                    }

        _LOGGER.debug("get_schedule: %d canali nella risposta", len(result))
        return {"schedule": result}

    async def _handle_get_channels(call: ServiceCall) -> ServiceResponse:
        """Restituisce la lista canali completa, riusabile da Astrion (SPEC §6).

        La stessa lista è nell'attributo `channels` del sensore riepilogativo, ma
        quell'attributo supera il limite del recorder (16 KB) e non viene storicizzato;
        questo servizio la fornisce sempre completa, senza quel limite.
        """
        channels: list[dict] = []
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            coordinator: GuidaTvCoordinator = entry.runtime_data
            channels.extend(coordinator.data.get("channels", []))

        channels = sort_channels(channels)
        _LOGGER.debug("get_channels: %d canali nella risposta", len(channels))
        return {"channels": channels}

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _handle_refresh)
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SCHEDULE,
        _handle_get_schedule,
        schema=_GET_SCHEDULE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_CHANNELS,
        _handle_get_channels,
        supports_response=SupportsResponse.ONLY,
    )


def _resolve_date(value: str | None) -> str | None:
    """Converte 'oggi'/'domani'/'ieri'/'dopodomani' o passa 'YYYY-MM-DD'."""
    if not value:
        return None
    today = dt_util.now().date()
    offsets = {"ieri": -1, "oggi": 0, "domani": 1, "dopodomani": 2}
    if value in offsets:
        from datetime import timedelta

        return (today + timedelta(days=offsets[value])).isoformat()
    return value  # assunto già "YYYY-MM-DD"


def _match_filters(
    prog: dict,
    date_filter: str | None,
    time_from: str | None,
    time_to: str | None,
) -> bool:
    """Verifica se un programma rientra nei filtri data/orario (ora locale)."""
    start = dt_util.parse_datetime(prog.get("start") or "")
    if start is None:
        return False
    start_local = dt_util.as_local(start)

    if date_filter and start_local.date().isoformat() != date_filter:
        return False
    if time_from and start_local.strftime("%H:%M") < time_from:
        return False
    return not (time_to and start_local.strftime("%H:%M") > time_to)
