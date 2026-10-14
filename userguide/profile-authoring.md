# Create a profile with Codex

Workflow version: **1.7.0**, 2026-10-08. This version identifies the authoring
instructions, not the runtime release or an EnOcean specification version.

Use the [versioned prompt](prompts/eep-profile-v1.7.md) to create one standard EEP
or manufacturer-specific profile directly from its sources. The compiler is not
required. Every output is initially a review candidate, not a supported profile.

## 1. Prepare the inputs

Work in a local checkout with an installed runtime. Provide these inputs to Codex:

- One profile identifier and the intended device/model and RX/TX operations.
- The Registry-v3 specification and semantic role/domain/object-type rules for
  the target checkout. In the development repository these are
  `docs/eep-registry-schema.md`, `docs/semantic-roles.md` and, for proprietary
  profiles, `docs/proprietary-profiles.md`.
- The human-maintained `eep/semantic-role-mapping.xlsx`, sheet
  `semantic-role-mapping`. Codex reads `Human Decision Semantic Role` directly
  by column header and Function Key, without saving or changing the workbook.
  An explicitly supplied reviewed JSON is a fallback only when the workbook is
  unavailable; an old export must not override current workbook decisions.
- Relevant official XML, IP JSON and PDF, or manufacturer documentation.
- The profile list `eep/eep-list.csv`. The uniquely matched `eep` row supplies
  `func_description` from `func description` and `type_description` from
  `type description`; `description` combines them with `, `. Empty cells, missing
  or ambiguous rows, and factual contradictions with the protocol evidence require
  a targeted question before a complete candidate can be generated. There is no
  automatic fallback to official titles. The CSV is read only.
- A suitable shipped reference profile, and sanitized telegram samples with
  independently known expected values, if available.

For a standard EEP such as `A5-14-07`, the development source layout is:

```text
enocean/eeps/eep268.xml
enocean/eeps/json/A5-14-07.json
enocean/eeps/ip/A5-14-07_ip.pdf
eep/eep-list.csv
eep/semantic-role-mapping.xlsx
```

These are development paths, not promises that a public checkout includes those
files. In a public checkout supply missing documents/mapping as local files and
fill in their actual paths in the request. Do not rely on private repository
access. If the format specification or approved roles are unavailable, obtain
them from the maintainer before asking for a complete profile. Existing shipped
profiles alone do not constitute an authoritative specification.

For a proprietary profile use a descriptive lower-case manufacturer/model ID
consistent with the supplied specification. Provide the documented radio RORG
and payload format; do not invent an official EEP number. Missing manufacturer
details may prevent a complete result.

Respect third-party rights: keep manuals locally unless redistribution is allowed.
Prefer publisher links and precise page/section citations in review reports.
Never provide secrets, complete live configuration, databases or unfiltered
captures. Sanitized samples should identify payload, RORG and expected values
without unnecessary installation identifiers.

## 2. Start the request

Copy the entire [prompt v1.7](prompts/eep-profile-v1.7.md) into a Codex chat attached
to the checkout. Complete the input block with actual paths. The profile identifier
is entered once; Codex derives the per-profile JSON/PDF paths and output filename.
Explicit source paths override the conventional layout for manufacturer documents
or different source versions.

Specify an isolated output root, for example `.cache/profile-authoring`. Do not
select `eep/registry` as the output directory. The agent creates one subdirectory
per profile containing:

```text
<PROFILE>.json                 complete candidate, only when blockers are resolved
review.md                      sources, field/function/role correspondence, decisions
test-vectors.json              independently justified RX/TX examples
verification.md                checks actually run and remaining gaps
```

Additional isolated tests are allowed. If important facts or human role decisions
are missing, expect a blocked review, not a runnable JSON with guessed values.
Codex may ask targeted questions. Answering a question approves only the specified
profile/value; it does not change the global workbook unless separately requested.

## 3. Review and verify

Prompt v1.7.0 makes the CSV the primary source for profile-level descriptions.
Verify the literal source cells and derived combined description against the
actual profile, especially ranges, endpoints, units and bit width. Any factual
contradiction or empty description requires a human answer; an apparent typo is
not permission to choose another source silently. Record the CSV fingerprint,
row/headers, source comparison and profile-local answer. Channel/field descriptions
remain source-grounded; CSV text never overrides technical scaling or bit positions.
[v1.6.0](prompts/eep-profile-v1.6.md) remains unchanged for reproducibility.

Prompt v1.6.0 keeps verification focused on the requested profile (typically
10-30 distinct vectors for simple profiles, adjusted to actual branches). Full
raw-value sweeps and tests of unrelated profiles are not the default. Preserve
meaningful existing names; shorten explanatory source prose instead of copying it
literally into keys. For established temperature/humidity profiles prefer
`humidity`, `temperature` and `t_sensor`. Long explanations belong in descriptions.
[v1.5.0](prompts/eep-profile-v1.5.md) remains available for reproducibility.

