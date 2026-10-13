"""Formatage des nombres à la française (virgule décimale, espace fine des milliers)."""
from __future__ import annotations

import math

NA = "n.d."


def is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def fmt_num(x: float | None, decimals: int = 1) -> str:
    if not is_number(x):
        return NA
    return f"{x:,.{decimals}f}".replace(",", "\u202f").replace(".", ",")


def fmt_pct(x: float | None, decimals: int = 1, signed: bool = True) -> str:
    """x est une fraction (0.123 -> +12,3 %). signed=False affiche la valeur absolue."""
    if not is_number(x):
        return NA
    value = fmt_num(abs(x) * 100, decimals)
    prefix = ""
    if signed and x > 0:
        prefix = "+"
    elif signed and x < 0:
        prefix = "-"
    return f"{prefix}{value} %"
