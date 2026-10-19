# MQTT Model

## External gateway command observations (2026-10-16)

Since 2026-10-19, external gateway RX commands are published retained at
`<base_topic>/devices/gateways/<BASE_ID>/<SENDER_ID>/command`. This device
namespace is distinct from the application's existing singular `gateway` topics.
It replaces the non-retained
`<base_topic>/gateways/<BASE_ID>/channels/<SENDER_ID>/command` path; subscribers
and broker ACLs must migrate. Only the new path is published. The next decoded
RX command establishes the retained observation; no history backfill occurs.
Retain represents the last observation, not online status or actuator state.
Removal of configuration does not clear retained observations automatically;
obsolete retained topics require explicit broker cleanup when decommissioning.
Payload fields are `base_id`, `sender_id`, `profile`, `profile_direction: "tx"`,
`telegram_type_id`, `timestamp`, raw `fields`, and decoded `values`. Value entries
carry `value`, `raw_value`, `unit` and optional `meaning`; enum values remain
numeric codes. A received command never updates a physical actuator's confirmed
state. Profile-less channels remain raw-only on existing busmonitor paths.
No transmit subscription is introduced. Dedicated retained gateway inventory and
metrics topics are deferred; use the management read API described in the
[gateway guide](../../userguide/gateways.md).

## Enum channel state contract (2026-10-07)

Device `state` JSON under `channels.<name>` and per-channel `state` JSON expose
the numeric protocol enum code as `value` and its symbolic label as optional
`meaning`. The active binding enum overrides the channel enum. Profile
`semantic_value` does not replace the public enum code, including boolean or
numeric semantic overrides. Unknown codes omit meaning. The scalar channel
`/value` topic likewise publishes the numeric code, without a separate meaning
topic. Existing configured device/alias topic namespaces are unchanged.

```json
{"channels": {"door_contact": {"value": 0, "meaning": "door_closed"},
              "lock_contact": {"value": 1, "meaning": "door_unlocked"},
              "supply_voltage": {"value": 3.0, "unit": "V"}}}
```

This excerpt omits existing device metadata and timestamps. Non-enum measurements
remain scaled/rounded semantic numbers and pure non-enum booleans remain booleans.
No meaning is fabricated for measurements. Value and meaning derive from the same
observation and have the same channel update timestamp. The retained state replaces
the whole updated channel entry, so an unknown new code does not retain an old label.

This changes the previous enum state contract, which could return strings or
boolean/numeric semantic overrides. Consumers must use codes or JSON meaning as
appropriate. Retained data is refreshed on new observations; old cached/historical
states are not converted automatically. Profile output-name changes are separate
API/MQTT identifier migrations. RX publication does not change TX/set encoding.

## Overview

This document defines the canonical MQTT model for `enocean-mqtt`.

The MQTT model defines:

- topic hierarchy
- topic naming
- payload structure and content
- publish semantics
- publish filtering behaviour
- retain policies
- timestamp handling
- gateway telemetry
- runtime monitoring topics
- busmonitor event transport
- device-oriented integration topics

The MQTT model supports three primary information classes:

1. telegram-oriented bus monitoring
2. device- and value-oriented automation integration
3. gateway and service monitoring

The MQTT model is intentionally stable, predictable and machine-readable.

---

## MQTT Design Principles

The MQTT model of `enocean-mqtt` follows several intentionally stable architectural principles.

Primary goals include:

- MQTT-first runtime architecture
- stable and predictable topic structures
- machine-readable payloads
- deterministic runtime behaviour
- replay-compatible event transport
- API-first semantics
- integration simplicity
- long-term architectural stability

The MQTT model intentionally prioritizes:

- semantic consistency
- runtime observability
- low integration complexity
- deterministic event transport
- long-term maintainability

The MQTT structure should remain stable independently of internal implementation details whenever reasonably possible.

---

## Core Terminology

| Term | Meaning |
|---|---|
| `busmonitor` | Telegram-oriented diagnostics and runtime analysis |
| `device` | Physical EnOcean device identified by device ID (EURID) |
| `alias` | Human-friendly MQTT mirror topic for a device |
| `virtual&nbspdevice` | Software-emulated EnOcean-compatible device |
| `channel` | Logical semantic value or datapoint published by a physical or virtual device |
| `state` | Current semantic state representation |
| `command` | Runtime control command or semantic EnOcean device control command. Gateway commands control the runtime itself, whereas device commands control EnOcean devices or virtual devices |
| `message` | Sendable EnOcean message or TX function exposed by a bidirectional physical device |
| `set` | Writable MQTT input endpoint. For bidirectional physical devices, `set` is used below `message/<message>/set`. For virtual devices, `set` is used below `channel/<channel>/set`. |
| `live mode` | Runtime operation using real RF telegrams |
| `replay mode` | Deterministic replay-based runtime execution |
| `runtime event` | Internal operational or protocol event |
| `telegram event` | Structured representation of an EnOcean telegram |

