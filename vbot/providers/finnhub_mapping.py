"""Conversion des réponses Finnhub vers les modèles internes (module pur, testable hors ligne).

IMPORTANT : les noms de champs de /stock/metric ci-dessous sont des candidats.
Ils doivent être vérifiés sur une réponse réelle avec scripts/inspect_metrics.py
avant la mise en service ; le code ignore proprement toute clé absente.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from ..models import CompanySnapshot, NewsItem

CURRENT_KEYS: dict[str, tuple[str, ...]] = {
    "pe": ("peTTM", "peExclExtraTTM", "peBasicExclExtraTTM"),
    "ev_ebitda": ("evEbitdaTTM", "currentEv/ebitdaTTM", "evEbitdaAnnual"),
    "p_fcf": ("pfcfShareTTM", "pfcfShareAnnual"),
    "ps": ("psTTM", "psAnnual"),
    "pb": ("pbQuarterly", "pbAnnual"),
}

SERIES_KEYS: dict[str, tuple[str, ...]] = {
    "pe": ("pe", "peTTM"),
    "ev_ebitda": ("evEbitda", "evEbitdaTTM", "ev/ebitda"),
    "p_fcf": ("pfcf", "pfcfTTM"),
    "ps": ("ps", "psTTM"),
    "pb": ("pb",),
}

FUNDAMENTAL_KEYS: dict[str, tuple[str, ...]] = {
    "eps_growth": ("epsGrowthTTMYoy",),
    "revenue_growth": ("revenueGrowthTTMYoy",),
    "roe": ("roeTTM",),
    "net_margin": ("netProfitMarginTTM",),
    "debt_to_equity": ("totalDebt/totalEquityQuarterly", "totalDebt/totalEquityAnnual"),
    "price_return_52w": ("52WeekPriceReturnDaily",),
}

# Champs exprimés en pourcentage par Finnhub (12.5 = 12,5 %) -> convertis en fraction.
PERCENT_FIELDS = {"eps_growth", "revenue_growth", "roe", "net_margin", "price_return_52w"}
HISTORY_POINTS = 7


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def first_number(mapping: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for k in keys:
        value = _num(mapping.get(k))
        if value is not None:
            return value
    return None


def parse_series(annual: dict[str, Any], keys: tuple[str, ...], max_points: int = HISTORY_POINTS) -> list[float]:
    for k in keys:
        points = annual.get(k)
        if not isinstance(points, list):
            continue
        rows = [
            (str(p.get("period", "")), _num(p.get("v")))
            for p in points
            if isinstance(p, dict)
        ]
        values = [v for _, v in sorted(rows, key=lambda r: r[0], reverse=True) if v is not None]
        if values:
            return values[:max_points]
    return []


def extract_current_multiples(metrics_payload: dict[str, Any]) -> dict[str, float | None]:
    metric = metrics_payload.get("metric") or {}
    return {key: first_number(metric, keys) for key, keys in CURRENT_KEYS.items()}


def build_snapshot(
    symbol: str,
    quote: dict[str, Any],
    profile: dict[str, Any],
    metrics_payload: dict[str, Any],
) -> CompanySnapshot:
    metric = metrics_payload.get("metric") or {}
    annual = (metrics_payload.get("series") or {}).get("annual") or {}

    price = _num(quote.get("c"))
    price = price if price and price > 0 else None  # Finnhub renvoie 0 pour un symbole inconnu
    change = _num(quote.get("dp"))
    ts = _num(quote.get("t"))

    fundamentals: dict[str, float | None] = {}
    for key, keys in FUNDAMENTAL_KEYS.items():
        value = first_number(metric, keys)
        if value is not None and key in PERCENT_FIELDS:
            value /= 100.0
        fundamentals[key] = value

    return CompanySnapshot(
        symbol=symbol,
        name=str(profile.get("name") or symbol),
        currency=str(profile.get("currency") or ""),
        industry=str(profile.get("finnhubIndustry") or "n.d."),
        price=price,
        change_1d=change / 100.0 if change is not None and price else None,
        quote_time=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None,
        multiples=extract_current_multiples(metrics_payload),
        history={key: parse_series(annual, keys) for key, keys in SERIES_KEYS.items()},
        fundamentals=fundamentals,
    )


def parse_news(raw: Any) -> list[NewsItem]:
    items: list[NewsItem] = []
    if not isinstance(raw, list):
        return items
    for n in raw:
        if not isinstance(n, dict):
            continue
        ts = _num(n.get("datetime"))
        headline = n.get("headline")
        if not ts or not isinstance(headline, str) or not headline.strip():
            continue
        items.append(
            NewsItem(
                headline=headline,
                summary=str(n.get("summary") or ""),
                source=str(n.get("source") or "n.d."),
                url=str(n.get("url") or ""),
                published_at=datetime.fromtimestamp(ts, tz=timezone.utc),
            )
        )
    return items
