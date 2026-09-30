"""Costanti dell'integrazione Guida TV.

Riferimenti alla specifica (SPEC.md):
- §2 Fonte: guidatv.org, scrape unico
- §3 Guida: da ieri a dopodomani (il sito non espone 7 giorni)
- §4 Aggiornamento: 1×/giorno a orario configurabile + servizio refresh
- §6 Entità: sensore lista canali, un sensore per canale, diagnostico
"""

from __future__ import annotations

from typing import Final

# Dominio dell'integrazione (deve combaciare con manifest.json e le cartelle)
DOMAIN: Final = "guida_tv"

# --- Sorgente dati (SPEC §2) -------------------------------------------------
BASE_URL: Final = "https://guidatv.org"
CHANNELS_PATH: Final = "/canali"
# Pagine giorno servite dal sito: la base è "oggi", i suffissi sono i giorni
# aggiuntivi. Il sito NON espone oltre "dopodomani" (SPEC §3).
DAY_PATHS: Final = {
    "ieri": "/ieri",
    "oggi": "",
    "domani": "/domani",
    "dopodomani": "/dopodomani",
}
# User-Agent realistico: guidatv.org è un'app Next.js che rifiuta client anonimi.
USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# --- Chiavi di configurazione (config_flow / options) (SPEC §4, §5) ----------
CONF_UPDATE_HOUR: Final = "update_hour"          # ora del refresh giornaliero
CONF_UPDATE_MINUTE: Final = "update_minute"      # minuto del refresh giornaliero
CONF_REQUEST_DELAY: Final = "request_delay"      # pausa tra richieste (s)
CONF_CATEGORIES: Final = "categories"            # categorie canali da includere
CONF_INCLUDE_YESTERDAY: Final = "include_yesterday"  # includere "ieri" nella guida
CONF_DOWNLOAD_LOGOS: Final = "download_logos"    # scaricare i loghi in locale
CONF_SELECTED_CHANNELS: Final = "selected_channels"  # slug dei canali da scaricare

# --- Valori di default (SPEC §4) ---------------------------------------------
DEFAULT_UPDATE_HOUR: Final = 5
DEFAULT_UPDATE_MINUTE: Final = 0
DEFAULT_REQUEST_DELAY: Final = 1.0   # secondi, per non sovraccaricare il sito
DEFAULT_INCLUDE_YESTERDAY: Final = True
DEFAULT_DOWNLOAD_LOGOS: Final = True

# Loghi locali (SPEC §6): salvati sotto /config/www così HA li serve su /local
# www è la cartella statica di HA; il primo uso di /local richiede un riavvio.
LOGO_SUBDIR: Final = "guida_tv/loghi"          # relativo a <config>/www/
LOGO_URL_BASE: Final = "/local/guida_tv/loghi"  # URL pubblico servito da HA
ATTR_LOGO_LOCAL: Final = "logo_local"

# Timeout per singola richiesta HTTP
HTTP_TIMEOUT: Final = 30

# --- Attributi entità (SPEC §6) ----------------------------------------------
ATTR_CHANNELS: Final = "channels"
ATTR_NUMBER: Final = "number"
ATTR_LOGO: Final = "logo"
ATTR_CATEGORY: Final = "category"
ATTR_START: Final = "start"
ATTR_STOP: Final = "stop"
ATTR_PROGRESS: Final = "progress"
ATTR_IMAGE: Final = "image"
ATTR_GENRE: Final = "genre"
ATTR_DESCRIPTION: Final = "description"
ATTR_NEXT_TITLE: Final = "next_title"
ATTR_NEXT_START: Final = "next_start"
ATTR_LAST_UPDATE: Final = "last_update"
ATTR_ERRORS: Final = "errors"
ATTR_CHANNEL_COUNT: Final = "channel_count"
ATTR_PROGRAM_COUNT: Final = "program_count"

# --- Servizi (SPEC §5) -------------------------------------------------------
SERVICE_REFRESH: Final = "refresh"
SERVICE_GET_SCHEDULE: Final = "get_schedule"
SERVICE_GET_CHANNELS: Final = "get_channels"
ATTR_CHANNEL: Final = "channel"
ATTR_DATE: Final = "date"
ATTR_TIME_FROM: Final = "time_from"
ATTR_TIME_TO: Final = "time_to"

# --- Storage (SPEC §8: la guida sopravvive al riavvio) -----------------------
STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = f"{DOMAIN}_cache"

# Prefisso stabile per gli unique_id dei sensori
UNIQUE_ID_PREFIX: Final = DOMAIN
