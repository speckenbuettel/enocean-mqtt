# Configuration Model

## External gateway registry (2026-10-16)

The optional `gateways.json` file resides beside the configured `devices_json`.
It stores external gateway base IDs/range sizes and explicitly configured radio
channel offsets with optional name, description and profile. Observations and
metrics do not belong in this file. Existing assigned-profile records remain
compatible; null profiles/new descriptions require coordinated API/runtime
updates. Registry writers use an OS file lock and atomic replacement. UI writes
add an `expected_revision` check; stale edits return HTTP 409 rather than silently
replacing a newer record. The `.lock` sidecar is coordination state, not portable
configuration. See the [gateway guide](../../userguide/gateways.md) for the schema,
Base-ID derivation and migration behavior.

## Scope

The global runtime configuration controls:

- Application identity and timezone
- Registry and import/export paths
- EnOcean interfaces and TX behaviour
- MQTT connectivity
- MQTT topic identifier selection
- MQTT publication intervals
- Default device publication policy
- Runtime metrics windows
- SQLite persistence
- The embedded Web API
- Process logging
- Optional Pushover notifications

It does not configure MQTT topic names that are fixed by the canonical MQTT model. It also does not contain secrets directly.

## Format and location

All runtime configuration files use JSON. YAML is intentionally unsupported.

The configuration file is expected at:

```text
config/config.json
```

The repository example is:

```text
config/config.example.json
```

Relative paths are resolved from the process working directory. The normal deployment therefore starts the application from the repository or installed application root.

## Design principles

The configuration model is:

- Explicit and human-editable
- Machine-readable and schema-validatable
- Strict about unknown fields
- Free of duplicate settings
- Organized by ownership
- Independent of secrets
- Stable for Web API and Web-UI use

Subsystem activation is defined in the owning section. Core gateway and busmonitor behaviour is always active and therefore has no enable switch.

## Canonical target structure

```text
application
paths
enocean
mqtt
topics
gateway
metrics
publish_defaults
sqlite
web_api
logging
notifications
```

## Pushover notifications

`notifications.pushover` is optional and disabled by default. Existing configuration
files remain valid. Settings → Notifications exposes the section even on older
installations. Enter the Pushover User Token (User Key) and application API Token,
enable Pushover, save, and use **Send Pushover test message**. Restart the gateway
to apply automatic notification settings.

