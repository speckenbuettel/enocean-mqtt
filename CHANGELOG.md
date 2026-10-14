# Changelog

This changelog records user-visible, operational and compatibility-relevant changes to
`enocean-mqtt`. Starting with 0.9.0, the project uses SemVer (`MAJOR.MINOR.PATCH`) as defined
in [Project Versioning](docs/project-versioning.md). For the currently supported
scope and validation boundaries, see [Known Limitations](KNOWN_LIMITATIONS.md).

## Unreleased

- Corrected CI type errors in foreign-device storage/filtering and test fixtures;
  updated A5-20-06 regression expectations for the reviewed profile's selector
  variants, semantic roles, protocol constants and managed temperature fallback.
  Configuration tests now explicitly isolate their project root, preventing
  relative test secret paths from resolving into the development checkout.

## 0.9.0 — 2026-10-14

Planned first public pre-1.0 release for user testing, consolidating the changes
below and superseding the internal 2026-10-002 baseline. Runtime, API, MQTT and
Python package versions derive from VERSION and now report 0.9.0. Earlier dated
versions remain historical entries; no separate public version is maintained.
The maintainer
reports successful completion of the private test candidate's acceptance
checklist. That candidate was based on 2026-10-001; later code, documentation and
export-selection changes require a new export and proportionate revalidation.
This version assignment does not publish or approve a public release.

- Include the required composite-field runtime module in the public export and
  replace internal-only documentation links with selected runtime sources.

- Documented virtual sensor snapshot requirements, managed/default fields,
  aggregation as a resettable quiet interval, cached-value reuse and restart
  initialization, plus the MQTT-only visibility of delayed virtual TX errors.

- Review repository automation and Python packaging configuration: document
  active workflows, dependency/version ownership and deployment boundaries;
  run CI on Python 3.11 and 3.12 with read-only repository access. Ignore local
  temporary output and SQLite files and remove temporary PDF images from tracking.
  Use SPDX license metadata with bundled license/credits; builds require
  setuptools 77 or newer. Runtime dependency requirements are unchanged.

- Keep the dark navy navigation with light links and blue active/hover/focus
  highlights. Enlarge its logo to 56 px and add a palette-silver `#96A5AF` border
  to distinguish it from the dark background.

- Darken Foreign-device rows and legend swatches to palette silver `#96A5AF`,
  clearly separating them from Unknown devices on the `#F4F6F8` background.

- Version the shared Web UI stylesheet by its contents so cached older palette
  definitions cannot make Unknown and Foreign legend colors look identical.
  Foreign rows and legend swatches also fall back to palette grey when the new
  shared color variables are unavailable.

- Bus Monitor adds All / Teach-In only / Exclude Teach-In filtering for recognized
  A5/4BS and D5/1BS telegrams, consistently in history, live display and CSV export.
  Detection uses the raw LRN bit rather than archived status flags. Foreign-device
  rows use palette grey, decode failures use red, and a compact legend below the
  table explains all colors and their priority. List/live payloads now include
  `decode_error`, enabling the same failure marking as telegram details.

