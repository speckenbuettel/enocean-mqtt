"""Export semantic-role-mapping.xlsx to semantic-role-mapping.json."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]

SOURCE = Path("eep/semantic-role-mapping.xlsx")
TARGET = Path("eep/semantic-role-mapping.json")
SHEET_NAME = "semantic-role-mapping"


def normalize_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def main() -> None:
    df = pd.read_excel(SOURCE, sheet_name=SHEET_NAME)

    records = []
    for row in df.fillna("").to_dict(orient="records"):
        records.append({normalize_key(str(k)): v for k, v in row.items()})

    TARGET.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
