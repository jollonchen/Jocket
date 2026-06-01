from __future__ import annotations

import math
from typing import Iterable


def finite_float_values(values: Iterable[object]) -> list[float]:
    """Return only finite numeric values, dropping None, NaN and infinities."""
    finite_values: list[float] = []
    for value in values:
        numeric = finite_float_or_none(value)
        if numeric is not None:
            finite_values.append(numeric)
    return finite_values


def finite_float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(numeric):
        return numeric
    return None
