"""Interface commune des sources de données de marché."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..models import CompanySnapshot, NewsItem


class MarketDataProvider(Protocol):
    name: str

    async def snapshot(self, symbol: str) -> CompanySnapshot | None:
        """None si le symbole est inconnu de la source."""

    async def peers(self, symbol: str) -> list[str]: ...

    async def current_multiples(self, symbol: str) -> dict[str, float | None]: ...

    async def news(self, symbol: str, start: datetime, end: datetime) -> list[NewsItem]: ...

    async def exists(self, symbol: str) -> bool: ...

    async def aclose(self) -> None: ...
