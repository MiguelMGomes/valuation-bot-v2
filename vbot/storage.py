"""Persistance SQLite : watchlist et historique des signaux.

RGPD : aucune donnée personnelle n'est stockée (pas d'identifiant Discord).
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol   TEXT PRIMARY KEY,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol     TEXT NOT NULL,
    verdict    TEXT NOT NULL,
    score      REAL,
    confidence TEXT,
    cause      TEXT,
    alerted    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_created ON signals(symbol, created_at);
"""

ALERTABLE = {"undervalued", "overvalued"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._lock = threading.Lock()

    def init(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def seed_watchlist(self, symbols: Iterable[str], now: datetime) -> int:
        """Initialise la watchlist uniquement si elle est vide (la base fait foi ensuite)."""
        with self._lock, self._conn:
            (count,) = self._conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()
            if count:
                return 0
            rows = [(s, _iso(now)) for s in symbols]
            self._conn.executemany("INSERT OR IGNORE INTO watchlist(symbol, added_at) VALUES (?, ?)", rows)
            return len(rows)

    def add_symbol(self, symbol: str, now: datetime) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO watchlist(symbol, added_at) VALUES (?, ?)", (symbol, _iso(now))
            )
            return cur.rowcount == 1

    def remove_symbol(self, symbol: str) -> bool:
        with self._lock, self._conn:
            return self._conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,)).rowcount == 1

    def list_symbols(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute("SELECT symbol FROM watchlist ORDER BY symbol")]

    def record_signal(
        self,
        symbol: str,
        verdict: str,
        score: float | None,
        confidence: str,
        cause: str,
        alerted: bool,
        now: datetime,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO signals(symbol, verdict, score, confidence, cause, alerted, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (symbol, verdict, score, confidence, cause, int(alerted), _iso(now)),
            )

    def should_alert(self, symbol: str, verdict: str, cooldown_hours: int, now: datetime) -> bool:
        """Alerte si le verdict est alertable ET (changement d'état OU délai de carence écoulé)."""
        if verdict not in ALERTABLE:
            return False
        with self._lock:
            last = self._conn.execute(
                "SELECT verdict FROM signals WHERE symbol = ? ORDER BY id DESC LIMIT 1", (symbol,)
            ).fetchone()
            if last is None or last[0] != verdict:
                return True
            last_alert = self._conn.execute(
                "SELECT created_at FROM signals WHERE symbol = ? AND verdict = ? AND alerted = 1 "
                "ORDER BY id DESC LIMIT 1",
                (symbol, verdict),
            ).fetchone()
        if last_alert is None:
            return True
        return now - datetime.fromisoformat(last_alert[0]) >= timedelta(hours=cooldown_hours)
