# Runtime Commands

## Overview

This document defines the runtime command interface for `enocean-mqtt`.

Runtime commands are operational commands. They control the running gateway without requiring a host, container or service restart.

Runtime commands may be transported through:

- MQTT,
- REST / Web API.

Both transports use the same runtime command dispatcher, validation model and command semantics.

MQTT remains the primary lightweight local runtime-command transport.

REST exposes the same command semantics to Web-UI, CLI tooling, integration tests, OBS-related tooling and AI-assisted agents through the Semantic Runtime API.

The identity model used by commands is summarized below. See also the
[MQTT model](specifications/mqtt-model.md) and
[configuration reference](specifications/configuration.md).

---

## EEP cache: `eeps.reload`

EEP definitions are loaded lazily on first use and shared by RX decoding, TX
encoding and busmonitor history decoding within the process. Editing, replacing
or deleting a file does not change a cached definition. There is no automatic
file-change detection. A service restart discards the cache.

Publish `{"command":"eeps.reload"}` without retain to
`<base_topic>/gateway/command`, or send an authenticated
`POST /api/v1/runtime/commands/eeps.reload` with body `{}`. The dashboard provides
the same action as **Validate and reload EEPs**.

The command reads all JSON profiles in the active registry and the standard
fallback registry, giving the active directory precedence for matching names.
It also checks previously cached profiles, so a deleted cached profile without
a fallback rejects the reload. JSON parsing, runtime model construction and
local channel/message/field references must pass for every profile before the
cache is replaced atomically. A failure reports the filename and leaves the
entire previous cache active. This is runtime validation, not compiler validation
or hardware testing. Success logs the loaded filenames and profile count.

New profiles are included by reload even if no device has used them yet. A
previously unused profile can also be loaded on its first use. Missing or invalid
first loads are not cached and may be retried after correcting the file.

Subsequent operations use the replacement definitions; an operation already
holding a definition may finish with its previous version. Reload does not
rewrite stored telegrams, republish old MQTT values, change device assignments
or rebuild device/datapoint inventories. Reload the relevant device inventory
separately when changing its structure. Separate processes have separate caches
and must each reload or restart.

---

## Canonical Identity Model

| Identifier | Applies to | Meaning |
|---|---|---|
| `device_id` | physical device | EURID of a real physical EnOcean device |
| `device_name` | physical device | human-readable physical device name |
| `alias` | physical device | stable MQTT/API-safe technical alias |
| `virtual_device_id` | virtual device | MQTT-visible identity of a gateway-emulated EnOcean device |
| `sender_id` | gateway TX identity | gateway-managed RF sender identity used for outgoing telegrams |

Rules:

- Physical devices are addressed by `device_id` in gateway-layer commands.
- Physical devices are published below `<base_topic>/device/<device_id>/...` in MQTT.
- Alias topics are optional mirrors below `<base_topic>/alias/<alias>/...`.
- Virtual devices are addressed by `virtual_device_id` in gateway-layer commands.
- Virtual devices are published below `<base_topic>/virtual/<virtual_device_id>/...` in MQTT.
- `sender_id` is not the primary identity of a physical device.
- `sender_id` is reserved for gateway-managed EnOcean TX identities used by bidirectional physical devices and virtual devices.
- High-level REST clients should normally use API devices and datapoints rather than sender IDs.

---

## Runtime Command Transports

### MQTT Transport

All global runtime commands use:

```text
<base_topic>/gateway/command
```

Example:

```text
enocean-mqtt/gateway/command
```

Retain:

```text
false
```

QoS:

```text
1
```

### REST Transport

The REST projection of runtime commands uses:

```text
POST /api/v1/runtime/commands/{command_name}
```

Conceptual request:

```json
{
  "payload": {},
  "transaction_id": "optional-client-id"
}
```

For commands that naturally map to resource-oriented API actions, the Web API may expose convenience endpoints such as:

```text
POST /api/v1/devices/import
POST /api/v1/devices/{device_id}/republish
POST /api/v1/runtime/commands/devices.reload
```

Such endpoints shall dispatch the same runtime command logic. They must not introduce a second command model.

### Shared Command Semantics

The following rule is normative:

```text
MQTT command payload
REST command request
        ↓
same runtime command dispatcher
        ↓
same validation
        ↓
same runtime side effects
        ↓
same structured command result semantics
```

---

