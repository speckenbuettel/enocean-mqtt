# Changelog

This changelog records user-visible, operational and compatibility-relevant changes to
`enocean-mqtt`. The project uses the chronological `YYYY-MM-NNN` version format defined
in [`docs/project-versioning.md`](docs/project-versioning.md). Broader architectural
context and earlier project evolution are documented in
[`docs/project-history.md`](docs/project-history.md).

## Unreleased

### Added

- Added `GET /api/v1/busmonitor/metrics/telegram-activity` for server-side SQLite
  aggregation of the `1h`, `24h`, `3d` and `7d` activity ranges used by the EnOcean
  Metrics Web UI.
- Added RX known/unknown aggregation based on the current physical-device registry while
  retaining TX as a single total series.

### Changed

- Changed the EnOcean Metrics activity charts to consume bounded server-side aggregates
  instead of downloading and aggregating paginated raw telegram history in the browser.
- Structured the Web UI Settings page into collapsible Application, EnOcean, MQTT,
  SQLite, API and Logging groups while retaining the existing API-backed configuration
  workflow.
- Replaced the Device Management placeholder with an API-backed registry workspace for
  physical, virtual and unknown devices, including statistics, search and filtering,
  editing, deletion, CSV import previews and CSV exports.
- Added physical and virtual teach-in actions plus explicit user-confirmed receiver
  records, so receiver assignments are not presented as automatically verified when the
  EnOcean teach-in method provides no acknowledgement.

## 2026-08-003 — 2026-08-29

### Added

- Added operating-system-backed singleton protection to prevent multiple gateway
  runtimes from using the same installation concurrently.
- Added regression coverage for singleton acquisition and process-level restarts.

### Changed

- Changed `gateway.restart` to re-execute the current process after orderly runtime
  cleanup, allowing the command to work consistently under systemd and Docker.
- Consolidated the completed development runtime into `main` as the new stable internal
  baseline.
- Removed obsolete standalone TX-profile JSON files after migration to the Registry-v3
  runtime model.
- Refined the Runtime Web UI and added browser favicon support.

### Fixed

- Corrected the process-restart callback contract to match `os.execv` and restored clean
  static type checking.

## 2026-08-002 — 2026-08-28

### Added

- Added a structured Web UI Settings editor for all supported configuration sections.
- Added timezone and default-interface selectors and form-based EnOcean interface
  management.
- Added MQTT password handling through the configured secrets file.
- Added Web API token creation, role selection and deletion in the Web UI.
- Added direct gateway restart after saving settings that require a restart.
- Added live EnOcean activity views with selectable time ranges.
- Added `message_load_15mins`, Web API and Web UI state to gateway health telemetry.
- Added a configurable active-device metrics window.

### Changed

- Consolidated EnOcean serial settings below `enocean.interfaces`.
- Replaced `enocean.default_interface_id` with `enocean.default_interface`.
- Removed redundant top-level serial, status and runtime-command configuration blocks.
- Made live mode the fixed startup mode; replay is now selected explicitly at runtime.
- Applied MQTT clean-session and reconnect timing settings in the runtime.
- Fixed gateway, LWT and runtime-command topic structures according to the canonical MQTT
  model.
- Aligned MQTT event and health payloads with the finalized model and standardized
  timestamps to exactly three fractional digits.
- Made the Settings, Dashboard, Busmonitor and Metrics layouts denser and responsive.

### Fixed

- Corrected Dashboard RX/TX state reporting for configured EnOcean interfaces.
- Restored TX teach-in metadata in the MQTT event stream.
- Serialized concurrent SQLite RX and TX writes.
- Prevented persistence, MQTT and decoding callback failures from terminating the ESP3
  serial reader.

### Migration notes

- Existing production configurations must be recreated or migrated using
  `config/config.example.json` and `docs/specifications/configuration.md`.
- Use `enocean.default_interface`; `enocean.default_interface_id` is no longer supported.
- Restart the gateway after saving restart-dependent configuration changes.

## 2026-08-001 — 2026-08-21

### Added

- Added stable live USB300 reception and transmission on Raspberry Pi hardware.
- Added named multi-interface management with default TX routing, reconnect controls,
  optional network bridges and per-interface sender-ID allocation.
- Added ESP3 transport metrics for frames, RADIO_ERP1 telegrams, bytes, CRC errors,
  unsupported packet types and last RX/TX activity.
- Added bidirectional Registry-v3 based communication for physical and virtual devices,
  including semantic MQTT commands and teach-in generation.
- Added the runtime service facade and semantic REST API for devices, datapoints and
  current runtime values.
- Added versioned gateway status, health, metrics, EnOcean, busmonitor and runtime-command
  API endpoints.
- Added authenticated runtime-command execution over HTTP using the same command semantics
  as MQTT.
- Added semantic datapoint updates over Server-Sent Events for API clients.
- Added the authenticated Web UI application with session login, role-based API tokens,
  Dashboard and Busmonitor workflows.
- Added SQLite-backed telegram history, decode-on-read queries and live event streaming.

### Changed

- Routed physical and virtual TX through the shared ESP3 interface manager.
- Published live ESP3 traffic with `runtime_mode=live` and exposed its interface identity
  throughout status and event payloads.
- Aligned the Dashboard with the canonical MQTT gateway model.
- Reused the Registry-v3 sender-ID model for physical-device and virtual-device TX.

### Fixed

- Fixed ESP3 disconnect and read-loop shutdown races during reconnect and bridge switching.
- Fixed A5 4BS teach-in encoding to include the correct FUNC, TYPE and manufacturer data.
- Hardened configuration loading, empty retained MQTT payload handling, API discovery and
  static asset delivery for long-running deployment.

