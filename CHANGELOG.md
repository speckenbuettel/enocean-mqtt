# Changelog

User-facing releases of enocean-mqtt. Public release history starts with 0.9.0.
For support boundaries, see [Known Limitations](KNOWN_LIMITATIONS.md).

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
