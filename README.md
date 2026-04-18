# Crestron Audio for Home Assistant

A Home Assistant custom integration that controls a Crestron audio processor over
telnet. Each audio zone (e.g. Kitchen, Deck, Patio) is exposed as a
`media_player` entity with power, volume, mute, and source selection.

## Features

- **Async** — built on `telnetlib3`, no thread pool or blocking I/O.
- **Resilient** — automatically detects a hung audio service and issues a
  `reboot` command on the standard telnet port (default `23`) to recover.
- **UI config flow** — add your controller and zones from Settings → Devices &
  Services; no YAML required.
- **YAML import** — existing `media_player: platform: crestron` blocks are
  auto-imported on first launch. A repair notice will remind you to remove them
  from `configuration.yaml`.
- **HACS compatible** — install as a custom repository in HACS.

## Installation

### HACS (recommended)

1. In HACS, open **Integrations** and choose **Custom repositories**.
2. Add `https://github.com/cdheiser/crestron` with category **Integration**.
3. Install **Crestron Audio** and restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** and search for
   **Crestron Audio**.

### Manual

Copy `custom_components/crestron/` into your Home Assistant `config/custom_components/`
directory and restart Home Assistant.

## Configuration

The UI flow asks for four fields:

| Field | Description | Default |
|---|---|---|
| Host | Hostname or IP of the Crestron processor | — |
| Audio control port | TCP port of the audio service | `2000` |
| Reboot port | Standard telnet management port used for the `reboot` recovery command | `23` |
| Zones | Comma-separated zone names, exactly as used in the Crestron program | `KITCHEN, DECK, PATIO` |

One config entry is created per host. All zones on that host share a single
telnet connection.

## YAML migration

Legacy configuration is still accepted and auto-imported on startup:

```yaml
media_player:
  - platform: crestron
    host: crestron
    port: 2000
    name: KITCHEN
  - platform: crestron
    host: crestron
    port: 2000
    name: DECK
  - platform: crestron
    host: crestron
    port: 2000
    name: PATIO
```

Each `- platform: crestron` entry is merged into a single config entry for the
host. Once the config entry shows up under **Devices & Services**, delete the
YAML block and restart — a repair notice will remind you while it's still
present.

## How the reboot recovery works

The Crestron audio service on port 2000 occasionally becomes unresponsive.
When the integration fails to connect or talk to it, it:

1. Opens a new telnet connection to the standard telnet port (default `23`).
2. Sends `reboot\r\n`.
3. Closes the connection.

A cooldown (180 seconds) prevents reboot storms if multiple zones fail at the
same time. The cooldown does not apply to the next successful reconnect —
only to re-issuing the reboot command itself.

## Supported commands

For each zone `ZONE`, the integration sends:

| Home Assistant action | Command sent |
|---|---|
| turn_on | `ZONE ON` |
| turn_off | `ZONE OFF` |
| volume_up | `ZONE VOLUME UP` |
| volume_down | `ZONE VOLUME DOWN` |
| set_volume_level (0..1) | `ZONE VOLUME SET <0..100>` |
| mute_volume (on/off) | `ZONE MUTE ON` / `ZONE MUTE OFF` |
| select_source (Chromecast / iTunes) | `ZONE CHROMECAST` / `ZONE ITUNES` |

Polled every 15 seconds: `ZONE POWER`, `ZONE VOLUME CHECK`, `ZONE SOURCE`.

## Limitations

- Source list is hardcoded to **Chromecast** and **iTunes** — edit
  `const.py → SOURCES` if your Crestron program uses a different set.
- Mute state is tracked optimistically in HA and is not read back from the
  controller.

## License

MIT — see [LICENSE](LICENSE).
