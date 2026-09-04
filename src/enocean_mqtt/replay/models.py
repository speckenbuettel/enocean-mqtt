"""Replay data models."""

from __future__ import annotations

from dataclasses import dataclass

WEINZIERL_ENO_DATA_TELEGRAM_TYPE = "0"


@dataclass(slots=True)
class ReplayTelegram:
    """Normalized replay telegram representation.

    The model intentionally stays close to the busmonitor layer.
    It represents raw or normalized EnOcean telegram data and does not
    contain semantic device/channel state.
    """

    telegram_id: int
    timestamp: str | None
    protocol: str | None
    telegram_type: str | None
    direction: str | None
    eno_id: str | None
    eno_rorg: str | None
    eno_data: str | None
    eno_rssi: str | None
    raw_frame_data: str | None
    raw_apdu_data: str | None
    properties: dict[str, str]
    source: str | None = None
    destination_id: str | None = None
    status: str | None = None
    port: str | None = None
    optional_data: str | None = None
    subtelegram_count: int | None = None
    security_level: int | None = None
    tick_count: int | None = None
    interface_id: str | None = None

    @property
    def is_enocean_telegram(self) -> bool:
        """Return True for EnOcean payload telegrams."""

        if self.source == "dolphin_view":
            return self.telegram_type == "Radio"

        return self.telegram_type == WEINZIERL_ENO_DATA_TELEGRAM_TYPE

    @property
    def normalized_direction(self) -> str | None:
        """Return a normalized direction label."""

        if self.direction is None:
            return None

        direction = self.direction.lower()

        if direction in {"incoming", "in", "rx", "from"}:
            return "rx"

        if direction in {"outgoing", "out", "tx", "to"}:
            return "tx"

        return direction

    @property
    def payload_hex(self) -> str | None:
        """Return payload as compact uppercase hexadecimal string."""

        if self.eno_data is None:
            return None

        return "".join(self.eno_data.split()).upper()

    @property
    def sender_id(self) -> str | None:
        """Return sender ID as uppercase hexadecimal string."""

        if self.eno_id is None:
            return None

        return self.eno_id.strip().upper()
