"""Derive Python distribution metadata from the canonical project VERSION."""

import re
from pathlib import Path


def package_version(root: Path) -> str:
    """Keep SemVer releases; convert legacy dated revisions for historical builds."""
    value = (root / "VERSION").read_text(encoding="utf-8").strip()
    if re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        return value
    match = re.fullmatch(r"([0-9]{4})-(0[1-9]|1[0-2])-([0-9]{3})", value)
    if match is None:
        raise ValueError("VERSION must use SemVer MAJOR.MINOR.PATCH or legacy YYYY-MM-NNN")
    return ".".join(str(int(part)) for part in match.groups())


if __name__ == "__main__":
    from setuptools import setup

    setup(version=package_version(Path(__file__).resolve().parent))
