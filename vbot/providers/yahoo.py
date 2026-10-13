"""Source Yahoo Finance via la bibliothèque non officielle yfinance.

- Aucune API officielle : l'accès peut être limité ou bloqué par Yahoo à tout moment.
- Usage personnel uniquement (conditions d'utilisation de Yahoo).
- Les appels sont sérialisés, espacés (YAHOO_MIN_INTERVAL_S) et mis en cache.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime
from typing import Any, Callable

from ..models import CompanySnapshot, NewsItem
from .errors import MarketDataError
from .yahoo_mapping import (
    build_yahoo_snapshot,
    is_valid_info,
    parse_yahoo_news,
    region_for_symbol,
    yahoo_current_multiples,
)

log = logging.getLogger(__name__)

TTL_INFO = 300.0
TTL_STATEMENTS = 24 * 3600.0
TTL_NEWS = 900.0


def frame_to_dict(df: Any) -> dict[str, dict[str, float]]:
    """DataFrame yfinance (lignes = postes, colonnes = dates) -> dict pur Python."""
    if df is None or getattr(df, "empty", True):
        return {}
    out: dict[str, dict[str, float]] = {}
    for col in df.columns:
        key = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)[:10]
        values: dict[str, float] = {}
        for idx, raw in df[col].items():
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                values[str(idx)] = value
        out[key] = values
    return out


def history_to_list(df: Any) -> list[tuple[str, float]]:
    if df is None or getattr(df, "empty", True) or "Close" not in df.columns:
        return []
    out = []
    for idx, raw in df["Close"].items():
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            out.append((idx.strftime("%Y-%m-%d"), value))
    return out


def series_to_list(series: Any) -> list[tuple[str, float]]:
    if series is None or getattr(series, "empty", True):
        return []
    return [(idx.strftime("%Y-%m-%d"), float(v)) for idx, v in series.items()]


class YahooProvider:
    name = "Yahoo Finance"

    def __init__(
        self,
        min_interval_s: float = 2.0,
        peer_overrides: dict[str, list[str]] | None = None,
        cache_dir: str | None = None,
        max_retries: int = 2,
        rate_limit_backoff_s: float = 60.0,
        ticker_factory: Callable[[str], Any] | None = None,
        industry_factory: Callable[..., Any] | None = None,
    ) -> None:
        if ticker_factory is None or industry_factory is None:
            import yfinance as yf  # import différé : dépendance lourde

            if cache_dir and hasattr(yf, "set_tz_cache_location"):
                yf.set_tz_cache_location(cache_dir)
            ticker_factory = ticker_factory or yf.Ticker
            industry_factory = industry_factory or yf.Industry
        self._ticker_factory = ticker_factory
        self._industry_factory = industry_factory
        self._min_interval = min_interval_s
        self._max_retries = max_retries
        self._backoff = rate_limit_backoff_s
        self._peer_overrides = {k.upper(): v for k, v in (peer_overrides or {}).items()}
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self._tickers: dict[str, Any] = {}
        self._cache: dict[tuple[str, ...], tuple[float, Any]] = {}

    # ----- Infrastructure ------------------------------------------------
    def _ticker(self, symbol: str) -> Any:
        if symbol not in self._tickers:
            self._tickers[symbol] = self._ticker_factory(symbol)
        return self._tickers[symbol]

    async def _call(self, label: str, fn: Callable[[], Any]) -> Any:
        for attempt in range(1, self._max_retries + 2):
            error: Exception | None = None
            async with self._lock:
                wait = self._last_call + self._min_interval - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    return await asyncio.to_thread(fn)
                except Exception as exc:  # yfinance lève des exceptions hétérogènes
                    error = exc
                finally:
                    self._last_call = time.monotonic()
            if type(error).__name__ == "YFRateLimitError":
                if attempt <= self._max_retries:
                    delay = self._backoff * attempt
                    log.warning("Yahoo limite les requêtes (%s), nouvelle tentative dans %.0f s", label, delay)
                    await asyncio.sleep(delay)
                    continue
                raise MarketDataError(
                    "Yahoo Finance limite actuellement les requêtes de ce serveur (HTTP 429). "
                    "Réessayez plus tard ou passez DATA_PROVIDER=finnhub."
                ) from error
            raise MarketDataError(f"Yahoo Finance : échec de « {label} » ({type(error).__name__})") from error
        raise MarketDataError(f"Yahoo Finance : échec de « {label} »")  # pragma: no cover

    async def _cached(self, key: tuple[str, ...], ttl: float, label: str, fn: Callable[[], Any]) -> Any:
        hit = self._cache.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        value = await self._call(label, fn)
        self._cache[key] = (time.monotonic() + ttl, value)
        return value

    async def _optional(self, key: tuple[str, ...], ttl: float, label: str, fn: Callable[[], Any], default: Any) -> Any:
        try:
            return await self._cached(key, ttl, label, fn)
        except MarketDataError as exc:
            log.warning("Donnée facultative indisponible (%s) : %s", label, exc)
            return default

    async def _info(self, symbol: str) -> dict[str, Any]:
        t = self._ticker(symbol)
        return await self._cached((symbol, "info"), TTL_INFO, f"info {symbol}", lambda: dict(t.info or {}))

    # ----- Interface MarketDataProvider ------------------------------------
    async def snapshot(self, symbol: str) -> CompanySnapshot | None:
        info = await self._info(symbol)
        if not is_valid_info(info):
            return None
        t = self._ticker(symbol)
        income = await self._optional((symbol, "income"), TTL_STATEMENTS, "compte de résultat",
                                      lambda: frame_to_dict(t.income_stmt), {})
        balance = await self._optional((symbol, "balance"), TTL_STATEMENTS, "bilan",
                                       lambda: frame_to_dict(t.balance_sheet), {})
        cashflow = await self._optional((symbol, "cashflow"), TTL_STATEMENTS, "flux de trésorerie",
                                        lambda: frame_to_dict(t.cashflow), {})
        prices = await self._optional(
            (symbol, "prices"), TTL_STATEMENTS, "historique de cours",
            lambda: history_to_list(t.history(period="6y", interval="1mo", auto_adjust=False)), [],
        )
        splits = await self._optional((symbol, "splits"), TTL_STATEMENTS, "divisions du nominal",
                                      lambda: series_to_list(t.splits), [])
        snap = build_yahoo_snapshot(symbol, info, income, balance, cashflow, prices, splits)
        if not income:
            snap = _with_note(snap, "Comptes annuels indisponibles : historique des multiples non calculé.")
        return snap

    async def peers(self, symbol: str) -> list[str]:
        if symbol in self._peer_overrides:
            return list(self._peer_overrides[symbol])
        info = await self._info(symbol)
        key = info.get("industryKey")
        if not key:
            return []
        region = region_for_symbol(symbol)
        symbols = await self._optional(("industry", str(key), region), TTL_STATEMENTS, "pairs sectoriels",
                                       lambda: self._industry_top(str(key), region), [])
        return [s for s in symbols if s != symbol]

    def _industry_top(self, key: str, region: str) -> list[str]:
        try:
            industry = self._industry_factory(key, region=region)
        except TypeError:  # versions de yfinance sans paramètre region
            industry = self._industry_factory(key)
        df = industry.top_companies
        if df is None or getattr(df, "empty", True):
            return []
        values = df["symbol"] if "symbol" in getattr(df, "columns", []) else df.index
        return [str(s).upper() for s in values]

    async def current_multiples(self, symbol: str) -> dict[str, float | None]:
        return yahoo_current_multiples(await self._info(symbol))

    async def news(self, symbol: str, start: datetime, end: datetime) -> list[NewsItem]:
        t = self._ticker(symbol)
        raw = await self._cached((symbol, "news"), TTL_NEWS, "actualités", lambda: list(t.news or []))
        return [n for n in parse_yahoo_news(raw) if start <= n.published_at <= end]

    async def exists(self, symbol: str) -> bool:
        return is_valid_info(await self._info(symbol))

    async def aclose(self) -> None:
        return None


def _with_note(snap: CompanySnapshot, note: str) -> CompanySnapshot:
    from dataclasses import replace

    return replace(snap, notes=snap.notes + (note,))
