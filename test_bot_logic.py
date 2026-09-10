# -*- coding: utf-8 -*-
"""
test_bot_logic.py - LINE Bot 業務邏輯、資料庫、自然語言指令與 Flex Message 整合測試
"""

import os
import sys
import json
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
        shutil.rmtree(self.test_dir, ignore_errors=True)

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

        # ── 測試自選觀察名單 (Watchlist) CRUD（預設不設上限） ──
        # 預設不設上限：加入 2330 到觀察名單
        ok_w, msg_w = bot_db.add_to_watchlist(self.user_id, "2330", "台積電", db_path=self.test_db)
        self.assertTrue(ok_w)
        self.assertIn("台積電", msg_w)

        # 加入 00708L
        ok_w2, _ = bot_db.add_to_watchlist(self.user_id, "00708L", "期元大S&P黃金正2", db_path=self.test_db)
        self.assertTrue(ok_w2)

        # 加入第 3 檔（預設無上限，應順利成功）
        ok_w3, _ = bot_db.add_to_watchlist(self.user_id, "2603", "長榮", db_path=self.test_db)
        self.assertTrue(ok_w3)

        # 查詢名單（應有 3 檔）
        wl = bot_db.get_user_watchlist(self.user_id, db_path=self.test_db)
        self.assertEqual(len(wl), 3)

        # 移除 2330
        rm_ok = bot_db.remove_from_watchlist(self.user_id, "2330", db_path=self.test_db)
        self.assertTrue(rm_ok)
        wl_after = bot_db.get_user_watchlist(self.user_id, db_path=self.test_db)
        self.assertEqual(len(wl_after), 2)

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

        # 測試多日冷卻機制 (cooldown_days=5)
        # 在 2026-09-08 記錄 BPA 買點告警
        bot_db.record_alert_log(uid, "2454", "BPA_BUY_SETUP", 1450.0, "2026-09-08", db_path=self.test_db)
        # 於第 1~4 天內 (2026-09-09 至 2026-09-12) 應被攔截
        self.assertFalse(bot_db.should_send_alert(uid, "2454", "BPA_BUY_SETUP", "2026-09-09", db_path=self.test_db, cooldown_days=5))
        self.assertFalse(bot_db.should_send_alert(uid, "2454", "BPA_BUY_SETUP", "2026-09-12", db_path=self.test_db, cooldown_days=5))
        # 於第 5 天 (2026-09-13) 冷卻期滿，應允許發送 (True)
        self.assertTrue(bot_db.should_send_alert(uid, "2454", "BPA_BUY_SETUP", "2026-09-13", db_path=self.test_db, cooldown_days=5))

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
            "stop_pct": 0.07,
            "buf_7": 108.60,
            "tag": "🟢 獲利持有",
            "tag_color": "#22c55e"
        }]
        portfolio_flex = bot_flex.build_portfolio_flex("小明", items, 40000.0, 4.08)
        self.assertEqual(portfolio_flex["type"], "bubble")
        self.assertIn("header", portfolio_flex)
        self.assertIn("body", portfolio_flex)

        # 測試停損警報 Flex
        alert_flex = bot_flex.build_stop_loss_alert_flex(
            "晶技", "3042", 160.0, 175.0, 162.75, -8.57,
            stop_pct=0.093, stop_basis="3×ATR20（日波動 3.10%）"
        )
        self.assertEqual(alert_flex["type"], "bubble")
        self.assertIn("浮虧警戒通知", alert_flex["header"]["contents"][0]["text"])
        # 動態警戒幅度與依據必須實際帶進卡片，防止退回硬寫 -7%
        alert_text = json.dumps(alert_flex, ensure_ascii=False)
        self.assertIn("-9.3%", alert_text)
        self.assertIn("3×ATR20", alert_text)
        self.assertNotIn("強制停損底線", alert_text)

        # 測試單股 BPA Flex
        single_flex = bot_flex.build_single_stock_flex(
            "台積電", "2330", 1020.0, 15.0, 1.49, 1005.0,
            "🟢 建議買入", "順應 20 EMA 向上推升", 1000.0, 1050.0
        )
        self.assertEqual(single_flex["type"], "bubble")

        # 測試 1:1 復刻 Web 儀表板旗艦級 4合1 多維綜合評鑑 Flex
        dash_flex = bot_flex.build_dashboard_stock_flex(
            stock_name="台積電", ticker="2330", market="tse",
            close_now=1020.0, chg_val=15.0, chg_pct=1.49,
            realtime_info={"is_realtime": True, "time": "13:30:00"},
            df=None, bpa_res={}, trend_score=2, trend_stage="多頭推升",
            rating_badge="優質多頭", comp={"score": 85, "badge": "⭐⭐⭐⭐⭐ 優質多頭", "action_tag": "🟢 建議買入"},
            sr={"s1": 1000.0, "r1": 1050.0}
        )
        self.assertEqual(dash_flex["type"], "bubble")
        self.assertEqual(dash_flex["size"], "giga")
        self.assertIn("台積電", dash_flex["header"]["contents"][0]["contents"][0]["contents"][0]["text"])

        # 驗證日K卡片 footer 已移除 5分K 當沖按鍵
        footer_btn_labels = [b.get("action", {}).get("label", "") for b in dash_flex.get("footer", {}).get("contents", [])]
        self.assertNotIn("⚡ 5分K 當沖", footer_btn_labels, "日K卡片 footer 應已移除 5分K 當沖按鍵")

        # 驗證 5分K 卡片 footer 已移除 查日K 按鍵
        flex_5m = bot_flex.build_5m_stock_flex({
            "ticker": "2330", "stock_name": "台積電", "market": "tse",
            "close_now": 1020.0, "change_today": 15.0, "change_today_pct": 1.49,
            "high_today": 1025.0, "low_today": 1005.0, "range_today": 20.0,
            "data_time_str": "13:30", "ema_now": 1015.0, "ema_bias_pct": 0.5,
            "bpa_status": "多頭順勢", "bpa_status_color": "#22c55e",
            "last_bar_type": "多頭趨勢棒", "vol_now": 2000, "vol_ratio_5m": 1.5,
            "action_tag": "🟢 順勢偏多", "action_sub": "順勢運行", "action_color": "#22c55e",
            "whale_tag": "大單敲進", "whale_color": "#22c55e", "whale_advice": "動能充沛",
            "mtf_status": "多時框多方", "conformal_status": "合格", "noise_ratio": 1.0,
            "buy_stop": 1025.0, "sell_stop": 1005.0, "stop_loss": 995.0,
            "stop_type": "前低防守", "r_val": 25.0, "target_1r": 1045.0, "target_2r": 1070.0
        })
        footer_5m_btns = [b.get("action", {}).get("label", "") for b in flex_5m.get("footer", {}).get("contents", [])]
        self.assertNotIn("📊 查日K (4合1)", footer_5m_btns, "5分K卡片 footer 應已移除 查日K 按鍵")

        # 測試 自選觀察清單 Flex
        wl_flex = bot_flex.build_watchlist_flex("小明", [{
            "ticker": "2330",
            "stock_name": "台積電",
            "current_price": 1020.0,
            "chg_val": 15.0,
            "chg_pct": 1.49,
            "bpa_zh": "AIL 多頭主控",
            "bpa_color": "#4ade80",
            "dist_desc": "回踩月線有守"
        }])
        self.assertEqual(wl_flex["type"], "bubble")
        self.assertIn("自選觀察清單", wl_flex["header"]["contents"][0]["contents"][0]["text"])

        # 測試 高勝率買點觸發推播 Flex
        sig_flex = bot_flex.build_buy_signal_alert_flex(
            "台積電", "2330", "🔥 High 2 (H2) 雙重底回踩買點",
            "波段回檔 ABC 修正結束，空方無力跌破！", 1020.0, 1025.0, 1000.0, 1050.0, 1075.0
        )
        self.assertEqual(sig_flex["type"], "bubble")
        self.assertIn("高勝率買點觸發", sig_flex["header"]["contents"][0]["text"])

    def test_04_command_parser_integration(self):
        """測試自然語言指令解析與相應回覆"""
        # 測試 說明 指令
        res_help = line_server.handle_user_command(self.user_id, "說明")
        self.assertIn("操盤秘書指令指南", res_help)

        # 測試 買 指令
        res_buy = line_server.handle_user_command(self.user_id, "買 2330 980")
        self.assertIn("已成功記錄持股", res_buy)
        self.assertIn("980.00", res_buy)

        # 測試 賣 指令
        res_sell = line_server.handle_user_command(self.user_id, "賣 2330")
        self.assertIn("已成功將【2330】結案平倉", res_sell)

        # 測試 單檔股票 BPA 雙時框輪播查詢 (如 2330 與 00708L / 00708l)
        res_single = line_server.handle_user_command(self.user_id, "2330")
        self.assertIsInstance(res_single, dict)
        self.assertEqual(res_single.get("type"), "carousel")
        self.assertEqual(len(res_single.get("contents", [])), 2, "Carousel 應包含日K與5分K兩張圖卡")

        # 測試 槓桿/反向 ETF 與英數字後綴代號 (如 00708L)
        res_etf = line_server.handle_user_command(self.user_id, "00708L")
        self.assertIsInstance(res_etf, dict)
        self.assertEqual(res_etf.get("type"), "carousel")
        self.assertEqual(len(res_etf.get("contents", [])), 2)

        # 測試小寫代號輸入 (如 00708l) 自動轉大寫處理
        res_etf_lower = line_server.handle_user_command(self.user_id, "00708l")
        self.assertIsInstance(res_etf_lower, dict)
        self.assertEqual(res_etf_lower.get("type"), "carousel")
        self.assertEqual(len(res_etf_lower.get("contents", [])), 2)

        # 測試 持倉 / 庫存 指令
        res_pos_empty = line_server.handle_user_command(self.user_id, "持倉")
        self.assertIn("尚無任何持倉記錄", res_pos_empty)

        # 測試 關注 / 追蹤 指令（支援 關注 2330 與快捷指令 +2330, +00708L）
        res_watch = line_server.handle_user_command(self.user_id, "關注 2330")
        self.assertIn("成功將【台積電 (2330)】加入自選觀察名單", res_watch)

        res_plus = line_server.handle_user_command(self.user_id, "+00708L")
        self.assertIn("成功將【期元大S&P黃金正2 (00708L)】加入自選觀察名單", res_plus)

        # 測試 自選 / 清單 指令 (回傳 Flex 卡片)
        res_wl = line_server.handle_user_command(self.user_id, "自選")
        self.assertIsInstance(res_wl, dict)
        self.assertEqual(res_wl.get("type"), "bubble")

        # 測試 取消關注 指令（支援 取消關注 2330 與快捷指令 -2330, -00708L）
        res_unwatch = line_server.handle_user_command(self.user_id, "取消關注 2330")
        self.assertIn("成功將【2330】移出觀察清單", res_unwatch)

        res_minus = line_server.handle_user_command(self.user_id, "-00708L")
        self.assertIn("成功將【00708L】移出觀察清單", res_minus)

    def test_05_patrol_worker_simulation(self):
        """測試盤中巡邏 Worker 跌破停損比對與冷卻去重"""
        import monitor_worker
        from unittest.mock import patch

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

    def test_06_watchlist_patrol_simulation(self):
        """測試觀察名單巡邏 Worker 回測買點比對與冷卻去重"""
        import monitor_worker
        from unittest.mock import patch

        old_db = bot_db.DEFAULT_DB_PATH
        try:
            bot_db.DEFAULT_DB_PATH = self.test_db
            # 加入觀察名單
            bot_db.add_to_watchlist(self.user_id, "2330", "台積電")

            # 模擬觸發 High 2 買點信號
            mock_signal = {
                "triggered": True,
                "signal_name": "🔥 High 2 (H2) 雙重底回踩買點",
                "signal_desc": "波段回檔 ABC 修正結束，空方無力跌破！",
                "buy_stop": 1025.0,
                "sell_stop": 1000.0,
                "target_1r": 1050.0,
                "target_2r": 1075.0,
                "close_now": 1020.0,
                "stock_name": "台積電",
                "market": "tse"
            }

            with patch("monitor_worker.check_bottom_confirmation_signals", return_value=mock_signal):
                # 第一次巡邏：應發出 1 則買點通知
                triggered_buy1 = monitor_worker.run_watchlist_patrol_cycle(force_test=True)
                self.assertEqual(triggered_buy1, 1)

                # 第二次巡邏：當日已推播過，應啟動單日冷卻去重 (0 則)
                triggered_buy2 = monitor_worker.run_watchlist_patrol_cycle(force_test=False)
                self.assertEqual(triggered_buy2, 0)
        finally:
            bot_db.DEFAULT_DB_PATH = old_db

    def test_07_mtf_and_institutional_gate(self):
        """自動化驗證：多時框對齊 (MTF Alignment) 與法人籌碼硬門檻 (Hard Gate)"""
        import pandas as pd
        import kline
        import monitor_worker
        from unittest.mock import patch

        # 1. 測試法人籌碼硬門檻：若近3日法人賣超超過 300 張，應硬性攔截不予推播
        mock_daily_res_bearish_inst = {
            "df": pd.DataFrame({"close": [180.0], "low": [178.0], "high": [182.0], "ema20": [180.0], "vol_ma": [1000.0], "volume": [500.0]}),
            "bpa_res": {"always_in_code": "AIL", "signals": ["🔥 High 2 (H2) 雙重底回踩買點"]},
            "sr_levels": {"s1": 180.0},
            "close_now": 180.0,
            "stock_name": "晶技",
            "inst_df": pd.DataFrame({"total": [-150, -100, -100]}) # 近3日合計賣超 -350 張
        }
        res_inst_blocked = monitor_worker.check_bottom_confirmation_signals("3042", analysis_res=mock_daily_res_bearish_inst)
        self.assertFalse(res_inst_blocked["triggered"], "法人近3日賣超 > 300張時，應觸發硬門檻攔截！")

        # 2. 測試法人中性或買超時，正常放行
        mock_daily_res_bullish_inst = {
            "df": pd.DataFrame({"close": [180.0], "low": [178.0], "high": [182.0], "ema20": [180.0], "vol_ma": [1000.0], "volume": [500.0], "bpa_h2": [True]}),
            "bpa_res": {"always_in_code": "AIL", "signals": ["🔥 High 2 (H2) 雙重底回踩買點"]},
            "sr_levels": {"s1": 180.0},
            "close_now": 180.0,
            "stock_name": "晶技",
            "inst_df": pd.DataFrame({"total": [50, 100, 200]}) # 近3日合計買超 +350 張
        }
        res_inst_passed = monitor_worker.check_bottom_confirmation_signals("3042", analysis_res=mock_daily_res_bullish_inst)
        self.assertTrue(res_inst_passed["triggered"], "法人買超且技術面吻合時，應正常觸發！")

        # 3. 測試 5分K 多時框箝制：當日線處於空方架構 (AIS 或跌破日MA20)，5m 即使在均線上，也嚴禁偏多買進
        mock_daily_for_5m = {
            "bpa_res": {"always_in_code": "AIS"},
            "trend_score": -4,
            "df": pd.DataFrame({"ma20": [200.0]}), # 現價 180，遠低於日MA20 (200)
            "inst_df": pd.DataFrame({"total": [-100, -100, -100]})
        }
        with patch("core.analyzer.analyze_stock", return_value=mock_daily_for_5m):
            # 注意：analyze_stock_5m 內部呼叫的是 core.analyzer 自身模組內的 analyze_stock，
            # 而不是 kline.py 這個相容性 facade 重新匯出的名稱，兩者是不同的物件參照，
            # 所以必須直接對定義它的模組（core.analyzer）下 patch，才能攔截到內部呼叫。
            res_5m = kline.analyze_stock_5m("3042", days=1)
            self.assertIn("mtf_status", res_5m)
            # 若 bpa_status 出現多頭，必須被壓制，嚴禁給出多方買進建議
            if "多" in res_5m["bpa_status"]:
                self.assertNotIn("建議偏多買進", res_5m["action_tag"])
                self.assertNotIn("建議順勢做多", res_5m["action_tag"])
                self.assertTrue(
                    any(kw in res_5m["action_tag"] for kw in ["逆日線弱彈", "暫緩開倉", "拒絕開倉"]),
                    f"Unexpected action_tag: {res_5m['action_tag']}"
                )

    def test_08_conformal_prediction_abstention(self):
        """自動化驗證：Conformal Prediction 雜訊比與拒絕開倉門檻 (Abstention Gate)"""
        import pandas as pd
        import monitor_worker

        # 1. 測試極端單日巨震 (當日振幅 > 2.5x ATR20) 時，觸發 Conformal 拒絕開倉
        # 構造 ATR 約為 2.0，但當日高低差高達 8.0 元 (4倍 ATR) 的極端巨震日
        fake_high = [100.0 + i * 0.5 for i in range(25)]
        fake_low = [98.0 + i * 0.5 for i in range(25)]
        fake_close = [99.0 + i * 0.5 for i in range(25)]
        # 最後一天巨震
        fake_high[-1] = 120.0
        fake_low[-1] = 110.0
        fake_close[-1] = 115.0

        mock_extreme_vol_df = pd.DataFrame({
            "high": fake_high,
            "low": fake_low,
            "close": fake_close,
            "ema20": fake_close,
            "vol_ma": [1000.0] * 25,
            "volume": [800.0] * 25,
            "bpa_h2": [False] * 24 + [True]
        })

        mock_res = {
            "df": mock_extreme_vol_df,
            "bpa_res": {"always_in_code": "AIL", "signals": ["🔥 High 2 (H2) 雙重底回踩買點"]},
            "sr_levels": {"s1": 110.0},
            "close_now": 115.0,
            "stock_name": "極端波動股",
            "inst_df": pd.DataFrame({"total": [100, 100, 100]})
        }

        res_conformal_blocked = monitor_worker.check_bottom_confirmation_signals("9999", analysis_res=mock_res)
        self.assertFalse(res_conformal_blocked["triggered"], "當日極端巨震 (>2.5x ATR) 時，應啟動 Conformal 拒絕推播！")

    def test_09_hmm_regime_filtering(self):
        """測試方案二：HMM 市場狀態雙層濾網 (Two-Stage Regime Gate)"""
        import monitor_worker
        import kline
        import pandas as pd

        # 構造常態多頭 K 棒
        n = 30
        dates = pd.date_range("2026-08-01", periods=n)
        close = [100.0 + i * 0.5 for i in range(n)]
        df_normal = pd.DataFrame({
            "date": dates,
            "open": close,
            "high": [c + 1.0 for c in close],
            "low": [c - 0.5 for c in close],
            "close": close,
            "ema20": close,
            "volume": [1000.0] * n,
            "vol_ma": [1000.0] * n,
            "bpa_h2": [False] * (n - 1) + [True]
        })

        # 1. 測試自選買點雷達在 HMM 震盪市況下自動攔截
        mock_adverse_res = {
            "df": df_normal,
            "bpa_res": {"always_in_code": "AIL", "signals": ["🔥 High 2 (H2) 雙重底回踩買點"]},
            "sr_levels": {"s1": 110.0},
            "close_now": 115.0,
            "stock_name": "震盪股",
            "inst_df": pd.DataFrame({"total": [100, 100, 100]}),
            "composite_rating": {"score": 88},
            "regime_info": {"is_adverse": True, "regime_name": "⚠️ 高波震盪市況"}
        }
        res_adverse = monitor_worker.check_bottom_confirmation_signals("2454", analysis_res=mock_adverse_res)
        self.assertFalse(res_adverse["triggered"], "處於 HMM 高波震盪市況時，應啟動市場狀態閘道攔截推播！")

        # 2. 測試順勢環境下放行
        mock_healthy_res = {
            **mock_adverse_res,
            "regime_info": {"is_adverse": False, "regime_name": "🟢 順勢波段環境"}
        }
        res_healthy = monitor_worker.check_bottom_confirmation_signals("2454", analysis_res=mock_healthy_res)
        self.assertTrue(res_healthy["triggered"], "處於 HMM 順勢環境且具備優質體質時，應放行推播！")
        self.assertIn("regime_status", res_healthy)

        # 3. 測試 evaluate_composite_rating 的雙層門檻 (80 分 vs 85 分)
        # 構造模擬評級環境
        bpa_mock = {"always_in_zh": "🟢 多頭主升趨勢", "always_in_code": "AIL"}
        vol_mock = {"wyckoff_status": "🟢 放量推升", "summary": "多方量能推升"}
        
        # 80 分在順勢環境 -> BUY
        r_healthy = kline.evaluate_composite_rating(
            df_normal, bpa_mock, vol_mock, pd.DataFrame({"total": [500] * 5}),
            {"eps_ttm": 15.0, "pe_ratio": 15.0, "quarterly_eps": [3.0, 3.5, 4.0, 4.5]},
            "2330", "tse", regime_info={"is_adverse": False}
        )
        if r_healthy["score"] >= 80:
            self.assertEqual(r_healthy["action_type"], "BUY", "順勢市況且評分>=80分時應輸出 BUY")

        # 在高波震盪環境下，評分 80~84 分應降級為 WAIT
        r_adverse_80 = kline.evaluate_composite_rating(
            df_normal, bpa_mock, vol_mock, pd.DataFrame({"total": [500] * 5}),
            {"eps_ttm": 15.0, "pe_ratio": 15.0, "quarterly_eps": [3.0, 3.5, 4.0, 4.5]},
            "2330", "tse", regime_info={"is_adverse": True}
        )
        if 80 <= r_adverse_80["score"] < 85:
            self.assertEqual(r_adverse_80["action_type"], "WAIT", "震盪市況下 80~84 分應降級為 WAIT 觀望")

if __name__ == "__main__":
    unittest.main()