---

## MQTT Architectural Role

MQTT acts as the primary runtime event transport layer of `enocean-mqtt`.

MQTT is optimized for:

- runtime event distribution
- integration into external systems
- runtime commands
- telemetry transport
- live event streaming

MQTT is intentionally not intended to become:

- a historical query interface
- a pagination interface
- a persistence abstraction
- a general-purpose query API

Historical inspection and filtering are handled separately by SQLite and the Web API layer.

---

## Live and Historical Data Separation

The architecture intentionally distinguishes between:

- live runtime event distribution
- historical event persistence
- historical inspection and analysis

MQTT remains the primary live event transport layer of `enocean-mqtt`.

SQLite and the Web API layer provide additional convenience functionality for:

- historical inspection
- filtering
- pagination
- time-window analysis
- technical observability

The availability of SQLite or Web API components must not be required for normal MQTT-based runtime operation.

---

## Architectural Layer Responsibilities

The `enocean-mqtt` architecture separates responsibilities between runtime processing, event transport, persistence, query handling and visualization.

| Layer | Primary Responsibility |
|---|---|
| Runtime | Event generation and processing |
| MQTT | Runtime event distribution |
| SQLite | Historical event persistence |
| Web API | Historical queries and filtering |
| Web UI | Visualization and analysis |

This separation intentionally prevents MQTT from evolving into a historical query or persistence abstraction layer while preserving the MQTT-first architecture of the project.

---

## Replay Architecture

Replay functionality primarily belongs to the runtime and testing architecture.

Replay acts as an alternative runtime event source and is mainly intended for deterministic runtime testing, decoder validation and regression testing.

---

## Runtime Metrics and Historical Analysis

Runtime metrics published via MQTT primarily represent live runtime state and operational telemetry.

Long-term historical analysis, filtering and correlation may additionally be provided through SQLite persistence and Web API queries.

This separation allows MQTT to remain optimized for runtime event distribution while enabling extended historical observability through optional persistence and analysis layers.

---

## Base Topic

All topics are published below a configurable base topic.

Default:

```text
enocean
```

Examples:

```text
enocean/home/raspi
home/raspi/enocean
building/enocean
```

Site, host or gateway identifiers are not fixed protocol levels. They may be included in the configurable base topic if required.

---

## Top-Level Structure

```text
<base_topic>/
├── busmonitor/
├── device/
├── alias/
├── virtual/
└── gateway/
```

Meaning:

```text
busmonitor = telegram-oriented analysis and diagnostics
device     = physical EnOcean devices by device_id
alias      = optional human-friendly mirror by technical alias
virtual    = emulated or virtual EnOcean devices
gateway    = gateway runtime lifecycle, commands, logs and errors
```

---

## Canonical MQTT Structure

```text
<base_topic>/
├── busmonitor/
│   ├── rx/
│   │   ├── event
│   │   └── raw/
│   │       └── telegram
│   │
│   ├── tx/
│   │   ├── event
│   │   └── raw/
│   │       └── telegram
│   │
│   ├── metrics
│   └── unknown_devices/
│       └── <sender_id>
│
├── device/
│   └── <device_id>/
│        ├── info
│        ├── metrics
│        ├── state
│        ├── channel/
│        │   └── <channel>/
│        │        ├── value
│        │        └── state
│        │
│        ├── message/          (only for bidirectional devices)
│        │   └── <message>/
│        │        └── set
│        │
│        └── command
│
├── alias/
│   └── <alias>/
│        ├── info
│        ├── metrics
│        ├── state
│        ├── channel/
│        │   └── <channel>/
│        │        ├── value
│        │        └── state
│        │
│        └── message/
│            └── <message>/
│                 └── set
│
├── virtual/
│   └── <virtual_device_id>/
│        ├── info
│        ├── metrics
│        ├── state
│        ├── channel/
│        │   └── <channel>/
│        │        └── set
│        │
│        └── command
│
└── gateway/
    ├── status
    ├── enocean
    ├── runtime_mode
    ├── health
    ├── metrics
    ├── log
    ├── error
    ├── command
    ├── uptime
    └── version
```

---

## Physical Device Communication Model

The MQTT topic hierarchy does not encode the communication class of a physical device as an additional topic level.

All physical EnOcean devices are published below:

```text
<base_topic>/device/<device_id>/...
```

