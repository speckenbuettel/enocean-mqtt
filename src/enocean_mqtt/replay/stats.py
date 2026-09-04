"""Statistics for Weinzierl replay capture files."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime

from enocean_mqtt.replay.weinzierl_enolog import WeinzierlEnologReader

RORG_NAMES = {
    0xA5: "4BS",
    0xD5: "1BS",
    0xF6: "RPS",
    0xD2: "VLD",
}



def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(
        description="Show replay statistics for Weinzierl .enolog files."
    )

    parser.add_argument(
        "capture_file",
        help="Path to Weinzierl .enolog capture file",
    )

    return parser.parse_args()



def main() -> None:
    """Run replay statistics analysis."""

    args = parse_args()

    reader = WeinzierlEnologReader(args.capture_file)

    sender_counter: Counter[str] = Counter()
    rorg_counter: Counter[str] = Counter()

    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None

    telegram_count = 0

    for telegram in reader.iter_telegrams(limit=1_000_000):
        telegram_count += 1

        if telegram.eno_id:
            sender_counter[telegram.eno_id] += 1

        if telegram.eno_rorg:
            try:
                rorg_value = int(telegram.eno_rorg)
                rorg_hex = f"0x{rorg_value:02X}"
                rorg_name = RORG_NAMES.get(rorg_value, "Unknown")
                rorg_label = f"{rorg_hex} ({rorg_name})"
            except ValueError:
                rorg_label = telegram.eno_rorg

            rorg_counter[rorg_label] += 1

        if telegram.timestamp:
            timestamp = datetime.fromisoformat(
                telegram.timestamp.replace("Z", "+00:00")
            )

            if first_timestamp is None:
                first_timestamp = timestamp

            last_timestamp = timestamp

    print("Replay statistics")
    print("=================")
    print()

    print(f"Telegrams:         {telegram_count}")
    print(f"Unique senders:    {len(sender_counter)}")

    if first_timestamp and last_timestamp:
        duration = last_timestamp - first_timestamp
        duration_seconds = duration.total_seconds()

        print(f"Capture start:     {first_timestamp.isoformat()}")
        print(f"Capture end:       {last_timestamp.isoformat()}")
        print(f"Capture duration:  {duration}")

        if duration_seconds > 0:
            telegram_rate = telegram_count / duration_seconds
            print(f"Telegram rate:     {telegram_rate:.2f} telegrams/s")

    print()
    print("RORG distribution")
    print("-----------------")

    for rorg, count in rorg_counter.most_common():
        print(f"{rorg:<20} {count}")

    print()
    print("Top senders")
    print("-----------")

    for sender, count in sender_counter.most_common(10):
        print(f"{sender:<12} {count}")


if __name__ == "__main__":
    main()
