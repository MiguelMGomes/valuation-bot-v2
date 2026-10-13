"""Contrôle de la source de données active, sans Discord.

Usage (dans le conteneur) : python scripts/check_data.py AAPL MC.PA
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vbot.config import normalize_symbol  # noqa: E402
from vbot.formatting import fmt_num, fmt_pct  # noqa: E402
from vbot.models import MULTIPLE_LABELS  # noqa: E402
from vbot.providers.factory import build_provider  # noqa: E402


async def check(provider, symbol: str) -> bool:
    print(f"\n===== {symbol} ({provider.name}) =====")
    snap = await provider.snapshot(symbol)
    if snap is None:
        print("ÉCHEC : symbole inconnu de la source.")
        return False
    print(f"Société     : {snap.name} · {snap.industry} · {snap.currency}")
    print(f"Cours       : {fmt_num(snap.price, 2)} ({fmt_pct(snap.change_1d)} sur la séance)")
    print("Multiples   : actuel | historique (du plus récent au plus ancien)")
    for key, label in MULTIPLE_LABELS.items():
        hist = ", ".join(fmt_num(v) for v in snap.history.get(key, [])) or "aucun"
        print(f"  {label:<10} {fmt_num(snap.multiples.get(key)):>8} | {hist}")
    print("Fondamentaux :")
    for key, value in snap.fundamentals.items():
        shown = fmt_num(value, 2) if key == "debt_to_equity" else fmt_pct(value)
        print(f"  {key:<18} {shown}")
    for note in snap.notes:
        print(f"  Note : {note}")
    peers = await provider.peers(symbol)
    print(f"Pairs ({len(peers)}) : {', '.join(peers[:8]) or 'aucun'}")
    now = datetime.now(timezone.utc)
    news = await provider.news(symbol, now - timedelta(days=30), now)
    print(f"Actualités 30 j : {len(news)}")
    for n in news[:3]:
        print(f"  - {n.published_at:%d/%m} {n.headline[:90]} ({n.source})")
    return True


async def main(symbols: list[str]) -> int:
    provider = build_provider(
        os.getenv("DATA_PROVIDER", "yahoo").lower(),
        finnhub_api_key=os.getenv("FINNHUB_API_KEY"),
        yahoo_min_interval_s=float(os.getenv("YAHOO_MIN_INTERVAL_S", "2.0")),
        peers_file=os.getenv("PEERS_FILE") or None,
    )
    ok = True
    try:
        for s in symbols:
            ok &= await check(provider, normalize_symbol(s))
    finally:
        await provider.aclose()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:] or ["AAPL"])))
