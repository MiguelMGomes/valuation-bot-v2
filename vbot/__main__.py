"""Point d'entrée : python -m vbot"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from .analyzer import Analyzer, AnalyzerConfig
from .config import ConfigError, Settings
from .valuation import ValuationConfig


def main() -> None:
    load_dotenv()
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"Configuration invalide : {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s : %(message)s")

    from .bot import ValuationBot
    from .providers.factory import build_provider
    from .storage import Store

    data_dir = os.path.dirname(settings.db_path) or "."
    os.makedirs(data_dir, exist_ok=True)
    cache_dir = os.path.join(data_dir, "yf-cache")
    os.makedirs(cache_dir, exist_ok=True)

    store = Store(settings.db_path)
    store.init()
    store.seed_watchlist(settings.watchlist_seed, datetime.now(timezone.utc))

    try:
        provider = build_provider(
            settings.data_provider,
            finnhub_api_key=settings.finnhub_api_key,
            finnhub_rate_per_minute=settings.finnhub_rate_per_minute,
            yahoo_min_interval_s=settings.yahoo_min_interval_s,
            peers_file=settings.peers_file,
            cache_dir=cache_dir,
        )
    except ConfigError as exc:
        print(f"Configuration invalide : {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    summarizer = None
    if settings.anthropic_api_key:
        from .llm import NewsSummarizer

        summarizer = NewsSummarizer(settings.anthropic_api_key, settings.anthropic_model)

    analyzer = Analyzer(
        provider,
        AnalyzerConfig(
            valuation=ValuationConfig(
                undervalued_threshold=settings.undervalued_threshold,
                overvalued_threshold=settings.overvalued_threshold,
                min_metrics=settings.min_metrics,
            ),
            max_peers=settings.max_peers,
            news_lookback_days=settings.news_lookback_days,
        ),
        summarizer,
    )
    logging.getLogger(__name__).info("Source de données : %s", provider.name)
    bot = ValuationBot(settings, analyzer, store, provider)
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
