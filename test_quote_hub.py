# -*- coding: utf-8 -*-
"""
test_quote_hub.py - 中央即時報價 Hub 單元測試
"""

import time
import unittest
from unittest.mock import patch, MagicMock

from core.quote_hub import (
    GlobalRateLimiter,
    fetch_realtime_quotes_batch,
    fetch_realtime_quote,
    _parse_twse_item
)


class TestQuoteHub(unittest.TestCase):
    def test_01_global_rate_limiter(self):
        """測試全域冷卻限流器強制等待 >= min_interval"""
        limiter = GlobalRateLimiter(min_interval=0.2)
        t0 = time.time()
        limiter.wait()
        limiter.wait()
        t1 = time.time()
        # 兩次間隔應大於 0.18 秒
        self.assertGreaterEqual(t1 - t0, 0.18)

    def test_02_parse_twse_item(self):
        """測試 TWSE MIS JSON 項目解析邏輯"""
        raw_item = {
            "c": "2330",
            "n": "台積電",
            "z": "1000.0",
            "o": "995.0",
            "h": "1005.0",
            "l": "990.0",
            "v": "25000",
            "t": "13:30:00",
            "d": "20260910"
        }
        parsed = _parse_twse_item(raw_item)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["ticker"], "2330")
        self.assertEqual(parsed["close"], 1000.0)
        self.assertEqual(parsed["open"], 995.0)
        self.assertEqual(parsed["high"], 1005.0)
        self.assertEqual(parsed["low"], 990.0)
        self.assertEqual(parsed["volume"], 25000.0)

    def test_03_parse_twse_fallback_to_bid_or_ask(self):
        """測試未有最新成交價 (z='-') 時自動取買賣首檔或昨收"""
        raw_item = {
            "c": "2454",
            "z": "-",
            "b": "1200.0_1195.0_",
            "a": "1205.0_",
            "y": "1190.0",
            "o": "1195.0",
            "h": "1205.0",
            "l": "1190.0",
            "v": "100",
            "t": "09:00:05",
            "d": "20260910"
        }
        parsed = _parse_twse_item(raw_item)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["close"], 1200.0)

    def test_04_batch_quotes_mocked(self):
        """測試批次查詢多檔股票邏輯"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "msgArray": [
                {"c": "2330", "z": "1000.0", "o": "995.0", "h": "1005.0", "l": "990.0", "v": "1000", "t": "12:00:00", "d": "20260910"},
                {"c": "2454", "z": "1500.0", "o": "1490.0", "h": "1510.0", "l": "1480.0", "v": "500", "t": "12:00:00", "d": "20260910"}
            ]
        }
        with patch("requests.get", return_value=mock_resp):
            quotes = fetch_realtime_quotes_batch([("2330", "tse"), ("2454", "tse")])
            self.assertEqual(len(quotes), 2)
            self.assertEqual(quotes["2330"]["close"], 1000.0)
            self.assertEqual(quotes["2454"]["close"], 1500.0)


if __name__ == "__main__":
    unittest.main()