Physical devices may be unidirectional or bidirectional.

```text
Physical Device
├── unidirectional
│   ├── device_id
│   ├── eep/profile
│   └── channels[]
│
└── bidirectional
    ├── bidirectional_eep
    │   ├── device_id
    │   ├── eep/profile
    │   ├── channels[]
    │   ├── messages[]
    │   └── sender_id
    │
    └── complementary_rx_tx_eeps
        ├── device_id
        ├── rx_eep/profile
        ├── tx_eep/profile
        ├── channels[]
        ├── messages[]
        └── sender_id
```

For unidirectional physical devices, MQTT publishes received or derived semantic values through `channel/<channel>/value` and `channel/<channel>/state`.

For bidirectional physical devices, received or derived semantic values are still published through `channel/<channel>/value` and `channel/<channel>/state`.

Writable EnOcean functions of bidirectional physical devices are exposed through:

```text
<base_topic>/device/<device_id>/message/<message>/set
```

The `sender_id` field in a bidirectional physical device does not identify the physical device itself. It identifies the gateway-managed EnOcean RF sender identity used for outgoing telegram transmission.

---

## Device Identifiers

Each configured physical device uses three separate identifiers:

| Field | Purpose | Example |
|---|---|---|
| `device_id` | EnOcean Unique Radio Identifier (EURID) | `52523B1A` |
| `device_name` | Human-readable display name | `TH-Sensor Badezimmer` |
| `alias` | Stable technical alias for topics and configuration | `th_sensor_badezimmer` |

Rules:

- `device_id` is uppercase hexadecimal without `0x` prefix.
- `device_name` is intended for humans and may contain spaces and mixed case.
- `alias` is lowercase `snake_case`, MQTT-safe and unique within the gateway configuration.
- `alias` is normally generated from `device_name` and should remain stable once used externally.

Example:

```json
{
  "device_id": "52523B1A",
  "device_name": "TH-Sensor Badezimmer",
  "alias": "th_sensor_badezimmer"
}
```

The field `sender_id` is reserved for gateway-managed EnOcean RF sender identities used for transmitting telegrams.

For physical receive-only devices, no `sender_id` is required.

For bidirectional physical devices, `sender_id` identifies the gateway-side RF sender identity used to transmit telegrams to the physical device.

For virtual devices, `sender_id` identifies the gateway-side RF sender identity used by the emulated EnOcean device.

---

## Device Topic Identifier Mode

The authoritative device branch always uses the device ID:

```text
<base_topic>/device/<device_id>/...
```

Optional alias topics may be published as a mirror:

```text
<base_topic>/alias/<alias>/...
```

Supported publication modes:

```text
device_id = publish only <base_topic>/device/<device_id>/...
both      = additionally publish mirrored <base_topic>/alias/<alias>/...
```

Default:

```text
device_id
```

Example in `both` mode:

```text
enocean/device/52523B1A/channel/temperature/state
enocean/alias/th_badezimmer/channel/temperature/state
```

The device ID topic remains authoritative. Alias topics are convenience mirrors.

Writable alias message topics are allowed and must be resolved to the authoritative device_id internally.

Only the device ID topic supports device commands.

---

## busmonitor Topics

The `busmonitor` branch is telegram-oriented.

It represents EnOcean radio traffic and diagnostic information independently of configured devices.

The busmonitor publishes every relevant RX/TX telegram and must not apply device-level publish filtering.

---

### RX Event Stream

```text
<base_topic>/busmonitor/rx/event
```

Purpose:

- publish every received telegram event as structured JSON
- preserve telegram metadata
- provide replay-compatible event streams
- provide canonical MQTT event serialization

Retain:

```text
false
```

Example payload:

```json
{
  "timestamp_local": "2025-06-13T06:16:29.764+02:00",
  "timestamp_unix": 1749788189.764,

  "direction": "rx",

  "rorg": "A5",
  "sender_id": "059AD109",
  "destination_id": "FFFFFFFF",
  "data": "96000008",

  "erp1_status": "00",
  "erp1_status_decoded": {
    "repeater_count": 0,
    "repeater_permitted": true,
    "hash_type": "checksum",
    "contains_teach_in": false
  },

  "raw_telegram": "A5 96 00 00 08 05 9A D1 09 00",

  "subtelegram_count": 0,

  "rssi_dbm": -83,
  "interface_id": "usb300",
  "port": "COM3"
}
```

---

### F6/RPS status metadata

F6 RX and TX event payloads include `erp1_status_decoded` when `erp1_status`
contains one valid hexadecimal byte. This structure is also used by the Web UI
for live, SQLite history and replay telegrams, including unknown senders.
For example, status `31` produces:

