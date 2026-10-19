# External gateways

External gateways such as KNX–EnOcean bridges and building automation controllers
can transmit using several sender IDs from their base-ID range. Register the
gateway once under **Devices → + Gateway** rather than registering every sender
as a physical device. This category describes external transmitters; the local
ESP3 interfaces remain configured separately.

Alternatively, choose **Register as gateway** on an Unknown Devices row.
**Register as device** continues to create an individual physical device.
For sender IDs in the standard EnOcean Base-ID address range, the form clears
the lower seven bits to prefill the Base ID and displays the observed sender and
offset. For example, sender `FFABCDC1` yields base `FFABCD80`, offset `65`.
Verify the address model against the gateway configuration before saving. For
other sender identities, confirm the Base ID manually. The source sender must
belong to the proposed range; it is not persisted as a channel automatically.

Enter the gateway's name and base ID, with optional manufacturer, model and
description. The base ID must contain eight hexadecimal digits. Standard Base IDs
are aligned to 128 addresses (`00` or `80` in the last byte). Existing manually
configured non-aligned interval starts remain accepted for compatibility; they
are not verified protocol Base IDs and are never migrated silently. By default, the gateway owns the 128 consecutive sender IDs
from base ID through base ID + 127. A smaller sender count can be configured.
Sender IDs outside that range retain their existing classification. An absent
gateway registry preserves previous behavior.
Gateway ranges must not overlap or extend beyond `FFFFFFFF`.

All IDs in the configured range are classified as belonging to a registered
gateway even if no channel profile is assigned. This identifies their owner;
it does not mean their channel or EEP is known.
They are excluded from unknown-device discovery, its API/CSV results and the
unknown series in the activity chart. Raw telegrams remain available in the
busmonitor and SQLite, subject to existing storage policies.

## Optional channel profiles

Add a channel profile only when its commands should be decoded. A channel offset
is the numeric difference between its sender ID and the gateway's base ID; offset
0 is the base ID itself. Offsets must be unique and inside the configured range.
Use the EEP actually transmitted by that channel. Do not infer a channel's EEP
from its sender ID or the gateway model.

For example, a gateway at the illustrative base ID `FFABCD00` can have D2-01-0E
profiles at offsets 0 and 1 and A5-20-06 at offset 2. This example does not claim
hardware validation for a particular gateway model.

Gateway telegrams are physically received (`rx`) by enocean-mqtt, but their
contents use the profile's **gateway-to-device command definitions** (`tx`).
For A5-20-06, these are DIR-2; D2-01-0E uses its command definitions. The decoder
keeps these two directions separate. A profile must include suitable TX telegram
definitions and message bindings for semantic command decoding. Other profiles
and gateway models require their own validation; D2 remains experimental.

Runtime, busmonitor live/history and dashboard use the same passive gateway
command decoder. A channel with no profile remains raw-only and does not produce
a missing-profile decode error. An assigned invalid profile or malformed command
is reported separately. Hardware-free tests and a synthetic browser review do
not establish complete real-device/profile coverage.

Gateway ownership takes precedence over an existing physical-device registration
in the same range for runtime and busmonitor decoding. An explicit channel profile
takes precedence over that registration's profile; otherwise the old profile/EEP
is used as a compatibility fallback. Existing registrations are not deleted.
After assigning channel profiles, obsolete physical registrations can be removed
explicitly. Deleting a gateway restores individual sender classification.

The latest decoded command per gateway channel is published retained at:

```text
<base_topic>/devices/gateways/<BASE_ID>/<SENDER_ID>/command
```

The payload contains `base_id`, `sender_id`, `profile`, `profile_direction: "tx"`,
`telegram_type_id`, `timestamp`, raw `fields` and decoded `values`. Enum values use
their numeric code with an optional `meaning`. These observations do not update
physical device-state topics and do not prove that a receiver acted on a command.
Retain makes the last observation visible to new subscribers; its timestamp may
be old and does not indicate that the gateway is currently online.

Since 2026-10-19 this replaces
`<base_topic>/gateways/<BASE_ID>/channels/<SENDER_ID>/command` (previously
non-retained). Update subscriptions and broker ACLs to the new path. The old path
is no longer published. A retained observation first appears after the next
successfully decoded received command; existing history is not backfilled.
Removing a gateway or channel does not automatically clear its retained command;
remove obsolete retained topics explicitly at the broker when decommissioning.

## Persistence and API

Gateways are saved in `gateways.json` beside the configured `devices.json`.
The file is optional. Runtime and API readers observe saved changes without a
restart. Unknown entries already collected in memory and retained MQTT unknown
topics are cleared on the next telegram processed by the runtime. Historical
telegram records are preserved. Historical counters already accumulated during
the current run are not rewritten.

The Device Management API exposes:

