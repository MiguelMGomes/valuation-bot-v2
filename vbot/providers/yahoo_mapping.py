"""Conversion des données Yahoo Finance (via yfinance) vers les modèles internes.

Module pur : les DataFrames pandas sont convertis en dictionnaires par la couche
client (yahoo.py), ce qui rend toute la logique testable hors ligne.

Historique des multiples : recalculé à partir des comptes annuels publiés
(BPA, chiffre d'affaires, EBITDA, capitaux propres, FCF, dette, trésorerie) et
du cours de clôture à la date de clôture de chaque exercice.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any

from ..models import MULTIPLE_LABELS, CompanySnapshot, NewsItem

HISTORY_POINTS = 5

INFO_MULTIPLES: dict[str, tuple[str, ...]] = {
    "pe": ("trailingPE",),
    "ev_ebitda": ("enterpriseToEbitda",),
    "ps": ("priceToSalesTrailing12Months",),
    "pb": ("priceToBook",),
}

EPS_ROWS = ("Diluted EPS", "Basic EPS")
REVENUE_ROWS = ("Total Revenue", "Operating Revenue")
EBITDA_ROWS = ("EBITDA", "Normalized EBITDA")
EQUITY_ROWS = ("Stockholders Equity", "Common Stock Equity")
SHARES_ROWS = ("Ordinary Shares Number", "Share Issued")
DEBT_ROWS = ("Total Debt",)
CASH_ROWS = ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")
FCF_ROWS = ("Free Cash Flow",)

# Suffixe de place de cotation Yahoo -> région (pour les pairs sectoriels)
REGION_BY_SUFFIX = {
    "PA": "FR", "DE": "DE", "F": "DE", "L": "GB", "AS": "NL", "BR": "BE", "MI": "IT",
    "MC": "ES", "SW": "CH", "LS": "PT", "ST": "SE", "CO": "DK", "HE": "FI", "OL": "NO",
    "TO": "CA", "T": "JP", "HK": "HK", "AX": "AU",
}

Statements = dict[str, dict[str, float]]  # {"2025-12-31": {"Diluted EPS": 5.1, ...}}


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


def region_for_symbol(symbol: str) -> str:
    suffix = symbol.rsplit(".", 1)[1] if "." in symbol else ""
    return REGION_BY_SUFFIX.get(suffix, "US")


def is_valid_info(info: dict[str, Any]) -> bool:
    has_name = bool(info.get("longName") or info.get("shortName"))
    has_price = first_number(info, ("currentPrice", "regularMarketPrice", "previousClose")) is not None
    return has_name and has_price


def yahoo_current_multiples(info: dict[str, Any]) -> dict[str, float | None]:
    out: dict[str, float | None] = {key: first_number(info, keys) for key, keys in INFO_MULTIPLES.items()}
    mcap, fcf = _num(info.get("marketCap")), _num(info.get("freeCashflow"))
    out["p_fcf"] = mcap / fcf if mcap and fcf and fcf > 0 and mcap > 0 else None
    return out


def _price_on_or_before(prices: list[tuple[date, float]], d: date, max_gap_days: int = 40) -> float | None:
    candidates = [(pd, c) for pd, c in prices if pd <= d and (d - pd).days <= max_gap_days]
    return max(candidates)[1] if candidates else None


def _append_ratio(target: list[float], numerator: float | None, denominator: float | None) -> None:
    if numerator and denominator and numerator > 0 and denominator > 0:
        target.append(numerator / denominator)


def historical_multiples(
    income: Statements,
    balance: Statements,
    cashflow: Statements,
    prices: list[tuple[str, float]],
    price_factor: float = 1.0,
    exclude_before: date | None = None,
    max_points: int = HISTORY_POINTS,
) -> dict[str, list[float]]:
    """Multiples de fin d'exercice, du plus récent au plus ancien."""
    parsed_prices = [(date.fromisoformat(d[:10]), c * price_factor) for d, c in prices if _num(c)]
    history: dict[str, list[float]] = {k: [] for k in MULTIPLE_LABELS}
    for d_str in sorted(set(income) | set(balance) | set(cashflow), reverse=True):
        fy_end = date.fromisoformat(d_str[:10])
        if exclude_before and fy_end < exclude_before:
            continue
        price = _price_on_or_before(parsed_prices, fy_end)
        if not price:
            continue
        inc, bal, cf = income.get(d_str, {}), balance.get(d_str, {}), cashflow.get(d_str, {})
        _append_ratio(history["pe"], price, first_number(inc, EPS_ROWS))
        shares = first_number(bal, SHARES_ROWS)
        if shares and shares > 0:
            mcap = price * shares
            _append_ratio(history["ps"], mcap, first_number(inc, REVENUE_ROWS))
            _append_ratio(history["pb"], mcap, first_number(bal, EQUITY_ROWS))
            _append_ratio(history["p_fcf"], mcap, first_number(cf, FCF_ROWS))
            ev = mcap + (first_number(bal, DEBT_ROWS) or 0.0) - (first_number(bal, CASH_ROWS) or 0.0)
            _append_ratio(history["ev_ebitda"], ev, first_number(inc, EBITDA_ROWS))
    return {k: v[:max_points] for k, v in history.items()}


