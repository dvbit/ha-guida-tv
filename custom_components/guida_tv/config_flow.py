"""Config flow e Options flow per Guida TV.

Riferimenti alla specifica (SPEC.md §4, §5):
- Configurazione interamente da UI, una sola config entry.
- Opzioni: orario refresh giornaliero, pausa tra richieste, includere "ieri",
  scaricare i loghi, e la SELEZIONE DEI CANALI da scaricare (nuovo, v1.6.0).
- La selezione canali si può cambiare in seguito riconfigurando l'integrazione
  (Options Flow): la lista viene ri-scaricata fresca e preseleziona la scelta
  già salvata (o tutti i canali, se l'entry non aveva mai avuto una selezione).
"""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    BASE_URL,
    CHANNELS_PATH,
    CONF_DOWNLOAD_LOGOS,
    CONF_INCLUDE_YESTERDAY,
    CONF_REQUEST_DELAY,
    CONF_SELECTED_CHANNELS,
    CONF_UPDATE_HOUR,
    CONF_UPDATE_MINUTE,
    DEFAULT_DOWNLOAD_LOGOS,
    DEFAULT_INCLUDE_YESTERDAY,
    DEFAULT_REQUEST_DELAY,
    DEFAULT_UPDATE_HOUR,
    DEFAULT_UPDATE_MINUTE,
    DOMAIN,
    HTTP_TIMEOUT,
    USER_AGENT,
)
from .scraper import channel_choice_label, parse_channels, sort_channels


async def _fetch_channel_choices(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Scarica /canali e ritorna le opzioni pronte per un SelectSelector.

    Una sola richiesta HTTP (SPEC §2), riusata sia dal setup iniziale sia dal
    reconfigure. Solleva aiohttp.ClientError/TimeoutError se il sito non risponde;
    il chiamante decide come presentarlo nel flow.
    """
    session = async_get_clientsession(hass)
    async with session.get(
        f"{BASE_URL}{CHANNELS_PATH}",
        headers={"User-Agent": USER_AGENT},
        timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
    ) as resp:
        resp.raise_for_status()
        html = await resp.text()
    channels = sort_channels(parse_channels(html))
    return [
        selector.SelectOptionDict(value=c["slug"], label=channel_choice_label(c))
        for c in channels
        if c.get("slug")
    ]


class GuidaTvConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gestisce l'aggiunta dell'integrazione (una sola entry)."""

    VERSION = 1

    def __init__(self) -> None:
        """Inizializza lo stato del flow (scelte canali cache tra gli step)."""
        self._channel_choices: list[selector.SelectOptionDict] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Passo iniziale: entry unica, nessun parametro obbligatorio."""
        # Una sola config entry (SPEC §1 analogo: hub singolo)
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return await self.async_step_channels()

        # Nessun dato richiesto: conferma e passa alla scelta canali
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    async def async_step_channels(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Scelta dei canali da scaricare (SPEC: selezione al setup)."""
        if self._channel_choices is None:
            try:
                self._channel_choices = await _fetch_channel_choices(self.hass)
            except (TimeoutError, aiohttp.ClientError):
                return self.async_abort(reason="cannot_connect")

        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input.get(CONF_SELECTED_CHANNELS) or []
            if not selected:
                errors["base"] = "no_channels_selected"
            else:
                return self.async_create_entry(
                    title="Guida TV",
                    data={},
                    options={CONF_SELECTED_CHANNELS: selected},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_SELECTED_CHANNELS, default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=self._channel_choices,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="channels", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GuidaTvOptionsFlow:
        """Ritorna l'options flow."""
        return GuidaTvOptionsFlow()


class GuidaTvOptionsFlow(OptionsFlow):
    """Opzioni configurabili da UI (SPEC §4, §5).

    Nota (learnings): non sovrascrivere self.config_entry in __init__.
    Due step: "init" (impostazioni generali) poi "channels" (selezione canali,
    ri-scaricata fresca e preselezionata con la scelta già salvata).
    """

    def __init__(self) -> None:
        """Inizializza lo stato tra gli step (opzioni generali + scelte canali)."""
        self._pending_options: dict[str, Any] = {}
        self._channel_choices: list[selector.SelectOptionDict] | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Form opzioni generali; al submit passa allo step canali."""
        if user_input is not None:
            self._pending_options = dict(user_input)
            return await self.async_step_channels()

        current = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_HOUR,
                    default=current.get(CONF_UPDATE_HOUR, DEFAULT_UPDATE_HOUR),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=23, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_UPDATE_MINUTE,
                    default=current.get(CONF_UPDATE_MINUTE, DEFAULT_UPDATE_MINUTE),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=59, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_REQUEST_DELAY,
                    default=current.get(CONF_REQUEST_DELAY, DEFAULT_REQUEST_DELAY),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=10.0, step=0.5, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(
                    CONF_INCLUDE_YESTERDAY,
                    default=current.get(
                        CONF_INCLUDE_YESTERDAY, DEFAULT_INCLUDE_YESTERDAY
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_DOWNLOAD_LOGOS,
                    default=current.get(
                        CONF_DOWNLOAD_LOGOS, DEFAULT_DOWNLOAD_LOGOS
                    ),
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_channels(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ri-selezione canali (SPEC: modificabile riconfigurando).

        La lista è ri-scaricata fresca (possono comparire nuovi canali Sky);
        la selezione già salvata è preselezionata. Se l'entry non aveva mai
        avuto una selezione esplicita (creata prima di questa funzionalità),
        preseleziona TUTTI i canali disponibili ora, cosicché confermare senza
        modifiche registra esplicitamente "tutti" (SPEC §5 retrocompatibilità).
        """
        if self._channel_choices is None:
            try:
                self._channel_choices = await _fetch_channel_choices(self.hass)
            except (TimeoutError, aiohttp.ClientError):
                return self.async_abort(reason="cannot_connect")

        current_selection = self.config_entry.options.get(CONF_SELECTED_CHANNELS)
        default_selection = (
            current_selection
            if current_selection is not None
            else [choice["value"] for choice in self._channel_choices]
        )

        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input.get(CONF_SELECTED_CHANNELS) or []
            if not selected:
                errors["base"] = "no_channels_selected"
            else:
                return self.async_create_entry(
                    title="",
                    data={**self._pending_options, CONF_SELECTED_CHANNELS: selected},
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_CHANNELS, default=default_selection
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=self._channel_choices,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="channels", data_schema=schema, errors=errors
        )