## 2026-06-010

### Added

- Added A5 4BS teach-in generation and runtime commands for virtual EnOcean devices.
- Added provisional teach-in metadata to busmonitor RX/TX event payloads.
- Added round-trip validation of generated teach-in telegrams through TX, RX injection,
  decoding and retained state publication.

### Changed

- Changed teach-in detection for A5 and D5 telegrams to use the correct DB0.3 flag.
- Prevented teach-in telegrams from overwriting semantic sensor channels with meaningless
  decoded values.

### Fixed

- Corrected A5 teach-in payload encoding for RORG, FUNC, TYPE and manufacturer fields.
- Fixed MQTT wildcard dispatch for virtual-device channel commands.
- Restored virtual-device TX publication to the busmonitor event path.

## 2026-06-009

### Added

- Added multi-select sender and RORG filtering to the Busmonitor Web UI.
- Added Web API support for querying multiple sender IDs in one request.

### Changed

- Simplified sender filter labels and introduced compact RORG labels.

### Fixed

- Restored the virtual-device runtime, gateway publisher and Busmonitor JavaScript after an
  incomplete intermediate change.
- Restored clean Ruff and mypy validation.

## 2026-06-008

### Added

- Added device-based sender selection and sender ID/name display modes to Busmonitor.
- Added compact and extended telegram table views.
- Added structured tooltips for sender, RORG, status and decoded channel information.
- Added a 48-hour hourly RX/TX activity chart.

### Changed

- Refined timestamp precision, tooltip placement and operational terminology throughout
  the Busmonitor UI.

## 2026-06-007

### Added

- Added declarative Registry-v3 TX metadata and generic ERP1 encoding for virtual devices.
- Added persistent virtual-device definitions, state caching and snapshot aggregation.
- Added semantic MQTT channel commands below
  `/virtual/<virtual_device_id>/channel/<channel>/set`.
- Added synthetic TX-to-RX round-trip validation through MQTT injection and runtime
  decoding.

## 2026-06-006

### Added

- Added the first operational SQLite-backed Busmonitor Web UI.
- Added cursor-based pagination, relative time ranges and filters for RORG, runtime mode,
  direction and known devices.
- Added millisecond timestamp rendering and CSV export.
- Added decode-on-read API processing through the shared runtime decoder.
- Added semantic channel tooltips while retaining raw-only SQLite persistence.

### Changed

- Refactored the FastAPI Web UI into shared templates and static assets.

## 2026-06-005

### Added

- Added SQLite schema v2 for raw RX/TX telegram history.
- Added configurable replay persistence and deterministic bounded retention with
  hysteresis cleanup.
- Added WAL mode for concurrent runtime and API access.

### Changed

- Stored raw telegrams and payloads as binary BLOB data.
- Standardized persistence and API reconstruction around `RuntimeTelegramEvent` v2 and
  `timestamp_unix`.
- Disabled replay persistence by default.

## 2026-06-004

### Added

- Added MQTT RX injection through `busmonitor/rx/inject`.
- Added ERP1 hexadecimal and structural validation for injected telegrams.

### Changed

- Routed injected and replay telegrams through the same runtime pipeline.
- Standardized sender IDs to uppercase and marked injected events with `port="inject"`.

## 2026-06-003

### Added

- Added broker-outage resilience so replay and decoding continue while MQTT is offline.
- Added automatic retained gateway-topic republication after reconnect.
- Added canonical ERP1 telegram normalization across DolphinView and Weinzierl replay
  sources.

### Changed

- Standardized runtime timestamps to millisecond precision.
- Promoted the compiled EEP registry to the canonical runtime registry source.
- Omitted unavailable replay source data instead of publishing synthetic values.

### Fixed

- Corrected Weinzierl replay payload extraction and ERP1 reconstruction.

## 2026-06-002

### Added

- Added the retained gateway EnOcean state topic.
- Added compact gateway metrics and detailed per-RORG busmonitor metrics.
- Added sender-ID based device topics and a dedicated device alias namespace.
- Added structured MQTT reporting for broker interruption events.

### Changed

- Aligned gateway, busmonitor and device payloads with the canonical MQTT model.
- Refactored gateway health into machine-oriented diagnostic telemetry.
- Standardized ISO-8601 and Unix timestamps to millisecond precision.

### Fixed

- Prevented temporary MQTT outages from terminating replay processing.
- Republished retained gateway state after MQTT reconnects.

## 2026-06-001

### Added

- Added the registry-driven, telegram-centric runtime decoder.
- Added dependency-aware selection for telegrams, messages, channels and ranges.
- Added CMD- and ECID-aware telegram identity matching.
- Added structured decoder trace logging through MQTT gateway log topics.
- Added initial dependency-aware coverage for A5-20-06 and D2-01-0E.

## 2026-05-004

### Added

- Added replay start, stop and state runtime commands.
- Added structured command validation and differentiated error reporting.
- Added retained gateway and device republish commands.
- Added the initial `gateway.restart` runtime command.
- Added the retained gateway runtime-mode topic.

### Changed

- Consolidated runtime state into explicit live and replay modes.
- Refactored replay status and metrics into type-safe payload structures.

### Fixed

- Synchronized replay state between gateway health and the retained runtime-mode topic.
- Restored clean Ruff, mypy and GitHub Actions validation.

## 2026-05-003

### Changed

- Consolidated MQTT topics and payloads into the canonical `mqtt-model.md` specification.
- Deprecated the separate `mqtt-topics.md` and `publish-policy.md` documents.
- Restored alias and virtual-device structures in the canonical MQTT model.
- Introduced canonical document metadata and lossless refactoring rules.
- Replaced the simulation subsystem with the replay architecture.
