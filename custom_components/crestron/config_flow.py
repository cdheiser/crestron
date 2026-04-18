"""Config flow for the Crestron integration."""
from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
import voluptuous as vol

from .const import (
    CONF_REBOOT_PORT,
    CONF_ZONES,
    DEFAULT_PORT,
    DEFAULT_REBOOT_PORT,
    DOMAIN,
)


def _parse_zones(raw: str) -> list[str]:
    return [z.strip() for z in raw.split(",") if z.strip()]


class CrestronConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """UI and YAML import flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            zones = _parse_zones(user_input[CONF_ZONES])
            if not zones:
                errors[CONF_ZONES] = "no_zones"
            else:
                host = user_input[CONF_HOST]
                port = user_input[CONF_PORT]
                unique_id = f"{host}:{port}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Crestron ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_REBOOT_PORT: user_input[CONF_REBOOT_PORT],
                        CONF_ZONES: zones,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Required(CONF_REBOOT_PORT, default=DEFAULT_REBOOT_PORT): int,
                vol.Required(CONF_ZONES, default="KITCHEN, DECK, PATIO"): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_import(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        """Import a single YAML platform entry, merging into an existing entry if present."""
        host = user_input[CONF_HOST]
        port = int(user_input.get(CONF_PORT, DEFAULT_PORT))
        name = user_input[CONF_NAME]
        unique_id = f"{host}:{port}"

        for entry in self._async_current_entries(include_ignore=False):
            if entry.unique_id != unique_id:
                continue
            zones = list(entry.data.get(CONF_ZONES, []))
            if name in zones:
                return self.async_abort(reason="already_configured")
            self.hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_ZONES: [*zones, name]},
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(entry.entry_id)
            )
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Crestron ({host})",
            data={
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_REBOOT_PORT: DEFAULT_REBOOT_PORT,
                CONF_ZONES: [name],
            },
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CrestronOptionsFlow:
        return CrestronOptionsFlow(config_entry)


class CrestronOptionsFlow(config_entries.OptionsFlow):
    """Edit zones and reboot port after setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        data = self._entry.data
        if user_input is not None:
            zones = _parse_zones(user_input[CONF_ZONES])
            if not zones:
                errors[CONF_ZONES] = "no_zones"
            else:
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    data={
                        **data,
                        CONF_REBOOT_PORT: user_input[CONF_REBOOT_PORT],
                        CONF_ZONES: zones,
                    },
                )
                return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_REBOOT_PORT,
                    default=data.get(CONF_REBOOT_PORT, DEFAULT_REBOOT_PORT),
                ): int,
                vol.Required(
                    CONF_ZONES,
                    default=", ".join(data.get(CONF_ZONES, [])),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
