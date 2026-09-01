"""Shared utility functions for the PST application.

Ported from src/pricingEngine.js (lines 31-51) to ensure calculation
parity between the existing JS POC and the new Python Streamlit app.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    """Return the current UTC timestamp as an ISO-8601 string (seconds precision)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_number(value: Any, fallback: float = 0.0) -> float:
    """Convert *value* to a float, stripping commas and trailing '%'.

    Port of ``pricingEngine.js:toNumber()`` (line 31).

    >>> to_number("1,234.56")
    1234.56
    >>> to_number("", 0)
    0.0
    >>> to_number(None)
    0.0
    """
    if value is None or value == "":
        return float(fallback)
    text = str(value).replace(",", "").replace("%", "").strip()
    if text == "":
        return float(fallback)
    try:
        return float(text)
    except (ValueError, TypeError):
        return float(fallback)


def normalize_percent(value: Any) -> float:
    """Normalise a percentage value to a 0-1 decimal.

    If the absolute value is > 1, it is assumed to be expressed out of 100
    and will be divided accordingly.

    Port of ``pricingEngine.js:normalizePercent()`` (line 38).

    >>> normalize_percent(5)
    0.05
    >>> normalize_percent(0.05)
    0.05
    """
    number = to_number(value)
    return number / 100 if abs(number) > 1 else number


def round_to_currency(value: float) -> float:
    """Round to two decimal places (standard currency rounding).

    Port of ``pricingEngine.js:roundToCurrency()`` (line 43).

    >>> round_to_currency(1.005)
    1.01
    """
    return round(float(value) + 1e-9, 2)


def round_up_to_unit(value: float, unit: float | int = 1) -> float:
    """Round *value* **up** to the nearest multiple of *unit*.

    Port of ``pricingEngine.js:roundUpToUnit()`` (line 47).

    >>> round_up_to_unit(44914.95, 5)
    44915.0
    >>> round_up_to_unit(100.0, 1)
    100.0
    """
    rounding_unit = to_number(unit, 1)
    if rounding_unit <= 0:
        return round_to_currency(value)
    return round_to_currency(math.ceil(value / rounding_unit) * rounding_unit)


def clean_text(value: Any) -> str:
    """Return a stripped string, or empty string for None."""
    if value is None:
        return ""
    return str(value).strip()
