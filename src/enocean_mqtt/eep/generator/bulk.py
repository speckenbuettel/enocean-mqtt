"""Bulk compiler for normalized EEP registry JSON files."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

import enocean_mqtt.eep.generator.parser as parser_module
from enocean_mqtt.eep.generator.parser import EEPGeneratorError, load_eep_definition
from enocean_mqtt.eep.generator.semantic_mapping import (
    apply_semantic_shortcut_mapping,
    enrich_definition_tx_metadata,
)
from enocean_mqtt.eep.generator.validator import validate_eep_definition
from enocean_mqtt.eep.generator.writer import write_eep_json


def _text(element: ET.Element, name: str) -> str:
    """Return stripped child text."""

    return (element.findtext(name) or "").strip()


def _normalize_hex(value: str) -> str:
    """Normalize XML number notation."""

    value = value.strip().upper()

    if value.startswith("0X"):
        value = value[2:]

    return value.zfill(2)


def iter_eep_ids(xml_path: str | Path) -> list[str]:
    """Return all EEP IDs contained in an Alliance XML file."""

    tree = ET.parse(xml_path)
    root = tree.getroot()

    eep_ids: list[str] = []

    for rorg in root.findall("./profile/rorg"):
        rorg_number = _normalize_hex(_text(rorg, "number"))

        for func in rorg.findall("./func"):
            func_number = _normalize_hex(_text(func, "number"))

            for eep_type in func.findall("./type"):
                type_number = _normalize_hex(_text(eep_type, "number"))

                eep_ids.append(
                    f"{rorg_number}-{func_number}-{type_number}"
                )

    return sorted(set(eep_ids))


def compile_all_eep_definitions(
    xml_path: str | Path,
    output_dir: str | Path,
    eep_ids: list[str] | None = None,
) -> tuple[int, int]:
    """Compile EEP definitions into normalized registry JSON."""

    apply_semantic_shortcut_mapping(parser_module)

    generated = 0
    failed = 0

    targets = eep_ids or iter_eep_ids(xml_path)

    for eep_id in targets:
        try:
            definition = load_eep_definition(xml_path, eep_id)
            definition = enrich_definition_tx_metadata(definition)

            issues = validate_eep_definition(definition)
            output_file = write_eep_json(definition, output_dir)

            generated += 1
            print(f"OK     {eep_id} -> {output_file}")

            for issue in issues:
                print(f"       {issue}")

        except EEPGeneratorError as exc:
            failed += 1
            print(f"FAILED {eep_id}: {exc}")

    return generated, failed


def main() -> None:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description="Bulk-compile normalized EEP registry JSON files",
    )

    parser.add_argument(
        "--xml",
        required=True,
        help="Path to Alliance EEP XML file",
    )

    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for generated registry files",
    )

    parser.add_argument(
        "--eep",
        action="append",
        dest="eep_ids",
        help="Compile only the specified EEP ID (repeatable)",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    generated, failed = compile_all_eep_definitions(
        xml_path=args.xml,
        output_dir=output_dir,
        eep_ids=args.eep_ids,
    )

    print()
    print(f"Generated: {generated}")
    print(f"Failed:    {failed}")


if __name__ == "__main__":
    main()
