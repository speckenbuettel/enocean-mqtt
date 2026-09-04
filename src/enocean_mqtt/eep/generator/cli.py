"""CLI for minimal EEP XML registry generation."""

from __future__ import annotations

import argparse

import enocean_mqtt.eep.generator.parser as parser_module
from enocean_mqtt.eep.generator.parser import load_eep_definition
from enocean_mqtt.eep.generator.semantic_mapping import (
    apply_semantic_shortcut_mapping,
    enrich_definition_tx_metadata,
)
from enocean_mqtt.eep.generator.writer import write_eep_json


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(
        description="Generate canonical EEP registry JSON from EnOcean Alliance XML."
    )

    parser.add_argument(
        "--xml",
        required=True,
        help="Path to EnOcean Alliance XML file",
    )

    parser.add_argument(
        "--eep",
        required=True,
        help="EEP identifier, e.g. A5-14-0A",
    )

    parser.add_argument(
        "--output-dir",
        default="eep/registry",
        help="Target registry directory",
    )

    return parser.parse_args()



def main() -> None:
    """Generate canonical EEP JSON file."""

    args = parse_args()

    apply_semantic_shortcut_mapping(parser_module)

    definition = load_eep_definition(args.xml, args.eep)
    definition = enrich_definition_tx_metadata(definition)

    target_file = write_eep_json(definition, args.output_dir)

    print(f"Generated: {target_file}")


if __name__ == "__main__":
    main()