def build_yahoo_snapshot(
    symbol: str,
    info: dict[str, Any],
    income: Statements,
    balance: Statements,
    cashflow: Statements,
    prices: list[tuple[str, float]],
    splits: list[tuple[str, float]],
) -> CompanySnapshot:
    notes: list[str] = []
    price = first_number(info, ("currentPrice", "regularMarketPrice"))
    prev = first_number(info, ("regularMarketPreviousClose", "previousClose"))
    ts = _num(info.get("regularMarketTime"))
    currency = str(info.get("currency") or "")
    fin_currency = str(info.get("financialCurrency") or currency)

    # Cotation en pence (Londres) alors que les comptes sont en livres
    price_factor = 0.01 if currency == "GBp" and fin_currency == "GBP" else 1.0
    if currency and fin_currency and currency != fin_currency and price_factor == 1.0:
        history: dict[str, list[float]] = {}
        notes.append(
            f"Devise de cotation ({currency}) différente de celle des comptes ({fin_currency}) : "
            "historique des multiples non calculé."
        )
    else:
        split_dates = sorted(date.fromisoformat(d[:10]) for d, r in splits if _num(r) and r != 1)
        last_split = split_dates[-1] if split_dates else None
        statement_dates = [date.fromisoformat(d[:10]) for d in (set(income) | set(balance) | set(cashflow))]
        exclude_before = last_split if last_split and statement_dates and last_split > min(statement_dates) else None
        if exclude_before:
            notes.append(
                "Division du nominal récente : historique limité aux exercices clos après cette opération."
            )
        history = historical_multiples(income, balance, cashflow, prices, price_factor, exclude_before)

    def frac(key: str) -> float | None:
        return _num(info.get(key))

    de = _num(info.get("debtToEquity"))
    fundamentals = {
        "eps_growth": frac("earningsGrowth"),
        "revenue_growth": frac("revenueGrowth"),
        "roe": frac("returnOnEquity"),
        "net_margin": frac("profitMargins"),
        "debt_to_equity": de / 100.0 if de is not None else None,  # Yahoo l'exprime en %
        "price_return_52w": frac("52WeekChange"),
    }
    if fundamentals["eps_growth"] is not None:
        notes.append(
            "Croissance du BPA et du CA : dernier trimestre publié comparé au même trimestre de "
            "l'exercice précédent (donnée Yahoo Finance)."
        )

    return CompanySnapshot(
        symbol=symbol,
        name=str(info.get("longName") or info.get("shortName") or symbol),
        currency=currency,
        industry=str(info.get("industry") or info.get("sector") or "n.d."),
        price=price,
        change_1d=(price / prev - 1.0) if price and prev else None,
        quote_time=datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None,
        multiples=yahoo_current_multiples(info),
        history=history,
        fundamentals=fundamentals,
        notes=tuple(notes),
    )


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def parse_yahoo_news(raw: Any) -> list[NewsItem]:
    """Gère l'ancien format (champs à plat) et le format actuel (clé « content »)."""
    items: list[NewsItem] = []
    if not isinstance(raw, list):
        return items
    for n in raw:
        if not isinstance(n, dict):
            continue
        c = n.get("content") if isinstance(n.get("content"), dict) else n
        title = c.get("title")
        published = _parse_dt(c.get("pubDate") or c.get("displayTime") or n.get("providerPublishTime"))
        if not isinstance(title, str) or not title.strip() or published is None:
            continue
        provider = c.get("provider")
        source = provider.get("displayName") if isinstance(provider, dict) else n.get("publisher")
        url = ""
        for key in ("canonicalUrl", "clickThroughUrl"):
            block = c.get(key)
            if isinstance(block, dict) and block.get("url"):
                url = str(block["url"])
                break
        url = url or str(n.get("link") or "")
        items.append(
            NewsItem(
                headline=title,
                summary=str(c.get("summary") or c.get("description") or ""),
                source=str(source or "n.d."),
                url=url,
                published_at=published,
            )
        )
    return items
