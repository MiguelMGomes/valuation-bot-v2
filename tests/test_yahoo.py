"""Source Yahoo Finance : conversion des données et fournisseur complet, avec un faux yfinance."""
import unittest

import pandas as pd

from tests.fixtures import NOW
from vbot.analyzer import Analyzer, AnalyzerConfig
from vbot.attribution import Cause
from vbot.providers.errors import MarketDataError
from vbot.providers.yahoo import YahooProvider, frame_to_dict, history_to_list
from vbot.providers.yahoo_mapping import (
    build_yahoo_snapshot, historical_multiples, parse_yahoo_news, region_for_symbol, yahoo_current_multiples,
)
from vbot.valuation import ValuationConfig, Verdict

FY = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]
INCOME = {d: {"Diluted EPS": 5.0, "Total Revenue": 37e9, "EBITDA": 7e9} for d in FY}
BALANCE = {d: {"Ordinary Shares Number": 1e9, "Stockholders Equity": 27e9, "Total Debt": 10e9,
               "Cash And Cash Equivalents": 5e9} for d in FY}
CASHFLOW = {d: {"Free Cash Flow": 5.5e9} for d in FY}
PRICES = [(f"{y}-{m:02d}-01", 110.0) for y in range(2020, 2027) for m in range(1, 13)]

TARGET_INFO = {
    "longName": "Testco Inc", "currency": "USD", "financialCurrency": "USD", "industry": "Software",
    "industryKey": "software-infrastructure", "currentPrice": 101.25, "previousClose": 100.0,
    "trailingPE": 15.0, "enterpriseToEbitda": 10.0, "priceToSalesTrailing12Months": 2.0, "priceToBook": 3.0,
    "marketCap": 150e9, "freeCashflow": 10e9, "earningsGrowth": 0.30, "revenueGrowth": 0.08,
    "returnOnEquity": 0.22, "profitMargins": 0.15, "debtToEquity": 60.0, "52WeekChange": -0.05,
}


def peer_info(scale):
    return {"longName": "Peer", "currentPrice": 50.0, "trailingPE": 20 * scale, "enterpriseToEbitda": 14 * scale,
            "priceToSalesTrailing12Months": 2.9 * scale, "priceToBook": 4.1 * scale,
            "marketCap": 100e9, "freeCashflow": 100e9 / (19 * scale)}


INFOS = {"TST": TARGET_INFO, "PEER1": peer_info(0.9), "PEER2": peer_info(1.0),
         "PEER3": peer_info(1.1), "PEER4": peer_info(1.05)}

NEWS_NEW_FORMAT = [{"id": "1", "content": {
    "title": "Testco beats quarterly earnings estimates", "summary": "Revenue above expectations.",
    "pubDate": "2026-10-07T13:00:00Z", "provider": {"displayName": "Reuters"},
    "canonicalUrl": {"url": "https://example.com/a"}}}]


def frame(statements):
    return pd.DataFrame({pd.Timestamp(d): v for d, v in statements.items()})


class FakeTicker:
    def __init__(self, symbol, rate_limited=False):
        self.symbol, self.rate_limited = symbol, rate_limited

    @property
    def info(self):
        if self.rate_limited:
            raise YFRateLimitError("Too Many Requests")
        return INFOS.get(self.symbol, {})

    income_stmt = property(lambda self: frame(INCOME))
    balance_sheet = property(lambda self: frame(BALANCE))
    cashflow = property(lambda self: frame(CASHFLOW))
    splits = property(lambda self: pd.Series(dtype=float))
    news = property(lambda self: NEWS_NEW_FORMAT)

    def history(self, period, interval, auto_adjust):
        idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in PRICES])
        return pd.DataFrame({"Close": [c for _, c in PRICES]}, index=idx)


class YFRateLimitError(Exception):
    pass


class FakeIndustry:
    def __init__(self, key, region="US"):
        self.top_companies = pd.DataFrame({"name": ["a"] * 5}, index=["TST", "PEER1", "PEER2", "PEER3", "PEER4"])


def provider(rate_limited=False):
    return YahooProvider(min_interval_s=0, max_retries=1, rate_limit_backoff_s=0,
                         ticker_factory=lambda s: FakeTicker(s, rate_limited), industry_factory=FakeIndustry)


