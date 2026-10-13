"""Vérifie les noms de champs réellement renvoyés par Finnhub (à lancer avant la mise en service).

Usage : FINNHUB_API_KEY=... python scripts/inspect_metrics.py AAPL
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vbot.providers.finnhub import FinnhubClient  # noqa: E402
from vbot.providers.finnhub_mapping import CURRENT_KEYS, FUNDAMENTAL_KEYS, SERIES_KEYS  # noqa: E402


async def main(symbol: str) -> None:
    client = FinnhubClient(os.environ["FINNHUB_API_KEY"], rate_per_minute=30)
    try:
        payload = await client.metrics(symbol)
        quote = await client.quote(symbol)
        peers = await client.peers(symbol)
    finally:
        await client.aclose()
    metric = payload.get("metric") or {}
    annual = (payload.get("series") or {}).get("annual") or {}
    print(f"Quote : {quote}")
    print(f"Pairs : {peers}\n")
    for title, mapping, source in (
        ("Multiples actuels", CURRENT_KEYS, metric),
        ("Fondamentaux", FUNDAMENTAL_KEYS, metric),
        ("Séries annuelles", SERIES_KEYS, annual),
    ):
        print(f"== {title}")
        for key, candidates in mapping.items():
            found = [c for c in candidates if c in source]
            sample = source.get(found[0]) if found else None
            if isinstance(sample, list):
                sample = sample[:2]
            print(f"  {key:<18} {'OK  ' + found[0] if found else 'ABSENT'}  {sample if found else ''}")
    print("\nClés 'metric' disponibles :", ", ".join(sorted(metric)))
    print("\nClés 'series.annual' disponibles :", ", ".join(sorted(annual)))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"))
