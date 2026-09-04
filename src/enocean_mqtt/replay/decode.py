"""Decode Weinzierl replay capture files using the EEP decoder engine."""

from __future__ import annotations

import argparse
import json
from typing import Any

from enocean_mqtt.devices.registry import DeviceRegistry
from enocean_mqtt.eep.decoder import EEPDecodeError, decode_eep, decoded_values_to_plain_dict
from enocean_mqtt.replay.weinzierl_enolog import WeinzierlEnologReader

RORG_TO_EEP_PREFIX = {
    "165": "A5",
    "213": "D5",
    "246": "F6",
    "210": "D2",
}



def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(
        description="Decode Weinzierl .enolog replay files using known EEP definitions."
    )

    parser.add_argument(
        "capture_file",
        help="Path to Weinzierl .enolog capture file",
    )

    parser.add_argument(
        "--devices-json",
        help="Path to devices.json registry",
    )

    parser.add_argument(
        "--eep",
        action="append",
        default=[],
        metavar="SENDER_ID=EEP",
        help="Assign EEP to sender ID, e.g. 059AB4C3=A5-14-03. Can be used multiple times.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of EnOcean telegrams to process",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Print decoded telegrams as JSON lines",
    )

    return parser.parse_args()



def parse_eep_mapping(values: list[str]) -> dict[str, str]:
    """Parse sender-to-EEP CLI mapping."""

    mapping: dict[str, str] = {}

    for value in values:
        if "=" not in value:
            raise SystemExit(f"Invalid --eep mapping: {value}")

        sender_id, eep = value.split("=", 1)
        mapping[sender_id.strip().upper()] = eep.strip()

    return mapping



def telegram_to_dict(
    telegram_id: int,
    timestamp: str | None,
    sender_id: str | None,
    device_id: str | None,
    device_name: str | None,
    known_device: bool,
    eep: str | None,
    payload: str | None,
    decoded: dict[str, Any] | None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build serializable decoded replay output."""

    return {
        "telegram_id": telegram_id,
        "timestamp": timestamp,
        "sender_id": sender_id,
        "device_id": device_id,
        "device_name": device_name,
        "known_device": known_device,
        "eep": eep,
        "payload": payload,
        "decoded": decoded,
        "error": error,
    }



def print_text_result(result: dict[str, Any]) -> None:
    """Print one decoded telegram in human-readable form."""

    print(f"telegram_id:   {result['telegram_id']}")
    print(f"timestamp:     {result['timestamp']}")
    print(f"sender_id:     {result['sender_id']}")
    print(f"device_id:     {result['device_id']}")
    print(f"device_name:   {result['device_name']}")
    print(f"known_device:  {result['known_device']}")
    print(f"eep:           {result['eep']}")
    print(f"payload:       {result['payload']}")

    if result["error"]:
        print(f"error:         {result['error']}")
    elif result["decoded"]:
        print("decoded:")

        for name, channel in result["decoded"].items():
            unit = channel.get("unit") or ""
            print(f"  {name}: {channel['value']} {unit}".rstrip())

    print()



def main() -> None:
    """Decode replay capture contents."""

    args = parse_args()
    eep_mapping = parse_eep_mapping(args.eep)

    registry: DeviceRegistry | None = None

    if args.devices_json:
        registry = DeviceRegistry.from_json(args.devices_json)

    reader = WeinzierlEnologReader(args.capture_file)

    processed = 0

    for telegram in reader.iter_telegrams(limit=args.limit):
        processed += 1

        sender_id = telegram.eno_id.upper() if telegram.eno_id else None

        device = None
        device_id = None
        device_name = None
        known_device = False

        if registry and sender_id:
            device = registry.get_by_device_id(sender_id)

            if device:
                device_id = device.device_id
                device_name = device.device_name
                known_device = True

        eep = eep_mapping.get(sender_id or "")

        if eep is None and device:
            eep = device.registry_profile

        decoded: dict[str, Any] | None = None
        error: str | None = None

        if eep is None:
            error = "No EEP mapping for sender"
        elif telegram.eno_data is None:
            error = "Telegram has no EnOcean payload"
        else:
            try:
                decoded_telegram = decode_eep(eep, telegram.eno_data)
                decoded = decoded_values_to_plain_dict(decoded_telegram)
            except EEPDecodeError as exc:
                error = str(exc)

        result = telegram_to_dict(
            telegram_id=telegram.telegram_id,
            timestamp=telegram.timestamp,
            sender_id=sender_id,
            device_id=device_id,
            device_name=device_name,
            known_device=known_device,
            eep=eep,
            payload=telegram.eno_data,
            decoded=decoded,
            error=error,
        )

        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print_text_result(result)

    if processed == 0:
        print("No EnOcean telegrams found.")


if __name__ == "__main__":
    main()
