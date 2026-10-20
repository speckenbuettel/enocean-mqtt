# Known Limitations

Virtual sensor TX aggregates cached inputs into profile-defined telegrams. Missing
active required values prevent encoding; continuous input updates can postpone
the quiet-interval timer indefinitely. Cached input values have no automatic
freshness expiry and must be initialized again after a gateway restart. Delayed
virtual TX errors are currently published only to the non-retained, QoS-0
`<base_topic>/gateway/error` topic by the virtual error publisher, not additionally
logged there or returned as asynchronous failures to the original API/OBS write.
See [the virtual sensor guide](userguide/devices.md#virtual-sensor-transmission-in-detail).

This page describes the current implementation and validation boundaries for the
first public release. It is not a promise that every configured device, profile
or interface has been tested. See the [User Guide](userguide/README.md) for setup
and the [Changelog](CHANGELOG.md) for changes in a particular release.

## Interfaces and profiles

- External gateway channels, range selection and scoped metrics have offline
  coverage and maintainer-reported basic operation as of 2026-10-16. Web UI layout
  cleanup is deferred; model/profile-specific live acceptance remains open. Historical
  metrics are limited by retention/storage policies; process-local fallback
  excludes earlier runs. Existing non-aligned manual gateway ranges require
  review rather than automatic migration. Gateway ownership alone does not mean
  that a channel has an EEP, and local sender-ID collisions need operator review.
  No command observation proves actuator state. See the
  [gateway work list](userguide/gateways.md#open-work-recorded-on-2026-10-16).

- The Registry TX encoder does not evaluate telegram `constraints[]`. Simple
  numeric field scalings clamp to their raw range and may round inputs;
  semantic `ranges[]` are not TX input validation. Profile JSON alone cannot
  enforce these rules for outbound telegrams. Before physical use of D2-01-0E
  measurement configuration, callers must validate MAT in `10..2550` in steps
  of `10`, MIT in `1..255` in integer steps, and `MAT >= MIT` on the semantic
  interval values before encoding. Zero intervals and inverted bounds can
  otherwise be accepted. The stricter bounds of composite `field_parts` values
  do not add general TX constraint enforcement. See the
  [runtime encoder implementation](src/enocean_mqtt/eep/runtime_encoder.py).

- Startup skips virtual devices whose EEP profile is missing, unreadable
  or invalid, logging an error per device. Other devices continue registering.
  Skipped devices receive no MQTT command subscriptions; restore their profiles
  and restart or reload virtual devices to retry. This does not select compiler
  candidates automatically or disable their persisted configuration.

- EnOcean USB300 is the reference interface for maintainer-reported live RX/TX
  tests. Other ESP3-compatible interfaces require their own hardware validation;
  protocol compatibility alone is not a hardware support guarantee.
- Hardware-free replay can exercise decoding and downstream processing. It does
  not test the physical serial link, radio reception, transmission or pairing.
- Only the explicitly selected profiles shipped with a release are in its scope.
  A profile file or successful compiler run alone does not establish complete
  RX/TX, Teach-In or real-device support. Related TYPE variants need individual
  validation, including their ranges, units, enums and command bindings.
- The D2/VLD EEP family is not yet stably implemented and is not part of the
  stable supported release scope. Individual D2 profiles remain experimental;
  their presence does not establish stable RX/TX or Teach-In support. Do not
  infer D2 support from successful A5, D5 or F6 tests.
- Bidirectional 4BS Teach-In does not currently work and is not supported in
  this release. Ordinary 4BS data transmission or sending a unidirectional
  Teach-In telegram does not establish bidirectional Teach-In support.
- A successfully sent Teach-In telegram does not prove that a receiver accepted
  pairing. Likewise, an accepted/transmitted command does not prove the requested
  physical state was reached; that requires suitable device feedback or observation.

## API and integrations

The device-specific HTTP republish operation currently returns
`501 Not Implemented` when its handler is reached:

| Operation | Current limitation |
|---|---|
| `POST /api/v1/devices/{device_id}/republish` | Device republishing through this HTTP endpoint is not implemented. |

`POST /api/v1/datapoints/{datapoint_id}/value` is implemented for writable physical
message datapoints and virtual-device channels, provided their owning TX runtime
is available. An `accepted` response is not receiver confirmation or proof of a
physical state change. Profile-specific API/OBS end-to-end acceptance remains open.

The republish gap does not mean that all transmission or runtime commands are unavailable.
Consult the [runtime command contract](docs/runtime-commands.md) for implemented
command paths. An endpoint's presence in Swagger/OpenAPI is not evidence of a
working end-to-end operation. The API directions required by a specific client
must be tested before that workflow is described as supported.

The dedicated open bridge server adapter is undergoing integration testing. Final
acceptance of discovery, updates, commands, authentication and reconnect behavior
remains open. Existing MQTT integration and the dedicated adapter are separate
integration paths.

Enum state values are numeric codes with an optional string `meaning`. Existing
clients comparing enum values to strings or booleans must migrate; the OBS adapter's
selection of value versus meaning requires its own update and acceptance. See the
[2026-10-001 migration notes](CHANGELOG.md#enum-state-contract-change).

The busmonitor live SSE stream buffers only while a client is connected and drops
its backlog after the last disconnect. It is not a history archive; use telegram
queries for stored history. Connected clients currently share a single queue, so
multiple simultaneous busmonitors may divide live events rather than each receive
every event. Slow consumers can still overflow the bounded live queue; this does
not by itself imply lost radio reception, MQTT processing or stored telegrams.

## Deployment and security boundaries

- MQTT TLS is not currently implemented by the gateway's MQTT configuration/client
  path. Use a trusted, appropriately isolated network; API authentication does not
  encrypt MQTT traffic.
- Configure API/Web UI authentication as described in the User Guide. Do not expose
  the service directly to the public Internet. A deployment requiring remote access
  needs separately configured and tested transport protection and access controls.
- FastAPI's default interactive API documentation loads browser assets from
  external URLs, including CDN scripts/styles, a hosted favicon and Google Fonts
  for ReDoc. Swagger/ReDoc may therefore not render in an offline browser even
  when the local API itself is reachable.
- A native Linux installation, optionally run as a systemd service, is the current
  deployment path. Docker supports Linux AMD64/ARM64 through the
  [container deployment guide](userguide/docker.md). Container acceptance checks
  are hardware-free; USB hotplug may require recreation and Linux device permissions
  remain host-specific. Docker Desktop USB passthrough is not part of that scope.
- EnOcean Secure and remote management/commissioning are future work and are not
  part of the initial supported feature set.

## Reporting additional limitations

Use the [public issue tracker](https://github.com/speckenbuettel/enocean-mqtt/issues)
and follow [CONTRIBUTING.md](CONTRIBUTING.md). Include the version and precise
operation tested, and sanitize configuration, logs and telegram samples first.
