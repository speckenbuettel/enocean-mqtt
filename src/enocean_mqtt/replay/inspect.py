"""Inspect Weinzierl replay capture files."""

from __future__ import annotations

import argparse

from enocean_mqtt.replay.weinzierl_enolog import WeinzierlEnologReader


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(
        description="Inspect Weinzierl .enolog replay files."
    )

    parser.add_argument(
        "capture_file",
        help="Path to Weinzierl .enolog capture file",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of telegrams to inspect",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print all telegram properties",
    )

    return parser.parse_args()



def main() -> None:
    """Inspect replay capture contents."""

    args = parse_args()

    reader = WeinzierlEnologReader(args.capture_file)

    telegram_count = reader.get_telegram_count()

    print(f"Loaded {telegram_count} telegrams")
    print()

    telegrams_found = 0

    for telegram in reader.iter_telegrams(limit=args.limit):
        telegrams_found += 1

        print(f"telegram_id: {telegram.telegram_id}")
        print(f"timestamp:   {telegram.timestamp}")
        print(f"protocol:    {telegram.protocol}")
        print(f"type:        {telegram.telegram_type}")
        print(f"direction:   {telegram.direction}")
        print(f"eno_id:      {telegram.eno_id}")
        print(f"eno_rorg:    {telegram.eno_rorg}")
        print(f"eno_rssi:    {telegram.eno_rssi}")
        print(f"eno_data:    {telegram.eno_data}")

        if args.verbose:
            print()
            print("properties:")

            for key in sorted(telegram.properties):
                value = telegram.properties[key]
                print(f"  {key} = {value}")

        print()

    if telegrams_found == 0:
        print("No telegrams matched current filter.")


if __name__ == "__main__":
    main()
