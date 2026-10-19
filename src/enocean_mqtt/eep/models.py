"""Formal EEP registry models.

The models in this module describe the normalized Registry v3 runtime model used
by enocean-mqtt.

Registry v3 separates protocol fields, semantic objects, and telegram bindings:

- ``fields`` / ``status_fields`` contain technical raw telegram fields.
- ``channels`` contain device-to-gateway semantic values.
- ``messages`` contain gateway-to-device semantic values and commands.
- ``channel_bindings`` / ``message_bindings`` connect raw fields with semantic
  objects for a concrete telegram variant.

A few legacy attributes are intentionally retained as optional compatibility
fields while the loader, decoder, TX runtime, and generated registry files are
migrated to the canonical Registry v3 shape. New code should use the Registry v3
fields documented by the class docstrings.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Literal

DataType = Literal["boolean", "float", "integer", "string", "enum"]
Direction = Literal["rx", "tx"]
DependencySource = Literal["field", "status_field", "context", "telegram_id"]
DeviceClass = Literal[
    "sensor",
    "actuator_unidirectional",
    "actuator_bidirectional",
    "controller",
]
FunctionGroupDirection = Literal["from", "to"]
ObjectType = Literal[
    "measurement",
    "state",
    "setpoint",
    "command",
    "configuration",
    "diagnostic",
    "selector",
]
OutputTarget = Literal["mqtt", "api", "storage"]
ProfileDirection = Literal["unidirectional", "bidirectional"]
ProfileType = Literal["standard", "proprietary"]

SemanticValue = int | str | bool | float
SourcesDefinition = list[str] | dict[str, Any]


@dataclass(slots=True)
class LinearScale:
    """Linear raw-to-semantic conversion."""

    raw_min: float
    raw_max: float
    scale_min: float
    scale_max: float


@dataclass(slots=True)
class ValueMapping:
    """Discrete raw-to-semantic value mapping for enum-like values.

    ``value`` is the raw protocol value. ``label`` is a stable registry and
    diagnostic label. If ``semantic_value`` is present, runtime decoding returns
    that value instead of the label.
    """

    value: SemanticValue
    label: str
    semantic_value: SemanticValue | None = None
    description: str | None = None


@dataclass(slots=True)
class DependencyDefinition:
    """Runtime dependency condition.

    This object is used for executable conditions on bindings and constraints.
    Therefore ``field`` is required here.
    """

    field: str
    source: DependencySource = "field"
    equals: SemanticValue | None = None
    not_equals: SemanticValue | None = None
    values: list[SemanticValue] = dataclass_field(default_factory=list)
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)
    gte: int | float | None = None
    lte: int | float | None = None

    def __post_init__(self) -> None:
        from enocean_mqtt.eep.numeric_conditions import validate_bounds

        validate_bounds(self.gte, self.lte)


@dataclass(slots=True)
class DependencyDescription:
    """Review/API dependency description.

    Registry v3 allows profile-level and telegram-level ``dependencies[]`` as
    documentation and validation metadata. These entries describe *why* a
    semantic object depends on a selector, but they are not directly executable
    runtime conditions. Runtime conditions remain ``DependencyDefinition`` values
    on ``depends_on`` fields.
    """

    target: str | None = None
    depends_on: DependencyDefinition | None = None
    reason: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(slots=True)
class ValueRangeMapping:
    """Semantic value range description.

    Registry v3 semantic ranges use ``min``/``max``/``step``. Legacy raw range
    fields remain optional to allow transitional loading of existing generated
    files until the compiler output is fully aligned.
    """

    min: int | float | None = None
    max: int | float | None = None
    step: int | float | None = None
    unit: str | None = None
    description: str | None = None

    # Transitional compatibility for older registry files.
    raw_min: int | float | None = None
    raw_max: int | float | None = None
    label: str | None = None
    scale: LinearScale | None = None
    depends_on: DependencyDefinition | None = None


@dataclass(slots=True)
class RuntimeHintDefinition:
    """Runtime behaviour hints imported from source metadata."""

    transmit_on_connect: bool | None = None
    transmit_on_event: bool | None = None
    transmit_on_duplicate: bool | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(slots=True)
class OutputDefinition:
    """Target-specific output policy."""

    mqtt: bool = True
    api: bool = True
    storage: bool = True
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(slots=True)
class TxDefinition:
    """TX snapshot and cache handling metadata."""

    managed: bool = False
    default_value: SemanticValue | None = None
    runtime_default: str | None = None
    runtime_default_channel: str | None = None
    required_for_snapshot: bool = False
    aggregation_window_seconds: float | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)


# Backwards-compatible names used by current runtime modules.
ChannelTxDefinition = TxDefinition
ProfileTxDefinition = TxDefinition


@dataclass(slots=True)
class FieldDefinition:
    """Technical raw field definition inside payload or status data."""

    name: str
    offset: int
    size: int
    shortcut: str | None = None
    description: str | None = None
    data_type: DataType | None = None
    signed: bool = False
    raw_min: int | float | None = None
    raw_max: int | float | None = None
    enum: list[ValueMapping] = dataclass_field(default_factory=list)
    default_value: SemanticValue | None = None
    reserved: bool = False
    constant: SemanticValue | None = None
    source: Literal["payload", "status"] = "payload"
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    # Transitional compatibility for older registry files.
    bitrange: str | None = None


# Backwards-compatible name used by the current loader and decoder.
BitFieldDefinition = FieldDefinition


@dataclass(slots=True)
class ConstraintDefinition:
    """Declarative telegram validation rule."""

    name: str | None = None
    field: str | None = None
    equals: SemanticValue | None = None
    not_equals: SemanticValue | None = None
    values: list[SemanticValue] = dataclass_field(default_factory=list)
    if_dependency: DependencyDefinition | None = None
    requires: DependencyDefinition | None = None
    description: str | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(slots=True)
class ContextUpdateDefinition:
    """Runtime context update derived from a decoded telegram."""

    context: str
    from_field: str | None = None
    value: SemanticValue | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(slots=True)
class FunctionGroupDefinition:
    """Source-derived semantic function group imported from IP JSON."""

    name: str
    title: str
    direction: FunctionGroupDirection
    description: str | None = None
    functions: list[str] = dataclass_field(default_factory=list)
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(slots=True)
class ChannelDefinition:
    """Canonical device-to-gateway semantic value definition."""

    name: str
    data_type: DataType
    semantic_role: str | None = None
    object_type: ObjectType | None = None
    display_name: str | None = None
    description: str | None = None
    source_key: str | None = None
    function_group: str | None = None
    semantic_confidence: str | None = None
    semantic_attributes: dict[str, Any] = dataclass_field(default_factory=dict)
    unit: str | None = None
    enum: list[ValueMapping] = dataclass_field(default_factory=list)
    ranges: list[ValueRangeMapping] = dataclass_field(default_factory=list)
    default_value: SemanticValue | None = None
    value_resolution: float | None = None
    value_precision: int | None = None
    runtime: RuntimeHintDefinition | None = None
    output: OutputDefinition = dataclass_field(default_factory=OutputDefinition)
    tx: TxDefinition | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    # Transitional compatibility fields. New Registry v3 data should not use
    # these; loader migration will map older values into canonical fields.
    channel_type: str | None = None
    writable: bool = False
    friendly_name: str | None = None
    field_ref: str | None = None
    bitfield: FieldDefinition | None = None
    scale: LinearScale | None = None
    depends_on: DependencyDefinition | None = None

    @property
    def api_object_type(self) -> str | None:
        """Return canonical object type for API consumers."""

        return self.object_type or self.channel_type


@dataclass(slots=True)
class FieldPartDefinition:
    """Whole unsigned payload field placed at an LSB-based raw value offset."""

    field_ref: str
    value_offset: int


@dataclass(slots=True)
class ChannelBindingDefinition:
    """Telegram-specific mapping from a raw field to a semantic channel."""

    channel_ref: str
    field_ref: str | None = None
    scale: LinearScale | None = None
    enum: list[ValueMapping] = dataclass_field(default_factory=list)
    ranges: list[ValueRangeMapping] = dataclass_field(default_factory=list)
    depends_on: DependencyDefinition | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    # Transitional compatibility for older registry files.
    bitfield_ref: str | None = None
    field_parts: list[FieldPartDefinition] = dataclass_field(default_factory=list)


@dataclass(slots=True)
class MessageBindingDefinition:
    """Telegram-specific mapping from a semantic message to a raw field."""

    message_ref: str
    field_ref: str | None = None
    scale: LinearScale | None = None
    enum: list[ValueMapping] = dataclass_field(default_factory=list)
    ranges: list[ValueRangeMapping] = dataclass_field(default_factory=list)
    depends_on: DependencyDefinition | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    # Transitional compatibility for older registry files.
    bitfield_ref: str | None = None
    field_parts: list[FieldPartDefinition] = dataclass_field(default_factory=list)


@dataclass(slots=True)
class MessageDefinition:
    """Canonical gateway-to-device semantic value or command definition."""

    name: str
    data_type: DataType | None = None
    semantic_role: str | None = None
    object_type: ObjectType | None = None
    display_name: str | None = None
    description: str | None = None
    source_key: str | None = None
    function_group: str | None = None
    semantic_confidence: str | None = None
    semantic_attributes: dict[str, Any] = dataclass_field(default_factory=dict)
    unit: str | None = None
    enum: list[ValueMapping] = dataclass_field(default_factory=list)
    ranges: list[ValueRangeMapping] = dataclass_field(default_factory=list)
    default_value: SemanticValue | None = None
    value_resolution: float | None = None
    value_precision: int | None = None
    runtime: RuntimeHintDefinition | None = None
    output: OutputDefinition = dataclass_field(default_factory=OutputDefinition)
    tx: TxDefinition | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    # Message extension fields, especially for D2 command-based profiles.
    message_id: str | None = None
    message_type: str = "command"
    command_id: str | None = None
    extended_command_id: str | None = None
    response_to: str | None = None
    response_timeout_ms: int | None = None
    request: dict[str, Any] | None = None
    response: dict[str, Any] | None = None

    # Transitional compatibility fields.
    channels: list[ChannelDefinition] = dataclass_field(default_factory=list)
    channel_bindings: list[ChannelBindingDefinition] = dataclass_field(default_factory=list)
    depends_on: DependencyDefinition | None = None


@dataclass(slots=True)
class TelegramIdentity:
    """Protocol-level telegram identity."""

    rorg: str
    cmd: str | None = None
    ecid: str | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(slots=True)
class TelegramDefinition:
    """Normalized protocol telegram variant definition."""

    telegram_type_id: str
    telegram_id: TelegramIdentity
    direction: Direction | None = None
    description: str | None = None
    fields: list[FieldDefinition] = dataclass_field(default_factory=list)
    status_fields: list[FieldDefinition] = dataclass_field(default_factory=list)
    channel_bindings: list[ChannelBindingDefinition] = dataclass_field(default_factory=list)
    message_bindings: list[MessageBindingDefinition] = dataclass_field(default_factory=list)
    constraints: list[ConstraintDefinition] = dataclass_field(default_factory=list)
    context_updates: list[ContextUpdateDefinition] = dataclass_field(default_factory=list)
    dependencies: list[DependencyDescription] = dataclass_field(default_factory=list)
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    # Transitional compatibility fields.
    channels: list[ChannelDefinition] = dataclass_field(default_factory=list)
    messages: list[MessageDefinition] = dataclass_field(default_factory=list)
    metadata_channels: list[ChannelDefinition] = dataclass_field(default_factory=list)
    teach_in: dict[str, Any] | None = None
    security: dict[str, Any] | None = None


@dataclass(slots=True)
class EEPDefinition:
    """Normalized Registry v3 EEP or proprietary profile definition."""

    eep: str
    rorg: str
    func: str
    type: str
    profile_type: ProfileType = "standard"
    func_description: str | None = None
    type_description: str | None = None
    description: str | None = None
    source: str | None = None
    source_version: str | None = None
    sources: SourcesDefinition = dataclass_field(default_factory=list)
    direction: ProfileDirection | None = None
    device_class: DeviceClass | None = None
    function_groups: list[FunctionGroupDefinition] = dataclass_field(default_factory=list)
    channels: list[ChannelDefinition] = dataclass_field(default_factory=list)
    messages: list[MessageDefinition] = dataclass_field(default_factory=list)
    telegrams: list[TelegramDefinition] = dataclass_field(default_factory=list)
    dependencies: list[DependencyDescription] = dataclass_field(default_factory=list)
    tx: TxDefinition | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    # Transitional compatibility fields.
    addressing: str | None = None
    teach_in_method: str | None = None
    metadata_channels: list[ChannelDefinition] = dataclass_field(default_factory=list)
    security: dict[str, Any] | None = None
