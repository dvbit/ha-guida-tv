"""Config flow e Options flow per Guida TV.

Riferimenti alla specifica (SPEC.md §4, §5):
- Configurazione interamente da UI, una sola config entry.
- Opzioni: orario refresh giornaliero, pausa tra richieste, includere "ieri".
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DOWNLOAD_LOGOS,
    CONF_INCLUDE_YESTERDAY,
    CONF_REQUEST_DELAY,
    CONF_UPDATE_HOUR,
    CONF_UPDATE_MINUTE,
    DEFAULT_DOWNLOAD_LOGOS,
    DEFAULT_INCLUDE_YESTERDAY,
    DEFAULT_REQUEST_DELAY,
    DEFAULT_UPDATE_HOUR,
    DEFAULT_UPDATE_MINUTE,
    DOMAIN,
)


class GuidaTvConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gestisce l'aggiunta dell'integrazione (una sola entry)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Passo iniziale: entry unica, nessun parametro obbligatorio."""
        # Una sola config entry (SPEC §1 analogo: hub singolo)
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Guida TV", data={})

        # Nessun dato richiesto: conferma e crea
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GuidaTvOptionsFlow:
        """Ritorna l'options flow."""
        return GuidaTvOptionsFlow()


class GuidaTvOptionsFlow(OptionsFlow):
    """Opzioni configurabili da UI (SPEC §4, §5).

    Nota (learnings): non sovrascrivere self.config_entry in __init__.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Form opzioni."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

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
