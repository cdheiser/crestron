"""Constants for the Crestron integration."""
from __future__ import annotations

DOMAIN = "crestron"

CONF_ZONES = "zones"
CONF_REBOOT_PORT = "reboot_port"

DEFAULT_PORT = 2000
DEFAULT_REBOOT_PORT = 23

SOURCES: dict[str, str] = {
    "Chromecast": "CHROMECAST",
    "iTunes": "ITUNES",
}

POLL_INTERVAL_SECONDS = 30
REBOOT_COOLDOWN_SECONDS = 180
COMMAND_TIMEOUT_SECONDS = 2.0
CONNECT_TIMEOUT_SECONDS = 5.0
