"""Orchestration d'une analyse : données -> valorisation -> attribution -> actualités -> rapport."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from .attribution import Attribution, Cause, attribute_pe_change, classify_cause
from .models import MULTIPLE_LABELS
from .news import TaggedNews, select_material_news
from .providers.base import MarketDataProvider
from .providers.errors import MarketDataError
from .report import Report, build_report
from .valuation import ValuationConfig, ValuationResult, Verdict, evaluate

log = logging.getLogger(__name__)


class AnalysisError(RuntimeError):
    """Analyse impossible (message destiné à l'utilisateur)."""


class Summarizer(Protocol):
    async def summarize(self, facts: str, news_block: str) -> str | None: ...


@dataclass(frozen=True)
class AnalyzerConfig:
    valuation: ValuationConfig
    max_peers: int = 6
    news_lookback_days: int = 30
    peer_cache_ttl_s: float = 24 * 3600
    daily_move_threshold: float = 0.04


@dataclass(frozen=True)
class AnalysisResult:
    report: Report
    valuation: ValuationResult
    attribution: Attribution
    cause: Cause


class Analyzer:
    def __init__(
        self,
        provider: MarketDataProvider,
        config: AnalyzerConfig,
        summarizer: Summarizer | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._cfg = config
        self._summarizer = summarizer
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._peer_cache: dict[str, tuple[float, dict[str, float | None]]] = {}

    async def analyze(self, symbol: str) -> AnalysisResult:
        now = self._clock()
        try:
            snapshot = await self._provider.snapshot(symbol)
        except MarketDataError as exc:
            raise AnalysisError(str(exc)) from exc
        if snapshot is None:
            raise AnalysisError(
                f"Aucune donnée pour {symbol} : symbole inconnu ou non couvert par {self._provider.name}."
            )

        valuation = evaluate(snapshot, await self._peer_multiples(symbol), self._cfg.valuation)
        news = await self._news(symbol, snapshot.name, now)
        attribution = attribute_pe_change(
            snapshot.fundamentals.get("price_return_52w"), snapshot.fundamentals.get("eps_growth")
        )
        cause = classify_cause(
            attribution, None if news is None else len(news), snapshot.change_1d, self._cfg.daily_move_threshold
        )
        report = build_report(
            snapshot, valuation, attribution, cause, news, self._cfg.valuation,
            self._cfg.news_lookback_days, now, source=self._provider.name,
        )
        if self._summarizer and valuation.verdict in (Verdict.UNDERVALUED, Verdict.OVERVALUED):
            ai = await self._summarizer.summarize(report.facts, report.news_for_llm)
            if ai:
                report = replace(report, ai_summary=ai)
        return AnalysisResult(report, valuation, attribution, cause)

    async def _peer_current(self, peer: str) -> dict[str, float | None]:
        cached = self._peer_cache.get(peer)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        multiples = await self._provider.current_multiples(peer)
        self._peer_cache[peer] = (time.monotonic() + self._cfg.peer_cache_ttl_s, multiples)
        return multiples

    async def _peer_multiples(self, symbol: str) -> dict[str, list[float]]:
        try:
            peers = await self._provider.peers(symbol)
        except MarketDataError as exc:
            log.warning("Pairs indisponibles pour %s : %s", symbol, exc)
            return {}
        peers = [p for p in dict.fromkeys(p.upper() for p in peers) if p != symbol][: self._cfg.max_peers]
        results = await asyncio.gather(*(self._peer_current(p) for p in peers), return_exceptions=True)
        aggregated: dict[str, list[float]] = {k: [] for k in MULTIPLE_LABELS}
        for peer, res in zip(peers, results):
            if isinstance(res, BaseException):
                log.debug("Multiples indisponibles pour le pair %s : %s", peer, res)
                continue
            for key, value in res.items():
                if value is not None and key in aggregated:
                    aggregated[key].append(value)
        return aggregated

    async def _news(self, symbol: str, name: str, now: datetime) -> list[TaggedNews] | None:
        start = now - timedelta(days=self._cfg.news_lookback_days)
        try:
            raw = await self._provider.news(symbol, start, now)
        except MarketDataError as exc:
            log.warning("Actualités indisponibles pour %s : %s", symbol, exc)
            return None
        return select_material_news(raw, symbol, name, now, self._cfg.news_lookback_days)
