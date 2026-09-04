# enocean-mqtt User Guide

This guide describes installation, configuration and operation of `enocean-mqtt` on Linux and Raspberry Pi.

> [!NOTE]
> Releases below `1.0.0` may introduce incompatible configuration or interface changes.

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

---

## Requirements

The reference deployment is Linux, including Raspberry Pi OS.

Required components:

- Python 3.11 or newer;
- Git;
- an MQTT broker reachable from the gateway;
- an ESP3-compatible EnOcean serial interface for live radio operation.

USB300 and TCM310-class interfaces are supported. Replay can be used without radio hardware.

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
git clone https://github.com/seneca-III/enocean-mqtt.git
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

The installation creates the `enocean-mqtt` command in `.venv/bin/`.

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

Authentication is shown disabled above so that a new installation can be brought up before the first API token has been created. The final bootstrap procedure for creating the first token will be added to this guide together with the corresponding runtime procedure; after the first token exists, authentication should be enabled for normal operation.

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

### Recommended full starting configuration

For a normal installation with MQTT, live EnOcean RX, SQLite and Web UI enabled, start from `config/config.example.json` and change at least:

1. `application.timezone`;
2. `enocean.default_interface` and the interface `device`;
3. `mqtt.host` and, where required, MQTT credentials;
4. `sqlite.enabled` to `true` if telegram history is wanted;
5. `web_api.enabled` to `true` if the Web UI/API is wanted;
6. API authentication after the initial token has been created.

The repository example contains all supported configuration sections and is the reference for optional settings.

---

## First Start

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

The initial creation of the first administrative token requires a dedicated bootstrap procedure. That procedure is the one remaining authentication item to be implemented/documented before enabling authentication on a fresh installation. Until then, a new local installation can be validated with `web_api.authentication.enabled` set to `false`.

Do not expose an unauthenticated Web API to an untrusted network.

---

## Web UI

The integrated Web UI provides the operational interface for dashboard/status information, live and historical bus monitoring, devices, virtual devices, metrics, configuration and token management.

<!-- Screenshot: images/dashboard.png -->

<!-- Screenshot: images/settings.png -->

<!-- Screenshot: images/api-tokens.png -->

---

## Devices and EEPs

Known physical devices are stored in the configured device registry. Virtual devices are stored separately and use sender IDs allocated to the gateway for supported TX workflows.

<!-- Screenshot: images/devices.png -->

<!-- Screenshot: images/virtual-devices.png -->

EEP/profile implementation and hardware validation are different statuses. The public repository therefore provides separate compatibility information for implemented/tested EEPs, manufacturer-specific profiles and tested physical devices.

---

## Bus Monitor and Replay

The Bus Monitor provides live and, with SQLite enabled, historical RX/TX inspection. Raw telegram data is retained independently of semantic decoding so that unknown or unsupported telegrams remain available for diagnostics and later analysis.

Displayed information can include direction, sender ID, raw telegram, decoded data, EEP/profile, RSSI, repeater information, Teach-In state and known/unknown-device status.

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

---

## Updating a Native Installation

For a Git-based installation:

```bash
cd /home/enocean/enocean-mqtt
git pull
source .venv/bin/activate
python -m pip install -e .
sudo systemctl restart enocean-mqtt
```

Review release notes and configuration changes before updating between development releases below `1.0.0`.
