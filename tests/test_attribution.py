import unittest

from vbot.attribution import Cause, Driver, attribute_pe_change, classify_cause, describe_attribution


class AttributionTests(unittest.TestCase):
    def test_earnings_driven(self):
        a = attribute_pe_change(-0.05, 0.30)
        self.assertEqual(a.driver, Driver.EARNINGS)
        self.assertAlmostEqual(a.pe_change, 0.95 / 1.30 - 1)
        self.assertIn("origine fondamentale", describe_attribution(a))

    def test_price_driven(self):
        self.assertEqual(attribute_pe_change(-0.35, 0.02).driver, Driver.PRICE)

    def test_mixed(self):
        self.assertEqual(attribute_pe_change(-0.15, 0.15).driver, Driver.MIXED)

    def test_unknown_when_missing_or_negative_eps(self):
        self.assertEqual(attribute_pe_change(None, 0.1).driver, Driver.UNKNOWN)
        self.assertEqual(attribute_pe_change(0.1, -1.2).driver, Driver.UNKNOWN)
        self.assertIn("Décomposition impossible", describe_attribution(attribute_pe_change(None, None)))

    def test_cause_classification(self):
        price = attribute_pe_change(-0.35, 0.02)
        self.assertEqual(classify_cause(price, 2, None), Cause.NEWS)
        self.assertEqual(classify_cause(price, 0, None), Cause.MARKET_NO_CATALYST)
        self.assertEqual(classify_cause(price, None, None), Cause.UNDETERMINED)
        self.assertEqual(classify_cause(attribute_pe_change(-0.05, 0.30), 3, None), Cause.FUNDAMENTALS)
        unknown = attribute_pe_change(None, None)
        self.assertEqual(classify_cause(unknown, 1, -0.07), Cause.NEWS)
        self.assertEqual(classify_cause(unknown, 1, -0.01), Cause.UNDETERMINED)


if __name__ == "__main__":
    unittest.main()
