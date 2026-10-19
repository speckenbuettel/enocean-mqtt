"""Inclusive numeric bounds shared by RX, TX and registry validation."""

from __future__ import annotations

import math
from typing import Any


def validate_bounds(gte: Any = None, lte: Any = None) -> None:
    for name, bound in (("gte", gte), ("lte", lte)):
        if bound is not None and (
            type(bound) not in (int, float)
            or (isinstance(bound, float) and not math.isfinite(bound))
        ):
            raise ValueError(f"{name} must be a finite number")
    if gte is not None and lte is not None and gte > lte:
        raise ValueError("gte must not exceed lte")


def bounds_match(value: Any, gte: Any = None, lte: Any = None) -> bool:
    validate_bounds(gte, lte)
    if gte is None and lte is None:
        return True
    if type(value) not in (int, float):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return (gte is None or value >= gte) and (lte is None or value <= lte)
