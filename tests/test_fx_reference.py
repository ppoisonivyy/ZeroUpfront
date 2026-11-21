from io import BytesIO
from unittest import TestCase
from unittest.mock import patch
from urllib.error import URLError

from app import fx_reference as fx


class HistoricalFXTests(TestCase):
    def setUp(self):
        fx._historical_rate.cache_clear()
        self.addCleanup(fx._historical_rate.cache_clear)

    @patch("app.fx_reference.urlopen")
    def test_valid_response_is_cached_and_converts_minor_units(self, fetch):
        fetch.return_value = BytesIO(b'{"base":"USD","quote":"THB","date":"2026-11-19","rate":33.905}')
        for _ in range(2):
            rate = fx.reference()
            self.assertEqual((rate["status"], rate["usd_minor"], rate["rate_thb_per_usd"]), ("available",704911,"33.905"))
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0].full_url, "https://api.frankfurter.dev/v2/rate/USD/THB?date=2026-11-19&providers=ECB")

    @patch("app.fx_reference.urlopen")
    def test_outage_and_malformed_or_misdated_responses_allow_retry(self, fetch):
        fetch.side_effect = [URLError("offline"), BytesIO(b'{}'),
            BytesIO(b'{"base":"THB","quote":"USD","date":"2026-11-19","rate":33}'),
            BytesIO(b'{"base":"USD","quote":"THB","date":"2026-11-20","rate":33}'),
            BytesIO(b'{"base":"USD","quote":"THB","date":"2026-11-19","rate":0}'),
            BytesIO(b'{"base":"USD","quote":"THB","date":"2026-11-19","rate":34}')]
        for _ in range(5):
            self.assertEqual(fx.reference()["status"], "unavailable")
        self.assertEqual(fx.reference()["status"], "available")