class MappingTests(unittest.TestCase):
    def test_current_multiples_with_computed_p_fcf(self):
        m = yahoo_current_multiples(TARGET_INFO)
        self.assertEqual(m["pe"], 15.0)
        self.assertAlmostEqual(m["p_fcf"], 15.0)

    def test_historical_multiples_from_statements(self):
        h = historical_multiples(INCOME, BALANCE, CASHFLOW, PRICES)
        self.assertEqual(len(h["pe"]), 4)
        self.assertAlmostEqual(h["pe"][0], 22.0)
        self.assertAlmostEqual(h["ev_ebitda"][0], (110e9 + 10e9 - 5e9) / 7e9)
        self.assertAlmostEqual(h["p_fcf"][0], 20.0)

    def test_currency_mismatch_skips_history(self):
        info = TARGET_INFO | {"currency": "USD", "financialCurrency": "TWD"}
        snap = build_yahoo_snapshot("TSM", info, INCOME, BALANCE, CASHFLOW, PRICES, [])
        self.assertEqual(snap.history, {})
        self.assertTrue(any("devise" in n.lower() for n in snap.notes))

    def test_pence_quotation_is_converted(self):
        info = TARGET_INFO | {"currency": "GBp", "financialCurrency": "GBP"}
        pence = [(d, c * 100) for d, c in PRICES]
        snap = build_yahoo_snapshot("XYZ.L", info, INCOME, BALANCE, CASHFLOW, pence, [])
        self.assertAlmostEqual(snap.history["pe"][0], 22.0)

    def test_recent_split_truncates_history(self):
        snap = build_yahoo_snapshot("TST", TARGET_INFO, INCOME, BALANCE, CASHFLOW, PRICES, [("2024-06-10", 4.0)])
        self.assertEqual(len(snap.history["pe"]), 2)
        self.assertTrue(any("nominal" in n for n in snap.notes))

    def test_fundamentals_normalized(self):
        snap = build_yahoo_snapshot("TST", TARGET_INFO, INCOME, BALANCE, CASHFLOW, PRICES, [])
        self.assertAlmostEqual(snap.fundamentals["debt_to_equity"], 0.6)
        self.assertAlmostEqual(snap.change_1d, 0.0125)

    def test_news_both_formats(self):
        old = [{"title": "Old format headline", "publisher": "AP", "link": "https://x.y/z",
                "providerPublishTime": 1791500000}]
        items = parse_yahoo_news(NEWS_NEW_FORMAT + old + [{"content": {"title": ""}}])
        self.assertEqual([i.source for i in items], ["Reuters", "AP"])
        self.assertEqual(items[0].url, "https://example.com/a")
        self.assertIsNotNone(items[0].published_at.tzinfo)

    def test_region(self):
        self.assertEqual(region_for_symbol("MC.PA"), "FR")
        self.assertEqual(region_for_symbol("AAPL"), "US")

    def test_frame_conversion(self):
        d = frame_to_dict(frame({"2025-12-31": {"Diluted EPS": 5.0, "EBITDA": float("nan")}}))
        self.assertEqual(d, {"2025-12-31": {"Diluted EPS": 5.0}})
        self.assertEqual(history_to_list(None), [])


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_pipeline_with_yahoo(self):
        analyzer = Analyzer(provider(), AnalyzerConfig(ValuationConfig(), news_lookback_days=30), clock=lambda: NOW)
        result = await analyzer.analyze("TST")
        self.assertEqual(result.valuation.verdict, Verdict.UNDERVALUED)
        self.assertEqual(result.cause, Cause.FUNDAMENTALS)
        self.assertEqual(result.report.source, "Yahoo Finance")
        self.assertEqual(len(result.report.news_lines), 1)
        self.assertTrue(any("trimestre" in v for v in result.report.vigilance))

    async def test_unknown_symbol(self):
        self.assertIsNone(await provider().snapshot("ZZZZ"))
        self.assertFalse(await provider().exists("ZZZZ"))

    async def test_rate_limit_becomes_explicit_error(self):
        with self.assertRaises(MarketDataError) as ctx:
            await provider(rate_limited=True).snapshot("TST")
        self.assertIn("429", str(ctx.exception))

    async def test_peer_overrides(self):
        p = YahooProvider(min_interval_s=0, peer_overrides={"MC.PA": ["KER.PA", "RMS.PA"]},
                          ticker_factory=FakeTicker, industry_factory=FakeIndustry)
        self.assertEqual(await p.peers("MC.PA"), ["KER.PA", "RMS.PA"])


if __name__ == "__main__":
    unittest.main()