```json
{
  "repeater_count": 1,
  "repeater_permitted": true,
  "repeater_status": "repeated_once",
  "hash_type": "checksum",
  "contains_teach_in": false,
  "rps": {
    "t21": 1,
    "nu": 1,
    "ptm_type": 2,
    "message_type": "N"
  }
}
```

- Bit 5 (`T21`) selects PTM type 1 or 2. Bit 4 (`NU`) selects `U` or `N`.
  These are protocol classifications; they do not identify a specific manufacturer
  or model and must not be used alone to infer a press/release action.
- Bit 7 identifies the radio hash algorithm: `checksum` or `crc8`.
  This is independent of the ESP3 serial frame CRC.
- `repeater_count` retains the existing raw low-nibble value for compatibility.
  Values 0, 1 and 2 mean original, once repeated and twice repeated.
  Value 15 means **do not repeat**, not fifteen hops; `repeater_permitted` is false.
  Values 3 through 14 are reserved, with `repeater_status: "reserved"` and
  `repeater_permitted: null`. The raw status remains available.
- `contains_teach_in` is false for F6. RPS has no dedicated Teach-In flag;
  an ordinary data telegram may be used while a receiver is in learn mode.
  TX `teach_in` is also false for F6; this does not prove or disprove pairing.

Compatibility: the nested `rps` object and `repeater_status` are additive.
Previously incorrect F6 Teach-In, hash and repeater-permission values are corrected.
Consumers must tolerate the documented null for reserved repeater codes. Existing
topic names and non-F6 payloads are unchanged. SQLite history is recomputed from
the original status byte on read; no schema migration or archive rewrite occurs.

