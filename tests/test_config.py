import json
import os
import tempfile
import unittest
from unittest import mock

from vbot.config import ConfigError, Settings
from vbot.providers.factory import load_peer_overrides

BASE = {"DISCORD_TOKEN": "x", "DISCORD_ALERT_CHANNEL_ID": "123"}


class ConfigTests(unittest.TestCase):
    def test_yahoo_default_needs_no_finnhub_key(self):
        with mock.patch.dict(os.environ, BASE, clear=True):
            s = Settings.from_env()
        self.assertEqual(s.data_provider, "yahoo")
        self.assertIsNone(s.finnhub_api_key)

    def test_finnhub_requires_key(self):
        with mock.patch.dict(os.environ, BASE | {"DATA_PROVIDER": "finnhub"}, clear=True):
            with self.assertRaises(ConfigError):
                Settings.from_env()

    def test_yahoo_interval_floor(self):
        with mock.patch.dict(os.environ, BASE | {"YAHOO_MIN_INTERVAL_S": "0.1"}, clear=True):
            with self.assertRaises(ConfigError):
                Settings.from_env()

    def test_peers_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"mc.pa": ["ker.pa", "RMS.PA"]}, f)
        try:
            self.assertEqual(load_peer_overrides(f.name), {"MC.PA": ["KER.PA", "RMS.PA"]})
        finally:
            os.unlink(f.name)
        with self.assertRaises(ConfigError):
            load_peer_overrides("/nope.json")


if __name__ == "__main__":
    unittest.main()
