"""Passive SIGNAL decoding, EnOcean Alliance Signal Telegram V3.5, sections 2.1-2.19.

Source: https://www.enocean-alliance.org/st/ . No automatic responses or TX.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

RORG_NAMES = {
    "A3": "HRC",
    "A4": "SYS",
    "A8": "ACK",
    "40": "CDM",
    "32": "NON_SEC",
    "33": "SEC_CDM",
    "B0": "GP_TEACH_IN",
    "B2": "GP_COMPLETE",
    "F6": "RPS",
    "D5": "1BS",
    "A5": "4BS",
    "D2": "VLD",
    "D1": "MSC",
    "A6": "ADT",
    "C6": "SM_LRN_REQ",
    "C7": "SM_LRN_ANS",
    "A7": "SM_REC",
    "C5": "SYS_EX",
    "30": "SEC",
    "31": "SEC_ENCAPS",
    "34": "SEC_MAN",
    "35": "SEC_TI",
    "D0": "SIGNAL",
    "D4": "UTE",
}

_NAMES = (
    "Reserved",
    "SMART ACK mailbox empty",
    "SMART ACK mailbox does not exist",
    "SMART ACK reset: trigger learn request",
    "Request status update",
    "Last unicast-message acknowledge",
    "Energy status",
    "Device revision",
    "Heartbeat",
    "RX window open",
    "RX-channel quality",
    "Duty cycle status",
    "Device configuration changed",
    "Harvester energy delivery",
    "TX mode off",
    "TX mode on",
    "Backup battery status",
    "Learn mode status",
    "Product ID",
    "Date and time",
)
_LENGTHS = {4: 2, 6: 2, 7: 9, 10: 8, 11: 2, 13: 2, 16: 2, 17: 10, 18: 7, 19: 7}


def decode_signal(data: str | None) -> dict[str, Any]:
    """Return diagnostics, retaining reserved and malformed messages as raw data."""
    result: dict[str, Any] = {"valid": False, "fields": {}}
    try:
        payload = bytes.fromhex(data or "")
    except ValueError:
        return {**result, "error": "Invalid hexadecimal SIGNAL payload"}
    if not payload:
        return {**result, "error": "Missing SIGNAL MID"}
    mid = payload[0]
    result.update(
        mid=f"{mid:02X}",
        name=_NAMES[mid] if mid < len(_NAMES) else "Reserved",
        optional_data=payload[1:].hex().upper(),
    )
    if not 1 <= mid <= 19:
        return {**result, "error": "Reserved SIGNAL MID"}
    expected = _LENGTHS.get(mid, 1)
    if len(payload) != expected:
        return {**result, "error": f"Expected {expected} payload bytes, got {len(payload)}"}
    fields: dict[str, Any] = result["fields"]
    errors: list[str] = []

    def reserved(condition: bool, name: str) -> None:
        if condition:
            errors.append(f"Reserved {name} value")

    if mid == 4:
        requests = [
            "EEP status",
            "Energy status",
            "Device revision",
            "RX-channel quality",
            "Harvester energy delivery",
            "Date and time",
        ]
        value = payload[1]
        fields.update(
            requested_status=value,
            requested_status_name=requests[value] if value < 6 else "Reserved",
        )
        reserved(value > 5, "requested status")
    elif mid in (6, 16):
        value = payload[1]
        fields["energy_percent"] = value if value <= 100 else None
        if mid == 6:
            fields["last_message_power_loss"] = value == 0
        else:
            fields["backup_battery_detected"] = value != 255
        reserved(value > 100 and not (mid == 16 and value == 255), "energy")
    elif mid == 7:
        fields.update(
            software_version=".".join(map(str, payload[1:5])),
            hardware_version=".".join(map(str, payload[5:9])),
        )
    elif mid == 9:
        fields.update(rx_window_open=True, rx_period_seconds=None)
    elif mid == 10:
        fields.update(
            device_id=payload[1:5].hex().upper(),
            dbm_worst=None if payload[5] == 255 else 127 - payload[5],
            dbm_best=None if payload[6] == 255 else 127 - payload[6],
            subtelegram_count=payload[7] >> 4 or None,
            max_repeater_level=None if payload[7] & 15 == 15 else payload[7] & 15,
        )
        reserved(3 <= (payload[7] & 15) <= 14, "repeater level")
    elif mid in (11, 13):
        value = payload[1] & 15
        if mid == 11:
            fields.update(
                duty_cycle_status=value, communication_available=value == 1 if value < 2 else None
            )
            reserved(value > 1, "duty cycle")
        else:
            fields.update(
                charging_capability=value,
                charging_description=["Very good", "Good", "Average", "Bad", "Very bad"][value]
                if value < 5
                else "Reserved",
            )
            reserved(value > 4, "charging capability")
    elif mid == 17:
        value, timeout = payload[1], payload[2]
        fields.update(
            link_table_full=bool(value & 128),
            teach_requests_enabled=bool(value & 64),
            learn_mode_type=(value >> 4) & 3,
            teach_result=value & 15,
            remaining_timeout_seconds=timeout * 10 if 1 <= timeout <= 254 else None,
            timeout_status="Not defined"
            if timeout == 0
            else "Not applicable"
            if timeout == 255
            else "Defined",
            device_id=None if payload[3:7] == b"\xff" * 4 else payload[3:7].hex().upper(),
            device_eep=None if payload[7:10] == b"\xff" * 3 else payload[7:10].hex().upper(),
        )
        reserved(6 <= (value & 15) <= 14, "teach result")
    elif mid == 18:
        fields.update(
            product_id=payload[1:].hex().upper(),
            manufacturer_id=payload[1:3].hex().upper(),
            product_reference=payload[3:7].hex().upper(),
        )
    elif mid == 19:
        daylight, hour = payload[4] >> 6, payload[4] & 63
        fields.update(
            year=2000 + payload[1],
            month=payload[2],
            day=payload[3],
            daylight_saving=daylight,
            hour=hour,
            minute=payload[5],
            second=payload[6],
        )
        reserved(daylight == 3, "daylight saving")
        try:
            fields["local_datetime"] = datetime(
                2000 + payload[1], payload[2], payload[3], hour, payload[5], payload[6]
            ).isoformat()
        except ValueError:
            errors.append("Invalid local date or time")
    result["valid"] = not errors
    if errors:
        result["error"] = "; ".join(errors)
    return result


def radio_diagnostics(rorg: str | None, data: str | None) -> dict[str, Any]:
    """Classify the received RORG without substituting a configured device EEP."""
    normalized = (rorg or "").upper()
    result: dict[str, Any] = {"telegram_kind": RORG_NAMES.get(normalized, "Unknown RORG")}
    if normalized == "D0":
        result["signal"] = decode_signal(data)
    elif normalized not in RORG_NAMES:
        result["protocol_warning"] = (
            "Unrecognized RORG; raw telegram retained without EEP interpretation"
        )
    return result
