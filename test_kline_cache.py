# -*- coding: utf-8 -*-
"""
test_kline_cache.py - 本地 SQLite 日K增量快取與 Parquet 種子單元測試
"""

import os
import shutil
import tempfile
import unittest
import pandas as pd
from unittest.mock import patch, MagicMock

import bot_db
from core.kline_cache import (
    init_kline_cache_table,
    load_ticker_from_seed,
    get_daily_kline_records,
    DEFAULT_SEED_PATH
)


class TestKlineCache(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.test_dir, "test_portfolio.db")
        self.old_db = bot_db.DEFAULT_DB_PATH
        bot_db.DEFAULT_DB_PATH = self.test_db

    def tearDown(self):
        bot_db.DEFAULT_DB_PATH = self.old_db
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_init_cache_table(self):
        """測試快取表自動建立"""
        init_kline_cache_table(self.test_db)
        with bot_db.get_connection(self.test_db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_kline'")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["name"], "daily_kline")

    def test_02_load_from_seed_and_query(self):
        """測試自真實 Parquet 種子檔讀取 2330 歷史資料"""
        if not os.path.exists(DEFAULT_SEED_PATH):
            self.skipTest("種子檔不存在，跳過此測試")

        count = load_ticker_from_seed("2330", db_path=self.test_db)
        self.assertGreater(count, 0)

        # 二次載入應被 IGNORE，不會重複膨脹
        count_repeat = load_ticker_from_seed("2330", db_path=self.test_db)
        self.assertEqual(count_repeat, count)

        # 查詢
        records = get_daily_kline_records("2330", "tse", months=6, db_path=self.test_db)
        self.assertGreater(len(records), 0)
        first = records[0]
        self.assertIn("date", first)
        self.assertIn("close", first)
        self.assertIn("volume", first)
        self.assertGreater(first["close"], 0)

    def test_03_cold_ticker_yfinance_fallback(self):
        """測試未在種子檔中的冷門股票走 yfinance 兜底寫入快取"""
        mock_yfinance_data = [
            {"date": "2026-09-01", "open": 50.0, "high": 52.0, "low": 49.0, "close": 51.0, "volume": 100.0},
            {"date": "2026-09-02", "open": 51.0, "high": 53.0, "low": 50.0, "close": 52.5, "volume": 120.0},
        ]
        with patch("core.kline_cache.load_ticker_from_seed", return_value=0):
            with patch("core.kline_cache._fetch_yfinance_bars", return_value=mock_yfinance_data):
                records = get_daily_kline_records("99999", "tse", months=1, db_path=self.test_db)
                self.assertEqual(len(records), 2)
                self.assertEqual(records[0]["close"], 51.0)
                self.assertEqual(records[1]["close"], 52.5)


if __name__ == "__main__":
    unittest.main()
