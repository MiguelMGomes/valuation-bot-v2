"""Client HTTP asynchrone Finnhub : limitation de débit, reprises, erreurs explicites."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import date
from typing import Any

import httpx

from .errors import MarketDataAccessError, MarketDataError

log = logging.getLogger(__name__)


class AsyncRateLimiter:
    """Espace les appels pour rester sous N requêtes par minute."""

    def __init__(self, rate_per_minute: int) -> None:
        self._interval = 60.0 / max(1, rate_per_minute)
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next = max(now, self._next) + self._interval


class FinnhubClient:
    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str, rate_per_minute: int = 50, timeout: float = 10.0, max_retries: int = 3) -> None:
        # La clé passe par l'en-tête X-Finnhub-Token : elle n'apparaît jamais dans les URL journalisées.
        self._http = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"X-Finnhub-Token": api_key, "User-Agent": "vbot/0.1"},
            timeout=timeout,
        )
        self._limiter = AsyncRateLimiter(rate_per_minute)
        self._max_retries = max_retries

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            await self._limiter.acquire()
            try:
                resp = await self._http.get(path, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                log.warning("Finnhub %s : erreur réseau (tentative %d) : %s", path, attempt, exc)
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise MarketDataError(f"Réponse non JSON sur {path}") from exc
                if resp.status_code in (401, 403):
                    raise MarketDataAccessError(
                        f"Accès refusé sur {path} (HTTP {resp.status_code}) : clé invalide ou "
                        "endpoint non inclus dans l'abonnement."
                    )
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_error = MarketDataError(f"HTTP {resp.status_code} sur {path}")
                    log.warning("Finnhub %s : HTTP %d (tentative %d)", path, resp.status_code, attempt)
                else:
                    raise MarketDataError(f"HTTP {resp.status_code} sur {path}")
            if attempt < self._max_retries:
                await asyncio.sleep(min(30.0, 2.0**attempt) + random.uniform(0, 1))
        raise MarketDataError(f"Échec après {self._max_retries} tentatives sur {path}") from last_error

    async def quote(self, symbol: str) -> dict[str, Any]:
        return await self._get("/quote", {"symbol": symbol}) or {}

    async def profile(self, symbol: str) -> dict[str, Any]:
        return await self._get("/stock/profile2", {"symbol": symbol}) or {}

    async def metrics(self, symbol: str) -> dict[str, Any]:
        return await self._get("/stock/metric", {"symbol": symbol, "metric": "all"}) or {}

    async def peers(self, symbol: str) -> list[str]:
        data = await self._get("/stock/peers", {"symbol": symbol})
        return [p for p in data if isinstance(p, str)] if isinstance(data, list) else []

    async def company_news(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        data = await self._get(
            "/company-news", {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat()}
        )
        return data if isinstance(data, list) else []
