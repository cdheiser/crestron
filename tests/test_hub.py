"""Unit tests for CrestronHub — connection, retry, and reboot logic."""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.crestron.const import CONF_REBOOT_PORT, CONF_ZONES
from custom_components.crestron.hub import CrestronHub


def _make_entry(zones: list[str] | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain="crestron",
        data={
            CONF_HOST: "crestron",
            CONF_PORT: 2000,
            CONF_REBOOT_PORT: 23,
            CONF_ZONES: zones or ["KITCHEN"],
        },
        unique_id="crestron:2000",
    )


class FakeReader:
    """Minimal asyncio-reader stand-in."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    async def readline(self) -> str:
        if not self._lines:
            return ""  # simulate EOF
        return self._lines.pop(0)

    async def read(self, _n: int = -1) -> str:
        return ""


class FakeWriter:
    """Minimal asyncio-writer stand-in."""

    def __init__(self) -> None:
        self.writes: list[str] = []
        self.closed = False

    def write(self, data: str) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class OpenConnectionStub:
    """Configurable fake for telnetlib3.open_connection."""

    def __init__(self) -> None:
        self.line_queues: dict[int, list[list[str]]] = {}
        self.fail_next: dict[int, int] = {}
        self.calls: list[tuple[str, int]] = []
        self.writers: list[FakeWriter] = []

    def enqueue(self, port: int, lines: list[str]) -> None:
        self.line_queues.setdefault(port, []).append(lines)

    def inject_failures(self, port: int, count: int) -> None:
        self.fail_next[port] = self.fail_next.get(port, 0) + count

    async def __call__(
        self, *, host: str, port: int, **_kwargs: Any
    ) -> tuple[FakeReader, FakeWriter]:
        self.calls.append((host, port))
        if self.fail_next.get(port, 0) > 0:
            self.fail_next[port] -= 1
            raise OSError(f"simulated connect failure: {host}:{port}")
        queue = self.line_queues.get(port, [])
        lines = queue.pop(0) if queue else []
        reader = FakeReader(lines)
        writer = FakeWriter()
        self.writers.append(writer)
        return reader, writer


@pytest.fixture
def open_stub():
    stub = OpenConnectionStub()
    with patch(
        "custom_components.crestron.hub.telnetlib3.open_connection",
        new=stub,
    ):
        yield stub


async def test_request_returns_first_line(
    hass: HomeAssistant, open_stub: OpenConnectionStub
) -> None:
    entry = _make_entry(["KITCHEN"])
    entry.add_to_hass(hass)
    open_stub.enqueue(2000, ["KITCHEN POWER ON\r\n"])

    hub = CrestronHub(hass, entry)
    try:
        result = await hub.request("KITCHEN POWER")
    finally:
        await hub.async_stop()

    assert result == "KITCHEN POWER ON"
    assert open_stub.calls == [("crestron", 2000)]
    assert open_stub.writers[0].writes == ["KITCHEN POWER\r\n"]


async def test_request_retries_once_on_empty_read(
    hass: HomeAssistant, open_stub: OpenConnectionStub
) -> None:
    entry = _make_entry(["KITCHEN"])
    entry.add_to_hass(hass)
    # First connection: empty reader → triggers ConnectionResetError → retry
    open_stub.enqueue(2000, [])
    open_stub.enqueue(2000, ["KITCHEN POWER ON\r\n"])

    hub = CrestronHub(hass, entry)
    try:
        result = await hub.request("KITCHEN POWER")
    finally:
        await hub.async_stop()

    assert result == "KITCHEN POWER ON"
    assert [c[1] for c in open_stub.calls] == [2000, 2000]


async def test_reboot_triggered_on_connect_failure(
    hass: HomeAssistant, open_stub: OpenConnectionStub
) -> None:
    entry = _make_entry(["KITCHEN"])
    entry.add_to_hass(hass)
    open_stub.inject_failures(2000, 2)  # both connect attempts fail

    hub = CrestronHub(hass, entry)
    try:
        with pytest.raises(ConnectionError):
            await hub.request("KITCHEN POWER")
    finally:
        await hub.async_stop()

    audio_calls = [c for c in open_stub.calls if c[1] == 2000]
    reboot_calls = [c for c in open_stub.calls if c[1] == 23]
    assert len(audio_calls) == 2
    assert len(reboot_calls) == 1
    reboot_writer = open_stub.writers[-1]
    assert "reboot" in "".join(reboot_writer.writes).lower()


async def test_reboot_cooldown_suppresses_rapid_retries(
    hass: HomeAssistant, open_stub: OpenConnectionStub
) -> None:
    entry = _make_entry(["KITCHEN"])
    entry.add_to_hass(hass)
    open_stub.inject_failures(2000, 4)  # two failed request cycles (2 attempts each)

    hub = CrestronHub(hass, entry)
    try:
        with pytest.raises(ConnectionError):
            await hub.request("KITCHEN POWER")
        with pytest.raises(ConnectionError):
            await hub.request("KITCHEN POWER")
    finally:
        await hub.async_stop()

    reboot_calls = [c for c in open_stub.calls if c[1] == 23]
    assert len(reboot_calls) == 1  # cooldown silenced the second round


async def test_trigger_reboot_bypasses_cooldown(
    hass: HomeAssistant, open_stub: OpenConnectionStub
) -> None:
    entry = _make_entry(["KITCHEN"])
    entry.add_to_hass(hass)
    open_stub.inject_failures(2000, 2)

    hub = CrestronHub(hass, entry)
    try:
        with pytest.raises(ConnectionError):
            await hub.request("KITCHEN POWER")  # fires one reboot via cooldown-guarded path
        await hub.trigger_reboot()  # manual → should reboot again
    finally:
        await hub.async_stop()

    reboot_calls = [c for c in open_stub.calls if c[1] == 23]
    assert len(reboot_calls) == 2


async def test_command_writes_without_reading(
    hass: HomeAssistant, open_stub: OpenConnectionStub
) -> None:
    entry = _make_entry(["KITCHEN"])
    entry.add_to_hass(hass)
    open_stub.enqueue(2000, [])

    hub = CrestronHub(hass, entry)
    try:
        await hub.command("KITCHEN ON")
    finally:
        await hub.async_stop()

    assert open_stub.writers[0].writes == ["KITCHEN ON\r\n"]


async def test_poll_collects_state_for_all_zones(
    hass: HomeAssistant, open_stub: OpenConnectionStub
) -> None:
    entry = _make_entry(["KITCHEN", "DECK"])
    entry.add_to_hass(hass)
    # DECK is off, so only POWER is queried for it — no VOLUME/SOURCE lines.
    open_stub.enqueue(
        2000,
        [
            "KITCHEN POWER ON\r\n",
            "KITCHEN VOLUME CURRENT 40\r\n",
            "KITCHEN SOURCE CHROMECAST\r\n",
            "DECK POWER OFF\r\n",
        ],
    )

    hub = CrestronHub(hass, entry)
    try:
        data = await hub._async_poll()
    finally:
        await hub.async_stop()

    assert data["KITCHEN"] == {
        "power": "KITCHEN POWER ON",
        "volume": 40,
        "source": "CHROMECAST",
    }
    assert data["DECK"] == {"power": "DECK POWER OFF"}
    # Only 4 lines consumed (3 KITCHEN + 1 DECK POWER); VOLUME/SOURCE skipped for OFF zone.
    assert open_stub.writers[0].writes == [
        "KITCHEN POWER\r\n",
        "KITCHEN VOLUME CHECK\r\n",
        "KITCHEN SOURCE\r\n",
        "DECK POWER\r\n",
    ]