## Runtime Response Model

MQTT runtime command responses and operational events are published via:

```text
<base_topic>/gateway/log
<base_topic>/gateway/error
<base_topic>/gateway/health
<base_topic>/gateway/runtime_mode
```

REST command responses should return structured command results directly and may also cause the normal MQTT/runtime event publications where the command changes runtime state.

Structured command results should include, where applicable:

| Field | Meaning |
|---|---|
| `command` | command name |
| `accepted` | whether the command was accepted for processing |
| `status` | `completed`, `failed`, `rejected` or `pending` |
| `transaction_id` | optional client-provided transaction identifier |
| `message` | human-readable summary |
| `errors` | structured validation or runtime errors |
| `result` | command-specific result payload |

---

## Runtime State Model

Supported runtime modes:

```text
live
replay
```

The active runtime mode is published via:

```text
<base_topic>/gateway/runtime_mode
```

Retain:

```text
true
```

Parallel runtime modes are not supported. Replay mode must be started explicitly via runtime command.

---

## Command Payload Classes

Simple MQTT commands use a plain UTF-8 payload:

```text
devices.reload
```

Complex MQTT commands use JSON payloads:

```json
{
  "command": "replay.start",
  "capture_file": "testdata/weinzierl/EnoTelListe1.enolog",
  "interval_seconds": 1.0
}
```

Parsing rule for MQTT payloads:

```text
payload starts with "{" → parse as JSON command
otherwise               → parse as simple string command
```

For JSON commands, the field `command` is mandatory.

REST commands use the path command name and an optional `payload` object.

---

## Structured Validation Errors

Runtime command validation failures publish structured runtime errors via MQTT:

```text
<base_topic>/gateway/error
```

REST command validation failures shall return structured API errors or structured command results.

Examples:

- invalid JSON payload,
- unknown command,
- missing required argument,
- unknown argument,
- invalid argument type,
- invalid runtime state transition,
- missing import or replay file,
- invalid device definition,
- invalid virtual device definition.

---

# Gateway Lifecycle Commands

## gateway.exit

Purpose:

- request graceful runtime exit,
- stop replay runtime if active,
- publish offline state,
- disconnect MQTT cleanly.

Simple MQTT payload:

```text
gateway.exit
```

Complex MQTT payload:

```json
{
  "command": "gateway.exit"
}
```

REST projection:

```text
POST /api/v1/runtime/commands/gateway.exit
```

---

## gateway.restart

Purpose:

- request graceful runtime restart,
- stop replay runtime if active,
- allow supervisor, systemd or container policy to restart the process.

Simple MQTT payload:

```text
gateway.restart
```

Complex MQTT payload:

```json
{
  "command": "gateway.restart"
}
```

REST projection:

```text
POST /api/v1/runtime/commands/gateway.restart
```

---

## gateway.stop

Status:

```text
deprecated
```

`gateway.stop` remains temporarily supported as compatibility alias for:

```text
gateway.exit
```

New integrations must use `gateway.exit`.

---

# Retained Topic Recovery Commands

## gateway.republish

Purpose:

- republish retained gateway/runtime topics,
- restore retained gateway MQTT state after broker restart.

Republished topics include:

```text
gateway/status
gateway/runtime_mode
gateway/version
gateway/health
gateway/metrics
gateway/uptime
busmonitor/metrics
```

Simple MQTT payload:

```text
gateway.republish
```

Complex MQTT payload:

```json
{
  "command": "gateway.republish"
}
```

REST projection:

```text
POST /api/v1/runtime/commands/gateway.republish
```

---

## devices.republish

Purpose:

- republish retained physical device metadata topics,
- republish retained aggregate physical device state topics where runtime state is available,
- restore selected retained physical device topics after MQTT broker restart.

Republished topics:

```text
device/<device_id>/info
device/<device_id>/state
```

If alias topic publication is enabled, the same selected topics are mirrored below:

```text
alias/<alias>/info
alias/<alias>/state
```

`devices.republish` does not republish per-channel topics because those are event-derived runtime topics and are not reconstructed by this command.

Simple MQTT payload:

```text
devices.republish
```

Complex MQTT payload:

```json
{
  "command": "devices.republish"
}
```

REST projection:

```text
POST /api/v1/runtime/commands/devices.republish
```

---

# Interface Runtime Commands

