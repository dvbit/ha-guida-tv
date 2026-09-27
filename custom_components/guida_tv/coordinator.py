"""Coordinator: scarica canali + guida, li mette in cache e li aggiorna.

Riferimenti alla specifica (SPEC.md):
- §2 Fonte unica guidatv.org, scrape
- §3 Guida da ieri a dopodomani
- §4 Refresh 1×/giorno a orario configurabile + servizio manuale; richieste
     distanziate da una pausa configurabile
- §7 Logging su tutti i livelli
- §8 Persistenza: la guida sopravvive al riavvio (Store su disco)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    BASE_URL,
    CHANNELS_PATH,
    CONF_CATEGORIES,
    CONF_DOWNLOAD_LOGOS,
    CONF_INCLUDE_YESTERDAY,
    CONF_REQUEST_DELAY,
    CONF_UPDATE_HOUR,
    CONF_UPDATE_MINUTE,
    DAY_PATHS,
    DEFAULT_DOWNLOAD_LOGOS,
    DEFAULT_INCLUDE_YESTERDAY,
    DEFAULT_REQUEST_DELAY,
    DEFAULT_UPDATE_HOUR,
    DEFAULT_UPDATE_MINUTE,
    HTTP_TIMEOUT,
    LOGO_SUBDIR,
    LOGO_URL_BASE,
    STORAGE_KEY,
    STORAGE_VERSION,
    USER_AGENT,
)
from .scraper import (
    logo_filename,
    logo_source_url,
    parse_channels,
    parse_detail_category,
    parse_programs,
    sanitize_slug,
)

_LOGGER = logging.getLogger(__name__)


class GuidaTvCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Gestisce fetch, cache e programmazione del refresh giornaliero."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Inizializza il coordinator.

        Non impostiamo update_interval: il refresh è pilotato da un trigger
        orario giornaliero (SPEC §4), non da un polling periodico.
        """
        super().__init__(
            hass,
            _LOGGER,
            name="Guida TV",
            update_interval=None,  # refresh giornaliero a orario fisso (SPEC §4)
        )
        self.entry = entry
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._unsub_daily = None
        # Struttura dati: {"channels": [...], "programs": {slug: [prog,...]},
        #                  "last_update": iso, "errors": [str,...]}
        self.data = {
            "channels": [],
            "programs": {},
            "last_update": None,
            "errors": [],
        }

    # -- Opzioni correnti (con default) --------------------------------------
    @property
    def _delay(self) -> float:
        return self.entry.options.get(CONF_REQUEST_DELAY, DEFAULT_REQUEST_DELAY)

    @property
    def _categories(self) -> list[str] | None:
        # None = tutte le categorie (SPEC §5 default: tutte)
        return self.entry.options.get(CONF_CATEGORIES) or None

    @property
    def _include_yesterday(self) -> bool:
        return self.entry.options.get(
            CONF_INCLUDE_YESTERDAY, DEFAULT_INCLUDE_YESTERDAY
        )

    @property
    def _download_logos(self) -> bool:
        return self.entry.options.get(CONF_DOWNLOAD_LOGOS, DEFAULT_DOWNLOAD_LOGOS)

    # -- Ciclo di vita --------------------------------------------------------
    async def async_prepare(self) -> None:
        """Carica la cache da disco e programma il refresh giornaliero.

        Se la cache esiste, i sensori partono subito popolati anche prima del
        primo scrape (SPEC §8: la guida sopravvive al riavvio).
        """
        cached = await self._store.async_load()
        if cached:
            self.data = cached
            _LOGGER.info(
                "Cache Guida TV caricata: %d canali, aggiornata al %s",
                len(cached.get("channels", [])),
                cached.get("last_update"),
            )
        else:
            _LOGGER.info("Nessuna cache Guida TV: primo scrape necessario")

        self._schedule_daily_refresh()

    @callback
    def _schedule_daily_refresh(self) -> None:
        """Programma (o riprogramma) il refresh all'orario configurato (SPEC §4)."""
        if self._unsub_daily is not None:
            self._unsub_daily()

        hour = self.entry.options.get(CONF_UPDATE_HOUR, DEFAULT_UPDATE_HOUR)
        minute = self.entry.options.get(CONF_UPDATE_MINUTE, DEFAULT_UPDATE_MINUTE)

        self._unsub_daily = async_track_time_change(
            self.hass,
            self._handle_daily_refresh,
            hour=hour,
            minute=minute,
            second=0,
        )
        _LOGGER.info("Refresh giornaliero Guida TV programmato alle %02d:%02d", hour, minute)

    @callback
    def _handle_daily_refresh(self, now: datetime) -> None:
        """Callback del trigger orario: avvia un refresh."""
        _LOGGER.info("Avvio refresh giornaliero Guida TV (%s)", now)
        self.hass.async_create_task(self.async_request_refresh())

    async def async_shutdown(self) -> None:
        """Annulla il trigger orario allo scaricamento dell'entry."""
        if self._unsub_daily is not None:
            self._unsub_daily()
            self._unsub_daily = None

    # -- Fetch di rete --------------------------------------------------------
    async def _fetch(self, session: aiohttp.ClientSession, path: str) -> str | None:
        """Scarica una pagina; ritorna il testo o None in caso di errore."""
        url = f"{BASE_URL}{path}"
        try:
            async with session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("HTTP %s per %s", resp.status, url)
                    return None
                text = await resp.text()
                _LOGGER.debug("Scaricata %s (%d byte)", url, len(text))
                return text
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.warning("Errore scaricando %s: %s", url, err)
            return None

    async def _download_logo(
        self,
        session: aiohttp.ClientSession,
        channel: dict[str, Any],
        logo_dir: str,
    ) -> str | None:
        """Scarica il logo del canale in locale e ritorna l'URL /local, o None.

        Scarica il PNG sorgente (non il proxy Next) solo se non già presente su
        disco (SPEC §6). Un fallimento non blocca il refresh: logga WARNING e
        ritorna comunque l'URL /local se il file esiste, altrimenti None.
        """
        source = logo_source_url(channel.get("logo"))
        if not source:
            return None
        safe = sanitize_slug(channel["slug"])
        filename = logo_filename(source, safe)
        dest = os.path.join(logo_dir, filename)
        public_url = f"{LOGO_URL_BASE}/{filename}"

        # Se già presente, non riscaricare (SPEC §6: solo mancanti)
        if await self.hass.async_add_executor_job(os.path.exists, dest):
            return public_url

        try:
            async with session.get(
                source,
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Logo HTTP %s per %s", resp.status, source)
                    return None
                data = await resp.read()
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.warning("Errore scaricando il logo %s: %s", source, err)
            return None

        try:
            await self.hass.async_add_executor_job(_write_bytes, dest, data)
        except OSError as err:
            _LOGGER.warning("Impossibile salvare il logo %s: %s", dest, err)
            return None

        _LOGGER.debug("Logo salvato: %s (%d byte)", dest, len(data))
        return public_url

    async def _async_update_data(self) -> dict[str, Any]:
        """Esegue lo scrape completo: canali + guida per ogni canale.

        Chiamato da DataUpdateCoordinator sia al primo refresh sia dai trigger
        (giornaliero o servizio manuale). In caso di fallimento totale del primo
        scrape solleva UpdateFailed; se esiste una cache, la conserva (SPEC §8).
        """
        session = async_get_clientsession(self.hass)
        errors: list[str] = []

        # 1) Lista canali (SPEC §2) --------------------------------------------
        channels_html = await self._fetch(session, CHANNELS_PATH)
        if channels_html is None:
            errors.append("Impossibile scaricare la lista canali")
            if self.data.get("channels"):
                _LOGGER.warning("Lista canali non scaricata: mantengo la cache")
                self.data["errors"] = errors
                return self.data
            raise UpdateFailed("Lista canali non disponibile e nessuna cache")

        channels = parse_channels(channels_html)
        if not channels:
            errors.append("Nessun canale estratto dalla pagina /canali")
            raise UpdateFailed("Parsing canali fallito")

        # 2) Giorni da scaricare (SPEC §3) ------------------------------------
        day_keys = list(DAY_PATHS.keys())
        if not self._include_yesterday:
            day_keys = [d for d in day_keys if d != "ieri"]

        # Prepara la cartella dei loghi una sola volta (SPEC §6)
        download_logos = self._download_logos
        logo_dir = os.path.join(
            self.hass.config.config_dir, "www", *LOGO_SUBDIR.split("/")
        )
        if download_logos:
            try:
                await self.hass.async_add_executor_job(
                    lambda: os.makedirs(logo_dir, exist_ok=True)
                )
            except OSError as err:
                errors.append(f"Cartella loghi non creabile: {err}")
                _LOGGER.warning("Impossibile creare %s: %s", logo_dir, err)
                download_logos = False

        # 3) Guida + categoria + logo per canale (SPEC §3, §4, §6) ------------
        programs: dict[str, list[dict[str, Any]]] = {}
        delay = self._delay
        for channel in channels:
            slug = channel["slug"]
            merged: list[dict[str, Any]] = []
            for day in day_keys:
                path = f"{CHANNELS_PATH}/{slug}{DAY_PATHS[day]}"
                await asyncio.sleep(delay)  # SPEC §4: non sovraccaricare il sito
                page = await self._fetch(session, path)
                if page is None:
                    errors.append(f"Guida non scaricata: {slug}/{day}")
                    continue
                merged.extend(parse_programs(page))
                # La categoria reale è nella pagina dettaglio "oggi" (SPEC §6):
                # la estraiamo dalla stessa pagina già scaricata, senza richieste extra.
                if day == "oggi" and not channel.get("category"):
                    channel["category"] = parse_detail_category(page)

            # Deduplica per (start, title) e ordina per orario di inizio
            seen: set[tuple] = set()
            unique: list[dict[str, Any]] = []
            for prog in sorted(merged, key=lambda p: p.get("start") or ""):
                key = (prog.get("start"), prog.get("title"))
                if key not in seen:
                    seen.add(key)
                    unique.append(prog)
            programs[slug] = unique

            # Logo locale (SPEC §6): scarica solo se abilitato e non già presente
            if download_logos:
                local = await self._download_logo(session, channel, logo_dir)
                if local:
                    channel["logo_local"] = local

        # Filtro categorie (SPEC §5): applicato ORA che la categoria è nota.
        # None = tutte. I programmi dei canali esclusi non vengono rimossi qui
        # perché già scaricati; l'esclusione riguarda le entità esposte.
        cats = self._categories
        if cats:
            before = len(channels)
            channels = [c for c in channels if c.get("category") in cats]
            _LOGGER.debug("Filtro categorie: %d -> %d canali", before, len(channels))

        result = {
            "channels": channels,
            "programs": programs,
            "last_update": dt_util.utcnow().isoformat(),
            "errors": errors,
        }

        # 4) Persistenza su disco (SPEC §8) -----------------------------------
        await self._store.async_save(result)

        total_progs = sum(len(v) for v in programs.values())
        _LOGGER.info(
            "Refresh Guida TV completato: %d canali, %d programmi, %d errori",
            len(channels),
            total_progs,
            len(errors),
        )
        return result


def _write_bytes(path: str, data: bytes) -> None:
    """Scrive i byte del logo su disco (eseguito in executor, non nel loop)."""
    with open(path, "wb") as handle:
        handle.write(data)