| Operation | Purpose |
|---|---|
| `GET /api/v1/device-management/gateways` | List registered gateways |
| `PUT /api/v1/device-management/gateways/{base_id}` | Create or replace a gateway |
| `DELETE /api/v1/device-management/gateways/{base_id}` | Remove a gateway |
| `GET /api/v1/device-management/gateways/{base_id}/channels` | Read configured/observed channels and observation scope |
| `GET /api/v1/device-management/gateways/{base_id}/metrics` | Read gateway/channel counters and rates |

Writes require administrator privileges. A PUT replaces the gateway record,
including its complete channel list. Responses used by the editing UI include a
`revision`; send it as `expected_revision` to reject stale updates with HTTP 409.
The UI does this automatically and asks the user to reload on conflict. Writes
are serialized across processes. The optional `.lock` sidecar is not configuration
that needs to be backed up. The management overview includes `gateways`
and `counts.gateways`; physical device counts exclude owned sender IDs.

Example registry using installation-independent IDs:

```json
{
  "gateways": [
    {
      "base_id": "FFABCD00",
      "name": "KNX bridge",
      "sender_count": 128,
      "channels": [
        {"offset": 0, "profile": "D2-01-0E"},
        {"offset": 1, "profile": "D2-01-0E"},
        {"offset": 2, "profile": "A5-20-06"}
      ]
    }
  ]
}
```

## Received channels and registration

Each gateway has its own table of sender IDs from which telegrams have been
received. Offset zero (sender ID equals base ID) is an ordinary valid channel.
Rows show channel name/profile, known/unknown status, received telegram counts,
first/last seen, RSSI and the last telegram. Configured but never observed
channels remain editable in the gateway form and do not appear as received rows.

Choose **Register as gateway channel** for an unknown row. The gateway, sender ID
and offset are fixed; enter a name, profile/EEP and optional description. Saving
updates the gateway channel without creating an independent physical device or
erasing telegram history. **Edit channel** updates existing assignments. A saved
channel without a profile stays unknown/incomplete. An assigned but unavailable
profile is a separate decode error. New nullable profiles/descriptions require
updated runtime and API readers; do not write these fields while older versions
that reject them still run.

## Busmonitor selection and colors

For external gateways, the Device filter offers one entry per gateway, not one
entry per channel. Selecting it includes all IDs in its configured range,
including unknown channels and offset zero. Existing non-gateway device entries
remain available. Other time/RORG/direction filters still apply. Exact sender-ID
search remains distinct: API `sender_id=FFABCD00` selects only that sender, whereas
`sender_id=gateway:FFABCD00` selects the gateway range. Comma-separated gateway
and exact sender selections form a union; CSV uses the same selection.

Known devices and assigned channels retain olive styling. Known gateways with
unknown/incomplete channels use light olive (`#8A965F`) with an explanatory legend
and tooltip. Missing EEP assignment is raw-only, not a red decode error. Actual
decode errors take precedence over Teach-In, which takes precedence over sender
colors. Hover uses an outline to distinguish interaction from assignment status.

## Metrics and observation limits

Expand the gateway/channel RX count to inspect outcome and repetition counters.
Gateway totals equal the sum of their channel totals. Received commands are
separate from confirmed actuator state. Rate/peak windows use the existing metrics
configuration. The view displays received/assigned/unknown/active channels;
unused sender capacity is not counted as observed or active.

By default, observations come from retained SQLite live RX, excluding replay and
TX. Stored retention limits and storage exclusions therefore limit the available
history. Historical decoding/classification uses the current registry and is
re-evaluated after a profile assignment. If SQLite or required provenance is
unavailable, the view uses available process-local live RX only; counters then
reset on restart, and a separate API process may have no such observations.
Stored and process-local counters are never added together. Source, time scope,
active/rate windows and coverage are exposed in the API. Rates keep at most 10,000
event timestamps per channel; a sample-completeness flag identifies partial rate
history without truncating cumulative event counters.

Warnings identify legacy physical registrations, foreign classifications or
local sender-pool overlaps. Existing records and foreign storage exclusions are
preserved for explicit operator reconciliation. A local TX event is never
counted as external gateway RX; a received loopback cannot be proven to originate
from a distinct external transmitter from sender identity alone.

## Open work recorded on 2026-10-16

The grouped received-channel view, channel registration, gateway range selection,
shared decoder, colors and scoped metrics are implemented and checked offline.
On 2026-10-16, the maintainer confirmed that the gateway functionality basically
works in their setup. Web UI layout and presentation cleanup is deferred.
This feedback does not establish complete model/profile-specific hardware
acceptance; detailed reception/profile validation remains a separate task.
Review any existing non-aligned manual range starts against actual gateway
settings. No automatic range migration or pairing/transmission is performed by
these features. Dedicated retained MQTT metrics/inventory topics remain deferred;
metrics are exposed through the read API and Device Management.
