"""Normalize eep-list.csv for Compiler 3.0 input.

This helper converts CSV files saved by spreadsheet applications into the
compiler's current canonical CSV format:

- UTF-8 without BOM
- comma separated
- stripped header and cell whitespace

It is intentionally small and deterministic. It can be removed once
compile_eep.py has been migrated to a dialect-aware CSV loader.
"""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path

SUPPORTED_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "iso-8859-1")
SUPPORTED_DELIMITERS = ",;\t"


def read_text_with_fallback(path: Path) -> tuple[str, str]:
    for encoding in SUPPORTED_ENCODINGS:
        try:
            return path.read_text(encoding=encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"Could not decode {path} with supported encodings")


def detect_dialect(text: str) -> type[csv.Dialect]:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=SUPPORTED_DELIMITERS)
    except csv.Error:
        first_line = sample.splitlines()[0] if sample.splitlines() else ""
        if ";" in first_line:
            class SemicolonDialect(csv.excel):
                delimiter = ";"

            return SemicolonDialect
        if "\t" in first_line:
            return csv.excel_tab
        return csv.excel


def normalize_row(row: dict[str | None, str | None]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        normalized_key = key.strip().lstrip("\ufeff")
        result[normalized_key] = (value or "").strip()
    return result


def normalize_csv(input_path: Path, output_path: Path) -> None:
    text, encoding = read_text_with_fallback(input_path)
    dialect = detect_dialect(text)
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError(f"CSV file has no header: {input_path}")
    fieldnames = [field.strip().lstrip("\ufeff") for field in reader.fieldnames]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, dialect=csv.excel)
        writer.writeheader()
        for raw_row in reader:
            writer.writerow(normalize_row(raw_row))

    print(
        f"OK normalized {input_path} -> {output_path} "
        f"(input_encoding={encoding}, input_delimiter={dialect.delimiter!r})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize eep-list.csv for Compiler 3.0")
    parser.add_argument("input", type=Path, nargs="?", default=Path("eep/eep-list.csv"))
    parser.add_argument("output", type=Path, nargs="?", default=Path("eep/eep-list.csv"))
    args = parser.parse_args()
    normalize_csv(args.input, args.output)


if __name__ == "__main__":
    main()
