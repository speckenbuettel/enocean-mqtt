"""Robust Compiler 3.0 entry point for Excel-maintained eep-list.csv.

This wrapper delegates to compile_eep.py but replaces its eep-list loader with a
reader that tolerates spreadsheet CSV files:

- UTF-8 with or without BOM
- Windows-1252 / ISO-8859-1
- comma, semicolon or tab delimiters
- surrounding header and cell whitespace

It exists as a low-risk compatibility entry point while compile_eep.py is still
being iterated.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
from pathlib import Path
from typing import Any, Protocol, cast

Json = dict[str, Any]
SUPPORTED_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "iso-8859-1")
SUPPORTED_DELIMITERS = ",;\t"
_COMPILER_PATH = Path(__file__).with_name("compile_eep.py")
_SPEC = importlib.util.spec_from_file_location("enocean_mqtt_compile_eep", _COMPILER_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Cannot load compiler from {_COMPILER_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
compiler = cast(Any, _MODULE)


class Diagnostics(Protocol):
    """Minimal diagnostics interface used by the robust CSV loader."""

    def warn(self, code: str, message: str, *, context: str | None = None) -> None: ...

    def error(self, code: str, message: str, *, context: str | None = None) -> None: ...


def read_text_with_fallback(path: Path, diagnostics: Diagnostics) -> str | None:
    for encoding in SUPPORTED_ENCODINGS:
        try:
            text = path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        if encoding not in {"utf-8", "utf-8-sig"}:
            diagnostics.warn(
                "EEP_LIST_ENCODING_FALLBACK",
                f"read EEP list with fallback encoding '{encoding}'",
            )
        return text
    diagnostics.error(
        "EEP_LIST_ENCODING_ERROR",
        f"could not decode EEP list with supported encodings: {path}",
    )
    return None


def detect_csv_dialect(
    text: str,
    diagnostics: Diagnostics,
) -> type[csv.Dialect]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=SUPPORTED_DELIMITERS)
    except csv.Error:
        first_line = sample.splitlines()[0] if sample.splitlines() else ""
        if ";" in first_line:

            class SemicolonDialect(csv.excel):
                delimiter = ";"

            dialect = SemicolonDialect
        elif "\t" in first_line:
            dialect = csv.excel_tab
        else:
            dialect = csv.excel
    if dialect.delimiter != ",":
        diagnostics.warn(
            "EEP_LIST_DELIMITER_DETECTED",
            f"detected EEP list delimiter {dialect.delimiter!r}",
        )
    return dialect


def normalize_csv_row(row: dict[str | None, str | None]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        normalized_key = key.strip().lstrip("\ufeff")
        result[normalized_key] = (value or "").strip()
    return result


def load_eep_list(
    path: Path,
    diagnostics: Diagnostics,
) -> dict[str, dict[str, str]]:
    if not path.exists():
        diagnostics.warn("EEP_LIST_MISSING", f"EEP list does not exist: {path}")
        return {}

    text = read_text_with_fallback(path, diagnostics)
    if text is None:
        return {}

    dialect = detect_csv_dialect(text, diagnostics)
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    fieldnames = {
        (field or "").strip().lstrip("\ufeff") for field in (reader.fieldnames or [])
    }

    required = {"eep", "direction", "device_class"}
    missing = sorted(required - fieldnames)
    for column in missing:
        diagnostics.warn(
            "EEP_LIST_COLUMN_MISSING",
            f"EEP list is missing column '{column}'; detected columns: {sorted(fieldnames)}",
        )
    if "eep" not in fieldnames:
        return {}

    result: dict[str, dict[str, str]] = {}
    for raw_row in reader:
        row = normalize_csv_row(raw_row)
        eep = row.get("eep", "").strip().upper()
        if not eep:
            diagnostics.warn("EEP_LIST_EMPTY_EEP", "ignored row without EEP id")
            continue
        if eep in result:
            diagnostics.warn(
                "EEP_LIST_DUPLICATE",
                f"duplicate EEP list row for {eep}; first row kept",
            )
            continue
        result[eep] = row
    return result


compiler._core.load_eep_list = load_eep_list


if __name__ == "__main__":
    compiler.main()
