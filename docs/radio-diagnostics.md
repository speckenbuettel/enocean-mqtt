# Radio telegram diagnostics

The busmonitor RORG filter includes data, management, security and SIGNAL
telegram types. **Other RORG** accepts a two-digit hexadecimal value, for example
`E5`, including types that the application does not recognize. **any RORG**
includes all archived and incoming types. The filter applies to history, CSV
selection and live updates.

## SIGNAL (D0)

SIGNAL messages extend a device's communication independently of its EEP. The
first payload byte is the message identifier (MID); it is not FUNC/TYPE and is
not interpreted as an EEP Teach-In. The busmonitor labels these messages
`D0 | SIGNAL`. Payload tooltips and details show the MID, its meaning, decoded
fields and validation diagnostics. Raw MQTT busmonitor payloads additionally
provide `telegram_kind` and `signal`; existing raw fields remain available.
Archive records are decoded on read, so no database migration is needed.

The passive decoder covers MIDs 01 through 13 (hexadecimal), including status
requests, energy, revision, heartbeat, RX windows, link quality, duty cycle,
configuration changes, harvesting, TX modes, backup battery, learn mode,
product identification and local date/time. Reserved MIDs/field values, invalid
dates and incorrect payload lengths are retained and reported as diagnostics.
Unknown/sentinel field values are represented as null, with additional status
where applicable. Version and product values remain manufacturer specific.

MID 09 reports that an RX window opened. Its duration is device specific and is
not encoded in the telegram; this observation does not establish that the
window is still open when displayed. MID 05 acknowledges reception of a unicast
message, not the actuator's resulting physical state. No automatic responses,
Teach-In operations or hardware commands are triggered by this decoder.

Source: EnOcean Alliance, [Signal Telegram specification](https://www.enocean-alliance.org/st/),
V3.5, sections 1.1-1.3 and 2.1-2.19. The supplied V3.5 document's revision table
includes changes through October 2024, despite the older release date on its
cover. This implementation uses its V3.5 field layouts (notably the low nibble
for MIDs 0B and 0D). Original specification documents are not redistributed.

## Unrecognized RORGs

An unrecognized RORG is preserved without substituting the device's configured
EEP or silently changing bits. The busmonitor marks it as unknown and provides
a `protocol_warning`. It does not enter the semantic device EEP pipeline.
This also avoids misleading payload-length errors and state updates from an
unrecognized telegram type.

E5 has no definition in the RORG sources reviewed for this change. E5 and A5
differ by one bit, which suggests a possible corruption but is not sufficient
to prove it. Similar payloads and close timestamps can strengthen the hypothesis;
they do not prove what the device transmitted over the air.

RORG names additionally follow the manufacturer's
[Dolphin API radio telegram definitions](https://www.enocean.com/wp-content/uploads/redaktion/support/dolphin4-api/EO3100I_API_Documentation/group__radio__telegram__struct__grp.html),
including legacy, chained and generic-profile identifiers. A filter entry means
that a type can be selected, not that its semantic decoding is implemented.

The ESP3 parser validates header and body CRC8 before normalizing RADIO_ERP1.
That protects the serial frame and does not independently prove the correctness
of the received radio message. The current SQLite archive stores canonical ERP1
data, not the full original ESP3 frame and its CRC. Establishing the origin of
an anomalous RORG may require a bounded diagnostic capture of complete ESP3
frames, receiver/firmware identification and comparison with an independent
receiver. Keep installation-specific captures private and collect only the
smallest relevant interval.
## RX screening and suspect telegrams

The gateway screens received telegrams before semantic EEP decoding. This does
not verify the original radio checksum: RADIO_ERP1 does not deliver that radio
hash to the host, and the archived canonical ERP1 bytes do not contain it. ESP3
CRC validation is a separate serial-link check. Passing screening does not prove
that the radio payload is correct.

The following classifications are deliberately separate:

| Classification | Meaning | Normal data decoding |
|---|---|---|
| `suspect` | Invalid structure, fixed payload length, or unrecognized RORG | Skipped |
| `profile_mismatch` | Valid RORG not covered by any RX identity in the assigned profile | Skipped; this can be a legitimate alternate telegram type |
| `teach_in_candidate` | A5/D5 LRN bit is clear | Normal data decoding skipped; unknown senders remain discoverable; intentional Teach-In is not proven |
| `sender_id_candidate` | Unknown sender differs by one or two bits from a currently configured physical device ID | Hint only; no suppression or reclassification |

All configured RX identities are considered, so a profile can cover multiple
RORGs. SIGNAL remains independent of the assigned EEP. Unsupported RORG bytes are
retained verbatim in the raw record and diagnostic event but are not added as
valid RORG categories or unknown devices by the live pipeline. No bytes or device
assignments are automatically corrected. Structural screening cannot detect all
plausible-but-wrong values or prove ownership of an unknown sender.

Live busmonitor RX events include additive `quality` metadata when screened as
above. History views also assess structure/profile compatibility on read using
the current profile; this does not rewrite old telegrams. Diagnosis metadata says
`corruption_proven: false` and gives the machine-readable `reason`. Real decoder
or registry/schema failures still remain errors; the known non-data/profile
rejections no longer create decoder tracebacks.

### Collection and monitoring

The Metrics page shows four screening counters and links to retained diagnostics.
The same counters and per-reason totals are published as
`decoder.telegram_quality` in the existing gateway/busmonitor MQTT metrics. They
count the current runtime session; replay statistics remain separate.

`GET /api/v1/runtime/diagnostics/telegrams?limit=100` reads retained raw evidence
and assessment metadata. `limit` is 1..500; optional `classification` selects one
of the four classifications. Existing API authentication/read permissions apply.
The response includes `diagnostics`, `retained_total` and counts by classification.

SQLite adds a separate `telegram_diagnostics` table (schema version 3), retaining
the newest 10,000 diagnostic records across restarts. Raw history remains under
its existing retention policy. Invalid hexadecimal input is kept only in the
diagnostic JSON, not converted to a BLOB. Existing live/replay persistence flags
and `exclude_from_sqlite` also apply to this collection: excluded senders still
affect session counters and live events, but their raw evidence is not persisted.

### Auditing foreign sender IDs

In development checkouts containing `tools/diagnostics/audit_foreign_senders.py`,
this optional tool compares
all foreign senders with the current physical device registry in a read-only
SQLite snapshot. Run it with `--database`, `--devices` and `--foreign-devices` paths;
it writes a JSON report to standard output. Store this installation-specific
report locally, not in public sources or issues.

The report distinguishes insufficient stored data, ID similarity alone, temporal
corroboration, and no close-ID evidence. Corroboration requires at most two ID-bit
differences, equal RORG/payload and equal upper status nibble within one second.
The lower repeater nibble may differ. Neither similarity nor corroboration is a
proof of bit corruption. Exclusions/retention limit the available history; zero
or one stored telegram does not establish the sender's lifetime transmission
count. The tool never changes foreign classifications, device IDs or raw history.
