"""Tests for the Crestron config and options flow."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.crestron.const import CONF_REBOOT_PORT, CONF_ZONES, DOMAIN


@pytest.fixture(autouse=True)
def _skip_real_setup():
    """Don't bring up the telnet hub during flow tests."""
    with patch(
        "custom_components.crestron.async_setup_entry",
        return_value=True,
    ):
        yield


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_HOST: "crestron.local",
            CONF_PORT: 2000,
            CONF_REBOOT_PORT: 23,
            CONF_ZONES: "KITCHEN, DECK, PATIO",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Crestron (crestron.local)"
    assert result["data"][CONF_ZONES] == ["KITCHEN", "DECK", "PATIO"]
    assert result["data"][CONF_PORT] == 2000
    assert result["data"][CONF_REBOOT_PORT] == 23


async def test_user_flow_rejects_empty_zones(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_HOST: "crestron.local",
            CONF_PORT: 2000,
            CONF_REBOOT_PORT: 23,
            CONF_ZONES: "   ,  ",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {CONF_ZONES: "no_zones"}


async def test_user_flow_aborts_on_duplicate(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "crestron.local",
            CONF_PORT: 2000,
            CONF_REBOOT_PORT: 23,
            CONF_ZONES: ["KITCHEN"],
        },
        unique_id="crestron.local:2000",
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_HOST: "crestron.local",
            CONF_PORT: 2000,
            CONF_REBOOT_PORT: 23,
            CONF_ZONES: "KITCHEN",
        },
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_import_creates_new_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={CONF_HOST: "crestron", CONF_PORT: 2000, CONF_NAME: "KITCHEN"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ZONES] == ["KITCHEN"]
    assert result["data"][CONF_REBOOT_PORT] == 23


async def test_import_merges_into_existing_entry(hass: HomeAssistant) -> None:
    existing = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "crestron",
            CONF_PORT: 2000,
            CONF_REBOOT_PORT: 23,
            CONF_ZONES: ["KITCHEN"],
        },
        unique_id="crestron:2000",
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={CONF_HOST: "crestron", CONF_PORT: 2000, CONF_NAME: "DECK"},
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    await hass.async_block_till_done()
    assert existing.data[CONF_ZONES] == ["KITCHEN", "DECK"]


async def test_import_skips_duplicate_zone(hass: HomeAssistant) -> None:
    existing = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "crestron",
            CONF_PORT: 2000,
            CONF_REBOOT_PORT: 23,
            CONF_ZONES: ["KITCHEN"],
        },
        unique_id="crestron:2000",
    )
    existing.add_to_hass(hass)

    await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={CONF_HOST: "crestron", CONF_PORT: 2000, CONF_NAME: "KITCHEN"},
    )
    await hass.async_block_till_done()
    assert existing.data[CONF_ZONES] == ["KITCHEN"]


async def test_options_flow_updates_zones(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "crestron",
            CONF_PORT: 2000,
            CONF_REBOOT_PORT: 23,
            CONF_ZONES: ["KITCHEN"],
        },
        unique_id="crestron:2000",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_REBOOT_PORT: 23, CONF_ZONES: "KITCHEN, DECK, PATIO"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_ZONES] == ["KITCHEN", "DECK", "PATIO"]
