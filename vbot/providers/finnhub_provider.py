"""Adaptateur Finnhub -> interface MarketDataProvider (source de secours)."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from ..models import CompanySnapshot, NewsItem
from .finnhub_mapping import build_snapshot, extract_current_multiples, parse_news


class FinnhubProvider:
    name = "Finnhub"

    def __init__(self, client: Any) -> None:
        self._client = client  # FinnhubClient ou équivalent (tests)

    async def snapshot(self, symbol: str) -> CompanySnapshot | None:
        quote, profile, metrics = await asyncio.gather(
            self._client.quote(symbol), self._client.profile(symbol), self._client.metrics(symbol)
        )
        if not profile and not (metrics or {}).get("metric"):
            return None
        return build_snapshot(symbol, quote or {}, profile or {}, metrics or {})

    async def peers(self, symbol: str) -> list[str]:
        return await self._client.peers(symbol)

    async def current_multiples(self, symbol: str) -> dict[str, float | None]:
        return extract_current_multiples(await self._client.metrics(symbol) or {})

    async def news(self, symbol: str, start: datetime, end: datetime) -> list[NewsItem]:
        return parse_news(await self._client.company_news(symbol, start.date(), end.date()))

    async def exists(self, symbol: str) -> bool:
        return bool(await self._client.profile(symbol))

    async def aclose(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close:
            await close()
