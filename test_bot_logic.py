# -*- coding: utf-8 -*-
"""
test_bot_logic.py - LINE Bot 業務邏輯、資料庫、自然語言指令與 Flex Message 整合測試
"""

import os
import sys
import unittest
import tempfile
import shutil

# 確保路徑
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import bot_db
import bot_flex
import line_server

class TestLineBotCore(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.test_dir, "test_portfolio.db")
        bot_db.init_db(self.test_db)
        self.user_id = "U_test_user_001"

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_01_db_user_and_position_crud(self):
        """測試資料庫用戶與持股新增、修改、查詢、平倉"""
        # 建立用戶
        user = bot_db.get_or_create_user(self.user_id, "測試操盤手", db_path=self.test_db)
        self.assertEqual(user["line_user_id"], self.user_id)
        self.assertEqual(user["display_name"], "測試操盤手")

        # 新增持股 2330 成本 980
        pos = bot_db.add_or_update_position(self.user_id, "2330", 980.0, 1000, "台積電", db_path=self.test_db)
        self.assertEqual(pos["ticker"], "2330")
        self.assertEqual(pos["cost_price"], 980.0)
        self.assertEqual(pos["shares"], 1000)

        # 查詢持倉列表
        positions = bot_db.get_user_positions(self.user_id, db_path=self.test_db)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["ticker"], "2330")

        # 更新持股 2330 成本為 950 (加碼攤平)
        pos_updated = bot_db.add_or_update_position(self.user_id, "2330", 950.0, 2000, "台積電", db_path=self.test_db)
        self.assertEqual(pos_updated["cost_price"], 950.0)
        self.assertEqual(pos_updated["shares"], 2000)

        positions_after = bot_db.get_user_positions(self.user_id, db_path=self.test_db)
        self.assertEqual(len(positions_after), 1)
        self.assertEqual(positions_after[0]["cost_price"], 950.0)

        # 新增第二檔持股 3042
        bot_db.add_or_update_position(self.user_id, "3042", 175.0, 1000, "晶技", db_path=self.test_db)
        positions_two = bot_db.get_user_positions(self.user_id, db_path=self.test_db)
        self.assertEqual(len(positions_two), 2)

        # 平倉 2330
        ok = bot_db.close_position(self.user_id, "2330", db_path=self.test_db)
        self.assertTrue(ok)
        positions_remaining = bot_db.get_user_positions(self.user_id, db_path=self.test_db)
        self.assertEqual(len(positions_remaining), 1)
        self.assertEqual(positions_remaining[0]["ticker"], "3042")

    def test_02_alert_throttle_deduplication(self):
        """測試單日單股告警去重冷卻機制"""
        user = bot_db.get_or_create_user(self.user_id, db_path=self.test_db)
        uid = user["id"]

        # 初次應允許發送
        self.assertTrue(bot_db.should_send_alert(uid, "2330", "STOP_LOSS_7", "2026-09-07", db_path=self.test_db))

        # 記錄發送日誌
        bot_db.record_alert_log(uid, "2330", "STOP_LOSS_7", 910.0, "2026-09-07", db_path=self.test_db)

        # 當天同標的同類型告警應被攔截 (False)
        self.assertFalse(bot_db.should_send_alert(uid, "2330", "STOP_LOSS_7", "2026-09-07", db_path=self.test_db))

        # 隔天應恢復允許發送 (True)
        self.assertTrue(bot_db.should_send_alert(uid, "2330", "STOP_LOSS_7", "2026-09-08", db_path=self.test_db))

    def test_03_flex_message_structures(self):
        """測試 LINE Flex Message 結構生成正確性"""
        items = [{
            "ticker": "2330",
            "stock_name": "台積電",
            "shares": 1000,
            "cost_price": 980.0,
            "current_price": 1020.0,
            "pnl": 40.0,
            "pnl_pct": 4.08,
            "pnl_amount": 40000.0,
            "stop_7": 911.40,
            "buf_7": 108.60,
            "tag": "🟢 獲利持有",
            "tag_color": "#22c55e"
        }]
        portfolio_flex = bot_flex.build_portfolio_flex("小明", items, 40000.0, 4.08)
        self.assertEqual(portfolio_flex["type"], "bubble")
        self.assertIn("header", portfolio_flex)
        self.assertIn("body", portfolio_flex)

        # 測試停損警報 Flex
        alert_flex = bot_flex.build_stop_loss_alert_flex("晶技", "3042", 160.0, 175.0, 162.75, -8.57)
        self.assertEqual(alert_flex["type"], "bubble")
        self.assertIn("🚨 BPA 強制停損緊急告警", alert_flex["header"]["contents"][0]["text"])

        # 測試單股 BPA Flex
        single_flex = bot_flex.build_single_stock_flex(
            "台積電", "2330", 1020.0, 15.0, 1.49, 1005.0,
            "🟢 建議買入", "順應 20 EMA 向上推升", 1000.0, 1050.0
        )
        self.assertEqual(single_flex["type"], "bubble")

    def test_04_command_parser_integration(self):
        """測試自然語言指令解析與相應回覆"""
        # 測試 說明 指令
        res_help = line_server.handle_user_command(self.user_id, "說明")
        self.assertIn("BPA 操盤秘書指令指南", res_help)

        # 測試 買 指令
        res_buy = line_server.handle_user_command(self.user_id, "買 2330 980")
        self.assertIn("已成功記錄持股", res_buy)
        self.assertIn("980.00", res_buy)

        # 測試 賣 指令
        res_sell = line_server.handle_user_command(self.user_id, "賣 2330")
        self.assertIn("已成功將【2330】結案平倉", res_sell)

    def test_05_patrol_worker_simulation(self):
        """測試盤中巡邏 Worker 跌破停損比對與冷卻去重"""
        import monitor_worker
        from unittest.mock import patch

        # 設定測試資料庫路徑給預設模組
        old_db = bot_db.DEFAULT_DB_PATH
        try:
            bot_db.DEFAULT_DB_PATH = self.test_db
            # 新增持股：成本 200 元，-7% 停損線為 186 元
            bot_db.add_or_update_position(self.user_id, "2330", 200.0, 1000, "台積電")

            # 模擬撮合現價為 180 元 (已跌破 186 元停損線)
            mock_rt = {"close": 180.0, "price": 180.0, "is_realtime": True}
            with patch("monitor_worker.fetch_realtime_bar", return_value=mock_rt):
                # 第一次巡邏：應觸發 1 則停損告警
                triggered_first = monitor_worker.run_patrol_cycle(force_test=True)
                self.assertEqual(triggered_first, 1)

                # 第二次巡邏：當日已告警過，應啟動冷卻去重 (0 則)
                triggered_second = monitor_worker.run_patrol_cycle(force_test=True)
                self.assertEqual(triggered_second, 0)
        finally:
            bot_db.DEFAULT_DB_PATH = old_db

if __name__ == "__main__":
    unittest.main()