Interface runtime commands control configured EnOcean transport interfaces without restarting the gateway process.

Interfaces are identified by `interface_id`. The `interface_id` is the configured runtime name of one physical EnOcean interface, for example `usb300_01`.

The interface base ID is not modeled as a global gateway identity. It belongs to the interface and should be sourced from `config/sender-id-registry.json` where possible:

```json
{
  "interfaces": [
    {
      "interface_id": "usb300_01",
      "base_id": "FFAA8000",
      "allocated_sender_ids": []
    }
  ]
}
```

If a single interface is configured, `interface_id` may be omitted from MQTT command payloads. If multiple interfaces are configured, commands that target one interface must include `interface_id`.

---

## interface.status

Purpose:

- return status for one configured EnOcean interface or all configured interfaces,
- expose connection state, serial port, transport status, optional base ID and transport metrics,
- support Web-UI and diagnostic tooling.

Simple MQTT payload:

```text
interface.status
```

Complex MQTT payload for one interface:

```json
{
  "command": "interface.status",
  "interface_id": "usb300_01"
}
```

REST projection:

```text
GET /api/v1/interfaces
GET /api/v1/interfaces/{interface_id}
POST /api/v1/runtime/commands/interface.status
```

---

## interface.connect

Purpose:

- connect one configured EnOcean interface at runtime,
- open the configured serial ESP3 device,
- start receiving ESP3 RADIO_ERP1 telegrams,
- publish updated gateway health/interface status.

Complex MQTT payload:

```json
{
  "command": "interface.connect",
  "interface_id": "usb300_01"
}
```

REST projection:

```text
POST /api/v1/interfaces/{interface_id}/connect
POST /api/v1/runtime/commands/interface.connect
```

---

## interface.disconnect

Purpose:

- disconnect one running EnOcean interface at runtime,
- close the serial device,
- stop receiving and transmitting through that interface,
- keep the gateway process and MQTT/Web API online.

Complex MQTT payload:

```json
{
  "command": "interface.disconnect",
  "interface_id": "usb300_01"
}
```

REST projection:

```text
POST /api/v1/interfaces/{interface_id}/disconnect
POST /api/v1/runtime/commands/interface.disconnect
```

---

## interface.reconnect

Purpose:

- disconnect and reconnect one EnOcean interface,
- support manual recovery after USB reconnects, serial permission fixes or device replacement.

Complex MQTT payload:

```json
{
  "command": "interface.reconnect",
  "interface_id": "usb300_01"
}
```

REST projection:

```text
POST /api/v1/interfaces/{interface_id}/reconnect
POST /api/v1/runtime/commands/interface.reconnect
```

---

## interface.network_bridge.start

Purpose:

- switch one configured EnOcean interface from `enocean-mqtt` ownership to a managed ser2net TCP bridge,
- stop the running ESP3 serial transport before ser2net opens the same serial device,
- expose the configured serial ESP3 device for external diagnostic tools,
- keep the gateway process, MQTT and Web API online while RF reception/transmission by `enocean-mqtt` is paused for that interface.

Complex MQTT payload:

```json
{
  "command": "interface.network_bridge.start",
  "interface_id": "usb300_01"
}
```

REST projection:

```text
POST /api/v1/interfaces/{interface_id}/network-bridge/start
POST /api/v1/runtime/commands/interface.network_bridge.start
```

The runtime must verify that the configured `ser2net` binary is available before disconnecting the ESP3 transport.

---

## interface.network_bridge.stop

Purpose:

- stop the managed ser2net process for one interface,
- leave the interface disconnected until `interface.connect` or `interface.reconnect` is requested,
- make the serial device available to `enocean-mqtt` again.

Complex MQTT payload:

```json
{
  "command": "interface.network_bridge.stop",
  "interface_id": "usb300_01"
}
```

REST projection:

```text
POST /api/v1/interfaces/{interface_id}/network-bridge/stop
POST /api/v1/runtime/commands/interface.network_bridge.stop
```

---

## interface.network_bridge.restart

Purpose:

- restart the managed ser2net bridge for one interface,
- perform the same availability and ownership checks as `interface.network_bridge.start`.

REST projection:

```text
POST /api/v1/interfaces/{interface_id}/network-bridge/restart
POST /api/v1/runtime/commands/interface.network_bridge.restart
```

---

## Interface Startup Semantics

Configured interfaces with `enabled: true` are connected during runtime startup.

