"""Structures de données partagées (sans dépendance externe)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

MULTIPLE_LABELS: dict[str, str] = {
    "pe": "PER",
    "ev_ebitda": "VE/EBITDA",
    "p_fcf": "P/FCF",
    "ps": "P/CA",
    "pb": "P/ANC",
}


@dataclass(frozen=True)
class NewsItem:
    headline: str
    summary: str
    source: str
    url: str
    published_at: datetime  # UTC


@dataclass(frozen=True)
class CompanySnapshot:
    symbol: str
    name: str
    currency: str
    industry: str
    price: float | None
    change_1d: float | None  # fraction : 0.012 = +1,2 %
    quote_time: datetime | None
    multiples: dict[str, float | None] = field(default_factory=dict)
    history: dict[str, list[float]] = field(default_factory=dict)  # du plus récent au plus ancien
    fundamentals: dict[str, float | None] = field(default_factory=dict)  # fractions
    notes: tuple[str, ...] = ()  # réserves sur les données, affichées en vigilance
