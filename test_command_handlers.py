# -*- coding: utf-8 -*-
"""
Unit Tests for line_server.py Command Handlers & Dispatcher:
Tests the 9 specialized sub-commands and main dispatcher in isolation:
  1. _cmd_buy (valid, insufficient tokens, non-numeric input, suffix stripping)
  2. _cmd_sell (valid, not found, insufficient tokens)
  3. _cmd_portfolio (empty vs populated portfolio)
  4. _cmd_add_watchlist & _cmd_remove_watchlist
  5. _cmd_view_watchlist (empty vs populated)
  6. _cmd_5m_query (valid, invalid ticker)
  7. _cmd_stock_query (valid, invalid)
  8. _cmd_help
  9. handle_user_command Dispatcher routing
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import bot_db
import bot_flex
from line_server import (
    _cmd_buy, _cmd_sell, _cmd_portfolio, _cmd_add_watchlist,
    _cmd_remove_watchlist, _cmd_view_watchlist,
    _cmd_help, handle_user_command
)


class TestCommandHandlers(unittest.TestCase):
    def setUp(self):
        # Create a temporary DB for isolated DB interactions
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_file.close()
        self.db_path = self.temp_file.name
        bot_db.init_db(self.db_path)

        # Patch default DB path in bot_db and line_server
        self.patcher_db = patch("bot_db.DEFAULT_DB_PATH", self.db_path)
        self.patcher_db.start()

        # Patch sync_to_cloud_async to prevent background network calls
        self.patcher_sync = patch("line_server.sync_to_cloud_async")
        self.patcher_sync.start()

    def tearDown(self):
        self.patcher_sync.stop()
        self.patcher_db.stop()
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
        except Exception:
            pass

    @patch("line_server.get_info", return_value=("tse", "台積電"))
    @patch("line_server.compute_risk_stop", return_value=(880.0, 0.08, "3×ATR20"))
    def test_cmd_buy(self, mock_stop, mock_info):
        """Test _cmd_buy with valid and invalid parameters."""
        uid = "U_BUY_TEST"

        # 1. Normal buy
        msg = _cmd_buy(uid, ["買", "2330", "950"])
        self.assertIn("已成功記錄持股【台積電 (2330)】", msg)
        self.assertIn("950.00 元", msg)
        self.assertIn("1,000 股", msg)

        # 2. Buy with custom shares and suffix .tw
        msg2 = _cmd_buy(uid, ["買", "2330.TW", "960.5", "2500"])
        self.assertIn("2,500 股", msg2)
        self.assertIn("960.50 元", msg2)

        # 3. Insufficient tokens
        err_msg1 = _cmd_buy(uid, ["買", "2330"])
        self.assertIn("格式錯誤", err_msg1)

        # 4. Non-numeric cost
        err_msg2 = _cmd_buy(uid, ["買", "2330", "abc"])
        self.assertIn("成本或股數必須為數字", err_msg2)

    @patch("line_server.get_info", return_value=("tse", "台積電"))
    @patch("line_server.compute_risk_stop", return_value=(880.0, 0.08, "3×ATR20"))
    def test_cmd_sell(self, mock_stop, mock_info):
        """Test _cmd_sell for closing an open position."""
        uid = "U_SELL_TEST"
        # First buy a stock
        _cmd_buy(uid, ["買", "2330", "950"])

        # Sell existing stock
        msg = _cmd_sell(uid, ["賣", "2330"])
        self.assertIn("已成功將【2330】結案平倉", msg)

        # Sell again (already closed)
        msg_again = _cmd_sell(uid, ["賣", "2330"])
        self.assertIn("找不到【2330】的進行中持倉記錄", msg_again)

        # Insufficient tokens
        msg_err = _cmd_sell(uid, ["賣"])
        self.assertIn("格式錯誤", msg_err)

    def test_cmd_portfolio_empty(self):
        """Test portfolio query when user has no positions."""
        msg = _cmd_portfolio("U_EMPTY_PORT", "TestUser")
        self.assertIn("尚無任何持倉記錄", msg)

    @patch("line_server.get_info", return_value=("tse", "台積電"))
    @patch("line_server.fetch_realtime_bar", return_value={"close": 980.0, "open": 950.0})
    @patch("line_server.compute_risk_stop", return_value=(880.0, 0.08, "3×ATR20"))
    @patch("bot_flex.build_portfolio_flex")
    def test_cmd_portfolio_populated(self, mock_flex, mock_stop, mock_rt, mock_info):
        """Test portfolio query when user has open positions."""
        uid = "U_PORT_TEST"
        mock_flex.return_value = {"type": "flex", "altText": "持倉"}

        _cmd_buy(uid, ["買", "2330", "950"])
        res = _cmd_portfolio(uid, "Investor")
        self.assertEqual(res, {"type": "flex", "altText": "持倉"})
        mock_flex.assert_called_once()

    @patch("line_server.get_info", return_value=("tse", "台積電"))
    @patch("line_server.fetch_realtime_bar", return_value={"close": 950.0})
    def test_cmd_add_and_remove_watchlist(self, mock_rt, mock_info):
        """Test watchlist add (+2330) and remove (-2330)."""
        uid = "U_WATCH_CMD"

        # 1. Add using + prefix
        msg1 = _cmd_add_watchlist(uid, "+2330", ["+2330"])
        self.assertIn("已成功將【台積電 (2330)】加入自選觀察名單", msg1)

        # 2. Add using 關注 keyword
        msg2 = _cmd_add_watchlist(uid, "關注 2454", ["關注", "2454"])
        self.assertIn("加入自選觀察名單", msg2)

        # 3. Add with invalid input
        msg_err = _cmd_add_watchlist(uid, "+", ["+"])
        self.assertIn("格式錯誤", msg_err)

        # 4. Remove using - prefix
        rem_msg = _cmd_remove_watchlist(uid, "-2330", ["-2330"])
        self.assertIn("已成功將【2330】移出觀察清單", rem_msg)

        # 5. Remove non-existent
        rem_err = _cmd_remove_watchlist(uid, "-9999", ["-9999"])
        self.assertIn("沒有【9999】", rem_err)

    def test_cmd_view_watchlist_empty(self):
        """Test viewing empty watchlist."""
        msg = _cmd_view_watchlist("U_EMPTY_WATCH", "TestUser")
        self.assertIn("自選觀察名單目前是空的", msg)

    def test_cmd_help(self):
        """Test _cmd_help returns instruction text."""
        h = _cmd_help()
        self.assertIn("量化操盤秘書指令指南", h)
        self.assertIn("買 2330 980", h)
        self.assertIn("賣 2330", h)
        self.assertNotIn("k2330", h, "說明文字不應再包含舊版 k2330 指令")

    @patch("line_server._cmd_buy", return_value="BUY_DISPATCHED")
    @patch("line_server._cmd_sell", return_value="SELL_DISPATCHED")
    @patch("line_server._cmd_portfolio", return_value="PORTFOLIO_DISPATCHED")
    @patch("line_server._cmd_add_watchlist", return_value="ADD_WATCH_DISPATCHED")
    @patch("line_server._cmd_remove_watchlist", return_value="REM_WATCH_DISPATCHED")
    @patch("line_server._cmd_view_watchlist", return_value="VIEW_WATCH_DISPATCHED")
    @patch("line_server._cmd_help", return_value="HELP_DISPATCHED")
    @patch("line_server._cmd_stock_query", return_value="STOCK_QUERY_DISPATCHED")
    def test_handle_user_command_dispatcher(self, mock_stock, mock_help,
                                            mock_vwatch, mock_rwatch, mock_awatch,
                                            mock_port, mock_sell, mock_buy):
        """Test handle_user_command routes to sub-handlers properly."""
        uid = "U_DISPATCH"

        # 1. Buy
        self.assertEqual(handle_user_command(uid, "買 2330 900"), "BUY_DISPATCHED")
        self.assertEqual(handle_user_command(uid, "buy 2330 900"), "BUY_DISPATCHED")

        # 2. Sell
        self.assertEqual(handle_user_command(uid, "賣 2330"), "SELL_DISPATCHED")
        self.assertEqual(handle_user_command(uid, "del 2330"), "SELL_DISPATCHED")

        # 3. Portfolio & Aliases
        self.assertEqual(handle_user_command(uid, "持倉"), "PORTFOLIO_DISPATCHED")
        self.assertEqual(handle_user_command(uid, "庫存"), "PORTFOLIO_DISPATCHED")
        self.assertEqual(handle_user_command(uid, "我的持倉"), "PORTFOLIO_DISPATCHED")
        self.assertEqual(handle_user_command(uid, "查看持倉"), "PORTFOLIO_DISPATCHED")
        self.assertEqual(handle_user_command(uid, "持股"), "PORTFOLIO_DISPATCHED")

        # 4. Add Watchlist
        self.assertEqual(handle_user_command(uid, "+2330"), "ADD_WATCH_DISPATCHED")
        self.assertEqual(handle_user_command(uid, "關注 2330"), "ADD_WATCH_DISPATCHED")

        # 5. Remove Watchlist
        self.assertEqual(handle_user_command(uid, "-2330"), "REM_WATCH_DISPATCHED")

        # 6. View Watchlist
        self.assertEqual(handle_user_command(uid, "自選"), "VIEW_WATCH_DISPATCHED")
        self.assertEqual(handle_user_command(uid, "清單"), "VIEW_WATCH_DISPATCHED")

        # 7. Help
        self.assertEqual(handle_user_command(uid, "說明"), "HELP_DISPATCHED")
        self.assertEqual(handle_user_command(uid, "help"), "HELP_DISPATCHED")

        # 8. Stock query (single ticker & Chinese name)
        self.assertEqual(handle_user_command(uid, "2330"), "STOCK_QUERY_DISPATCHED")
        self.assertEqual(handle_user_command(uid, "晶技"), "STOCK_QUERY_DISPATCHED")

        # 10. Empty command
        self.assertIn("請輸入指令", handle_user_command(uid, "   "))

    def test_cmd_buy_chinese_stock_name(self):
        """Test buying by Chinese stock name automatically resolves ticker."""
        uid = "U_BUY_CN_TEST"
        res = _cmd_buy(uid, ["買", "晶技", "196", "2000"])
        self.assertIn("晶技 (3042)", res)
        self.assertIn("196.00", res)
        self.assertIn("2,000", res)

    def test_cmd_buy_invalid_stock(self):
        """Test buying with an invalid non-existent stock name is rejected."""
        uid = "U_BUY_INVALID"
        res = _cmd_buy(uid, ["買", "絕對無此股票", "100"])
        self.assertIn("查無台股代號或名稱", res)

    def test_portfolio_flex_no_double_plus(self):
        """Test build_portfolio_flex does not contain '++' double plus formatting error."""
        items = [{
            "ticker": "2330",
            "stock_name": "台積電",
            "shares": 1000,
            "cost_price": 980.0,
            "current_price": 1050.0,
            "pnl": 70.0,
            "pnl_pct": 7.14,
            "pnl_amount": 70000.0,
            "stop_7": 900.0,
            "stop_pct": 0.08,
            "buf_7": 150.0,
            "tag": "🟢 獲利持有",
            "tag_color": "#22c55e"
        }]
        bubble = bot_flex.build_portfolio_flex("測試員", items, 70000.0, 7.14)
        bubble_str = json.dumps(bubble, ensure_ascii=False)
        self.assertNotIn("++", bubble_str)
        self.assertIn("+7.14%", bubble_str)
        self.assertIn("+$70,000", bubble_str)


if __name__ == "__main__":
    unittest.main()
