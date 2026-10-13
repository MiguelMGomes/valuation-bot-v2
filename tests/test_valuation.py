import unittest

from vbot.models import CompanySnapshot
from vbot.valuation import ValuationConfig, Verdict, evaluate, relative_gap, robust_median


def snap(multiples, history=None, fundamentals=None):
    return CompanySnapshot("TST", "Testco Inc", "USD", "Tech", 100.0, 0.01, None,
                           multiples, history or {}, fundamentals or {})


HIST = {k: [20.0, 21.0, 19.0, 22.0] for k in ("pe", "ev_ebitda", "p_fcf", "ps", "pb")}
PEERS = {k: [20.0, 20.0, 20.0, 20.0] for k in HIST}


class ValuationTests(unittest.TestCase):
    def test_median_ignores_non_meaningful_values(self):
        self.assertEqual(robust_median([10, -5, None, float("nan"), 20, 0, 9999]), (15.0, 2))

    def test_gap_is_clipped(self):
        self.assertEqual(relative_gap(100.0, 10.0), 1.0)
        self.assertAlmostEqual(relative_gap(15.0, 20.0), -0.25)
        self.assertIsNone(relative_gap(-3.0, 20.0))

    def test_undervalued(self):
        res = evaluate(snap({k: 14.0 for k in HIST}, HIST), PEERS)
        self.assertEqual(res.verdict, Verdict.UNDERVALUED)
        self.assertLess(res.score, -0.2)
        self.assertEqual(res.confidence, "élevée")

    def test_overvalued(self):
        res = evaluate(snap({k: 30.0 for k in HIST}, HIST), PEERS)
        self.assertEqual(res.verdict, Verdict.OVERVALUED)

    def test_neutral(self):
        res = evaluate(snap({k: 20.5 for k in HIST}, HIST), PEERS)
        self.assertEqual(res.verdict, Verdict.NEUTRAL)

    def test_insufficient_when_few_comparables(self):
        res = evaluate(snap({"pe": 14.0}, {"pe": HIST["pe"]}), {"pe": PEERS["pe"]})
        self.assertEqual(res.verdict, Verdict.INSUFFICIENT)
        self.assertIsNone(res.score)

    def test_negative_pe_excluded_and_flagged(self):
        multiples = {k: 14.0 for k in HIST} | {"pe": -8.0}
        res = evaluate(snap(multiples, HIST), PEERS)
        self.assertEqual(len(res.used), 4)
        self.assertTrue(any("PER non significatif" in f for f in res.flags))

    def test_value_trap_flags(self):
        res = evaluate(
            snap({k: 14.0 for k in HIST}, HIST, {"eps_growth": -0.25, "revenue_growth": -0.05, "debt_to_equity": 2.5}),
            PEERS,
        )
        joined = " ".join(res.flags)
        self.assertIn("value trap", joined)
        self.assertIn("Chiffre d'affaires en baisse", joined)
        self.assertIn("Endettement élevé", joined)

    def test_growth_justifies_premium(self):
        res = evaluate(snap({k: 30.0 for k in HIST}, HIST, {"eps_growth": 0.40}), PEERS)
        self.assertAlmostEqual(res.peg, 0.75)
        self.assertTrue(any("justifiée par la croissance" in f for f in res.flags))

    def test_thresholds_are_configurable(self):
        cfg = ValuationConfig(undervalued_threshold=-0.40, overvalued_threshold=0.40)
        res = evaluate(snap({k: 14.0 for k in HIST}, HIST), PEERS, cfg)
        self.assertEqual(res.verdict, Verdict.NEUTRAL)


if __name__ == "__main__":
    unittest.main()
