"""Tests for the CrestronZone media_player entity."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.media_player import MediaPlayerState

from custom_components.crestron.const import SOURCES
from custom_components.crestron.hub import CrestronHub
from custom_components.crestron.media_player import CrestronZone


def _make_hub(zone_data: dict | None = None) -> MagicMock:
    hub = MagicMock(spec=CrestronHub)
    hub.host = "crestron"
    hub.port = 2000
    hub.zones = ["KITCHEN"]
    hub.command = AsyncMock()
    hub.coordinator = MagicMock()
    hub.coordinator.data = {"KITCHEN": zone_data} if zone_data is not None else {}
    hub.coordinator.last_update_success = True
    hub.coordinator.async_request_refresh = AsyncMock()
    hub.coordinator.async_add_listener = MagicMock()
    return hub


def test_state_on() -> None:
    zone = CrestronZone(_make_hub({"power": "KITCHEN POWER ON"}), "KITCHEN")
    assert zone.state == MediaPlayerState.ON


def test_state_off() -> None:
    zone = CrestronZone(_make_hub({"power": "KITCHEN POWER OFF"}), "KITCHEN")
    assert zone.state == MediaPlayerState.OFF


def test_state_none_when_power_missing() -> None:
    zone = CrestronZone(_make_hub({}), "KITCHEN")
    assert zone.state is None


def test_volume_level() -> None:
    zone = CrestronZone(_make_hub({"volume": 40}), "KITCHEN")
    assert zone.volume_level == 0.4


def test_volume_level_clamped() -> None:
    zone = CrestronZone(_make_hub({"volume": 150}), "KITCHEN")
    assert zone.volume_level == 1.0


def test_source_reverse_lookup() -> None:
    zone = CrestronZone(_make_hub({"source": "CHROMECAST"}), "KITCHEN")
    assert zone.source == "Chromecast"


def test_source_unknown_returns_none() -> None:
    zone = CrestronZone(_make_hub({"source": "BOGUS"}), "KITCHEN")
    assert zone.source is None


def test_source_list_matches_const() -> None:
    zone = CrestronZone(_make_hub({}), "KITCHEN")
    assert zone.source_list == sorted(SOURCES.keys())


def test_unique_id_and_device_info() -> None:
    zone = CrestronZone(_make_hub({}), "KITCHEN")
    assert zone.unique_id == "crestron:2000:KITCHEN"
    assert zone.name == "KITCHEN"


async def test_async_turn_on_sends_command() -> None:
    hub = _make_hub({})
    zone = CrestronZone(hub, "KITCHEN")
    await zone.async_turn_on()
    hub.command.assert_awaited_once_with("KITCHEN ON")


async def test_async_turn_off_sends_command() -> None:
    hub = _make_hub({})
    zone = CrestronZone(hub, "KITCHEN")
    await zone.async_turn_off()
    hub.command.assert_awaited_once_with("KITCHEN OFF")


async def test_async_set_volume_level_rounds_to_percent() -> None:
    hub = _make_hub({})
    zone = CrestronZone(hub, "KITCHEN")
    await zone.async_set_volume_level(0.37)
    hub.command.assert_awaited_once_with("KITCHEN VOLUME SET 37")


async def test_async_volume_up_and_down() -> None:
    hub = _make_hub({})
    zone = CrestronZone(hub, "KITCHEN")
    await zone.async_volume_up()
    await zone.async_volume_down()
    assert [c.args[0] for c in hub.command.await_args_list] == [
        "KITCHEN VOLUME UP",
        "KITCHEN VOLUME DOWN",
    ]


async def test_async_select_source_maps_to_code() -> None:
    hub = _make_hub({})
    zone = CrestronZone(hub, "KITCHEN")
    await zone.async_select_source("Chromecast")
    hub.command.assert_awaited_once_with("KITCHEN CHROMECAST")


async def test_async_select_unknown_source_is_noop() -> None:
    hub = _make_hub({})
    zone = CrestronZone(hub, "KITCHEN")
    await zone.async_select_source("Bogus")
    hub.command.assert_not_awaited()