Configured interfaces with `enabled: false` remain idle even if the physical device is attached. They can be connected later only if configuration and runtime policy allow manual connection.

The current implementation provides manual runtime connect/disconnect/reconnect controls. Automatic hotplug retry based on reconnect settings is a planned follow-up.

# Replay Runtime Commands

## replay.start

Purpose:

- start a replay runtime session,
- switch runtime mode to `replay`,
- load the configured replay source file,
- process replay telegrams through the normal runtime pipeline,
- support deterministic runtime and regression tests.

Complex MQTT payload:

```json
{
  "command": "replay.start",
  "capture_file": "testdata/weinzierl/EnoTelListe1.enolog",
  "interval_seconds": 1.0,
  "limit": null
}
```

REST projection:

```text
POST /api/v1/runtime/commands/replay.start
```

REST request:

```json
{
  "payload": {
    "capture_file": "testdata/weinzierl/EnoTelListe1.enolog",
    "interval_seconds": 1.0,
    "limit": null
  }
}
```

Fields:

| Field | Meaning |
|---|---|
| `capture_file` | replay source file |
| `interval_seconds` | replay delay between telegrams in seconds |
| `limit` | optional telegram limit |

---

## replay.stop

Purpose:

- stop the active replay runtime,
- restore live runtime mode.

Simple MQTT payload:

```text
replay.stop
```

Complex MQTT payload:

```json
{
  "command": "replay.stop"
}
```

REST projection:

```text
POST /api/v1/runtime/commands/replay.stop
```

---

## Runtime State Transition Rules

| Current Mode | Command | Result |
|---|---|---|
| `live` | `replay.start` | allowed |
| `replay` | `replay.start` | rejected |
| `replay` | `replay.stop` | allowed |
| `live` | `replay.stop` | rejected |

Replay completion automatically restores:

```text
runtime_mode = live
```

---

# Physical Device Registry Runtime Commands

Physical device registry commands operate on the runtime physical device registry and its persisted JSON representation.

Physical devices are addressed by `device_id` at gateway-command level.

The runtime physical device registry is persisted in:

```text
config/devices.json
```

Physical device registry commands do not modify the virtual device registry. They modify the sender ID registry only when a deleted bidirectional physical device releases a gateway-managed TX sender allocation.

---

## device.import

Status:

```text
experimental
```

Purpose:

- import exactly one physical device via command JSON,
- create or update one runtime registry entry,
- persist updated `devices.json`,
- activate the updated registry without process restart.

Complex MQTT payload:

```json
{
  "command": "device.import",
  "device": {
    "device_id": "0185286B",
    "device_name": "Living Room Sensor",
    "alias": "living_room_sensor",
    "eep": "A5-04-02",
    "profile": "A5-04-02",
    "manufacturer": "Eltako",
    "model": "FTFSB",
    "description": "Living room temperature sensor",
    "enocean_secure": false,
    "enabled": true,
    "metadata": {
      "room": "Living Room",
      "floor": "EG",
      "equipment_id": "-BT101"
    }
  }
}
```

REST projection:

```text
POST /api/v1/runtime/commands/device.import
```

REST convenience endpoint may be provided:

```text
POST /api/v1/devices/import
```

Minimum required physical device fields:

| Field | Meaning |
|---|---|
| `device_id` | physical device EURID |
| `device_name` | human-readable name |
| `profile` | runtime receive-side decoder profile |

For standard EEP devices, `profile` normally equals `eep`.

---

## devices.import

Purpose:

- import physical devices from a CSV file,
- create or update runtime registry entries,
- persist updated `devices.json`,
- activate the updated registry without process restart,
- remove promoted devices from the unknown-device registry,
- publish or republish retained `info` and available aggregate `state` topics for imported devices.

Complex MQTT payload using the configured default import path:

```json
{
  "command": "devices.import"
}
```

Complex MQTT payload using an explicit import file:

```json
{
  "command": "devices.import",
  "import_file": "config/devices-import.csv"
}
```

REST projection:

```text
POST /api/v1/runtime/commands/devices.import
POST /api/v1/devices/import
```

Fields:

| Field | Meaning |
|---|---|
| `import_file` | optional CSV import file; if omitted, the configured default devices CSV import path is used |

The import operation is an upsert operation keyed by `device_id`.

Semantics:

- A CSV row with a new `device_id` creates a new physical device entry.
- A CSV row with an existing `device_id` updates the existing physical device entry.
- Existing registry entries not present in the CSV file are not deleted.
- Physical device import does not create virtual devices.
- Physical device import does not allocate gateway-managed TX sender IDs.
- Physical device import does not modify the sender ID registry.

The runtime must reject the command if the resolved CSV file does not exist or is empty.

### Canonical CSV Fields

The canonical physical device CSV format contains:

```text
device_id
device_name
alias
eep
profile
description
manufacturer
model
enocean_secure
floor
room
equipment_id
```

Fields not included in the base CSV exchange format:

```text
communication
sender_id
tx_eep
tx_profile
```

TX-specific physical device fields belong to the JSON device registry model and are not part of the base CSV import/export format.

---

## devices.export

Purpose:

- export the current runtime physical device registry to CSV,
- support reviewable device inventory snapshots,
- support external editing and later `devices.import`,
- support backup and migration workflows.

Complex MQTT payload using the configured default export path:

```json
{
  "command": "devices.export"
}
```

Complex MQTT payload using an explicit export file:

```json
{
  "command": "devices.export",
  "export_file": "config/devices-export.csv"
}
```

REST projection:

```text
POST /api/v1/runtime/commands/devices.export
GET  /api/v1/devices/export
```

Fields:

| Field | Meaning |
|---|---|
| `export_file` | optional CSV export file; if omitted, the configured default devices CSV export path is used |

The export operation is read-only with respect to the runtime registry. It does not change `devices.json`, MQTT retained topics, sender allocations, virtual devices, runtime mode or replay state.

The exported CSV uses the canonical CSV fields defined for `devices.import`.

---

## devices.reload

Purpose:

- reload the physical device registry from `config/devices.json`,
- replace the in-memory runtime device registry with the persisted registry,
- activate changed physical device definitions without process restart,
- clear retained MQTT topics for physical devices removed from the registry,
- republish retained `info` and available aggregate `state` topics for loaded devices.

Simple MQTT payload:

```text
devices.reload
```

Complex MQTT payload:

```json
{
  "command": "devices.reload"
}
```

REST projection:

```text
POST /api/v1/runtime/commands/devices.reload
```

Reload flow:

```text
config/devices.json
→ runtime physical device registry
→ retained MQTT cleanup for removed devices
→ retained info/state publication for active devices
→ datapoint projection refresh
```

For physical devices removed by the reload operation, retained cleanup must include physical device metadata, metrics, aggregate state, and channel state/value topics for both the authoritative device branch and optional alias branch.

The command does not modify CSV import/export files, virtual devices, replay files or historical busmonitor data.

---

## device.delete

Status:

```text
experimental
```

Purpose:

- delete exactly one physical device,
- remove the device from `devices.json`,
- remove the device from the runtime physical device registry,
- clear retained MQTT topics belonging to the physical device,
- release a gateway-managed TX sender ID if the physical device has one,
- persist the updated device registry,
- persist the updated sender registry if a sender allocation was released,
- refresh the datapoint projection.

Complex MQTT payload:

```json
{
  "command": "device.delete",
  "device_id": "05139B47"
}
```

REST projection:

```text
POST   /api/v1/runtime/commands/device.delete
DELETE /api/v1/devices/{device_id}
```

Fields:

| Field | Meaning |
|---|---|
| `device_id` | canonical identity of the physical device to delete |

The runtime must clear retained physical device metadata, metrics, aggregate state, and channel state/value topics for both the authoritative device branch and optional alias branch.

Released sender IDs may later be reused according to the sender registry allocation rules.

---

## device/<device_id>/command

Purpose:

- execute runtime actions on one configured physical device,
- trigger bidirectional device teach-in transmission,
- use the assigned gateway-managed `sender_id` for outgoing RF telegrams.

Physical-device-local MQTT runtime actions use:

```text
<base_topic>/device/<device_id>/command
```

If alias topic publication is enabled, the alias mirror uses:

```text
<base_topic>/alias/<alias>/command
```

Supported payload:

```json
{
  "command": "teach_in"
}
```

The command is accepted only for TX-capable physical devices, currently devices whose `communication` value is:

```text
bidirectional_eep
bidirectional_eep_pair
```

The target device must have:

| Field | Meaning |
|---|---|
| `sender_id` | gateway-managed EnOcean sender EURID used for the outgoing telegram |
| `tx_profile` or controller mapping | TX-capable EEP profile used to determine the teach-in payload |

For A5 profiles, the runtime generates a standard 4BS teach-in payload from the TX profile FUNC/TYPE and the manufacturer ID configured in:

```text
config/sender-id-registry.json
```

Example for A5-20-06 with manufacturer `760`:

```text
A5 80 37 60 80 <sender_id> 00
```

---

# Unknown Device Runtime Commands

## unknown_devices.export

Purpose:

- export the current unknown-device registry,
- support later review and promotion into the physical device registry,
- support commissioning workflows.

Complex MQTT payload using the configured default export path:

```json
{
  "command": "unknown_devices.export"
}
```

Complex MQTT payload using an explicit export file:

```json
{
  "command": "unknown_devices.export",
  "export_file": "config/unknown-devices-export.csv"
}
```

REST projection:

```text
POST /api/v1/runtime/commands/unknown_devices.export
```

Fields:

| Field | Meaning |
|---|---|
| `export_file` | optional export file; if omitted, the configured default unknown-device export path is used |

Promoting an unknown device into the physical device registry must result in a physical device with a canonical `device_id`.

---

# Virtual Device Runtime Commands

Virtual devices are addressed by `virtual_device_id` at gateway-command level.

Virtual devices are persisted in:

```text
config/virtual-devices.json
```

Gateway-managed RF sender identities used by virtual devices are persisted separately in:

```text
config/sender-id-registry.json
```

Virtual devices are published below:

```text
<base_topic>/virtual/<virtual_device_id>/...
```

Virtual devices are not physical devices and must not be represented below the physical MQTT `device` branch.

In the Web API, virtual devices are projected as normal API devices with writable datapoints.

---

## virtual_device.create

Status:

```text
experimental
```

Purpose:

- create exactly one virtual device via command JSON,
- allocate a gateway-managed RF sender ID automatically,
- generate persistent teach-in metadata,
- create or update a runtime virtual device registry entry,
- persist updated `virtual-devices.json`,
- persist updated `sender-registry.json`,
- activate the updated virtual device registry without process restart,
- refresh the API datapoint projection.

Complex MQTT payload:

```json
{
  "command": "virtual_device.create",
  "virtual_device": {
    "virtual_device_id": "weather_station",
    "eep": "A5-04-02",
    "profile": "A5-04-02",
    "channels": [
      "temperature",
      "humidity"
    ],
    "enabled": true
  }
}
```

REST projection:

```text
POST /api/v1/runtime/commands/virtual_device.create
```

REST convenience endpoint may be provided:

```text
POST /api/v1/devices
```

Fields:

| Field | Meaning |
|---|---|
| `virtual_device_id` | canonical MQTT/runtime identity of the virtual device |
| `eep` | official EEP, if applicable |
| `profile` | runtime TX encoder profile |
| `channels` | explicitly enabled TX channels |
| `enabled` | runtime enable state |

The runtime automatically performs sender ID allocation, teach-in method determination, teach-in telegram generation, sender registry persistence, EEP/profile validation and channel validation.

Virtual devices expose writable semantic input channels through MQTT:

```text
<base_topic>/virtual/<virtual_device_id>/channel/<channel>/set
```

and through API datapoints:

```text
/api/v1/devices/{device_id}/datapoints
/api/v1/datapoints/{datapoint_id}/value
```

---

## virtual_device.delete

Status:

```text
experimental
```

Purpose:

- delete one virtual device,
- remove the runtime virtual device registry entry,
- release the allocated gateway-managed RF sender ID,
- persist updated `virtual-devices.json`,
- persist updated `sender-registry.json`,
- clear retained MQTT topics belonging to the virtual device,
- refresh the API datapoint projection.

Complex MQTT payload:

```json
{
  "command": "virtual_device.delete",
  "virtual_device_id": "weather_station"
}
```

REST projection:

```text
POST   /api/v1/runtime/commands/virtual_device.delete
DELETE /api/v1/devices/{device_id}
```

Fields:

| Field | Meaning |
|---|---|
| `virtual_device_id` | canonical identity of the virtual device to delete |

The runtime must remove the virtual device definition, release the associated gateway-managed `sender_id`, persist both registries, and clear retained virtual device topics.

Cleared MQTT topics must include:

