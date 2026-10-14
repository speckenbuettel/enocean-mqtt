# Devices, imports and virtual sensors

Applies to the 2026-10-001 baseline. Complete the [installation and authentication
guide](README.md) first. Sign in with an **admin** token to make changes; a read
token is sufficient for viewing. Use a separate test installation initially.

## Before adding a device

An EEP describes the telegram, not just a product name. Determine the correct EEP
from the device manual, its configuration or a known Teach-In telegram. Do not
guess an EEP from RORG alone. Manufacturer-specific profiles use their own profile
identifier. Only profiles installed in the runtime registry can be selected.

Review [Known Limitations](../KNOWN_LIMITATIONS.md). A generated profile is not
automatically installed, approved or hardware-tested. Follow the
[profile-authoring guide](profile-authoring.md) for missing profiles.

Before changing existing devices, make a protected backup of your actual physical,
virtual and sender-ID registries. See [update and backup guidance](README.md#updating-a-native-installation).
CSV export is useful for physical devices but is not a complete installation backup.

## Foreign devices

Choose **Mark as foreign** in Unknown Devices for senders outside your installation.
This classification is stored centrally in `config/foreign-devices.json`, beside
the physical device registry, and is shared by browsers. Include this file in
backups. It is created on the first change; no configuration migration is required.
With a custom physical-registry path, the foreign registry is in the same directory.

Foreign devices are devices that do not belong to your own network. They appear
in their own **Foreign Devices** table, independently of retained telegrams, and
are excluded from the physical, virtual and unknown tables. Select **Foreign
devices** in the **All device types** list to show that table alone. Use
**Unmark as foreign** to restore normal handling.

In the Bus Monitor, **Device types** contains independent **Known devices**,
**Unknown devices** and **Foreign devices** checkboxes. Known and unknown start
selected; foreign starts unselected. Foreign classification takes precedence over
known/unknown membership. The same combination filters live/history rows, sender
selection and CSV export. Clearing all three shows no telegrams.

In that section, an administrator can enable **Exclude future telegrams from
SQLite** separately for each sender. There is currently no global exclusion
switch for all foreign devices. Marking a device foreign alone does not stop
storage. Changes take effect without restarting the gateway, for live and replay
storage when those modes are enabled. Existing SQLite history is retained. Removing
the classification also removes its storage exclusion. MQTT traffic, decoding and
bus-wide runtime counters continue to reflect received traffic. An unreadable or
invalid foreign registry logs a warning and preserves storage rather than losing
telegram history.

On the first admin visit from a browser with old local foreign markings, valid
sender IDs are imported into the central registry. Existing central storage policies
are preserved. The old browser list is removed only after successful import;
read-only visits do not migrate it.

The API exposes `GET /api/v1/device-management/foreign` and administrator-only
`PUT` / `DELETE /api/v1/device-management/foreign/{sender_id}`. A PUT body such as
`{"exclude_from_sqlite": false}` marks a sender without excluding its storage.
Busmonitor telegram queries, CSV export and sender discovery accept
`device_types=known,unknown` (or another combination of `known`, `unknown`,
`foreign`); `device_types=none` selects no types. Omission preserves the existing
unfiltered API behavior. `hide_foreign=true` is also available for API clients.

### Rename from external to foreign

The canonical file is now `foreign-devices.json` with a `foreign_devices` array.
An existing `external-devices.json` remains readable, including its per-device
SQLite policies. The first subsequent registry change writes the new file; the
old file is retained for rollback and is ignored while the new file exists.
If both files exist, the new file is authoritative and they are not merged.
Back up the new file after migration; do not delete it to revert a classification.
Old browser markings still migrate on an admin visit.

API clients must replace `/device-management/external` with
`/device-management/foreign`, `external_devices` with `foreign_devices`,
`external_device` with `foreign_device` and `hide_external` with `hide_foreign`.
These API names are renamed rather than maintained as aliases.

## 1. Register a physical sensor

1. Open **Device Management** in the Web UI. With working hardware, let the sensor
   send a telegram and find its sender ID under **Unknown Devices** or in Busmonitor.
   IDs have exactly eight hexadecimal characters, without spaces or `0x`.
2. Choose **Register device** on the unknown-device row, or **+ Device** to enter
   the ID manually. Unknown does not mean broken: the sender is not yet registered.
3. Enter a unique **Device name**, for example `Living room climate`. The UI
   generates the **Alias** from the name. Avoid names that normalize to the same
   alias; changing a name/alias can change discovery identities and break bindings.
4. Select the documented **EEP**. For a standard profile, leave **Profile** empty
   to use the EEP itself. For a proprietary device, select its installed **Profile**;
   do not invent a standard EEP to make the form accept it.
5. Optionally enter manufacturer, model, floor, room and equipment ID. Keep
   **Enabled** checked. Do not select **EnOcean Secure**: Secure operation is not
   supported by this release merely because the form contains that field.
6. Check the automatically derived **Communication**, **TX EEP** and **TX profile**.
   These describe profile/controller relationships, not proof of pairing. For
   local TX overrides, use the [controller guidance](README.md#controller-mappings-and-local-overrides).
7. Click **Save device**. The operation updates the persistent registry through
   the running gateway. No manual service restart is normally needed for UI changes.
8. Wait for a new **data** telegram. In Busmonitor, check the sender/name and
   decoded channels against the sensor's actual state. Registration does not
   manufacture fresh measurements or prove an EEP is correct.

Expected result: the sensor appears under **Physical Devices**, and new telegrams
produce the intended values. `Inactive` can simply mean no telegram arrived during
the configured activity window. Battery sensors may send only periodically.

Use **Edit** to change metadata or the profile. The physical Device ID cannot be
changed after registration. **Delete** removes the registry entry, not the radio
device or its pairing; later receptions can appear as unknown again. **Reload
registry** reloads persisted device definitions; it does not receive a fresh telegram.

Without radio hardware, you can create definitions and inspect discovery, but no
live reception is expected. Use the documented replay/injection workflow with
known samples; it is not a radio or pairing test.

## 2. Import and export physical devices

1. Click **Export devices** to obtain the current CSV format. Keep a backup copy.
   **Export unknown** is a diagnostic list, not an import-ready device registry.
2. Edit a copy in a text editor or spreadsheet. If using a spreadsheet, import ID
   columns as **text** so leading zeroes survive. Save as UTF-8 CSV and retain the
   headers. A file may use commas or semicolons; do not mix delimiters.
3. Enter one device per row. At minimum provide `device_id`, `device_name` and
   either `eep` or `profile`. Use the full exported column set when updating
   existing records: omitted/blank fields are not a general-purpose patch mechanism.
   Use `true`/`false` for boolean fields. Do not copy sender allocations from
   another gateway; these belong to its adapter and receiver pairing.
4. Click **Import CSV**, choose the file and review the new/updated/error counts.
   Cancel if there are errors and correct the file first. The current importer
   can skip invalid rows and import valid ones; it is **not an all-or-nothing
   transaction**, and preview success does not prove installed-profile validity.
5. Confirm only after checking the preview. Entries with the same Device ID update
   existing devices. Devices absent from the CSV are retained, not deleted.
6. Check the resulting rows, profile assignments and subsequent decoded telegrams.
   Export again and compare the result with your intended changes.

Illustrative minimum row, using a placeholder ID and a profile that must actually
be installed in your release:

```csv
device_id,device_name,eep,enabled
01020304,Living room climate,A5-04-01,true
```

Do not import this placeholder into production. CSV imports concern physical
devices; virtual definitions and sender allocations are backed up separately.

## 3. Create a virtual sensor

A virtual sensor emits an EnOcean telegram from values supplied by an integration.
It needs a profile with working offline encoding, the correct channel names and
a usable TX interface. A successful save is not proof of radio transmission.

1. For a real TX test, configure a supported interface, enable transmission and
   check its adapter base ID/sender allocation. Never invent a base ID or reuse
   another installation's sender IDs. With no hardware, restrict the exercise to
   configuration/discovery and replay; no receiver acceptance can be tested.
2. Open **Device Management → + Virtual device**.
3. Set **Virtual device ID**, for example `test_climate`. Use lowercase letters,
   numbers and underscores, without spaces. Treat it as a stable binding identity.
4. Select either an **EEP** or an installed manufacturer-specific **Profile**.
   For a standard EEP, leave Profile empty. For a manufacturer profile, EEP may
   remain empty; the selected Profile takes precedence for channel names and
   telegram encoding even when an EEP is also selected. The profile must support
   the required TX encoding.
5. In **Channels**, select the controllable channels offered by that definition,
   for example `humidity` and `temperature` only if those names exist in that profile.
   Protocol/control fields and channels supplied through profile defaults need not
   be exposed as user inputs. Supply every input required for a complete snapshot.
6. Optionally enter a device name and description; leave **Enabled** checked and
   click **Save virtual device**. The gateway allocates its sender ID. Record it
   for receiver setup and verify no profile/sender-allocation error was logged.
7. Discover its writable datapoints through API/OBS, or supply values using MQTT.
   Use engineering values for measurements and the profile's supported TX enum
   codes/types. `meaning` is a read-only explanation, not a writable command.

Example MQTT channel topics for the default base topic and the example names:

```text
enocean-mqtt/virtual/test_climate/channel/humidity/set       payload: 60
enocean-mqtt/virtual/test_climate/channel/temperature/set    payload: 20
```

Publish commands **without retain**. Replace the base topic, ID and channel names
with yours. Multiple updates are aggregated into a snapshot; missing required
values can prevent TX and produce a delayed MQTT error. See
[Virtual sensor transmission in detail](#virtual-sensor-transmission-in-detail).
This is not an automatic periodic
sensor simulator: your source integration must provide the desired updates.

Alternatively, in Swagger discover the actual datapoint ID first, then use
`POST /api/v1/datapoints/{datapoint_id}/value` with `{"value": 20}` for a writable
temperature datapoint. Use an admin token. Do not assume a datapoint ID from an
example. An `accepted` response means submitted to the owning runtime, not confirmed
receiver action. Delayed virtual-device encoding/radio failures are published to
`<base_topic>/gateway/error`; do not assume that this write response reports them.

Check Busmonitor for **TX**, the allocated sender and expected raw/decoded data;
also check logs. A TX entry alone is not proof a separate receiver heard it. Verify
the receiving gateway/device independently. If you receive `no matching TX telegram`,
check the profile's encoding support, direction, defaults and required channels.

### Virtual sensor transmission in detail

#### Why one datapoint write is not necessarily one radio telegram

A KNX integration often writes an individual group-address value. Writing one
virtual EnOcean datapoint instead updates the gateway's cached sensor state.
The selected EEP defines a radio payload with fixed fields: for example,
A5-04-02 carries humidity and temperature together. Its measurement telegram
cannot simply omit the temperature bytes because only humidity was updated.
Other profiles may have separate telegram types or conditional fields; the
requirement is a complete **applicable telegram**, not that every channel of every
profile must always be sent together.

The gateway combines separately supplied values into a snapshot, then encodes
the affected telegram type(s) using it, profile defaults and protocol constants.
A successful MQTT publish, displayed channel state or accepted API/OBS write is
not proof that this snapshot could be encoded or sent by radio.

#### Channel-level `tx` settings

These entries belong to an individual object in the profile's `channels` array:

```json
"tx": {
  "managed": false,
  "required_for_snapshot": true
}
```

- `managed: false`: an ordinary integration-supplied input, offered by the virtual
  device UI's channel selector. It does not mean that transmission is disabled.
- `managed: true`: a runtime/profile-managed field, hidden from that selector.
  This flag alone does **not** generate a value or make it optional. Supply a
  valid default/runtime rule if automatic completion is intended.
- `required_for_snapshot: true`: an active binding needs a value before its
  telegram can be encoded. A cached explicit value or applicable default can
  satisfy this requirement. It does not require a new value on every send.
- `required_for_snapshot: false` (or absent): this semantic requirement is not
  enforced. Missing data do not acquire a measured value; protocol fields may
  keep their initialized/default bits. Do not disable the requirement merely
  to bypass a missing measurement: it can produce misleading telegrams.

The encoder resolves explicit values first, then a channel's `tx.default_value`,
then its channel-level `default_value`. These are semantic values in the declared
unit/type, not raw payload bytes. Defaults are deliberate fallbacks, not
measurements. Protocol fields can additionally have constants/defaults.
With `tx.runtime_default: "channel_enabled"`, the virtual runtime supplies
`available` / `not_available` based on the enabled channel named by
`runtime_default_channel` (or the object's own name). Use only supported runtime
rules; `managed` alone is not such a rule.

Disabling a channel in the virtual-device definition does not remove the EEP's
field or its active required binding. If another measurement remains required
and has no default, selecting only one channel is not sufficient.

#### Profile-level aggregation window

This separate `tx` object is at the **root of the profile**, not inside a channel:

```json
"tx": {
  "aggregation_window_seconds": 10
}
```

The runtime waits for a quiet interval after the **last** input update. Each
update cancels the previous timer and starts a new one. The default is 10 seconds
when the setting is absent; the minimum is 1 second, including for zero or
negative settings. This is not a cyclic-send interval, immediate send-on-completion
or a maximum value age. Continuous updates faster than the interval can keep
postponing transmission. Identical input writes also restart the timer; virtual
input writes are not filtered by `runtime.transmit_on_duplicate`.

The latest value for each channel remains in memory across sends and failed
encoding attempts. There is no automatic value-age expiry. A later update to one
channel can send it together with an older cached value of another channel.
The source integration must decide whether that older value is acceptable.
The cache is not persistent: after a gateway restart, initialize all required
inputs again unless defaults provide them. Retained state topics are output,
not automatic restoration of the input cache.

Example after a fresh start, with humidity and temperature required and no
measurement defaults:

1. At 0 seconds, write humidity `60`. It is stored; no radio telegram yet.
2. At 4 seconds, write temperature `20`. The timer moves to 14 seconds.
3. At about 14 seconds, a telegram can contain humidity `60` and temperature `20`,
   provided profile encoding and the TX interface are usable.
4. Later, writing only temperature `21` can send humidity `60` and temperature
   `21` after another quiet interval. Humidity need not be resent for every
   telegram while its cached value remains appropriate.

If step 2 never happens, the timer expires with an incomplete snapshot: encoding
fails and no measurement telegram is sent. Humidity remains cached. A later
temperature update schedules a new attempt; there is no periodic retry without
another input update.

#### Configuration and diagnosis through MQTT, API and OBS

Choose enabled channels in **Device Management**. There is no per-device UI/config
override for the aggregation window: edit the selected profile JSON's root `tx`
object. This affects all devices using that profile. Defaults/requirements are
also profile settings. Back up customizations, preserve protocol correctness and
restart the gateway after profile edits to refresh cached definitions. Initialize
the inputs again. Changing an interval cannot fix a missing required value.

In OBS, bind and initialize every required input, or deliberately configure a
valid fallback. MQTT clients should likewise initialize them at startup using
non-retained `/set` commands. Thereafter send changes or deliberate periodic
updates according to the receiver's freshness requirements.

Subscribe to `<base_topic>/gateway/error`, for example `enocean-mqtt/gateway/error`.
Virtual TX errors contain `component: "virtual-device"`,
`message: "Virtual device TX failed"`, the affected `topic` and an `error` detail
such as `missing required value: temperature` or `no matching TX telegram`.
Events are non-retained and QoS 0: a disconnected observer can miss them.
The current virtual error publisher does not additionally write this error to
the application logger or expose an asynchronous per-write failure result to OBS.
Do not rely on the Web UI log view or `journalctl` alone for these errors.

Inspect `<base_topic>/virtual/<id>/state` for supplied values and their individual
timestamps, then the Busmonitor TX event and its transmission result. Input state
is not proof of radio transmission. A disabled/unavailable interface is separate
from an incomplete snapshot; transmission does not prove receiver acceptance.

## 4. Teach-In and receiver records

Receiving and decoding an ordinary sensor does not generally require transmitting
Teach-In from this gateway. Adding a device to the registry is not the same as
pairing an actuator with a virtual or gateway sender.

For a supported transmitting device/profile:

1. Read the receiver's manual and put the intended receiver into its learning mode.
   Perform this only on a safe test receiver; pairing and TX can change real equipment.
2. In Device Management select **Teach-in** for the physical or virtual device.
   Check the sender and profile before confirming transmission.
3. Check the receiver's documented success indication. Sent does not mean paired.
4. Use **Confirm receiver** only after you have independently verified success.
   This stores your confirmation; it is not an automatically received acknowledgement.
5. Leave learning mode and test an appropriate command/value, checking receiver
   behavior independently. A transmitted command is not proof of actuator state.

Bidirectional 4BS Teach-In does not currently work. The D2/VLD EEP family is not
yet stably implemented. Neither belongs to the stable supported release scope;
do not promise these workflows from successful ordinary A5/D5/F6 telegram tests.

## 5. Check one enum through MQTT, API and OBS

For a reviewed door profile, change the actual contact state and inspect the
new observation. MQTT JSON and API values should carry a numeric code and, when
known, its `meaning`, such as `0` / `door_closed`. Do not assume that `0` always
means closed or unlocked; the selected profile's table defines the meaning.

The scalar MQTT channel `/value` contains only the code. In an OBS version that
implements representation selection, bind **value** to a numeric object or
**meaning** to a string object. These are two views of one datapoint, not two
independently timestamped sensors. Missing/unknown meanings must not retain an old
label. For boolean objects, apply an explicit transformation based on the enum
table. Do not interpret every nonzero code as true without checking it.

Continue with the [practical acceptance checklist](acceptance-checklist.md).
