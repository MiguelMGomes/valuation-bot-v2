import unittest
from datetime import timedelta

from tests.fixtures import NOW
from vbot.storage import Store


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.store.init()

    def tearDown(self):
        self.store.close()

    def test_watchlist_seed_only_when_empty(self):
        self.assertEqual(self.store.seed_watchlist(["AAPL", "MSFT"], NOW), 2)
        self.assertEqual(self.store.seed_watchlist(["NVDA"], NOW), 0)
        self.assertTrue(self.store.add_symbol("NVDA", NOW))
        self.assertFalse(self.store.add_symbol("NVDA", NOW))
        self.assertTrue(self.store.remove_symbol("MSFT"))
        self.assertEqual(self.store.list_symbols(), ["AAPL", "NVDA"])

    def test_alert_dedup_cooldown_and_state_change(self):
        s = self.store
        self.assertFalse(s.should_alert("AAPL", "neutral", 72, NOW))
        self.assertTrue(s.should_alert("AAPL", "undervalued", 72, NOW))
        s.record_signal("AAPL", "undervalued", -0.3, "élevée", "x", True, NOW)
        self.assertFalse(s.should_alert("AAPL", "undervalued", 72, NOW + timedelta(hours=10)))
        self.assertTrue(s.should_alert("AAPL", "undervalued", 72, NOW + timedelta(hours=73)))
        s.record_signal("AAPL", "neutral", -0.1, "moyenne", "x", False, NOW + timedelta(hours=11))
        self.assertTrue(s.should_alert("AAPL", "undervalued", 72, NOW + timedelta(hours=12)))


if __name__ == "__main__":
    unittest.main()