```text
virtual/<virtual_device_id>/info
virtual/<virtual_device_id>/metrics
virtual/<virtual_device_id>/state
```

Released sender IDs may later be reused by deterministic sender registry allocation.

---

## virtual/<virtual_device_id>/command

Purpose:

- execute runtime actions on one virtual device,
- trigger teach-in transmission,
- support future TX control workflows.

Virtual-device-local MQTT runtime actions use:

```text
<base_topic>/virtual/<virtual_device_id>/command
```

instead of:

```text
<base_topic>/gateway/command
```

Initial supported payload:

```json
{
  "command": "teach_in"
}
```

REST projection may use:

```text
POST /api/v1/runtime/commands/virtual_device.teach_in
```

or a resource-oriented convenience endpoint:

```text
POST /api/v1/devices/{device_id}/teach-in
```

The runtime must load the persisted teach-in telegram, generate the ERP1 telegram, publish the TX telegram to the TX pipeline, and optionally transmit the telegram via RF.

In live mode with a connected ESP3 interface, the runtime transmits the teach-in telegram via RF and publishes the corresponding TX busmonitor event. Clients must not manually construct raw teach-in payloads.

---

# Registry and Persistence Summary

| Command | Reads | Writes | MQTT retained effect | API projection effect |
|---|---|---|---|---|
| `gateway.republish` | runtime state | none | republishes gateway retained topics | no model change |
| `devices.republish` | runtime physical device registry and runtime state cache | none | republishes device/alias `info` and available aggregate `state` | no model change |
| `devices.import` | CSV import file and runtime physical device registry | `devices.json` | publishes/republishes imported device `info` and available aggregate `state` | refreshes devices/datapoints |
| `devices.export` | runtime physical device registry | CSV export file | none | no model change |
| `devices.reload` | `devices.json` | runtime physical device registry | clears removed device topics and republishes active device `info`/available aggregate `state` | refreshes devices/datapoints |
| `device.import` | command JSON payload | `devices.json` | publishes imported device `info` and available aggregate `state` | refreshes devices/datapoints |
| `device.delete` | runtime physical device registry and sender registry | `devices.json`, optionally `sender-registry.json` | clears deleted physical device retained topics | refreshes devices/datapoints |
| `device/<device_id>/command` | physical device registry and sender registry | live TX state | sends teach-in telegrams for TX-capable physical devices | no model change |
| `virtual_device.create` | command JSON payload and sender registry | `virtual-devices.json`, `sender-registry.json` | publishes virtual device retained topics | refreshes devices/datapoints |
| `virtual_device.delete` | virtual device registry and sender registry | `virtual-devices.json`, `sender-registry.json` | clears deleted virtual device topics | refreshes devices/datapoints |
| `unknown_devices.export` | unknown-device registry | export file | none | no model change |
| `interface.status` | configured interface manager | none | publishes logs/status only | no model change |
| `interface.connect` | configured interface manager | live interface state | updates gateway health/interface status | no model change |
| `interface.disconnect` | configured interface manager | live interface state | updates gateway health/interface status | no model change |
| `interface.reconnect` | configured interface manager | live interface state | updates gateway health/interface status | no model change |
| `interface.network_bridge.start` | configured interface manager and ser2net config | live interface/bridge state | stops ESP3 ownership and starts managed ser2net bridge | no model change |
| `interface.network_bridge.stop` | configured interface manager and bridge state | live interface/bridge state | stops managed ser2net bridge | no model change |
| `interface.network_bridge.restart` | configured interface manager and bridge state | live interface/bridge state | restarts managed ser2net bridge | no model change |

---

# Scope Boundaries

Runtime commands are operational control commands.

They must not become:

- a general-purpose database query API,
- a historical event query API,
- a replacement for SQLite/Web API historical inspection,
- a generic automation rule engine,
- an alternative configuration model,
- a second REST-only command semantics beside MQTT commands.

Runtime commands may modify runtime registries and persisted registry files only where explicitly specified by this document.

---

# Future Extensions

Potential future runtime command extensions may include:

- device capability discovery,
- explicit teach-in workflows for physical devices,
- virtual device update commands,
- runtime schema introspection,
- MQTT command authentication,
- REST command authentication and authorization,
- Web UI provisioning workflows,
- OBS synchronization commands,
- automatic EnOcean interface hotplug/retry handling.
