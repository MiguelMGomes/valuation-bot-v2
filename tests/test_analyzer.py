"""Test de bout en bout du moteur avec la source Finnhub simulée (sans réseau)."""
import unittest

from tests.fixtures import NEWS, NOW, PEERS, TARGET_METRICS, TS_NOW
from vbot.analyzer import AnalysisError, Analyzer, AnalyzerConfig
from vbot.attribution import Cause
from vbot.providers.errors import MarketDataError
from vbot.providers.finnhub_provider import FinnhubProvider
from vbot.valuation import ValuationConfig, Verdict


class FakeClient:
    def __init__(self, fail_news=False, unknown=False):
        self.fail_news, self.unknown = fail_news, unknown

    async def quote(self, symbol):
        return {"c": 0, "dp": 0, "t": 0} if self.unknown else {"c": 101.25, "dp": 1.5, "t": TS_NOW}

    async def profile(self, symbol):
        return {} if self.unknown else {"name": "Testco Inc", "currency": "USD", "finnhubIndustry": "Technology"}

    async def metrics(self, symbol):
        if self.unknown:
            return {}
        return TARGET_METRICS if symbol == "TST" else PEERS[symbol]

    async def peers(self, symbol):
        return ["TST", *PEERS]

    async def company_news(self, symbol, start, end):
        if self.fail_news:
            raise MarketDataError("HTTP 503")
        return NEWS


class FakeSummarizer:
    def __init__(self):
        self.calls = 0

    async def summarize(self, facts, news_block):
        self.calls += 1
        return "Synthèse contrôlée."


def make(client, summarizer=None):
    return Analyzer(FinnhubProvider(client), AnalyzerConfig(ValuationConfig(), max_peers=6, news_lookback_days=30),
                    summarizer, clock=lambda: NOW)


class AnalyzerTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_pipeline_undervalued_fundamental(self):
        summarizer = FakeSummarizer()
        result = await make(FakeClient(), summarizer).analyze("TST")
        self.assertEqual(result.valuation.verdict, Verdict.UNDERVALUED)
        self.assertEqual(result.cause, Cause.FUNDAMENTALS)
        self.assertEqual(len(result.report.news_lines), 1)
        self.assertIn("beats quarterly earnings", result.report.news_lines[0])
        self.assertEqual(result.report.ai_summary, "Synthèse contrôlée.")
        self.assertEqual(summarizer.calls, 1)
        self.assertIn("PER", result.report.multiples_table)
        self.assertLessEqual(len(result.report.cause_detail), 1024)
        for arg in result.report.arguments:
            self.assertLessEqual(len(arg), 1024)

    async def test_news_outage_is_reported_not_fatal(self):
        result = await make(FakeClient(fail_news=True)).analyze("TST")
        self.assertIn("Flux d'actualités indisponible", result.report.cause_detail)

    async def test_unknown_symbol_raises(self):
        with self.assertRaises(AnalysisError):
            await make(FakeClient(unknown=True)).analyze("ZZZZ")


if __name__ == "__main__":
    unittest.main()
