"""Crestron media player entities."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.media_player import (
    PLATFORM_SCHEMA as MEDIA_PLAYER_PLATFORM_SCHEMA,
)
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import voluptuous as vol

from .const import DEFAULT_PORT, DOMAIN, SOURCES
from .hub import CrestronHub

_LOGGER = logging.getLogger(__name__)

SUPPORT_CRESTRON = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.SELECT_SOURCE
)

PLATFORM_SCHEMA = MEDIA_PLAYER_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Import legacy YAML `media_player: platform: crestron` entries."""
    async_create_issue(
        hass,
        DOMAIN,
        "deprecated_yaml",
        is_fixable=False,
        severity=IssueSeverity.WARNING,
        translation_key="deprecated_yaml",
    )

    # Serialize imports so concurrent YAML platform loads don't race on entry creation.
    lock: asyncio.Lock = hass.data.setdefault(f"{DOMAIN}_import_lock", asyncio.Lock())
    async with lock:
        await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={
                CONF_HOST: config[CONF_HOST],
                CONF_PORT: config.get(CONF_PORT, DEFAULT_PORT),
                CONF_NAME: config[CONF_NAME],
            },
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a media player entity for each configured zone."""
    hub: CrestronHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(CrestronZone(hub, zone) for zone in hub.zones)


class CrestronZone(CoordinatorEntity[Any], MediaPlayerEntity):
    """One audio zone on a Crestron host."""

    _attr_supported_features = SUPPORT_CRESTRON
    _attr_source_list = sorted(SOURCES.keys())

    def __init__(self, hub: CrestronHub, zone: str) -> None:
        super().__init__(hub.coordinator)
        self._hub = hub
        self._zone = zone
        self._attr_name = zone
        self._attr_unique_id = f"{hub.host}:{hub.port}:{zone}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{hub.host}:{hub.port}")},
            name=f"Crestron ({hub.host})",
            manufacturer="Crestron",
            configuration_url=f"http://{hub.host}",
        )
        self._muted = False

    @property
    def _zone_state(self) -> dict[str, Any]:
        data: dict[str, dict[str, Any]] | None = self.coordinator.data
        if not data:
            return {}
        return data.get(self._zone, {})

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and bool(self._zone_state)

    @property
    def state(self) -> MediaPlayerState | None:
        power = self._zone_state.get("power", "")
        if isinstance(power, str):
            if power.endswith("OFF"):
                return MediaPlayerState.OFF
            if power.endswith("ON"):
                return MediaPlayerState.ON
        return None

    @property
    def volume_level(self) -> float | None:
        vol_val = self._zone_state.get("volume")
        if vol_val is None:
            return None
        return max(0.0, min(1.0, float(vol_val) / 100.0))

    @property
    def is_volume_muted(self) -> bool:
        return self._muted

    @property
    def source(self) -> str | None:
        code = self._zone_state.get("source")
        if not code:
            return None
        for pretty, mapped in SOURCES.items():
            if mapped == code:
                return pretty
        return None

    # --- Commands ---------------------------------------------------------

    async def async_turn_on(self) -> None:
        await self._hub.command(f"{self._zone} ON")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self._hub.command(f"{self._zone} OFF")
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        await self._hub.command(f"{self._zone} VOLUME SET {round(volume * 100)}")
        await self.coordinator.async_request_refresh()

    async def async_volume_up(self) -> None:
        await self._hub.command(f"{self._zone} VOLUME UP")
        await self.coordinator.async_request_refresh()

    async def async_volume_down(self) -> None:
        await self._hub.command(f"{self._zone} VOLUME DOWN")
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        await self._hub.command(f"{self._zone} MUTE {'ON' if mute else 'OFF'}")
        self._muted = mute
        self.async_write_ha_state()

    async def async_select_source(self, source: str) -> None:
        code = SOURCES.get(source)
        if code is None:
            _LOGGER.warning("Unknown Crestron source: %s", source)
            return
        await self._hub.command(f"{self._zone} {code}")
        await self.coordinator.async_request_refresh()
