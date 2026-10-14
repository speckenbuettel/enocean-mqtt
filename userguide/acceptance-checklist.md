# Practical installation and integration checks

Use this checklist with the [installation guide](README.md) and
[device guide](devices.md). Record the gateway version, source revision, installed
profiles, interface, OBS version and test date. Save only sanitized results.
Start with a separate installation, broker namespace and test devices; a second
gateway must not claim production sender IDs or issue unintended actuator commands.

These are manual acceptance checks, not claims that hardware or OBS has already
passed. Mark each item **passed**, **failed** or **not tested**, with a short reason.

## Installation and authentication

- [ ] Install using only the public candidate, without private repository files.
- [ ] Start interactively, then as the documented service. Verify version 2026-10-001
  in the installed candidate, API/OpenAPI and gateway reporting.
- [ ] Create the first admin token, activate authentication, log in and log out.
- [ ] A read token can discover/read values but cannot change devices or write values.
- [ ] A missing token returns 401; an invalid token or insufficient role returns 403.
- [ ] Recover admin access using the guide. Verify the old recovered token is invalid
  and unrelated credentials remain valid. Keep real tokens out of reports.
- [ ] Restart the service; verify configuration, devices and sender IDs persist.

## Devices and imports

- [ ] Register one known physical sensor and check its first new decoded data telegram.
- [ ] Edit its description/location; verify the change survives restart.
- [ ] Reject an invalid ID, duplicate ID/name or unavailable profile in the UI.
- [ ] Export physical devices; reimport a copy with one safe change after checking
  the preview. Verify IDs with leading zeroes and existing devices not in the CSV.
- [ ] Cancel an import with a bad row. Do not treat partial-import behavior as atomic.
- [ ] On an isolated test device, delete the registry entry and verify the expected
  discovery change; subsequent radio reception may appear as unknown again.

## API and OBS reads

Use Swagger **Authorize** or an HTTP client with `Authorization: Bearer <token>`.
The gateway API uses the configured port (default 8001); do not use the
OBS server's own API URL by mistake. Never paste credentials into a URL or screenshot.

| Request | Expected result |
|---|---|
| `GET /api/v1/gateway/status` | Gateway reachable/status returned; verify actual runtime state |
| `GET /api/v1/devices` | Physical/virtual API devices discoverable |
| `GET /api/v1/devices/{id}/datapoints?include_values=true` | Actual datapoint IDs, types, access flags and current values |
| `GET /api/v1/datapoints/{id}/value` | Observation nested in `value`; inspect quality, timestamp, optional meaning |
| `GET /api/v1/datapoints/stream` | SSE observations, including initial snapshot by default; not raw busmonitor traffic |
| `GET /api/v1/gateway/adapter-status` | Adapter-facing gateway status projection |
| `GET /api/v1/gateway/adapter-status/stream` | Adapter-facing SSE updates |

- [ ] Configure OBS with this gateway address/port and the intended token.
- [ ] Browse a physical sensor, a writable virtual sensor and their datapoints.
- [ ] For a known enum, bind numeric **value** and string **meaning** to separate
  compatible OBS objects; verify both update from one actual observation.
- [ ] Verify measurement units/types and timestamp/quality handling; no new telegram
  should be presented as newly measured solely because the adapter reconnected.
- [ ] With a profile-defined unknown enum code in an isolated replay/injection test,
  verify meaning becomes unavailable rather than displaying a stale label.
- [ ] Restart only the test gateway or interrupt its connection safely. Verify OBS
  reports unavailable, reconnects and obtains current data without duplicate storms.

## Writes and radio

- [ ] On a configured virtual sensor, write every required measurement input using
  `POST /api/v1/datapoints/{id}/value`, body `{"value": 20}` or the actual valid value.
  Expect `accepted`; verify later TX/log outcome separately.
- [ ] Verify read-only writes return 409, unknown datapoints 404, missing/invalid
  value 422 and an unavailable TX runtime 503. Profile-dependent failures may occur
  later during snapshot encoding; inspect logs instead of relying on HTTP alone.
- [ ] Repeat the safe virtual write through an OBS output binding using **value**;
  **meaning** must not be offered as writable. Compare raw TX and receiving results.
- [ ] For a reviewed writable physical message, repeat one safe command and verify
  the receiver independently. Do not write an arbitrary numeric example to an actuator.
- [ ] If Teach-In is in scope, follow the receiver manual and record receiver-confirmed
  pairing separately from transmission and the manually stored receiver confirmation.
- [ ] Compare API values with MQTT JSON `value`/`meaning` and the actual device state.

Device-specific `POST /api/v1/devices/{id}/republish` remains 501 and is not required
for OBS's implemented read/write path. Use supported generic runtime commands when
needed; do not interpret republishing cached state as a fresh measurement.

## Replay, idle operation and recovery

- [ ] Without radio hardware, use known replay samples and verify decoding/API/MQTT.
  Mark hardware TX/RX and pairing **not tested**, not passed.
- [ ] Close every Busmonitor tab, allow traffic, then reopen it. Live SSE should
  not replay an idle backlog or report queue-full solely because no client was open.
- [ ] Open only one live Busmonitor for this test; multiple clients currently share
  a queue. For older events use the stored telegram history.
- [ ] Follow the update/backup guidance and restore a test installation with the
  service stopped. Verify device definitions, sender identities and token permissions.

Record failures with the exact step, expected/actual result and sanitized evidence.
Do not mark a release accepted from a successful install or a green unit test alone.
