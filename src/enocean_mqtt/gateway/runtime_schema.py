"""Runtime command schema validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeAlias

RuntimeArgumentType: TypeAlias = type | tuple[type, ...]


class RuntimeCommandValidationError(Exception):
    """Structured runtime command validation error."""

    def __init__(
        self,
        error_type: str,
        message: str,
        **details: Any,
    ) -> None:
        super().__init__(message)

        self.error_type = error_type
        self.message = message
        self.details = details


@dataclass(slots=True)
class RuntimeCommandDefinition:
    """Runtime command schema definition."""

    name: str
    required_fields: dict[str, RuntimeArgumentType] = field(default_factory=dict)
    optional_fields: dict[str, RuntimeArgumentType] = field(default_factory=dict)


class RuntimeCommandValidator:
    """Validate runtime command payloads."""

    def __init__(self) -> None:
        self._definitions: dict[
            str,
            RuntimeCommandDefinition,
        ] = {}

    def register(
        self,
        definition: RuntimeCommandDefinition,
    ) -> None:
        """Register command schema."""

        self._definitions[definition.name] = definition

    def validate(
        self,
        command: str,
        payload: dict[str, Any],
    ) -> None:
        """Validate runtime command payload."""

        definition = self._definitions.get(command)

        if definition is None:
            raise RuntimeCommandValidationError(
                "unknown_command",
                "Unknown runtime command",
                command=command,
            )

        allowed_fields = {
            "command",
            *definition.required_fields.keys(),
            *definition.optional_fields.keys(),
        }

        for field_name in payload:
            if field_name not in allowed_fields:
                raise RuntimeCommandValidationError(
                    "unknown_argument",
                    "Unknown runtime argument",
                    command=command,
                    argument=field_name,
                )

        for field_name, field_type in (
            definition.required_fields.items()
        ):
            if field_name not in payload:
                raise RuntimeCommandValidationError(
                    "missing_argument",
                    "Missing required argument",
                    command=command,
                    argument=field_name,
                )

            self._validate_field_type(
                command=command,
                field_name=field_name,
                field_type=field_type,
                value=payload[field_name],
            )

        for field_name, field_type in (
            definition.optional_fields.items()
        ):
            if field_name not in payload:
                continue

            value = payload[field_name]

            if value is None:
                continue

            self._validate_field_type(
                command=command,
                field_name=field_name,
                field_type=field_type,
                value=value,
            )

    @staticmethod
    def _type_name(field_type: RuntimeArgumentType) -> str:
        if isinstance(field_type, tuple):
            return " | ".join(
                item.__name__
                for item in field_type
            )

        return field_type.__name__

    def _validate_field_type(
        self,
        command: str,
        field_name: str,
        field_type: RuntimeArgumentType,
        value: Any,
    ) -> None:
        if isinstance(value, field_type):
            return

        raise RuntimeCommandValidationError(
            "invalid_argument_type",
            "Invalid runtime argument type",
            command=command,
            argument=field_name,
            expected_type=self._type_name(field_type),
            actual_type=type(value).__name__,
        )
