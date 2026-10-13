"""Construction de la source de données selon DATA_PROVIDER."""
from __future__ import annotations

import json
from pathlib import Path

from ..config import ConfigError, normalize_symbol


def load_peer_overrides(path: str | None) -> dict[str, list[str]]:
    """Fichier JSON facultatif : {"MC.PA": ["KER.PA", "RMS.PA", "CFR.SW"], ...}"""
    if not path:
        return {}
    file = Path(path)
    if not file.exists():
        raise ConfigError(f"PEERS_FILE introuvable : {path}")
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
        return {normalize_symbol(k): [normalize_symbol(p) for p in v] for k, v in raw.items()}
    except (ValueError, AttributeError, TypeError) as exc:
        raise ConfigError(f"PEERS_FILE invalide ({path}) : {exc}") from exc


def build_provider(
    data_provider: str,
    finnhub_api_key: str | None = None,
    finnhub_rate_per_minute: int = 50,
    yahoo_min_interval_s: float = 2.0,
    peers_file: str | None = None,
    cache_dir: str | None = None,
):
    if data_provider == "finnhub":
        if not finnhub_api_key:
            raise ConfigError("FINNHUB_API_KEY obligatoire avec DATA_PROVIDER=finnhub")
        from .finnhub import FinnhubClient
        from .finnhub_provider import FinnhubProvider

        return FinnhubProvider(FinnhubClient(finnhub_api_key, rate_per_minute=finnhub_rate_per_minute))
    if data_provider == "yahoo":
        from .yahoo import YahooProvider

        return YahooProvider(
            min_interval_s=yahoo_min_interval_s,
            peer_overrides=load_peer_overrides(peers_file),
            cache_dir=cache_dir,
        )
    raise ConfigError(f"DATA_PROVIDER inconnu : {data_provider!r} (valeurs : yahoo, finnhub)")
