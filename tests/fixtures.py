"""Données de test synthétiques (aucune donnée de marché réelle)."""
from datetime import datetime, timezone

NOW = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
TS_NOW = int(NOW.timestamp())


def series(values):
    return [{"period": f"{2025 - i}-12-31", "v": v} for i, v in enumerate(values)]


TARGET_METRICS = {
    "metric": {
        "peTTM": 15.0, "evEbitdaTTM": 10.0, "pfcfShareTTM": 14.0, "psTTM": 2.0, "pbQuarterly": 3.0,
        "epsGrowthTTMYoy": 30.0, "revenueGrowthTTMYoy": 8.0, "roeTTM": 22.0,
        "netProfitMarginTTM": 15.0, "totalDebt/totalEquityQuarterly": 0.6, "52WeekPriceReturnDaily": -5.0,
    },
    "series": {"annual": {
        "pe": series([22.0, 24.0, 21.0, 25.0]),
        "evEbitda": series([16.0, 15.0, 17.0, 14.0]),
        "pfcf": series([20.0, 22.0, 19.0, 21.0]),
        "ps": series([3.0, 3.2, 2.8, 3.1]),
        "pb": series([4.0, 4.5, 3.8, 4.2]),
    }},
}


def peer_metrics(scale: float):
    return {"metric": {"peTTM": 20 * scale, "evEbitdaTTM": 14 * scale, "pfcfShareTTM": 19 * scale,
                       "psTTM": 2.9 * scale, "pbQuarterly": 4.1 * scale}}


PEERS = {"PEER1": peer_metrics(0.9), "PEER2": peer_metrics(1.0), "PEER3": peer_metrics(1.1), "PEER4": peer_metrics(1.05)}

NEWS = [
    {"datetime": TS_NOW - 2 * 86400, "headline": "Testco beats quarterly earnings estimates, raises guidance",
     "summary": "Testco reported revenue above expectations.", "source": "Wire", "url": "https://example.com/a"},
    {"datetime": TS_NOW - 3 * 86400, "headline": "10 best stocks to buy now",
     "summary": "Testco among others.", "source": "Blog", "url": "https://example.com/b"},
    {"datetime": TS_NOW - 90 * 86400, "headline": "Testco announces acquisition",
     "summary": "Old news.", "source": "Wire", "url": "https://example.com/c"},
]