- Rename foreign-device classification throughout registry files, API fields,
  routes and Web UI. Existing `external-devices.json` data and SQLite exclusions
  remain readable; the next change writes `foreign-devices.json`. API clients
  must adopt the new names; see [migration guidance](userguide/devices.md#rename-from-external-to-foreign).
- Dashboard uses **Devices**, adds a foreign-device count, and offers
  `devices.republish`, `interface.connect` and `interface.disconnect`; interface
  actions target the selected interface. Bus Monitor uses a combined Known /
  Unknown / Foreign checkbox group with matching history, live and CSV filters,
  and consistent labels above controls. Device Management lists foreign devices
  separately with a device-type selector and a definition of foreign membership.

- Document the existing TX validation gap: telegram `constraints[]` are not
  enforced by the Registry encoder, simple numeric scalings clamp/round, and
  `ranges[]` do not validate outbound inputs. D2-01-0E measurement interval
  callers must validate MAT `10..2550` in steps of `10`, integer MIT `1..255`,
  and semantic `MAT >= MIT` before encoding for physical use. Profile JSON and
  the new composite-value bounds do not fix this runtime limitation. See
  [Known Limitations](KNOWN_LIMITATIONS.md#interfaces-and-profiles).

- Store foreign sender classifications centrally in `config/foreign-devices.json`
  instead of browser storage. Device Management provides a persistent External
  Devices list, and the Bus Monitor can hide these senders in live/history views,
  sender selection and CSV exports. Administrators may separately exclude future
  telegrams from SQLite per sender; existing history is retained and MQTT/runtime
  counters are unaffected. Changes take effect without restarting. Old browser
  markings migrate on an admin visit without overriding central storage policies.
  The API adds foreign-registry management and opt-in `hide_foreign` query
  filtering. See [foreign-device management](userguide/devices.md#foreign-devices).

- Virtual-device creation accepts either a standard EEP or a manufacturer profile.
  The form no longer requires an EEP when a profile is selected; the selected
  profile retains precedence for channel names and TX encoding.
- Correct Unknown Devices counts by RORG on EnOcean Metrics and replace corrupted
  placeholder characters with a dash.
- Remove the redundant Custom choice from Bus Monitor Quick range. From and To
  remain editable for any selected preset.

- Add optional Registry v3 `field_parts` bindings for one unsigned semantic raw
  value distributed across separate payload fields. RX assembles the value before
  semantic conversion; TX splits it after inverse conversion and rejects invalid
  references, duplicate/overlapping assignments and out-of-range composite values.
  Existing compiled `field_ref` profiles keep their behavior and require no
  changes or recompilation. Profiles using `field_parts` require the updated
  runtime. Compiler normalization/validation preserves explicit declarations;
  XML import does not infer them automatically. This adds no D2 profile, D2
  virtual-device adapter support or hardware validation. See the
  [runtime composite binding validation](src/enocean_mqtt/eep/field_parts.py).

- Preserve a final newline when runtime device management writes `devices.json`,
  matching the formatting of other runtime JSON files.

- Show the underlying EEP reload validation error in dashboard command results
  and service logs, including the affected profile and invalid reference. Version
  the dashboard script by its contents so browsers receive the corrected handler.

- Cache EEP definitions on first use for RX, TX and busmonitor decoding. File
  changes now require `eeps.reload` or a service restart. The new MQTT/HTTP runtime
  command and dashboard action validate all available profiles before atomically
  replacing the cache; failed reloads preserve the previous definitions.

- Decode F6/RPS status consistently in MQTT RX/TX events, replay and busmonitor
  live/history views: T21, NU, PTM type, N/U message type, checksum/CRC8 and repeater
  status. T21 is no longer mistaken for Teach-In. Historical metadata is corrected
  on read without changing archived telegrams; non-F6 event contracts are unchanged.
  Public export selection now includes the required SIGNAL module and its linked
  radio diagnostics documentation.

- Service Logs default to entries since the current service process started,
  with an option to show all retained logs. CSV/Text exports follow the displayed
  selection; the system journal is preserved. Runtime script URLs use content hashes.

- Busmonitor script and stylesheet URLs now use content hashes, preventing stale
  browser assets from leaving new RORG filter controls without matching logic.

- Grouped busmonitor RORG choices into common data telegrams and other types.
  Custom RORG input activates immediately for valid hexadecimal values and has
  an explicit checkbox to enable or disable it.

- Busmonitor filters include SIGNAL, management and security RORGs plus a custom
  hexadecimal RORG. SIGNAL messages are decoded independently of device EEPs,
  with MID, field and payload validation according to Signal Telegram V3.5.
  Unknown RORGs remain visible as raw diagnostics without EEP interpretation.
  Live updates respect the selected RORG filter.

- Runtime decoding checks each candidate's RORG before extracting payload fields,
  so short telegrams of another radio type cannot cause misleading A5 bit-field
  bounds errors. Unsupported types remain explicitly rejected.

- Added an explicit private-test export mode selecting all committed registry
  profiles without marking public release reviews or profile approvals complete.

- Added public third-party notices distinguishing the project's MIT-licensed code
  from EnOcean and manufacturer documentation used as profile sources; original
  source documents remain excluded from publication.

- Added a 30-day Telegram Activity range with daily buckets, independent RX/TX
  count axes and clearer RX classification and TX color coding.

- Reviewed public content selection, clarified chronological versions and stable
  support boundaries in README, documented project artwork origin and externally
  loaded API documentation assets. Profile redistribution review remains pending.

- Busmonitor tooltips use a viewport-positioned overlay outside the scrolling
  table, aligned columns and word-boundary wrapping for long labels. They flip
  above lower rows and stay within the viewport; keyboard focus is supported.

- Added step-by-step physical-device registration, CSV import/export, virtual
  sensor and Teach-In guidance, plus a fresh-install/API/OBS acceptance checklist.
- Semantic device mutation routes now return 400 for command validation errors,
  409 for execution conflicts and 503 when the runtime dispatcher is unavailable,
  instead of unhandled failures or a misleading unsupported-operation response.
  The device-specific republish route remains 501.

## 2026-10-001 — 2026-10-09

Consolidated development baseline for public-release preparation. Assigning this
version does not publish or approve the exported public candidate. Profile and
hardware support remain limited to the reviewed release selection.

### Runtime and profile authoring

- Profile prompt v1.7.0 takes profile/function/type descriptions from the uniquely
  matched EEP catalogue row, preserving maintained descriptions instead of silently
  substituting upstream titles. The public selection includes the current prompt.

- Busmonitor SSE buffers events only while a live client is connected and clears
  pending events after the last client disconnects. Idle browsers no longer cause
  queue-full warnings merely because the busmonitor is closed.

- Profile prompt v1.6.0 preserves short established channel names and scopes
  default verification to the requested profile, without exhaustive raw-value
  sweeps or unrelated-profile regressions.
- Busmonitor tooltips reserve space for values and wrap long keys, avoiding
  one-character-per-line values when a profile has long channel names.

- Profile-authoring prompt v1.5.0 requires offline data-telegram encoding and
  virtual-device emulation checks for every complete profile. Unidirectional
  sensors must not be delivered with an RX-only encoder restriction.

- Registry specification now places bindings inside their telegram variant,
  without binding-local telegram IDs. Dependency conditions use the loader's
  supported predicates and raw field codes, not unsupported `in`/`not_in` keys
  or enum label comparisons. Runtime code is unchanged.

- Profile-authoring prompt v1.4.0 reads the workbook's `Human Decision Semantic
  Role` directly. JSON is an explicit fallback only without the workbook; stale
  exports no longer require renewed approval of existing human decisions.

### Enum state contract change

- MQTT device/channel state and channel `/value` now publish numeric enum codes,
  not enum labels or boolean/numeric `semantic_value` overrides. JSON states also
  include optional `meaning` with the active enum label. Measurements without
  enums keep scaled/rounded values. Unknown codes omit meaning.
- Datapoint API discovery describes readable enum values as `integer` and exposes
  `representations` for `value` and read-only string `meaning`. Runtime value
  responses carry the same optional meaning. Binding-only enum metadata is included
  in discovery, with variant tables under `metadata.enum_variants`.
- Migration: update automations comparing old strings/booleans to use numeric
  codes or JSON `meaning`; refresh retained values and OBS discovery after upgrade.
  Datapoint IDs and write contracts are unchanged. The OBS adapter needs a separate
  update to offer these representations; it is not changed by this release work.

- Corrected Registry-v3 raw field specification and examples to the existing
  runtime keys `offset`, `size`, `raw_min` and `raw_max`; clarified bit numbering
  and physical versus semantic ranges. No runtime/profile migration is required.

- Added profile-authoring workflow and Codex prompt v1.0.0 for source-grounded
  standard/proprietary candidates, with human semantic approval, isolated output,
  provenance and explicit verification/publication boundaries.

- Compiler XML/IP merging now uses table source keys and aliases to join differently
  named functions, updating semantic bindings without renaming payload fields.

- Missing or invalid EEP profiles for virtual devices no longer abort startup:
  affected devices are logged and skipped while other devices continue.

- Compiler CLI now requires only `--eep`: standard XML and the corresponding
  available IP JSON are selected automatically. Explicit source overrides remain
  supported; semantic mapping and output defaults are unchanged.

- Compiler semantic review excludes the LRN/data `telegram_type` control bit
  while preserving its encoding and TX metadata. Sensor availability fields
  remain subject to table-based mapping and human approval.

### Added

- Compiler candidates now use `Human Decision Semantic Role` as the semantic
  approval source. Empty decisions skip the affected EEP; multiline decisions
  prompt locally or produce an actionable unattended report. Unrelated pending
  rows no longer delay reviewed profiles. This does not change shipped profiles
  or grant release/hardware approval.

- Added private local release-export tooling: committed allowlist selection,
  approved-profile catalogue filtering, payload fingerprints and read-only public
  comparison. Preview mode does not grant release approval; no automatic publication
  or private-history transfer is performed.

- Added offline first-admin setup and recovery through `enocean-mqtt-auth`
  (also `python -m enocean_mqtt.auth`). Setup never overwrites an existing registry;
  recovery rotates a named admin token or adds a missing admin, preserving other
  credentials. Documented authentication activation, login and recovery in the User Guide.

- Added optional Pushover delivery using separate User Key and application API Token
  files, plus a Notifications settings group with masked token entry and a test message.
- Added background notifications for gateway startup, shutdown through the runtime's
  cleanup path and gateway errors, with a bounded queue and configurable error cooldown.
- Added `POST /api/v1/notifications/pushover/send` for custom messages using saved
  settings; sending requires `admin` when API authentication is enabled.
- Added a reusable notification interface for future threshold rules. Threshold
  evaluation, hysteresis and recovery notifications are not implemented yet.

- Added `GET /api/v1/busmonitor/metrics/telegram-activity` for server-side SQLite
  aggregation of the `1h`, `24h`, `3d` and `7d` activity ranges used by the EnOcean
  Metrics Web UI.
- Added RX known/unknown aggregation based on the current physical-device registry while
  retaining TX as a single total series.

### Changed

- Replaced legacy installation-like examples with a disabled current-format device,
  empty sender/token registries and an unset adapter base ID. Existing operational
  files are not migrated or overwritten. Documented per-device TX-profile overrides
  and update/backup handling for shipped defaults versus local configuration.
- Corrected private catalogue generation paths and deterministic provenance;
  generated development lists are explicitly not public release approvals.
- Updated API limitations to reflect implemented semantic writes, retaining the
  outstanding device-specific HTTP republish and end-to-end acceptance limitations.

- Derived Python package metadata and the package's version attribute from `VERSION`;
  chronological runtime versions retain their spelling, while Python distribution
  metadata uses the equivalent dotted release number.
- Added public credits, contribution/assistant guidance and known limitations;
  repaired public documentation references and prepared runtime-only packaging.

- Compiler 3 now validates mapping review state and final three-part semantic
  roles before writing output. `--allow-incomplete` explicitly permits draft
  artifacts but retains a failing exit status when errors remain. Existing
  runtime profiles are not automatically regenerated or migrated.

- Changed the EnOcean Metrics activity charts to consume bounded server-side aggregates
  instead of downloading and aggregating paginated raw telegram history in the browser.
- Structured the Web UI Settings page into collapsible Application, EnOcean, MQTT,
  SQLite, API, Logging and Notifications groups while retaining the existing API-backed
  configuration workflow.
- Replaced the Device Management placeholder with an API-backed registry workspace for
  physical, virtual and unknown devices, including statistics, search and filtering,
  editing, deletion, CSV import previews and CSV exports.
- Added physical and virtual teach-in actions plus explicit user-confirmed receiver
  records, so receiver assignments are not presented as automatically verified when the
  EnOcean teach-in method provides no acknowledgement.

### Fixed

- Fixed semantic lookup so exact source keys take precedence over aliases and
  ambiguous mappings cannot silently depend on workbook row order.
- Preserved Object Type, additional review columns and zero/false attributes in
  the semantic source toolchain; redirected legacy exporters to the current JSON
  envelope format and exposed unresolved source rows in derived review output.
- Preserved runtime derived-value lookups for three-part roles through existing
  base-role configuration, while retaining explicit final-role overrides.

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