For the complete operator workflow and troubleshooting, see
[Pushover setup in Settings](../../userguide/README.md#pushover-setup-in-settings).
This section is the reference for configuration fields and runtime behavior.

Credentials are stored in separate files, defaulting to
`config/secrets/pushover_user_token` and `config/secrets/pushover_api_token`.
Only their paths and configured status appear in configuration responses.
Leaving a token field empty preserves its existing value. Files can also be
provisioned manually, containing one token each; protect them like the MQTT
password file. Relative paths follow the normal process working-directory convention.

| Setting | Default | Meaning |
| --- | --- | --- |
| `enabled` | `false` | Enable Pushover delivery |
| `user_token_file` | `config/secrets/pushover_user_token` | User or group key file |
| `api_token_file` | `config/secrets/pushover_api_token` | Application API token file |
| `device` | `""` | Optional Pushover device name(s); empty uses the account default |
| `priority` | `0` | Priority from -2 through 1; emergency priority 2 is unsupported |
| `timeout_seconds` | `5` | Network timeout, greater than 0 and at most 30 seconds |
| `notify_start` | `true` | Notify after gateway initialization |
| `notify_stop` | `true` | Notify when the runtime exits through its shutdown path |
| `notify_errors` | `true` | Forward gateway error events and uncaught main-runtime failures |
| `error_cooldown_seconds` | `300` | Minimum interval between automatic error notifications, across components |

The error cooldown resets when the process restarts. Suppressed error notifications
are discarded rather than deferred. Startup, shutdown and manual/test messages do
not use the error cooldown. **Notify Start**, **Notify Stop** and **Notify Errors**
only select automatic events; a test message can still be sent when these switches
are off and `enabled` is true.

Settings saves accept the write-only `pushover_user_token` and `pushover_api_token`
fields alongside `config` in `PUT /api/v1/config`. Omit either field to preserve
its saved value; an explicitly empty token is invalid. The browser omits blank
token fields automatically. Neither token belongs inside `notifications.pushover`.
Saved token values are never included in configuration or schema responses.

Messages use the application name as title. Error notifications contain the
component and summary, without the detailed diagnostic payload. HTTP delivery
runs in a background worker with a queue limited to 100 messages. A full queue
drops new messages and logs a warning. Delivery failures are logged locally and
do not interrupt EnOcean/MQTT processing. Requests are sent once, without automatic
retries or persistent storage. Shutdown waits at most `timeout_seconds + 1` seconds
for the worker; pending messages may be lost when the process exits. Power loss,
forced termination and complete network outages cannot reliably be reported by
the gateway itself.

Custom messages can be sent through `POST /api/v1/notifications/pushover/send`:

```json
{"title": "EnOcean gateway", "message": "Test message"}
```

This uses saved settings and requires the `admin` role when API authentication
is enabled (browser sessions also use the existing CSRF protection). A successful
response is `{"accepted_by_pushover": true}`; it confirms service acceptance,
not receipt on a phone. Disabled delivery returns 409, invalid messages 422,
and credential/network/service errors 502. Tokens are never returned by this route.

The reusable `Notification` and `NotificationService.notify()` interface provides
the delivery foundation for future threshold rules. Configurable threshold
evaluation, hysteresis and recovery messages are not implemented yet.

Protocol limits and token format follow the [official Pushover API](https://pushover.net/api).

## Example configuration

The following is an illustrative target configuration. Deployment-specific values, especially device paths, broker addresses and credentials, must be changed by the operator.

```json
{
  "application": {
    "name": "enocean-mqtt",
    "timezone": "Europe/Berlin"
  },
  "paths": {
    "eep_registry_directory": "eep/registry",
    "devices_json": "config/devices.json",
    "virtual_devices_json": "config/virtual-devices.json",
    "sender_id_registry": "config/sender-id-registry.json",
    "devices_csv_import": "data/devices.csv",
    "devices_csv_export": "data/export/devices.csv",
    "unknown_devices_csv_export": "data/export/unknown_devices.csv"
  },
  "enocean": {
    "default_interface": "usb300",
    "tx_enabled": false,
    "interfaces": [
      {
        "interface_id": "usb300",
        "enabled": true,
        "tx_enabled": false,
        "type": "serial_esp3",
        "device": "/dev/serial/by-id/usb-EnOcean_GmbH_EnOcean_USB_300-example-if00-port0",
        "base_id": "FF800000",
        "baudrate": 57600,
        "timeout_seconds": 1,
        "reconnect": {
          "enabled": true,
          "initial_delay_seconds": 5,
          "max_delay_seconds": 60
        },
        "network_bridge": {
          "enabled": false,
          "host": "0.0.0.0",
          "port": 7000,
          "ser2net_binary": "/usr/sbin/ser2net"
        }
      }
    ]
  },
  "mqtt": {
    "host": "mqtt.example.local",
    "port": 1883,
    "client_id": "enocean-mqtt",
    "username": "enocean",
    "password_file": "config/secrets/mqtt_password",
    "base_topic": "enocean",
    "clean_session": true,
    "keepalive_seconds": 30,
    "runtime_commands_enabled": true,
    "reconnect": {
      "initial_delay_seconds": 5,
      "max_delay_seconds": 60
    },
    "tls": {
      "enabled": false,
      "ca_cert_file": null,
      "client_cert_file": null,
      "client_key_file": null,
      "insecure_skip_verify": false
    }
  },
  "topics": {
    "device_topic_identifier": "device_id"
  },
  "gateway": {
    "health_publish_interval_seconds": 300
  },
  "metrics": {
    "peak_telegrams_window_seconds": 900,
    "telegram_mean_interval_window_seconds": 3600,
    "active_device_window_seconds": 86400
  },
  "publish_defaults": {
    "meta": true,
    "state": true,
    "value": true,
    "retain": true,
    "on_change_only": false,
    "change_threshold": null,
    "min_interval_seconds": null,
    "max_interval_seconds": null
  },
  "sqlite": {
    "enabled": false,
    "database_path": "data/sqlite/enocean-mqtt.sqlite",
    "persist_live": true,
    "persist_replay": false,
    "max_telegrams": 50000
  },
  "web_api": {
    "enabled": true,
    "host": "0.0.0.0",
    "port": 8001,
    "reload": false,
    "authentication": {
      "enabled": true,
      "token_file": "config/secrets/api-tokens.json"
    },
    "sse": {
      "enabled": true,
      "max_queue_size": 1000
    }
  },
  "logging": {
    "level": "INFO",
    "format": "text"
  }
}
```

# Configuration sections

## `application`

General application metadata.

```json
"application": {
  "name": "enocean-mqtt",
  "timezone": "Europe/Berlin"
}
```

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `name` | string | yes | `enocean-mqtt` | Stable application or instance name. Retained for UI, status and future multi-instance use. |
| `timezone` | string | no | `UTC` | IANA timezone used for local timestamp representations. |

`timezone` must be a valid IANA timezone such as `Europe/Berlin` or `Asia/Singapore`. Unix timestamps remain timezone-independent.

The former `subsystems` and `runtime_modes` objects are removed. Gateway and busmonitor processing are core runtime functions. SQLite and the Web API are enabled in their own sections. MQTT runtime commands are enabled below `mqtt`.

The process always starts in runtime mode `live`. Replay is a dynamic runtime state entered through runtime commands and is not a startup configuration.

## `paths`

Shared registry and import/export paths.

```json
"paths": {
  "eep_registry_directory": "eep/registry",
  "devices_json": "config/devices.json",
  "virtual_devices_json": "config/virtual-devices.json",
  "sender_id_registry": "config/sender-id-registry.json",
  "devices_csv_import": "data/devices.csv",
  "devices_csv_export": "data/export/devices.csv",
  "unknown_devices_csv_export": "data/export/unknown_devices.csv"
}
```

| Field | Type | Default | Meaning |
|---|---|---|---|
| `eep_registry_directory` | string | `eep/registry` | Active compiled EEP registry directory. |
| `devices_json` | string | `config/devices.json` | Physical device registry. This path is used by startup loading and runtime mutation commands. |
| `virtual_devices_json` | string | `config/virtual-devices.json` | Virtual-device registry. |
| `sender_id_registry` | string | `config/sender-id-registry.json` | Sender-ID allocation registry. |
| `devices_csv_import` | string | `data/devices.csv` | Default device CSV import source. |
| `devices_csv_export` | string | `data/export/devices.csv` | Default device CSV export target. |
| `unknown_devices_csv_export` | string | `data/export/unknown_devices.csv` | Default unknown-device CSV export target. |

Subsystem-owned paths do not belong here. In particular:

- the MQTT password path is `mqtt.password_file`
- the SQLite database path is `sqlite.database_path`
- the Web API token path is `web_api.authentication.token_file`

The former `replay_directory` and `sqlite_directory` fields are removed.

Replay commands receive an explicit capture-file path.

### Foreign-device classification and storage policy

Foreign devices use a separate `foreign-devices.json` file beside the physical
device registry, normally `config/foreign-devices.json`. There is no additional
`config.json` field. A missing file means no foreign senders are configured.
The registry is created by Device Management on the first change and must be
included in installation backups.

Each entry contains `sender_id` and the boolean `exclude_from_sqlite` (default
`false`). Classification alone does not suppress storage. Explicit exclusion
applies to future events for that sender in enabled live/replay persistence modes;
it does not delete existing rows or override `sqlite.persist_live` /
`sqlite.persist_replay`. Changes are read without restarting. MQTT processing and
bus-wide runtime counters are unaffected. If the file is unreadable or invalid,
the store logs a warning and continues normal persistence to avoid losing history.
See [Foreign devices](../../userguide/devices.md#foreign-devices) for the UI,
browser migration and API workflow.

## `enocean`

Physical EnOcean transport and TX safety configuration.

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
      "device": "/dev/ttyUSB0",
      "base_id": "FF800000",
      "baudrate": 57600,
      "timeout_seconds": 1.0
    }
  ]
}
```

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `default_interface` | string or null | no | `null` | Interface used when an operation does not explicitly select one. |
| `tx_enabled` | boolean | no | `false` | Global physical-radio TX switch. |
| `interfaces` | array | no | `[]` | Ordered collection of named EnOcean transport interfaces. |

Validation rules:

- Every `interface_id` must be non-empty and unique
- `default_interface` must reference an entry in `interfaces`
- If `interfaces` is empty, `default_interface` must be absent or `null`
- Array order has no default-interface semantics
- The runtime never silently falls back to a different TX interface

### EnOcean interface

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `interface_id` | string | yes | - | Stable logical interface identifier. |
| `enabled` | boolean | no | `false` | Connect the interface during startup. |
| `tx_enabled` | boolean | no | `false` | Permit physical-radio TX through this interface. |
| `type` | string | no | `serial_esp3` | Transport type. Currently only `serial_esp3` is supported. |
| `device` | string | yes | - | Serial device path. Stable `/dev/serial/by-id/...` paths are preferred. |
| `base_id` | string or null | no | `null` | EnOcean Base ID assigned to this physical interface. |
| `baudrate` | integer | no | `57600` | Serial baud rate. |
| `timeout_seconds` | number | no | `1` | Serial read and protocol-response timeout. Must be greater than zero. |
| `reconnect` | object | no | see below | Serial reconnect policy. |
| `network_bridge` | object | no | see below | Optional `ser2net` bridge owned by this interface. |

Base IDs are eight uppercase hexadecimal characters. According to the EnOcean EURID allocation rules, gateway Base IDs identify blocks of 128 sender IDs and therefore have their lowest seven bits cleared. Keep the configured sender-ID registry persistent across updates and restores; replacing it can change virtual-device identities and require pairing again.

### Interface reconnect

```json
"reconnect": {
  "enabled": true,
  "initial_delay_seconds": 5,
  "max_delay_seconds": 60
}
```

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `enabled` | boolean | no | `true` | Retry an interrupted serial interface. |
| `initial_delay_seconds` | integer | no | `5` | Initial reconnect delay. |
| `max_delay_seconds` | integer | no | `60` | Maximum reconnect delay. |

Both delays must be greater than zero and the initial delay must not exceed the maximum delay.

### Interface network bridge

```json
"network_bridge": {
  "enabled": false,
  "host": "0.0.0.0",
  "port": 7000,
  "ser2net_binary": "/usr/sbin/ser2net"
}
```

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `enabled` | boolean | no | `false` | Allow bridge control for this interface. |
| `host` | string | no | `0.0.0.0` | Bridge bind address. |
| `port` | integer | no | `7000` | TCP listen port. |
| `ser2net_binary` | string | no | `ser2net` | Path or executable name for `ser2net`. |

An interface cannot be used by the native serial transport and `ser2net` at the same time. Bridge operations therefore stop the native transport first.

### TX enablement and outcome

A generated telegram is physically handed to an EnOcean interface only when:

```text
enocean.tx_enabled
AND interface.enabled
AND interface.tx_enabled
AND interface is operational
```

Generated TX telegrams are always published to the TX busmonitor and may be persisted according to the SQLite persistence policy, even when physical TX is disabled.

The runtime Telegram Event contains:

```json
{
  "direction": "tx",
  "interface_id": "usb300",
  "transmission": "accepted"
}
```

Allowed transmission outcomes are:

| Value | Meaning |
|---|---|
| `accepted` | The interface accepted the ESP3 request with `RET_OK`. This is not an acknowledgement from the destination device. |
| `disabled` | The telegram was generated but physical TX was disabled globally or for the selected interface. |
| `failed` | Writing, interface response, or response timeout indicated failure. |

`disabled` is an expected dry-run outcome and does not generate a log or error event per telegram. `failed` generates a structured gateway error. 

The `transmission` field belongs to the runtime and MQTT Telegram Event model. It is intentionally not persisted as a column in the SQLite telegram table.

For TX events, `direction: "tx"` means a telegram generated for intended radio transmission. The `transmission` field states whether the interface accepted that transmission.

## `mqtt` (ab hier durchsehen)

MQTT broker connectivity and MQTT-specific runtime behaviour.

```json
"mqtt": {
  "host": "mqtt.example.local",
  "port": 1883,
  "client_id": "enocean-mqtt",
  "username": "enocean",
  "password_file": "config/secrets/mqtt_password",
  "base_topic": "enocean",
  "clean_session": true,
  "keepalive_seconds": 30,
  "runtime_commands_enabled": true,
  "reconnect": {
    "initial_delay_seconds": 5,
    "max_delay_seconds": 60
  }
}
```

| Field | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `host` | string | yes | - | MQTT broker hostname or address. |
| `port` | integer | no | `1883` | MQTT broker TCP port. |
| `client_id` | string | no | `enocean-mqtt` | MQTT client ID. Must be unique at the broker. |
| `username` | string or null | no | `null` | MQTT username. |
| `password_file` | string or null | no | `null` | Path to a file containing only the MQTT password. |
| `base_topic` | string | yes | - | Root topic for the canonical MQTT model. |
| `clean_session` | boolean | no | `true` | MQTT 3.1.1 clean-session behaviour passed to the client library. |
| `keepalive_seconds` | integer | no | `30` | MQTT keepalive interval. |
| `runtime_commands_enabled` | boolean | no | `true` | Subscribe to MQTT runtime commands. |
| `reconnect` | object | no | see below | Automatic reconnect timing. |
| `tls` | object | no | disabled | Reserved TLS configuration. |

`runtime_commands_enabled` controls only the MQTT subscription on:

```text
<base_topic>/gateway/command
```

It does not disable runtime commands invoked through the REST API, Web UI or internal runtime calls. Command QoS is fixed at `1`. Command outcomes are published through the canonical gateway log and error topics; there is no command-result topic.

### MQTT reconnect

```json
"reconnect": {
  "initial_delay_seconds": 5,
  "max_delay_seconds": 60
}
```

Automatic MQTT reconnect is mandatory and cannot be disabled. Both delays must be greater than zero and the initial delay must not exceed the maximum.

### MQTT TLS

```json
"tls": {
  "enabled": false,
  "ca_cert_file": null,
  "client_cert_file": null,
  "client_key_file": null,
  "insecure_skip_verify": false
}
```

| Field | Type | Meaning |
|---|---|---|
| `enabled` | boolean | Request TLS transport. |
| `ca_cert_file` | string or null | CA certificate path. |
| `client_cert_file` | string or null | Optional client certificate path. |
| `client_key_file` | string or null | Optional client private-key path. |
| `insecure_skip_verify` | boolean | Disable certificate hostname verification. Unsafe outside controlled testing. |

TLS fields are retained as reserved configuration but are not implemented by this revision. `enabled` must remain `false` until TLS support is implemented. The runtime must reject `enabled: true` rather than silently connecting without TLS.

## `topics`

Selection of the stable device identifier used in MQTT topic paths.

```json
"topics": {
  "device_topic_identifier": "device_id"
}
```

Allowed values:

| Value | Behaviour |
|---|---|
| `device_id` | Publish device-ID-based topics. |
| `alias` | Publish alias-based topics. Devices without an alias cannot use an alias topic. |
| `both` | Publish both device-ID- and alias-based topics when an alias exists. |

The legacy value `sender_id` is not valid. The project device model uses the canonical term `device_id`.

All other MQTT topic paths are fixed by the [MQTT model](mqtt-model.md) and are not configurable.

## `gateway`

Gateway runtime publication timing.

```json
"gateway": {
  "health_publish_interval_seconds": 300
}
```

| Field | Type | Default | Meaning |
|---|---|---|---|
| `health_publish_interval_seconds` | integer | `300` | Periodic gateway health publication interval. |

The value must be greater than zero.

Gateway processing is a core runtime function and cannot be disabled.

## `metrics`

Sliding observation windows used by runtime metrics.

```json
"metrics": {
  "peak_telegrams_window_seconds": 900,
  "telegram_mean_interval_window_seconds": 3600,
  "active_device_window_seconds": 86400
}
```

| Field | Type | Default | Meaning |
|---|---|---|---|
| `peak_telegrams_window_seconds` | integer | `900` | Rolling window used for peak telegram load. |
| `telegram_mean_interval_window_seconds` | integer | `3600` | Rolling window used for mean telegram intervals. |
| `active_device_window_seconds` | integer | `86400` | A known device is active when its last observed telegram falls within this window. |

All values must be greater than zero. The active-device definition is given in the [MQTT model](mqtt-model.md).

## `publish_defaults`

Default MQTT publication policy for decoded device data.

```json
"publish_defaults": {
  "meta": true,
  "value": true,
  "state": true,
  "retain": true,
  "on_change_only": false,
  "change_threshold": null,
  "min_interval_seconds": null,
  "max_interval_seconds": null
}
```

| Field | Type | Meaning |
|---|---|---|
| `meta` | boolean | Publish metadata topics by default. |
| `state` | boolean | Publish aggregate state topics by default. |
| `value` | boolean | Publish individual value topics per channel by default. |
| `retain` | boolean | Retain state-oriented publications by default. |
| `on_change_only` | boolean | Suppress unchanged values by default. |
| `change_threshold` | number or null | Minimum numeric change required for publication. |
| `min_interval_seconds` | number or null | Minimum interval between publications. |
| `max_interval_seconds` | number or null | Maximum interval before republishing current state. |

This section is intentionally retained, but its final precedence and runtime semantics require a separate design decision. Until that work is complete, the runtime must not claim that these fields influence publication. The implementation status must remain explicit in the example and release notes.

## `sqlite`

SQLite telegram persistence.

```json
"sqlite": {
  "enabled": false,
  "database_path": "data/sqlite/enocean-mqtt.sqlite",
  "persist_live": true,
  "persist_replay": false,
  "max_telegrams": 500000
}
```

| Field | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | boolean | `false` | Enable SQLite persistence. |
| `database_path` | string | `data/sqlite/enocean-mqtt.sqlite` | SQLite database file. |
| `persist_live` | boolean | `true` | Persist live RX and generated TX telegram events. |
| `persist_replay` | boolean | `false` | Persist replay-generated telegram events. |
| `max_telegrams` | integer | `0` | Maximum retained rows; `0` means unlimited. |

When retention is bounded, cleanup removes the oldest rows in batches while preserving monotonically increasing IDs and stable cursor pagination.

Generated TX telegrams may be persisted whether their runtime `transmission` outcome is `accepted`, `disabled` or `failed`. The outcome itself is not stored in the SQLite telegram schema.

## `web_api`

Embedded FastAPI and Web-UI service.

```json
"web_api": {
  "enabled": true,
  "host": "0.0.0.0",
  "port": 8001,
  "reload": false,
  "authentication": {
    "enabled": true,
    "token_file": "config/secrets/api-tokens.json"
  },
  "sse": {
    "enabled": true,
    "max_queue_size": 1000
  }
}
```

| Field | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | boolean | `false` | Start the embedded HTTP service. |
| `host` | string | `0.0.0.0` | HTTP bind address. |
| `port` | integer | `8001` | HTTP listen port. |
| `reload` | boolean | `false` | Enable uvicorn development auto-reload. Must remain false in production. |
| `authentication.enabled` | boolean | `false` | Require bearer-token authentication for protected API routes. |
| `authentication.token_file` | string | `config/secrets/api-tokens.json` | API token file. |
| `sse.enabled` | boolean | `true` | Enable live Server-Sent Events. |
| `sse.max_queue_size` | integer | `1000` | Maximum buffered events per live stream. |

Disabling the Web API does not disable MQTT, runtime commands, interfaces, SQLite or replay support.

See [Secrets](#secrets) for token formats and file permissions, and the
[authentication guide](../../userguide/README.md#web-ui-and-api-authentication)
for setup status and operational restrictions.

## `logging`

Process console logging.

```json
"logging": {
  "level": "INFO",
  "format": "text"
}
```

| Field | Type | Default | Meaning |
|---|---|---|---|
| `level` | string | `INFO` | Minimum emitted Python log severity. |
| `format` | string | `text` | Console log representation: `text` or `json`. |

Allowed levels and their visible messages are:

| Configured level | Visible levels |
|---|---|
| `DEBUG` | DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `INFO` | INFO, WARNING, ERROR, CRITICAL |
| `WARNING` | WARNING, ERROR, CRITICAL |
| `ERROR` | ERROR, CRITICAL |
| `CRITICAL` | CRITICAL |

Level input is normalized to uppercase. Unknown levels are configuration errors and must not silently fall back to `INFO`.

`text` produces human-readable console messages. `json` produces one JSON object per line with at least timestamp, level, logger and message fields. Exception records additionally include exception information.

Console logging is separate from the structured MQTT topics `gateway/log` and
`gateway/error` described in the [MQTT model](mqtt-model.md). Use `INFO` for normal
operation and enable `DEBUG` only for targeted diagnosis. Treat logs as sensitive:
review and sanitize them before sharing, including device identifiers and addresses.

# Fixed runtime behaviour

The following behaviour is intentionally not configurable:

- Initial runtime mode is `live`
- Gateway processing is active
- Busmonitor event processing is active
- MQTT reconnect is active
- MQTT command topic is `<base_topic>/gateway/command`
- MQTT command QoS is `1`
- Gateway status, health, metrics, log and error topics follow the canonical MQTT model
- Last Will topic, payload, retain and QoS follow the canonical MQTT model
- Runtime command results use gateway log or error events
- There is no command-result topic

# Secrets

Passwords, bearer tokens, certificate private keys and comparable secrets must not be stored directly in `config.json`.

Configuration stores only paths to secret material, including:

```text
mqtt.password_file
web_api.authentication.token_file
notifications.pushover.user_token_file
notifications.pushover.api_token_file
```

MQTT password files contain the password as plain text, without a JSON wrapper.
Each Pushover credential file contains one 30-character alphanumeric token;
surrounding whitespace is ignored. These files are not encrypted at rest.

API credentials use a JSON file with a top-level `tokens` array. Each entry contains
`name`, `token` and `roles`; supported roles are `read` and `admin`. The `admin` role
also grants read access; mutating API requests require `admin`. Token strings
must be valid Base64 encoding of at least 32 random bytes. Never use example tokens
as operational credentials. Use `python -m enocean_mqtt.auth init --name admin`
for local first-token creation or `recover --name admin` to replace an admin
credential while the service is stopped. See the authentication guide linked
above for the required OS account, exact file path, activation and recovery steps.

Keep secrets under `config/secrets/` where possible. On Linux, restrict that directory
to its owner (`700`) and credential files to owner read/write (`600`), ensuring the
owner is the account running the gateway service. Alternative group permissions
need to be configured deliberately if a separate administrator manages the files.
Relative paths are resolved from the runtime working directory. Protect backups
equally, and do not commit credentials or include them in public reports.

MQTT TLS settings are reserved; enabling TLS is currently rejected. A certificate
path in the configuration does not imply an encrypted MQTT connection.

# Validation policy

The final runtime configuration loader must:

- Reject malformed JSON
- Reject unknown top-level sections and unknown fields
- Apply documented defaults
- Validate numeric ranges and enum values
- Validate unique interface IDs and interface references
- Validate IANA timezone identifiers
- Reject active TLS until TLS is implemented
- Report field-qualified validation errors
- Avoid silently accepting legacy configuration

Configuration is validated completely during startup before external services, interfaces or persistence are started.

# Reload behaviour

The global runtime configuration is startup configuration and is not reloaded automatically.

Changing `config.json` requires a controlled application restart. Runtime commands may reload domain registries where explicitly supported, but that does not reload the global configuration model.

# Migration from the legacy model

| Legacy field or section | Target model |
|---|---|
| `application.subsystems` | removed |
| `application.runtime_modes` | removed |
| `application.*.tx` / `tx_enabled` | `enocean.tx_enabled` |
| top-level `serial` | removed; use `enocean.interfaces[]` |
| `enocean.gateway_base_id` | removed; use `enocean.interfaces[].base_id` |
| top-level `interfaces` | `enocean.interfaces` |
| top-level `default_tx_interface_id` | `enocean.default_interface` |
| `paths.replay_directory` | removed; replay commands use an explicit file path |
| `paths.sqlite_directory` | removed; use `sqlite.database_path` |
| hard-coded virtual-device path | `paths.virtual_devices_json` |
| `topics.device_topic_identifier: "sender_id"` | use `"device_id"` |
| top-level `runtime_commands` | removed; use `mqtt.runtime_commands_enabled` only for activation |
| top-level `status` | removed; canonical status and LWT behaviour is fixed |
| top-level `runtime` | removed; startup mode is always `live` |
| top-level `busmonitor` | removed; busmonitor behaviour is a core runtime function |
| `mqtt.reconnect.enabled` | removed; MQTT reconnect is always active |
| `logging.json` | replaced by `logging.format` |

# Deferred configuration work

The following work is intentionally deferred:

- Activating MQTT TLS
- Finalizing and wiring `publish_defaults` precedence
- Global hot reload of `config.json`
- Configurable notification thresholds, hysteresis and recovery messages
