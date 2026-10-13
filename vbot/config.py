"""Chargement et validation de la configuration (variables d'environnement)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class ConfigError(RuntimeError):
    """Configuration absente ou invalide."""


def normalize_symbol(raw: str) -> str:
    symbol = (raw or "").strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise ValueError(f"Symbole invalide : {raw!r}")
    return symbol


def _get(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        if required:
            raise ConfigError(f"Variable d'environnement obligatoire manquante : {name}")
        return default
    return value.strip()


def _int(name: str, default: int | None = None, minimum: int | None = None, required: bool = False) -> int:
    raw = _get(name, None if default is None else str(default), required=required)
    try:
        value = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} doit être un entier (reçu {raw!r})") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} doit être >= {minimum} (reçu {value})")
    return value


def _float(name: str, default: float) -> float:
    raw = _get(name, str(default))
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} doit être un nombre (reçu {raw!r})") from exc


@dataclass(frozen=True)
class Settings:
    discord_token: str
    alert_channel_id: int
    discord_guild_id: int | None
    data_provider: str
    finnhub_api_key: str | None
    finnhub_rate_per_minute: int
    yahoo_min_interval_s: float
    peers_file: str | None
    anthropic_api_key: str | None
    anthropic_model: str
    watchlist_seed: tuple[str, ...]
    max_watchlist: int
    scan_interval_minutes: int
    undervalued_threshold: float
    overvalued_threshold: float
    min_metrics: int
    max_peers: int
    news_lookback_days: int
    alert_cooldown_hours: int
    db_path: str
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        under = _float("UNDERVALUED_THRESHOLD", -0.20)
        over = _float("OVERVALUED_THRESHOLD", 0.20)
        if not under < 0 < over:
            raise ConfigError("Seuils incohérents : UNDERVALUED_THRESHOLD < 0 < OVERVALUED_THRESHOLD requis")
        data_provider = (_get("DATA_PROVIDER", "yahoo") or "yahoo").lower()
        if data_provider not in ("yahoo", "finnhub"):
            raise ConfigError("DATA_PROVIDER doit valoir 'yahoo' ou 'finnhub'")
        finnhub_key = _get("FINNHUB_API_KEY", required=data_provider == "finnhub")
        yahoo_interval = _float("YAHOO_MIN_INTERVAL_S", 2.0)
        if yahoo_interval < 0.5:
            raise ConfigError("YAHOO_MIN_INTERVAL_S doit être >= 0.5 (protection contre le blocage Yahoo)")
        guild_raw = _get("DISCORD_GUILD_ID")
        seed_raw = _get("WATCHLIST", "") or ""
        try:
            seed = tuple(dict.fromkeys(normalize_symbol(s) for s in seed_raw.split(",") if s.strip()))
        except ValueError as exc:
            raise ConfigError(f"WATCHLIST : {exc}") from exc
        return cls(
            discord_token=_get("DISCORD_TOKEN", required=True),  # type: ignore[arg-type]
            alert_channel_id=_int("DISCORD_ALERT_CHANNEL_ID", minimum=1, required=True),
            discord_guild_id=int(guild_raw) if guild_raw else None,
            data_provider=data_provider,
            finnhub_api_key=finnhub_key,
            finnhub_rate_per_minute=_int("FINNHUB_RATE_PER_MINUTE", 50, minimum=1),
            yahoo_min_interval_s=yahoo_interval,
            peers_file=_get("PEERS_FILE"),
            anthropic_api_key=_get("ANTHROPIC_API_KEY"),
            anthropic_model=_get("ANTHROPIC_MODEL", "claude-haiku-5-5"),  # type: ignore[arg-type]
            watchlist_seed=seed,
            max_watchlist=_int("MAX_WATCHLIST", 30, minimum=1),
            scan_interval_minutes=_int("SCAN_INTERVAL_MINUTES", 240, minimum=15),
            undervalued_threshold=under,
            overvalued_threshold=over,
            min_metrics=_int("MIN_METRICS", 3, minimum=2),
            max_peers=_int("MAX_PEERS", 6, minimum=3),
            news_lookback_days=_int("NEWS_LOOKBACK_DAYS", 30, minimum=1),
            alert_cooldown_hours=_int("ALERT_COOLDOWN_HOURS", 72, minimum=1),
            db_path=_get("DB_PATH", "data/vbot.sqlite3"),  # type: ignore[arg-type]
            log_level=(_get("LOG_LEVEL", "INFO") or "INFO").upper(),
        )