Sources: [EnOcean EEP V3.1](https://www.enocean-alliance.org/wp-content/uploads/2020/07/EnOcean-Equipment-Profiles-3-1.pdf),
sections 3.1.1 and 3.2.1, and
[EnOcean ERP1 STATUS Field Encoding](https://enoceanwiki.atlassian.net/wiki/spaces/EKB/pages/539623618/ERP1%2BSTATUS%2BField%2BEncoding).
These are technical references; original specifications are not redistributed.

---

### RX Raw Telegram

```text
<base_topic>/busmonitor/rx/raw/telegram
```

Purpose:

- publish only the raw telegram representation
- support lightweight replay and debugging
- provide Wireshark-like telegram visibility

Example payload:

```text
A5 96 00 00 08 05 9A D1 09 00
```

Retain:

```text
false
```

---

### TX Event Stream

```text
<base_topic>/busmonitor/tx/event
```

Purpose:

- publish every internally generated TX event
- support TX debugging and replay
- compare intended TX with actual RF traffic
- validate generated telegrams

Retain:

```text
false
```

Example payload:

```json
{
  "timestamp_local": "2025-06-13T06:16:29.764+02:00",
  "timestamp_unix": 1749788189.764,

  "direction": "tx",

  "rorg": "A5",
  "sender_id": "059AD109",
  "destination_id": "FFFFFFFF",
  "data": "00 C8 FA 0A",

  "teach_in": false,

  "erp1_status": "00",

  "raw_telegram": "A5 96 00 00 08 05 9A D1 09 00",

  "subtelegram_count": 1,

  "interface_id": "usb300",
  "port": "virtual-device",
  "transmission": "accepted"
}
```

---

### TX Raw Telegram

```text
<base_topic>/busmonitor/tx/raw/telegram
```

Purpose:

- publish only the generated TX telegram
- support replay and low-level debugging

Retain:

```text
false
```

---

### Busmonitor Metrics

```text
<base_topic>/busmonitor/metrics
```

Purpose:

- telegram statistics
- RX/TX counters
- decode statistics
- unknown device statistics
- telegram throughput metrics

`busmonitor/metrics` is telegram-observation oriented and reflects radio traffic statistics.

Example payload:

```json
{
  "rx": {
    "telegrams_total": 10234,
    "telegrams_per_minute": 61.7,
    "telegram_mean_interval_seconds": 0.9,
    "peak_telegrams_per_minute": 143.2,
    "repeated_telegrams_total": 381
  },

  "tx": {
    "telegrams_total": 83,
    "telegrams_per_minute": 0.4
  },

  "decoder": {
    "decoded_telegrams_total": 9980,
    "decode_errors_total": 17
  },

  "rorg": {
    "A5": {
      "telegrams_total": 8123,
      "telegrams_per_minute": 41.7
    },
    "F6": {
      "telegrams_total": 1744,
      "telegrams_per_minute": 8.3
    }
  },

  "unknown_devices": {
    "devices_total": 3,
    "telegrams_total": 84,
    "rorg": {
      "F6": {
        "devices_total": 1,
        "telegrams_total": 18,
        "telegrams_per_minute": 1.2
      }
    }
  },

  "last_rorg": "A5",
  "last_sender_id": "059AB3A6"
}
```

```"peak_telegrams_per_minute"``` is calculated using the configurable sliding observation window defined in the Metrics Calculation Policy section.

Retain:

```text
true
```

---

### Unknown Devices

```text
<base_topic>/busmonitor/unknown_devices/<sender_id>
```

Purpose:

- discovery of unconfigured devices
- onboarding support
- visibility of unknown senders
- runtime inventory assistance

Retain:

```text
true
```

Example payload:

```json
{
  "sender_id": "059AB3A6",
  "rorg": "F6",
  "telegrams": 1,
  "first_seen": "2025-06-13T06:16:29.764+02:00",
  "last_seen": "2025-06-13T06:16:38.843+02:00",
  "last_rssi_dbm": -83,
  "last_data": "50"
}
```

The mandatory `timestamp_local` / `timestamp_unix` pair applies to the primary event or publication timestamp. Additional semantic timestamps such as `first_seen`, `last_seen` or `last_update` may use ISO 8601 local timestamps unless explicitly specified otherwise.

---

## device Topics

The `device` branch is device- and value-oriented.

It represents decoded, automation-relevant information derived from EnOcean telegrams.

The `device` branch always uses the device ID as the topic identifier. The `device_id` is the EURID of the physical EnOcean device.

---

### Device Root

```text
<base_topic>/device/<device_id>
```

Rules:

- `<device_id>` is uppercase hexadecimal without `0x` prefix.
- Device IDs are stable identifiers for physical EnOcean senders.

---

### Device Information

```text
<base_topic>/device/<device_id>/info
```

Purpose:

- publish full device metadata as JSON
- provide a stable integration point for consumers
- support open bridge server (OBS) import and future native mapping

Retain:

```text
true
```

Example payload:

```json
{
  "device_id": "052523B1",
  "device_name": "TH-Sensor Badezimmer",
  "alias": "th_sensor_badezimmer",
  "description": "Wireless temperature and humidity sensor",

  "manufacturer": "Eltako",
  "model": "FTFSB",
  "eep": "A5-04-02",
  "profile": "eltako-ftfsb",

  "enocean_secure": false,
  "enabled": true,
  "sender_id": "FA888801",

  "metadata": {
    "floor": "OG",
    "room": "Badezimmer",
    "equipment_id": "-BT351"
  }
}
```

---

### Device Metrics

```text
<base_topic>/device/<device_id>/metrics
```

Purpose:

- device-specific runtime telemetry
- observed communication behaviour
- runtime activity diagnostics
- heartbeat and activity monitoring
- RF reception diagnostics

Retain:

```text
true
```

Example payload:

```json
{
  "timestamp_local": "2025-06-13T06:16:29.764+02:00",
  "timestamp_unix": 1749788189.764,

  "telegrams_total": 812,
  "telegrams_per_minute": 4.1,
  "telegram_mean_interval_seconds": 602,

  "last_seen": "2025-06-13T06:16:38.843+02:00",
  "last_seen_seconds_ago": 18,
  "last_rssi_dbm": -81
}
```

```"telegram_mean_interval_seconds"``` is calculated using the configurable sliding observation window defined in the Metrics Calculation Policy section.

---

### Device State

```text
<base_topic>/device/<device_id>/state
```

Purpose:

- publish a summary of channel states with timestamp

Example payload:

```json
{
  "timestamp_local": "2025-06-13T06:16:29.764+02:00",
  "timestamp_unix": 1749788189.764,

  "device_id": "0525B303",
  "device_name": "Türsensor Keller",
  "last_update": "2025-06-13T06:16:29.764+02:00",

  "channels": {
    "contact": {
      "value": "closed",
      "semantic_role": "security.contact",
      "object_type": "state",
      "last_update": "2025-06-13T06:16:29.764+02:00"
    },
    "battery_voltage": {
      "value": 3.01,
      "unit": "V",
      "semantic_role": "device.battery_voltage",
      "object_type": "measurement",
      "last_update": "2025-06-13T06:10:12.211+02:00"
    }
  },

  "last_telegram": {
    "rorg": "D5",
    "data": "50"
  }
}
```

The mandatory `timestamp_local` / `timestamp_unix` pair applies to the primary event or publication timestamp. Additional semantic timestamps such as `first_seen`, `last_seen` or `last_update` may use ISO 8601 local timestamps unless explicitly specified otherwise.

Retain:

```text
true
```

---

### Device Command

```text
<base_topic>/device/<device_id>/command
```

Purpose:

- device-specific management commands
- teach-in requests
- identify requests
- runtime maintenance actions

Retain:

```text
false
```

---

### Channel Value

```text
<base_topic>/device/<device_id>/channel/<channel>/value
```

Purpose:

- publish the plain decoded channel value
- provide simple integration for TWS, OBS, Node-RED, Grafana and similar consumers

Example:

```text
21.6
```

Retain:

```text
true
```

---

### Channel State

```text
<base_topic>/device/<device_id>/channel/<channel>/state
```

Purpose:

- publish the current channel state with timestamp
- provide a compact but self-describing runtime state

Example payload:

```json
{
  "timestamp_local": "2025-06-13T06:16:29.764+02:00",
  "timestamp_unix": 1749788189.764,
  "channel": "feed_temperature",
  "value": 37.5,
  "unit": "°C",
  "semantic_role": "climate.supply_temperature",
  "object_type": "measurement"
}
```

Retain:

```text
true
```

---

### Message Set

```text
<base_topic>/device/<device_id>/message/<message>/set
```

Purpose:

- expose writable EnOcean TX functions of bidirectional physical devices
- provide a stable MQTT input for runtime message validation
- decouple writable TX functions from receive-side semantic channels
- support bidirectional EEPs and complementary RX/TX EEP pairs

Typical payloads:

```text
ON
OFF
TRUE
FALSE
0
1
20.3
48.2
50
75
1013.25
```

MQTT-typical semantic payloads such as:

```text
ON
OFF
TRUE
FALSE
```

will automatically be normalized internally to the appropriate semantic control representation.

| MQTT payload | Normalized semantic value |
|---|---|
| `ON` | `1` / `true` |
| `OFF` | `0` / `false` |
| `TRUE` | `1` / `true` |
| `FALSE` | `0` / `false` |

The payload format is message-specific and defined by the effective TX profile.

The runtime must validate the message name and payload against the configured EEP/profile model before generating an EnOcean TX telegram.

Retain:

```text
false
```

---

## alias Topics

The `alias` branch is optional.

It is published only when the device topic identifier mode is set to `both`.

Alias topics mirror selected `device` topics using the configured technical `alias` instead of the device ID.

The human-readable `device_name` is not used in MQTT topic levels.

---

## virtual Topics

The `virtual` branch represents MQTT-visible gateway-emulated EnOcean devices.

Virtual devices do not mirror the physical `device` branch. They use their own TX-oriented MQTT structure below:

```text
<base_topic>/virtual/<virtual_device_id>/...
```

Virtual device input values are written through:

```text
<base_topic>/virtual/<virtual_device_id>/channel/<channel>/set
```

Physical bidirectional devices use `message/<message>/set` instead.

This allows:

- virtual EnOcean senders
- replay-driven automation
- software-defined sensors
- synthetic test devices
- future OBS-integrated virtual objects

---

## gateway Topics

The `gateway` branch describes:

- runtime lifecycle
- operational status
- runtime commands
- logs and warnings
- runtime errors
- structured diagnostics

The gateway branch does not contain decoded device values or telegram streams.

---

### Gateway Status

```text
<base_topic>/gateway/status
```

Payload:

```text
online
offline
```

Purpose:

- lightweight runtime state
- MQTT LWT integration
- operational availability state

Retain:

```text
true
```

---

### Gateway EnOcean Interface Status

```text
<base_topic>/gateway/enocean
```

Payload:

```text
connected
disconnected
```

Purpose:

- lightweight EnOcean interface state

Retain:

```text
true
```

---

### Gateway Runtime Mode

```text
<base_topic>/gateway/runtime_mode
```

Payload:

```text
live
replay
```

Purpose:

- indicate the currently active runtime input mode
- distinguish live operation from replay execution
- support dashboards and runtime observability
- support replay-aware integrations and automation logic
- expose the active telegram source behaviour

Retain:

```text
true
```

---

### Gateway Health

```text
<base_topic>/gateway/health
```

Purpose:

- runtime telemetry
- operational health
- runtime introspection
- memory usage
- uptime telemetry
- MQTT connection state
- EnOcean connection state
- replay and runtime state
- runtime configuration visibility

Health information is intentionally interval-driven and independent from telegram activity.

This prevents unnecessary MQTT traffic during replay or high telegram throughput.

Default publish interval:

```text
300 seconds
```

Configured via:

```json
{
  "gateway": {
    "health_publish_interval_seconds": 300
  }
}
```

Retain:

```text
true
```

Example payload:

```json
{
  "timestamp_local": "2026-06-04T05:08:34.838+02:00",
  "timestamp_unix": 1780542514.838,

  "online": true,
  "version": "2026-06-001",
  "uptime_seconds": 8177,
  "memory_rss_mb": 37.4,

  "runtime_mode": "live",

  "mqtt": {
    "connected": true,
    "host": "mqtt.example.local",
    "port": 1883,
    "client_id": "enocean-mqtt",
    "uptime_seconds": 8177,
    "reconnects": 0,
    "message_load_15mins": {
      "published": 401,
      "received": 10
    }
  },

  "enocean": {
    "connected": true,
    "tx_enabled": true,
    "default_interface": "usb300",
    "interfaces": [
      {
        "interface_id": "usb300",
        "connected": true,
        "tx_enabled": true,
        "port": "/dev/serial/by-id/usb-EnOcean_GmbH_EnOcean_USB_300_DD_FT6XHPO9-if00-port0",
        "base_id": "FF92A700",
        "metrics": {
          "received_esp3_frames": 10,
          "received_radio_erp1_telegrams": 6,
          "accepted_radio_erp1_telegrams": 4,
          "failed_radio_erp1_telegrams": 0,
          "crc_errors": 0,
          "unsupported_packet_types": 0,
          "bytes_received": 178,
          "bytes_transmitted": 93,
          "last_rx_timestamp": 1787815521.509,
          "last_tx_timestamp": 1787815481.429
        }
      }
    ]
  },

  "sqlite": {
    "enabled": true,
    "operational": true,
    "database_size_bytes": 3174400
  },

  "device_registry": {
    "last_reload": "2026-06-04T05:07:17.684+02:00",
    "devices_total": 22
  },

  "web_api": {
    "enabled": true,
    "operational": true,
    "host": "0.0.0.0",
    "port": 8001
  },

  "web_ui": {
    "enabled": true,
    "operational": true,
    "route": "/",
    "static_assets": true
  },

  "logging": {
    "level": "INFO"
  }
}
```

Field meanings:

| Field | Meaning |
|---|---|
| `online` | gateway runtime operational state |
| `version` | gateway software version from `VERSION` file |
| `uptime_seconds` | process uptime |
| `memory_rss_mb` | resident process memory usage |
| `runtime_mode` | live/replay |
| `mqtt.connected` | MQTT connection state |
| `mqtt.reconnects` | reconnect counter since startup |
| `mqtt.uptime_seconds` | time since last successful MQTT connection |
| `enocean_interface.connected` | EnOcean transport availability |
| `enocean_interface.port` | serial or network interface |
| `enocean_interface.base_id` | EnOcean interface/gateway base ID |
| `sqlite.enabled` | SQLite runtime enabled |
| `sqlite.operational` | SQLite runtime operational |
| `sqlite.database_size_bytes` | SQLite database file size |
| `device_registry.last_reload` | last successful device registry reload |
| `device_registry.devices_total` | number of devices loaded into device registry |
| `logging.level` | active runtime logging level |

---

### Gateway Commands

```text
<base_topic>/gateway/command
```

Purpose:

- runtime control
- replay control
- discovery management
- runtime reload requests
- future runtime API integration

Retain:

```text
false
```

Supported payloads:

```text
plain text for simple commands
JSON for complex commands
```

Example payload:

```json
{
  "command": "devices.reload"
}
```

For implemented and planned commands see [Runtime Commands](../runtime-commands.md).

---

### Gateway Metrics

```text
<base_topic>/gateway/metrics
```

Purpose:

- decoder statistics
- gateway-level telegram statistics
- aggregate device statistics
- runtime decoder diagnostics

`gateway/metrics` is gateway-runtime oriented and may aggregate decoder, device-registry and operational counters.

Metrics are intentionally event-driven.

The metrics topic should follow telegram and runtime activity rather than a fixed publication interval.

Example payload:

```json
{
  "rx": {
    "telegrams_total": 9980,
    "telegrams_per_minute": 58.4
  },

  "tx": {
    "telegrams_total": 83,
    "telegrams_per_minute": 0.4
  },

  "decoder": {
    "decoded_telegrams_total": 9980,
    "decode_errors_total": 17
  },

  "devices": {
    "known_devices_total": 42,
    "unknown_devices_total": 6,
    "active_devices_total": 37
  },

  "last_sender_id": "059AB3A6"
}
```

```"active_devices_total"``` = number of known devices from which at least one telegram was observed within the active device window (a configurable sliding observation window defined in the Metrics Calculation Policy section).

Retain:

```text
true
```

---

### Gateway Log

```text
<base_topic>/gateway/log
```

Purpose:

- structured runtime events
- informational messages
- warnings
- lifecycle events
- import and discovery notifications

Retain:

```text
false
```

---

### Gateway Error

```text
<base_topic>/gateway/error
```

Purpose:

- structured runtime exceptions
- unrecoverable runtime errors
- parser failures
- MQTT connection failures
- configuration and registry errors

Retain:

```text
false
```

---

### Gateway Uptime

```text
<base_topic>/gateway/uptime
```

Payload:

```text
seconds
```

The uptime topic is interval-driven and independent from telegram throughput.

Retain:

```text
true
```

---

### Gateway Version

```text
<base_topic>/gateway/version
```

Payload:

```text
version string
```

Source of truth:

```text
VERSION
```

The version topic is published once during startup and retained.

Retain:

```text
true
```

---

## Timestamp Policy

All JSON payloads containing timestamps should use two timestamp fields:

```json
{
  "timestamp_local": "2025-06-13T06:16:29.764+02:00",
  "timestamp_unix": 1749788189.764
}
```

Target architecture:

- `timestamp_local` should use the timezone configured in the application settings.
- If no timezone is configured, UTC with `Z` suffix should be used.
- `timestamp_unix` should always be included for unambiguous machine processing.

All published MQTT timestamps should be normalized to millisecond precision. ISO 8601 timestamps should use exactly three fractional second digits, and Unix timestamps should be represented as seconds with millisecond precision.

Additional timestamp formats should be avoided in normal MQTT payloads.

---

## Metrics Calculation Policy

Metrics using moving averages or peak calculations are based on configurable sliding observation windows.

The observation windows are intentionally configurable.

Default configuration:

```json
{
  "metrics": {
    "peak_telegrams_window_seconds": 900,
    "telegram_mean_interval_window_seconds": 3600,
    "active_device_window_seconds": 86400
  }
}
```

| Field | Meaning |
|---|---|
| `peak_telegrams_window_seconds` | Observation window for `peak_telegrams_per_minute` calculations |
| `telegram_mean_interval_window_seconds` | Observation window for `telegram_mean_interval_seconds` calculations |
| `active_device_window_seconds` | Observation window for `active_devices_total` determination |

---

## Retain Policy Summary

| Topic class | Retain |
|---|---|
| Busmonitor RX/TX event streams | false |
| Busmonitor raw telegrams | false |
| Busmonitor metrics | true |
| Busmonitor unknown devices | true |
| Device info | true |
| Device metrics | true |
| Device state | true |
| Device channel value | true |
| Device channel state | true |
| Device message set | false |
| Virtual device info | true |
| Virtual device metrics | true |
| Virtual device state | true |
| Virtual device channel set | false |
| Gateway status | true |
| Gateway EnOcean connection | true |
| Gateway runtime mode | true |
| Gateway health | true |
| Gateway metrics | true |
| Gateway log | false |
| Gateway error | false |
| Gateway command | false |
| Gateway uptime | true |
| Gateway version | true |

---

## Topic Naming Rules

- Topic levels should be lowercase, except for EnOcean EURIDs.
- EnOcean EURIDs used as `device_id` or `sender_id` must be uppercase hexadecimal without `0x` prefix.
- Human-readable device names belong into JSON payloads, not topic levels.
- Spaces are not allowed in topic levels.
- Channel names should use `snake_case`.
- Aliases should use `snake_case` and must be unique.

Examples:

```text
valid:   enocean/device/52523B1A/channel/temperature/state
valid:   enocean/device/52523B1A/channel/temperature/value
valid:   enocean/device/059E0500/message/switch/set
valid:   enocean/virtual/gateway_temperature/channel/temperature/set
valid:   enocean/alias/th_badezimmer/channel/temperature/state
invalid: enocean/device/0x52523b1a/channel/Temperature/state
invalid: enocean/alias/TH Badezimmer/channel/temperature/state
```

---

## Runtime Commands

Runtime commands are specified separately in [Runtime Commands](../runtime-commands.md).

Relevant topic:

```text
<base_topic>/gateway/command
```

Runtime commands must not be retained.

---

## Future Extensions

Potential future MQTT model extensions may include:

- per-device publish policies
- global default publish policies
- periodic forced republish of metadata
- advanced stale-value handling
- runtime quality propagation
- open bridge server (OBS)-driven publish policy generation
- dynamic runtime throttling

---

## Open Design Questions

- TX retry and acknowledgement handling
- OBS MQTT adapter mapping details
- binary payload handling versus hex-only representation
- retained cleanup strategy when devices are removed or renamed
- runtime command authentication and authorization
