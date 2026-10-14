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
