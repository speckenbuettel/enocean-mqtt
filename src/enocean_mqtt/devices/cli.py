"""CLI for device registry import/export."""

from __future__ import annotations

import argparse

from enocean_mqtt.devices.csv_format import export_csv, import_csv
from enocean_mqtt.devices.registry import DeviceRegistry


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""

    parser = argparse.ArgumentParser(
        description="Import/export EnOcean device registries."
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    csv_to_json = subparsers.add_parser(
        "csv-to-json",
        help="Import CSV and generate devices.json",
    )

    csv_to_json.add_argument("input_csv")
    csv_to_json.add_argument("output_json")

    json_to_csv = subparsers.add_parser(
        "json-to-csv",
        help="Export devices.json as CSV",
    )

    json_to_csv.add_argument("input_json")
    json_to_csv.add_argument("output_csv")

    return parser



def main() -> None:
    """Run device registry CLI."""

    parser = build_parser()

    args = parser.parse_args()

    if args.command == "csv-to-json":
        registry = import_csv(args.input_csv)
        registry.to_json(args.output_json)

        print(f"Imported {len(registry.devices)} devices")
        print(f"Written: {args.output_json}")

    elif args.command == "json-to-csv":
        registry = DeviceRegistry.from_json(args.input_json)
        export_csv(registry, args.output_csv)

        print(f"Exported {len(registry.devices)} devices")
        print(f"Written: {args.output_csv}")


if __name__ == "__main__":
    main()
