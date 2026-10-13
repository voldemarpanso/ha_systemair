"""Config flow for Systemair integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import httpx
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.httpx_client import create_async_httpx_client
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode

from .const import (
    CONF_SCAN_INTERVAL,
    DOMAIN,
    HA_SC_CLOUD_PUSH,
    HA_SC_CLOUD_PUSH_DEFAULT,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SCAN_INTERVAL,
)
from .saveconnect import SaveConnect

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema({
    vol.Required(CONF_EMAIL): str,
    vol.Required(CONF_PASSWORD): str,
    vol.Optional(HA_SC_CLOUD_PUSH, default=HA_SC_CLOUD_PUSH_DEFAULT): bool,
})


async def validate_login(hass: HomeAssistant, email: str, password: str) -> str | None:
    """Try to log in; returns an error key or None."""
    api = SaveConnect(email=email, password=password, ws_enabled=False, http_client=create_async_httpx_client(hass))
    try:
        if not await api.login():
            return "invalid_auth"
    except httpx.HTTPError:
        return "cannot_connect"
    except Exception:  # pylint: disable=broad-except
        _LOGGER.exception("Unexpected error during login")
        return "unknown"
    finally:
        await api.close()
    return None


class SystemairConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Systemair."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()
            if not (error := await validate_login(self.hass, user_input[CONF_EMAIL], user_input[CONF_PASSWORD])):
                return self.async_create_entry(title=user_input[CONF_EMAIL], data=user_input)
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input), errors=errors
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            if not (error := await validate_login(self.hass, entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])):
                return self.async_update_reload_and_abort(entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]})
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SystemairOptionsFlow()


class SystemairOptionsFlow(OptionsFlow):

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        cloud_push = options.get(HA_SC_CLOUD_PUSH, self.config_entry.data.get(HA_SC_CLOUD_PUSH, HA_SC_CLOUD_PUSH_DEFAULT))
        scan_interval = options.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL.total_seconds())
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_SCAN_INTERVAL, default=scan_interval): vol.All(
                    NumberSelector(NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL, step=5,
                        unit_of_measurement="s", mode=NumberSelectorMode.BOX,
                    )),
                    vol.Coerce(int),
                ),
                vol.Required(HA_SC_CLOUD_PUSH, default=cloud_push): bool,
            }),
        )
