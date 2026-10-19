# Changelog

User-facing releases of enocean-mqtt. Public release history starts with 0.9.0.
For support boundaries, see [Known Limitations](KNOWN_LIMITATIONS.md).

## 0.10.0 — 2026-10-19

- Add external gateway/channel management, passive command decoding and scoped
  metrics. See [gateway setup and limitations](userguide/gateways.md).
- Add RX screening diagnostics, busmonitor highlighting and a dashboard gateway count.
- Improve virtual-device naming and pause normal transmission when disabled,
  while retaining cached inputs and explicit Teach-In.
- Support numeric profile conditions and labelled enum ranges; simplify existing
  profiles without changing their numeric values or meanings.
- Include new and revised profiles; the exact changes are listed below.
  Updated range-based profiles require the 0.10.0 runtime.

### Migration and scope

External gateway command observations now use
`<base_topic>/devices/gateways/<BASE_ID>/<SENDER_ID>/command`. Update subscriptions
and ACLs from `gateways/<BASE_ID>/channels/<SENDER_ID>/command`; remove obsolete
retained topics explicitly. Retained observations are not actuator state or
proof of online status.

D2 remains experimental and bidirectional 4BS Teach-In does not work. Offline
regression checks do not replace model-specific hardware or OBS acceptance.

<!-- profile-changes:start -->
### Profile changes

- Added profiles: `A5-05-01`, `A5-06-01`, `A5-06-02`, `A5-06-03`, `A5-06-04`, `A5-06-05`, `A5-07-01`, `A5-07-02`, `A5-07-03`, `A5-08-01`, `A5-08-02`, `A5-08-03`, `A5-38-08`, `D2-01-00`.
- Updated profiles: `A5-04-01`, `A5-04-04`, `A5-14-01`, `A5-14-02`, `A5-14-03`, `A5-14-04`, `A5-14-05`, `A5-14-06`, `A5-14-08`, `A5-14-09`, `A5-20-01`, `A5-20-06`, `D2-01-0E`, `eltako-fud70s`.
<!-- profile-changes:end -->

## 0.9.0 — 2026-10-14

First public pre-1.0 version for user testing. Interfaces and configuration may
still evolve on the way to 1.0.0.

### Available functionality

- EnOcean ESP3 reception and transmission, with USB300 as the tested reference interface.
- MQTT gateway with device states, numeric enum values and optional meanings,
  raw telegrams, gateway diagnostics and runtime commands.
- REST API and Web UI for monitoring, configuration and device management,
  with token authentication, initial admin setup and recovery instructions.
- Physical and virtual devices, CSV device import/export and profile-based encoding.
  Virtual sensors combine cached inputs into complete telegrams after a quiet interval.
- Live/historical Bus Monitor, filters and CSV export, SQLite storage, traffic metrics
  and hardware-free replay of supported capture formats.
- Optional Pushover notifications and API-based integration with open bridge server.
- Linux/Raspberry Pi installation and systemd service instructions, device usage
  guidance and an acceptance checklist in the [User Guide](userguide/README.md).

### Included profiles

The initial public snapshot contains 52 standard and manufacturer-specific profiles.
See the [EEP catalogue](docs/catalogs/eep-list.md),
[manufacturer profiles](docs/catalogs/proprietary-profile-list.md) and
[device catalogue](docs/catalogs/device-list.md) for the available definitions
and recorded test status. Profile availability is not proof of hardware validation
for every compatible device.

### Enum state contract change

Enum states use numeric codes in `value` and, when known, their label in `meaning`.
API discovery offers these as integer and read-only string representations.
Clients using older string/boolean enum values must select the numeric code or
`meaning` instead, refresh retained states and refresh OBS discovery. Datapoint IDs
and write contracts are unchanged. OBS representation selection requires a separate
adapter update and acceptance test.

### Important limitations

- D2/VLD support is experimental, not stable.
- Bidirectional 4BS Teach-In does not currently work.
- Additional interfaces, secure EnOcean, remote management and Docker deployment
  are not part of the validated release scope.
- MQTT TLS and general outbound profile-constraint enforcement are not implemented;
  delayed virtual TX failures currently require monitoring the MQTT error topic.

Consult [Known Limitations](KNOWN_LIMITATIONS.md) before using this version with
real equipment. A sent telegram is not proof of receiver action or successful pairing.
