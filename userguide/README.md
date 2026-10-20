# enocean-mqtt User Guide

This guide describes installation, configuration and operation of `enocean-mqtt` on Linux and Raspberry Pi.

For Docker on Linux AMD64/ARM64, start with the [Docker installation guide](docker.md).
The configuration and device chapters below also apply to container installations.

> [!NOTE]
> Starting with `0.9.0`, releases use SemVer (`MAJOR.MINOR.PATCH`). This pre-1.0
> release is intended for user testing; interfaces may still change.
> Check the [Changelog](../CHANGELOG.md) before updating; configuration or interface
> changes may require migration.

## Contents

1. [Requirements](#requirements)
2. [Native Installation](#native-installation)
3. [EnOcean Interface](#enocean-interface)
4. [Configuration](#configuration)
5. [First Start](#first-start)
6. [Web UI and API Authentication](#web-ui-and-api-authentication)
7. [Web UI](#web-ui)
8. [Devices and EEPs](#devices-and-eeps)
9. [Bus Monitor and Replay](#bus-monitor-and-replay)
10. [REST API and Swagger](#rest-api-and-swagger)
11. [Running as a Service](#running-as-a-service)
12. [Smoke Test](#smoke-test)
13. [Troubleshooting](#troubleshooting)

For notifications, see [Pushover setup in Settings](#pushover-setup-in-settings).

For SIGNAL decoding and unknown radio types, see
[Radio telegram diagnostics](../docs/radio-diagnostics.md).

For external gateways with a base ID and channel sender IDs, see
[External gateways](gateways.md).

The System page's Service Logs default to **Since service start**, based on the
current gateway/Web API process start time. Choose **All retained logs** to inspect
earlier runs. CSV and Text exports contain the displayed selection. These filters
preserve the system journal; restarting the service does not delete older logs.

Before deployment, read [Known Limitations](../KNOWN_LIMITATIONS.md), including
hardware validation, incomplete API operations and network-security boundaries.

---

## Requirements

The reference deployment is Linux, including Raspberry Pi OS.

Required components:

- Python 3.11 or newer;
- Git;
- an MQTT broker reachable from the gateway;
- an ESP3-compatible EnOcean serial interface for live radio operation.

USB300 is the reference interface for live RX/TX testing. Other ESP3-compatible
interfaces, including TCM310-based hardware, require separate hardware validation.
Replay can be used without radio hardware.

On Debian, Ubuntu and Raspberry Pi OS, install the basic operating-system packages with:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
```

Verify Python:

```bash
python3 --version
```

---

## Native Installation

The native installation uses a Git checkout and a Python virtual environment. The repository root remains the runtime working directory because configuration and registry paths are relative to it.

### 1. Clone the repository

```bash
git clone https://github.com/speckenbuettel/enocean-mqtt.git
cd enocean-mqtt
```

### 2. Create the virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install enocean-mqtt

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

The installation creates the `enocean-mqtt` runtime command and the
`enocean-mqtt-auth` offline authentication helper in `.venv/bin/`.

Verify it with:

```bash
.venv/bin/enocean-mqtt --help
```

### 4. Create the runtime configuration

Start from the repository example:

```bash
cp config/config.example.json config/config.json
```

Do not edit `config/config.example.json`; keep it as a reference for the current release.

The interface's example `base_id` is `null`: do not invent or copy a transmitter
identity. Leave it unset for RX-only operation; before TX, use the actual adapter's
base ID and the supported sender-allocation workflow. TX remains disabled in the
example. A configured sender registry may supply an already established base ID.

Other example files are illustrative, not live installation data:

- `devices.example.json` contains one disabled physical sensor using current
  `device_id`/`device_name` fields. Replace its illustrative ID/profile before use;
  it creates no virtual device or TX allocation.
- `sender-id-registry.example.json` has no interfaces or allocated senders. Do not
  overwrite an existing sender registry: those identities may already be taught
  into receivers. The `760` manufacturer value is the application's default,
  not a device identity or a claim about your adapter.
- `api-tokens.example.json` is an empty format example, with no usable credentials.
  Do not copy it before `auth init`; create your own registry as described in
  [First admin setup](#first-admin-setup). An already copied empty registry can be
  populated with `auth recover` as described under [Admin recovery](#admin-recovery).

The next sections describe the required changes.

---

## EnOcean Interface

### Find the serial device

For a USB interface, inspect the persistent Linux device names:

```bash
ls -l /dev/serial/by-id/
```

Prefer a `/dev/serial/by-id/...` path over `/dev/ttyUSB0`, because the latter may change when USB devices are reconnected.

For a GPIO/UART-connected TCM310, use the serial device configured by the operating system, for example `/dev/serial0` where applicable.

### Serial permissions

The user running `enocean-mqtt` must be allowed to open the serial device. On Debian-family systems this normally means membership in `dialout`:

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in after changing group membership, or reboot the system.

Check the device permissions with:

```bash
ls -l /dev/serial/by-id/
```

Do not run `enocean-mqtt` as root merely to work around serial-device permissions.

### Interface settings

A normal receive-only interface is configured as:

```json
"enocean": {
  "default_interface": "usb300",
  "tx_enabled": false,
  "interfaces": [
    {
      "interface_id": "usb300",
      "enabled": true,
      "tx_enabled": false,
      "type": "serial_esp3",
      "device": "/dev/serial/by-id/YOUR-ENOCEAN-DEVICE",
      "baudrate": 57600,
      "timeout_seconds": 1.0
    }
  ]
}
```

`interface_id` is a local logical name. `default_interface` must reference one configured interface.

For physical transmission, TX must be enabled both globally and for the selected interface. Leave both settings `false` until transmission is intentionally required.

If `base_id` is configured manually, it must contain exactly eight hexadecimal digits and represent an EnOcean Base ID with the lowest seven bits cleared.

### Operation without radio hardware

An EnOcean interface is not required for replay, API/UI exploration or MQTT-based testing. The complete `enocean` section can be omitted from `config/config.json`. This uses the equivalent defaults:

```json
"enocean": {
  "default_interface": null,
  "tx_enabled": false,
  "interfaces": []
}
```

With no configured interfaces, no serial connection is attempted. The Web API, Web UI, MQTT processing, SQLite storage and replay remain available when their respective sections are configured. Live EnOcean RX and physical TX are unavailable until an interface is added.

This is preferable to leaving a sample interface enabled when no USB or UART adapter is connected: an enabled but unavailable device is correctly reported as disconnected and the runtime continues trying to reconnect it.

---

## Configuration

The runtime configuration is:

```text
config/config.json
```

It is strict JSON. Unknown fields are rejected. Relative paths are resolved from the repository root, so start the runtime with the repository root as its working directory.

Only the `mqtt` object is structurally mandatory in the configuration model; all other sections have defaults. For a useful live EnOcean gateway, however, configure **MQTT plus at least one enabled EnOcean interface**. For replay-only operation, omit `enocean` as described above.

### Minimal configuration without radio hardware

The smallest configuration for replay and MQTT-based tests contains only the required MQTT settings:

```json
{
  "mqtt": {
    "host": "192.0.2.10",
    "base_topic": "enocean"
  }
}
```

Replace the example broker address. Add `sqlite` and `web_api` sections from `config/config.example.json` when telegram history or the Web UI and Swagger are wanted.

### Minimal live configuration

The following is a practical minimal receive-only configuration:

```json
{
  "enocean": {
    "default_interface": "usb300",
    "interfaces": [
      {
        "interface_id": "usb300",
        "enabled": true,
        "device": "/dev/serial/by-id/YOUR-ENOCEAN-DEVICE"
      }
    ]
  },
  "mqtt": {
    "host": "192.0.2.10",
    "base_topic": "enocean"
  }
}
```

Replace the example broker address and serial-device path.

Defaults used by this configuration include:

- MQTT port `1883`;
- MQTT client ID `enocean-mqtt`;
- MQTT keepalive `30` seconds;
- serial type `serial_esp3`;
- serial baud rate `57600`;
- serial timeout `1.0` second;
- physical TX disabled;
- SQLite disabled;
- Web API and Web UI disabled;
- log level `INFO`.

This is sufficient for the core live bus-monitor/MQTT runtime. The Web UI requires `web_api.enabled: true` and SQLite-backed historical Bus Monitor data requires `sqlite.enabled: true`.

### MQTT authentication

Do not put the MQTT password directly into `config.json`. Configure the username and a password file:

```json
"mqtt": {
  "host": "mqtt.example.local",
  "port": 1883,
  "client_id": "enocean-mqtt",
  "username": "enocean",
  "password_file": "config/secrets/mqtt_password",
  "base_topic": "enocean"
}
```

Create the secret directory and password file:

```bash
mkdir -p config/secrets
printf '%s' 'YOUR_MQTT_PASSWORD' > config/secrets/mqtt_password
chmod 600 config/secrets/mqtt_password
```

MQTT TLS configuration exists in the configuration schema but TLS is not implemented in the current runtime. `mqtt.tls.enabled` must therefore remain `false`.

### Optional: application identity and timezone

```json
"application": {
  "name": "enocean-mqtt",
  "timezone": "Europe/Berlin"
}
```

`timezone` uses an IANA timezone name such as `Europe/Berlin` or `Asia/Singapore`. The default is `UTC`.

### Optional: SQLite persistence

Enable SQLite to retain telegram history for diagnostics and the historical Bus Monitor:

```json
"sqlite": {
  "enabled": true,
  "database_path": "data/sqlite/enocean-mqtt.sqlite",
  "persist_live": true,
  "persist_replay": false,
  "max_telegrams": 50000
}
```

`persist_live` controls storage of live telegrams. `persist_replay` controls storage of replay telegrams. `max_telegrams` bounds retained telegram history; `0` means no configured row limit.

### Optional: Web UI and REST API

The Web UI is served by the embedded FastAPI service. Enable it with:

```json
"web_api": {
  "enabled": true,
  "host": "0.0.0.0",
  "port": 8001,
  "reload": false,
  "authentication": {
    "enabled": false,
    "token_file": "config/secrets/api-tokens.json"
  },
  "sse": {
    "enabled": true,
    "max_queue_size": 1000
  }
}
```

With `host: "0.0.0.0"`, the service listens on all local network interfaces. Restrict the bind address if network-wide access is not required.

The example/default leaves authentication disabled for compatibility. Before the
first start with Web UI/API enabled, follow [First admin setup](#first-admin-setup)
to create a token locally and set `web_api.authentication.enabled` to `true`.
There is no need to start an unauthenticated service to create credentials.

### Optional: device topic identifier

```json
"topics": {
  "device_topic_identifier": "device_id"
}
```

Allowed values are:

- `device_id` — publish the device-ID topic hierarchy;
- `alias` — publish the alias hierarchy;
- `both` — publish both representations.

The default is `device_id`.

### Optional: registry and import/export paths

Defaults are:

```json
"paths": {
  "eep_registry_directory": "eep/registry",
  "devices_json": "config/devices.json",
  "virtual_devices_json": "config/virtual-devices.json",
  "sender_id_registry": "config/sender-id-registry.json",
  "devices_csv_import": "testdata/devices.csv",
  "devices_csv_export": "export/devices.csv",
  "unknown_devices_csv_export": "export/unknown_devices.csv"
}
```

Normally these values do not need to be changed for a standard installation.

### Optional: gateway and metrics intervals

```json
"gateway": {
  "health_publish_interval_seconds": 300
},
"metrics": {
  "peak_telegrams_window_seconds": 900,
  "telegram_mean_interval_window_seconds": 3600,
  "active_device_window_seconds": 86400
}
```

The defaults are suitable for normal operation.

### Optional: publication defaults

```json
"publish_defaults": {
  "meta": true,
  "state": true,
  "value": true,
  "retain": true,
  "on_change_only": false,
  "change_threshold": null,
  "min_interval_seconds": null,
  "max_interval_seconds": null
}
```

These settings define the default MQTT publication policy for devices unless a more specific policy overrides them.

### Optional: logging

```json
"logging": {
  "level": "INFO",
  "format": "text"
}
```

Supported levels are `DEBUG`, `INFO`, `WARNING`, `ERROR` and `CRITICAL`. Supported formats are `text` and `json`.

### Optional: Pushover notifications

Optional Pushover delivery is configured under `notifications.pushover` and is
disabled by default. See [Pushover setup in Settings](#pushover-setup-in-settings)
for the setup workflow and the
[configuration reference](../docs/specifications/configuration.md#pushover-notifications)
for every supported field and default.

### Recommended full starting configuration

For a normal installation with MQTT, live EnOcean RX, SQLite and Web UI enabled, start from `config/config.example.json` and change at least:

1. `application.timezone`;
2. `enocean.default_interface` and the interface `device`;
3. `mqtt.host` and, where required, MQTT credentials;
4. `sqlite.enabled` to `true` if telegram history is wanted;
5. `web_api.enabled` to `true` if the Web UI/API is wanted;
6. create an admin token and enable API authentication before starting the service.

The repository example contains all supported configuration sections and is the reference for optional settings.

---

## First Start

If using the Web UI/API, complete [First admin setup](#first-admin-setup) first.

Run the first start interactively from the repository root:

```bash
cd enocean-mqtt
source .venv/bin/activate
enocean-mqtt --config config/config.json
```

The default configuration path is already `config/config.json`, so this is also valid:

```bash
enocean-mqtt
```

Keep the explicit `--config` form when testing or documenting an installation because it makes the active configuration unambiguous.

During startup verify that there is no configuration traceback and the MQTT connection succeeds. For a live gateway, also verify that the configured serial interface opens. In operation without radio hardware, the absence of an EnOcean connection is expected.

Stop the foreground process with `Ctrl+C` after the initial test.

---

## Web UI and API Authentication

When the Web API is enabled, the Web UI and REST API use the same embedded FastAPI service. The default port is `8001`.

For a host named `enocean-gateway`, the Web UI is therefore normally reached at:

```text
http://enocean-gateway:8001/
```

FastAPI Swagger documentation is available under `/docs` when the Web API is running.

API authentication uses bearer tokens and supports role-based access. Existing tokens can be managed through the Web UI once an authenticated administrative session exists.

### First admin setup

Run these steps in an interactive terminal on the gateway host, **as the Linux
account that will run the service** (for example `falk`). Do not prefix the Python
command with `sudo`: that would use the wrong account and create root-owned files.
For an existing service, check its account with
`systemctl show enocean-mqtt --property=User`. If it uses a different account,
sign in as that account first; an administrator can use `sudo -iu ACCOUNT`.

The gateway must be stopped. Stop an existing systemd service with
`sudo systemctl stop enocean-mqtt`, or stop a foreground instance with `Ctrl+C`.
A fresh installation that has never been started needs no stop command.

From the repository root (adjust the installation path if necessary):

```bash
cd ~/enocean-mqtt
source .venv/bin/activate
python -m enocean_mqtt.auth init --name admin --token-file config/secrets/api-tokens.json
```

This creates a cryptographically random admin token without starting MQTT, the
Web API or the serial interface. It displays the new token in the terminal;
store it in a password manager. Do not include it in screenshots, logs, chat
messages or issues. Output redirection/pipes are refused to avoid accidental
secret logging. Terminal recording can still capture the output; disable it first.

The command creates the token file with owner-only permissions (`600` on Linux)
and a newly created containing directory with `700`. Existing parent-directory
permissions are not changed. The installed `enocean-mqtt-auth` command is an
equivalent shortcut; the module form above also works with an existing editable
installation after updating the source.

`init` refuses to overwrite **any** existing file, even an empty one. If the
registry already exists, use [Admin recovery](#admin-recovery) instead. Do not
copy the example token registry into production or use its example credentials.

Edit your configuration:

```bash
nano config/config.json
```

Inside the existing `web_api` section, set:

```json
"authentication": {
  "enabled": true,
  "token_file": "config/secrets/api-tokens.json"
}
```

Keep the surrounding JSON and other Web API settings intact. Save in nano with
`Ctrl+O`, confirm the filename with `Enter`, then exit with `Ctrl+X`.

The helper does **not** edit configuration or read `--config`. Its `--token-file`
is relative to the shell's current directory. Use the exact same file configured
in `web_api.authentication.token_file`; for a custom location, use the same
absolute path in both places. The standard relative path above assumes the
repository-root installation described in this guide.

Continue with [First Start](#first-start), or start an already installed service
with `sudo systemctl start enocean-mqtt`.

### Sign in and verify access

- Open `http://enocean-gateway:8001/` (replace the hostname). You should be
  redirected to `/login`.
- Username: `admin` (the token's `--name`, not necessarily your Linux username).
- Password: the generated token, including any trailing `=` characters.
- In Swagger under `/docs`, use **Authorize** to enter that same token as a
  bearer credential. In other API clients, send `Authorization: Bearer TOKEN`.
- A `read` token can read protected API resources. An `admin` token also grants
  read access and permits changes. Create separate tokens for integrations in
  the Web UI token-management page; keep an admin credential available.

Without credentials, `GET /api/v1/gateway/health` should return `401`. With a
valid token it should return `200`; a rejected token returns `403`. Merely opening
Swagger does not prove that protected API requests are authenticated. Do not put
real tokens into shell command lines, shared API collections or bug reports.

API authentication is separate from MQTT broker credentials and does not encrypt
HTTP or MQTT traffic. Use a trusted network; remote access needs separately
configured transport protection (for example HTTPS). Do not expose the service
directly to the public Internet or disable authentication to regain access.

### Admin recovery

Recovery requires local/SSH access to the gateway host as the service's Linux
account. It is not an unauthenticated remote password-reset endpoint.

1. Stop the service with `sudo systemctl stop enocean-mqtt`. Check
   `systemctl is-active enocean-mqtt`; it must report `inactive` (not `active`).
   Stop any manually started instance as well. Do not restart until recovery
   has succeeded and the configured token-file path has been checked.
2. As the service account, run from the installation directory:

   ```bash
   cd ~/enocean-mqtt
   source .venv/bin/activate
   python -m enocean_mqtt.auth recover --name admin --token-file config/secrets/api-tokens.json
   ```

3. Save the new token in your password manager. Check that authentication is
   still enabled in your configuration, then run
   `sudo systemctl start enocean-mqtt` and sign in with the new token.
4. Verify that the new token works and the replaced token is rejected. Update
   any integration that was using that particular admin token.

For an existing admin entry, `recover` replaces only its token. Other entries and
metadata are preserved; their credentials continue to work. If the specified
name no longer exists, it creates a new admin entry. It refuses to promote a
read-only entry: choose a different name in that case. Use the original admin
name when replacing a lost credential; choosing another name does not revoke
the original token. The required service restart clears existing browser sessions.

On Linux, the helper uses the gateway's per-user process lock and refuses to run
while that user's gateway is active. It cannot detect a gateway running as
another OS account, so using the correct account and stopping the service are
essential. Symbolic-link paths, wrong ownership and group/world-writable token
files/directories are refused. Fix ownership as appropriate and restrict the
dedicated secrets directory/file to `700`/`600`; do not broadly change permissions
on shared directories.

If the file is missing, `recover` refuses to create it: verify the configured path
first. Restore a protected backup or, if the registry really was lost, use `init`
to create a new one. All old integration tokens must then be recreated. Malformed
JSON, duplicate names/tokens or invalid entries are rejected without overwriting
the file. Preserve the file securely and repair it or restore a known-good backup
before retrying. Protect backups like the original: tokens are stored in plain
text, and restoring an older backup can reactivate previously revoked credentials.

---

## Web UI

The integrated Web UI provides the operational interface for dashboard/status information, live and historical bus monitoring, devices, virtual devices, metrics, configuration and token management.

<!-- Screenshot: images/dashboard.png -->

<!-- Screenshot: images/settings.png -->

<!-- Screenshot: images/api-tokens.png -->

### Settings

The Settings page groups configuration into Application, EnOcean, MQTT, SQLite,
API, Logging and Notifications. Administrative access is required to save changes
when authentication is enabled. Save changes before restarting the gateway; the
page indicates when a restart is required.

Secret inputs do not reveal saved values. Leaving the Pushover token fields blank
keeps the existing tokens; typing a replacement and saving updates the secret file.

### Pushover setup in Settings

You need a Pushover account with a receiving device, its **User Key** (shown as
**User Token** in Settings), and an **API Token** for your Pushover application.
These are separate from the gateway's Web API bearer tokens.

1. Open **Settings → Notifications → Pushover**.
2. Enter **User Token** and **API Token**. Enable **Enabled**.
3. Optionally set **Device** to your Pushover device name. Leave it empty to use
   default delivery. **Priority** defaults to `0` and supports `-2` through `1`.
4. Select the automatic messages with **Notify Start**, **Notify Stop** and
   **Notify Errors**. All three default to enabled once Pushover is activated.
5. Set **Error Cooldown Seconds** if needed. The default `300` allows at most one
   automatic error notification per five minutes across all gateway components.
6. Save, then click **Send Pushover test message** and verify receipt on your device.
   The test uses saved settings immediately and does not require a gateway restart.
7. Restart the gateway to apply the automatic notification settings.

Pushover remains optional: installations without a `notifications` section continue
to work with delivery disabled. The Settings page exposes the defaults automatically.
To disable automatic delivery, turn off **Enabled**, save and restart.

Tokens are stored as plain text in separate files, normally
`config/secrets/pushover_user_token` and `config/secrets/pushover_api_token`.
The configuration stores paths rather than token values. Ensure these files are
readable by the service user and keep them out of version control. For manual
configuration, provision one token per file and use the
[configuration example](../config/config.example.json) and
[secret-file guidance](../docs/specifications/configuration.md#secrets).

Automatic messages use the application name as their title. Gateway errors include
the component and summary; detailed diagnostics remain in the gateway logs. The
error cooldown does not apply to startup, shutdown or manually sent messages.
Restarting the process resets the cooldown.

Delivery is best effort. Automatic messages use a background queue; failed requests
are logged and are not automatically retried. Messages are not persisted across
restarts. Shutdown notifications require the runtime cleanup path to execute;
power loss, forced termination and a complete network outage cannot reliably be
reported by the gateway itself.

Custom messages are available through
[`POST /api/v1/notifications/pushover/send`](../docs/specifications/configuration.md#pushover-notifications).
Configurable upper/lower threshold rules, hysteresis and recovery messages are
future work; enabling Pushover does not create sensor alarms automatically.

---

## Devices and EEPs

EEP profiles are cached on first use. After updating profile JSON files, use
**Validate and reload EEPs** under the dashboard's Runtime Commands, or send
`eeps.reload` through MQTT/HTTP. A browser refresh alone no longer activates
changes. Reload validates all available profiles and keeps the previous cache
if any profile fails. See [EEP cache commands](../docs/runtime-commands.md#eep-cache-eepsreload).

Enum channel states expose a numeric `value` plus optional string `meaning`, for
example `0` / `door_closed`. Both are available in MQTT JSON and API runtime
values. The scalar MQTT channel `/value` contains only the numeric code. Scaled
measurements such as voltage remain engineering values. When updating from older
profiles/runtime versions, adjust comparisons to old strings/booleans and refresh
adapter discovery. The API advertises selectable representations; an adapter must
implement their selection before offering both in its UI.

For creating a source-grounded standard or proprietary profile with Codex, see
the [profile-authoring guide and versioned prompt](profile-authoring.md). Generated
profiles remain review candidates until separately verified and approved.

Known physical devices are stored in the configured device registry. Virtual devices are stored separately and use sender IDs allocated to the gateway for supported TX workflows.

Follow the [step-by-step device guide](devices.md) to register physical sensors,
import/export CSV, create virtual sensors, supply values and verify Teach-In.
Before binding virtual sensors in OBS or MQTT, read
[Virtual sensor transmission in detail](devices.md#virtual-sensor-transmission-in-detail):
required snapshot values, profile defaults, the aggregation quiet interval and
delayed errors are different from a single KNX group-address write.
Use the [practical acceptance checklist](acceptance-checklist.md) when testing a
fresh installation and its API/OBS integration.

<!-- Screenshot: images/devices.png -->

<!-- Screenshot: images/virtual-devices.png -->

EEP/profile implementation and hardware validation are different statuses. The public repository therefore provides separate compatibility information for implemented/tested EEPs, manufacturer-specific profiles and tested physical devices.

The Dashboard's **Devices** card includes the number of classified foreign
senders. **Runtime Commands** also offers **Republish devices (to MQTT)** and
**Connect selected interface** / **Disconnect selected interface**. The interface
commands target the selection in the EnOcean card, require administrator rights,
and can interrupt live reception when disconnecting.

### Controller mappings and local overrides

`config/device-controller-mappings.json` is versioned application data: it supplies
default receive-profile → transmit-profile relationships. Keep this shipped file
unchanged so updates can deliver reviewed defaults. It is not a personal device
registry and its `devices` list is not a place to store your installed devices.

For a physical device with `communication: "bidirectional_eep_pair"`, set
`tx_profile` on that device in your local `config/devices.json` to override the
default. A nonempty `tx_profile` takes precedence; otherwise the runtime looks up
the device's receive-side `profile` (or `eep`) in the shipped mapping. Both the
receive and transmit profiles must exist and be appropriate for the device.
This does not itself allocate a sender, enable TX or perform Teach-In.

For `bidirectional_eep` the runtime uses the same profile for RX/TX; the pair
override rule does not apply. There is no separate global local-override file or
automatic merge of custom mapping tables. A relationship needed by many users
should be contributed as a reviewed default.

If you previously edited the shipped table, back up those changes before updating
and transfer installation-specific choices to the affected devices' `tx_profile`
fields. Compare with the new defaults; do not blindly restore the old table over
an update. Restart the service after editing the local registry directly.

---

## Bus Monitor and Replay

The Bus Monitor provides live and, with SQLite enabled, historical RX/TX inspection. Raw telegram data is retained independently of semantic decoding so that unknown or unsupported telegrams remain available for diagnostics and later analysis.

Displayed information can include direction, sender ID, raw telegram, decoded data, EEP/profile, RSSI, repeater information, Teach-In state and known/unknown-device status.

In **Device types**, select any combination of **Known devices**, **Unknown
devices** and **Foreign devices**. Known and unknown are enabled initially;
foreign is disabled. This applies to live/history rows, sender selection and CSV
export. A foreign device does not belong to your own network. Manage its
classification and optional per-device SQLite exclusion under
**Device Management → Foreign Devices**; see
[Foreign devices](devices.md#foreign-devices). Visibility and storage are separate:
explicit SQLite exclusion affects future rows only. Bus-wide runtime counters
still include received traffic.

**Quick range** offers presets. You can edit **From** and **To** at any time to
choose your own range, without selecting a separate Custom mode.

**Teach-In** offers **All telegrams**, **Teach-In only** and **Exclude Teach-In**.
It recognizes A5/4BS and D5/1BS Teach-In from their payload's LRN bit and applies
the selection to live rows, historical queries and CSV export alongside the
device-type filters. F6/RPS status bits are not treated as Teach-In.

The color legend below the table explains olive green for known devices, a neutral
background for unknown devices, palette grey for foreign devices, yellow for
Teach-In and red for decode errors. Red takes precedence over yellow; yellow takes
precedence over device colors. Foreign classification takes precedence over known
membership. Inspect the data tooltip or telegram details for the decode error.

For F6/RPS telegrams, the status tooltip shows T21, NU, PTM type, N/U message type,
radio hash algorithm and repeater information. These fields are also available in
MQTT events and historical/replayed telegrams. F6 has no dedicated Teach-In bit;
T21 must not be interpreted as Teach-In. The repeater code 15 means “do not repeat”,
not fifteen repeater hops. See the
[MQTT status contract](../docs/specifications/mqtt-model.md#f6rps-status-metadata)
for field values and compatibility notes.

<!-- Screenshot: images/busmonitor.png -->

Replay processes previously captured EnOcean traffic through the same runtime pipeline as live traffic. It is intended for reproducible testing, regression testing and decoder validation. DolphinView and Weinzierl capture workflows are supported by the replay subsystem.

Replay does not require an `enocean` configuration section or a connected radio adapter. Start the service with the hardware-free configuration above, then use the replay controls in the Web UI/API, or supply a supported capture file to the command-line replay workflow.

---

## REST API and Swagger

The embedded FastAPI service exposes the runtime through REST endpoints used by the Web UI and external integrations.

Swagger/OpenAPI is the primary endpoint-level API reference and is available under:

```text
http://<gateway-host>:8001/docs
```

when the Web API uses its default port.

The API version displayed by Swagger/OpenAPI is read from the repository-root `VERSION` file when the service starts. Restart the service after changing that file.

<!-- Screenshot: images/swagger.png -->

When authentication is enabled, API clients send the configured bearer token in the `Authorization` header.

---

## Running as a Service

After the interactive smoke test succeeds, install `enocean-mqtt` as a systemd service.

The example below assumes:

- Linux user `enocean`;
- repository `/home/enocean/enocean-mqtt`;
- virtual environment `/home/enocean/enocean-mqtt/.venv`.

Replace these paths with the actual installation values.

Create and open `/etc/systemd/system/enocean-mqtt.service` with the `nano` text editor:

```bash
sudo nano /etc/systemd/system/enocean-mqtt.service
```

Paste the following content into the editor and replace the user name and paths with the actual installation values:

```ini
[Unit]
Description=enocean-mqtt runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=enocean
WorkingDirectory=/home/enocean/enocean-mqtt
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/enocean/enocean-mqtt/.venv/bin/enocean-mqtt --config config/config.json
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

In `nano`, save the file with `Ctrl+O`, confirm the file name with `Enter`, and close the editor with `Ctrl+X`.

The service user must have access to the repository files, secret files and EnOcean serial device. Add it to `dialout` if required:

```bash
sudo usermod -aG dialout enocean
```

Load and enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now enocean-mqtt
```

Check status:

```bash
sudo systemctl status enocean-mqtt
```

Follow logs:

```bash
journalctl -u enocean-mqtt -f
```

Restart after a configuration change:

```bash
sudo systemctl restart enocean-mqtt
```

If Mosquitto runs locally as a systemd service, `mosquitto.service` may additionally be added to the unit's `After=` line. It is not required when the broker is remote.

---

## Smoke Test

Perform this test after a fresh installation and after significant configuration changes.

### Core gateway

1. Start the runtime interactively or through systemd.
2. Confirm that it remains running without a traceback.
3. Confirm that the MQTT broker accepts the connection.
4. Confirm that the configured EnOcean serial interface opens without errors.
5. Operate a nearby EnOcean device.
6. Confirm that an RX telegram appears below the configured MQTT base topic in the bus-monitor hierarchy.
7. If the sender is configured with a supported EEP/profile, confirm that semantic device data is published.

An MQTT client such as `mosquitto_sub` can be used for a broad first check:

```bash
mosquitto_sub -h <mqtt-host> -t 'enocean/#' -v
```

Adapt the topic if a different `mqtt.base_topic` is configured. Add the broker's authentication options when required.

### SQLite

If SQLite is enabled, confirm that the database file is created:

```bash
ls -l data/sqlite/enocean-mqtt.sqlite
```

After receiving telegrams, historical Bus Monitor queries should contain the persisted live traffic.

### Web UI and API

If `web_api.enabled` is `true`:

1. open `http://<gateway-host>:8001/`;
2. confirm that the dashboard loads;
3. open `http://<gateway-host>:8001/docs`;
4. confirm that Swagger/OpenAPI loads;
5. check that the dashboard reports the expected MQTT and EnOcean state;
6. open the Bus Monitor and confirm that live telegrams appear.

If authentication is enabled, perform these checks with a valid token/session.

### Pushover (optional)

After saving enabled Pushover settings, send a test message from Settings and verify
both the success indication and receipt on your device. If **Notify Start** is
enabled, use the Settings restart action and confirm the subsequent startup message.
See [Pushover troubleshooting](#pushover-messages-do-not-arrive) if delivery fails.

### Service

If systemd is used:

```bash
systemctl is-active enocean-mqtt
systemctl is-enabled enocean-mqtt
journalctl -u enocean-mqtt -n 100
```

The expected service states are `active` and `enabled`, with no startup traceback in the journal.

---

## Troubleshooting

### Configuration is rejected

`config.json` is validated strictly. Check JSON syntax, field names and value types. Unknown configuration fields are rejected rather than silently ignored.

Compare the file with:

```text
config/config.example.json
```

### EnOcean interface cannot be opened

Check:

```bash
ls -l /dev/serial/by-id/
groups
```

Verify the configured device path, `dialout` membership and that no other process has opened the same serial port.

### MQTT does not connect

Check the broker address, port, credentials and network connectivity. If `password_file` is configured, verify that the file exists and is readable by the runtime user.

### Web UI/API is not reachable

Verify `web_api.enabled`, `web_api.host`, `web_api.port`, the runtime logs and local firewall rules. Also check whether another process already occupies the configured port.

### No telegrams are received

First establish whether the serial interface opened successfully. Then verify that the test device is within radio range and actually transmits. Replay can be used to distinguish radio/serial problems from downstream decoding and runtime-processing problems.

### Service fails but interactive start works

Compare the systemd `User`, `WorkingDirectory`, `ExecStart` and file permissions with the successful interactive environment. Relative configuration and registry paths depend on the correct working directory.

### Pushover messages do not arrive

- Save pending changes before using the test button and confirm **Enabled** is on.
- Check that the User Token is your Pushover User Key and the API Token belongs to
  your Pushover application. Each must contain 30 letters/digits; surrounding
  whitespace is removed. Gateway Web API bearer tokens cannot be used here.
- If token files are reported missing or unreadable, check their configured paths,
  the service working directory and service-user permissions.
- For connection failures, check DNS and outbound HTTPS access to `api.pushover.net`.
  The default network timeout is five seconds. Inspect `journalctl -u enocean-mqtt`
  for local Pushover warnings.
- HTTP 400 indicates a rejected request, for example invalid credentials or options;
  HTTP 429 indicates rate/quota rejection. Correct the cause before testing again.
- If the test succeeds but automatic messages do not arrive, restart after saving
  and check the three **Notify** switches. Repeated gateway errors are suppressed
  during the error cooldown; suppressed messages are not sent later.
- A successful test means Pushover accepted the message. If the phone shows nothing,
  check the receiving account/device and its notification settings.

---

## Updating a Native Installation

Review the changelog and migration notes first. For a Git-based installation,
use your actual installation directory and service account (the path below is
only the default example). Check for local changes before updating:

```bash
cd ~/enocean-mqtt
git status --short
```

Stop the service with `sudo systemctl stop enocean-mqtt` and make a protected,
separate backup of your actual configuration and data paths: `config/config.json`,
`config/devices.json`, `config/foreign-devices.json` (if present),
`config/virtual-devices.json`, `config/sender-id-registry.json`,
`config/secrets/`, and the SQLite database if enabled. Include the entire database
directory while the service is stopped, including any SQLite sidecar files.
Use owner-only access for backups; they contain credentials. Resolve any local
edits to tracked files explicitly before proceeding. Do not discard them or
replace the live configuration/registries with release examples.

Then update:

```bash
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
sudo systemctl restart enocean-mqtt
```

If any step fails, stop and investigate rather than continuing to the restart.
Verify service status, authenticated access and device/sender identities afterwards.
Git-ignored operational files are retained by a normal update; a directory copy
or restore procedure must preserve them explicitly. Shipped defaults such as
controller mappings may change, while per-device `tx_profile` values remain in
your local registry. Retain the previous release revision with the backup; restore
compatible code and data together, with the service stopped. Restoring old tokens
can reactivate revoked credentials, so review them before restarting.

### Original and repeated RX telegrams

Busmonitor metrics (MQTT and API) expose rx.original_telegrams,
rx.repeated_telegrams and rx.unclassified_telegrams, each with telegrams_total
and telegrams_per_minute. Totals are counted before decoding and reset with
the runtime statistics; rates use the same elapsed-runtime basis as the RX rate.
The existing rx.repeated_telegrams_total remains an alias for the repeated total.

Repeater counters 0 and 15 (original, do not repeat) are original; 1 and 2 are
repeated. Missing or reserved values are unclassified. TX does not contribute.
The telegram-activity API preserves rx.known and rx.unknown and adds the three
classification objects with known/unknown counts per time bucket. Historical
classification uses stored metadata and the current known-device registry.
The Metrics RX chart stacks Original, Repeated and Unclassified within the
Known and Unknown bars; tooltips expose the individual counts.
The selectable chart ranges extend from one hour to 30 days; the 30-day view
uses daily buckets. RX categories use distinct blue, grey and olive tones, TX
uses warm yellow, and both charts show independently scaled count axes.
