"""Shared Crestron telnet connection and polling coordinator."""
from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import telnetlib3

from .const import (
    COMMAND_TIMEOUT_SECONDS,
    CONF_REBOOT_PORT,
    CONF_ZONES,
    CONNECT_TIMEOUT_SECONDS,
    POLL_INTERVAL_SECONDS,
    REBOOT_COOLDOWN_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class CrestronHub:
    """One connection to one Crestron host, shared across all zones on that host."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.host: str = entry.data[CONF_HOST]
        self.port: int = entry.data[CONF_PORT]
        self.reboot_port: int = entry.data.get(CONF_REBOOT_PORT, 23)
        self.zones: list[str] = list(entry.data[CONF_ZONES])

        self._reader: Any = None
        self._writer: Any = None
        self._io_lock = asyncio.Lock()
        self._last_reboot_monotonic: float = 0.0

        self.coordinator: DataUpdateCoordinator[dict[str, dict[str, Any]]] = (
            DataUpdateCoordinator(
                hass,
                _LOGGER,
                name=f"crestron-{self.host}",
                update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
                update_method=self._async_poll,
            )
        )

    async def async_start(self) -> None:
        """Kick off the first poll."""
        await self.coordinator.async_config_entry_first_refresh()

    async def async_stop(self) -> None:
        """Close the telnet connection."""
        async with self._io_lock:
            await self._close_locked()

    # --- Connection management ---------------------------------------------

    async def _connect_locked(self) -> None:
        _LOGGER.debug("Connecting to Crestron audio %s:%s", self.host, self.port)
        self._reader, self._writer = await asyncio.wait_for(
            telnetlib3.open_connection(
                host=self.host,
                port=self.port,
                encoding="ascii",
                connect_minwait=0.05,
                connect_maxwait=0.2,
            ),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )

    async def _close_locked(self) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is not None:
            with contextlib.suppress(Exception):
                writer.close()

    async def _ensure_connected_locked(self) -> None:
        if self._writer is None or self._reader is None:
            try:
                await self._connect_locked()
            except (TimeoutError, OSError) as exc:
                await self._trigger_reboot()
                raise ConnectionError(
                    f"Cannot connect to {self.host}:{self.port}: {exc}"
                ) from exc

    async def _drain_unsolicited_locked(self) -> None:
        """Consume any bytes sitting in the read buffer from prior commands."""
        reader = self._reader
        if reader is None:
            return
        while True:
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=0.05)
            except TimeoutError:
                return
            except Exception:
                return
            if not data:
                return

    # --- Reboot recovery ---------------------------------------------------

    async def _trigger_reboot(self) -> None:
        """Connect to the standard-telnet management port and send reboot."""
        now = time.monotonic()
        if now - self._last_reboot_monotonic < REBOOT_COOLDOWN_SECONDS:
            _LOGGER.debug(
                "Crestron %s reboot suppressed (cooldown, %.0fs remaining)",
                self.host,
                REBOOT_COOLDOWN_SECONDS - (now - self._last_reboot_monotonic),
            )
            return
        self._last_reboot_monotonic = now
        _LOGGER.warning(
            "Crestron audio service on %s:%s unreachable; sending reboot via port %s",
            self.host,
            self.port,
            self.reboot_port,
        )
        try:
            conn = await asyncio.wait_for(
                telnetlib3.open_connection(
                    host=self.host,
                    port=self.reboot_port,
                    encoding="ascii",
                    connect_minwait=0.05,
                    connect_maxwait=0.2,
                ),
                timeout=CONNECT_TIMEOUT_SECONDS,
            )
        except (TimeoutError, OSError) as exc:
            _LOGGER.error(
                "Failed to open reboot telnet to %s:%s: %s",
                self.host,
                self.reboot_port,
                exc,
            )
            return
        writer: Any = conn[1]
        try:
            writer.write("reboot\r\n")
            with contextlib.suppress(TimeoutError, OSError):
                await asyncio.wait_for(writer.drain(), timeout=2.0)
            await asyncio.sleep(0.5)
        finally:
            with contextlib.suppress(Exception):
                writer.close()
        _LOGGER.info("Reboot command sent to %s", self.host)

    async def trigger_reboot(self) -> None:
        """Public hook so entities / services can force a reboot."""
        async with self._io_lock:
            await self._close_locked()
            self._last_reboot_monotonic = 0.0  # force send regardless of cooldown
            await self._trigger_reboot()

    # --- Protocol ----------------------------------------------------------

    async def request(self, command: str) -> str | None:
        """Send a command and return the first response line, or None."""
        async with self._io_lock:
            for attempt in (1, 2):
                try:
                    await self._ensure_connected_locked()
                    await self._drain_unsolicited_locked()
                    assert self._writer is not None and self._reader is not None
                    _LOGGER.debug("Sending: %s", command)
                    self._writer.write(f"{command}\r\n")
                    with contextlib.suppress(TimeoutError, OSError):
                        await asyncio.wait_for(self._writer.drain(), timeout=2.0)
                    try:
                        line = await asyncio.wait_for(
                            self._reader.readline(),
                            timeout=COMMAND_TIMEOUT_SECONDS,
                        )
                    except TimeoutError:
                        return None
                    if not line:
                        raise ConnectionResetError("peer closed")
                    line_str: str = str(line).strip()
                    _LOGGER.debug("Received: %s", line_str)
                    return line_str
                except (OSError, EOFError, ConnectionError) as exc:
                    _LOGGER.debug("Request '%s' failed (attempt %s): %s", command, attempt, exc)
                    await self._close_locked()
                    if attempt == 1:
                        continue
                    await self._trigger_reboot()
                    raise ConnectionError(f"Telnet request failed: {exc}") from exc
            return None

    async def command(self, command: str) -> None:
        """Send a fire-and-forget command."""
        async with self._io_lock:
            for attempt in (1, 2):
                try:
                    await self._ensure_connected_locked()
                    assert self._writer is not None
                    _LOGGER.debug("Sending: %s", command)
                    self._writer.write(f"{command}\r\n")
                    with contextlib.suppress(TimeoutError, OSError):
                        await asyncio.wait_for(self._writer.drain(), timeout=2.0)
                    return
                except (OSError, EOFError, ConnectionError) as exc:
                    _LOGGER.debug("Command '%s' failed (attempt %s): %s", command, attempt, exc)
                    await self._close_locked()
                    if attempt == 1:
                        continue
                    await self._trigger_reboot()
                    raise HomeAssistantError(
                        f"Crestron command '{command}' failed: {exc}"
                    ) from exc

    # --- Polling -----------------------------------------------------------

    async def _async_poll(self) -> dict[str, dict[str, Any]]:
        """Fetch the current state for every zone."""
        data: dict[str, dict[str, Any]] = {}
        had_error = False
        for zone in self.zones:
            zone_state: dict[str, Any] = {}
            try:
                power = await self.request(f"{zone} POWER")
                if power is not None:
                    zone_state["power"] = power
                volume_line = await self.request(f"{zone} VOLUME CHECK")
                if volume_line:
                    with contextlib.suppress(ValueError):
                        zone_state["volume"] = int(volume_line.split()[-1])
                source_line = await self.request(f"{zone} SOURCE")
                if source_line:
                    zone_state["source"] = source_line.split()[-1]
            except ConnectionError as exc:
                had_error = True
                _LOGGER.debug("Poll failed for zone %s: %s", zone, exc)
            data[zone] = zone_state

        if had_error and not any(data.values()):
            raise UpdateFailed(f"All zones failed to poll on {self.host}")
        return data