Prompt v1.5.0 requires offline encoding for virtual-device emulation for every
complete profile, independent of its immediate use. Unidirectional sensors can
still be emulated. Shared telemetry telegrams must be eligible for both decoder
and encoder; in the current runtime that means no telegram-level `rx` restriction.
Required snapshots, control defaults and availability must be verified through
the actual virtual-device encoding path. Unsupported/incompletely documented
emission is a blocker, not permission to silently deliver RX-only output.
[v1.4.0](prompts/eep-profile-v1.4.md) is retained for historical requests.

Prompt v1.4.0 reads human decisions directly from the workbook. A stale JSON with
missing decision fields does not trigger renewed role questions when the workbook
has the answers. No compiler/export step is required for direct profile authoring.
[v1.3.0](prompts/eep-profile-v1.3.md) remains available for older requests.

An exactly matched Function Key with one nonempty human-decision line is binding:
reuse it without asking again. Only empty or multiline decisions trigger role
questions. Resolve XML/IP naming differences from sources without renewed role
approval. Report input defects and missing protocol facts separately.
Prompt v1.1.0 clarifies this rule; [v1.0.0](prompts/eep-profile-v1.md) remains
available for reproducing earlier requests.

Prompt v1.2.0 additionally separates IP lookup keys from descriptive output names,
preserves complete source state labels and their polarity, and requires numeric
precision derived from documented resolution. Binding enums must agree with object
enums. Boolean conversion and output renaming are compatibility changes, not
automatic consequences of a semantic role. [v1.1.0](prompts/eep-profile-v1.1.md)
is retained unchanged.

Prompt v1.3.0 supersedes the string-output preference of v1.2.0. Descriptive source
names become output keys; enum state publishes numeric codes plus their label as
`meaning`. One channel exposes these two representations, not duplicate channels.
Measurements remain scaled numbers. See the current enum contracts in the MQTT
and API specifications. [v1.2.0](prompts/eep-profile-v1.2.md) remains reproducible.

Check the source version/page references and the field-to-function correspondence,
particularly bit numbering, inverted enums, unavailable/error values, selectors,
scaling and direction. Review every discrepancy and every proposed new role.

Verification has distinct levels:

1. JSON parsing, semantic contract and structural checks.
2. Loading by the actual target runtime using an isolated registry.
3. RX decoding and, where applicable, offline TX encoding against expected vectors.
4. Sanitized capture/replay checks, if available.
5. Explicitly authorized real-device testing, separately for RX, TX and Teach-In.

Passing an earlier level does not prove a later one. Round-trip encoding/decoding
alone is insufficient: the same wrong interpretation can pass both directions.
Tests must include independently sourced expected results. Data-telegram encoding
for emulation is required for a complete profile. Actuator commands and Teach-In
may be unsupported; do not fabricate those operations or their test vectors.

The agent uses the runtime loader and decoder/encoder in the checkout. Internal
generator validators and pytest tests may be absent from a public snapshot; their
absence must be reported. No missing test may be described as passed, and the
generator validator alone is not a complete JSON Schema validator.

## 4. Adopt deliberately

For virtual RPS telegrams, declare the required ERP1 status bits in
`telegrams[].status_fields` using `constant` or `default_value`. The encoder
keeps status offsets separate from payload offsets: `T21` at offset 2 and `NU`
at offset 3 produce status `30` for an N-message and `20` for a U-message.
Unspecified bits remain zero; profiles without declared status values retain
status `00`. Overlapping status fields, invalid bounds or values that do not fit
their field prevent encoding. Verify both payload and status through the virtual
snapshot encoder before adopting an RPS candidate.

Only after review and appropriate testing, back up the current profile and place
the approved candidate in the runtime's configured registry (default
`eep/registry`). Do not delete unrelated profiles or change a running service as
part of candidate generation. Installation and restarts require a separate request.

Record the target runtime version/commit, prompt version, source fingerprints and
test results with the profile. New prompt versions do not automatically regenerate
or approve existing profiles. To contribute, follow [Contributing](../CONTRIBUTING.md)
and preserve [source acknowledgments](../CREDITS.md).

## Publication prerequisites

This workflow is prepared locally; it does not authorize publication. Before
offering it as a self-contained public authoring workflow, the maintainer must
select these two documents and an approved format specification, role taxonomy
and reviewed semantic mapping for the public inventory. Internal planning links
must not become public dependencies. Until that bundle is available, users must
provide the required documents themselves; no private files are implicitly exported.
