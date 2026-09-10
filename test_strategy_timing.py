# -*- coding: utf-8 -*-
"""單元測試：60分K 時機層評估模組 (core/strategy_timing.py)
嚴格檢驗：
  1. 日K 方向許可證 (daily_bias) 硬限制
  2. 方案 A：回測 20 EMA 守穩確認與具體價位計算
  3. 日K 關鍵防守線跌破警示 (EXIT_ALERT)
  4. 60分K 爆量長上影出貨攔截
  5. 方案 B（推動過前高）與方案 C（區間放量突破）
"""
import unittest
import pandas as pd
from core.strategy_timing import evaluate_60m_timing


class TestStrategyTiming(unittest.TestCase):
    def _create_base_60m_df(self, n=25, base_p=100.0, trend=0.5):
        """建立合成 60 分鐘 K 線數據"""
        closes = [base_p + i * trend for i in range(n)]
        opens = [c - 0.2 for c in closes]
        highs = [c + 0.8 for c in closes]
        lows = [c - 0.6 for c in closes]
        volumes = [1000.0] * n

        df = pd.DataFrame({
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes
        })
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["vol_ma20"] = df["volume"].rolling(20, min_periods=1).mean()
        return df

    def test_daily_bias_gate_blocks_timing(self):
        """日K 方向許可證未通過時 (WAIT 或 SELL)，60分K 絕對禁止開多 (NONE)。"""
        df = self._create_base_60m_df(25)

        # 1. daily_bias = 'WAIT'
        res_wait = evaluate_60m_timing(df, daily_bias="WAIT")
        self.assertEqual(res_wait["timing_signal"], "NONE")
        self.assertFalse(res_wait["is_valid"])
        self.assertIn("日K 方向層未達買入許可", res_wait["reason"])

        # 2. daily_bias = 'SELL'
        res_sell = evaluate_60m_timing(df, daily_bias="SELL")
        self.assertEqual(res_sell["timing_signal"], "NONE")
        self.assertFalse(res_sell["is_valid"])

    def test_insufficient_data(self):
        """K 線根數 < 5 時返回 NONE。"""
        df_short = self._create_base_60m_df(3)
        res = evaluate_60m_timing(df_short, daily_bias="BUY_CANDIDATE")
        self.assertEqual(res["timing_signal"], "NONE")
        self.assertIn("長度不足", res["reason"])

    def test_scheme_a_pullback_ema20_success(self):
        """方案 A：60分K 回測 20 EMA 守穩收紅且具下影線拒絕 -> 觸發 ENTER_LONG。"""
        df = self._create_base_60m_df(25, base_p=100.0, trend=0.4)
        ema_now = float(df["ema20"].iloc[-1])

        # 設定最新一根：最低價回踩 20 EMA，收盤站回 EMA 之上，且留明顯下影線（>=35%）
        last_idx = len(df) - 1
        df.loc[last_idx, "low"] = round(ema_now - 0.05, 2)  # 輕微回踩 EMA
        df.loc[last_idx, "open"] = round(ema_now + 0.30, 2)
        df.loc[last_idx, "close"] = round(ema_now + 0.70, 2) # 收紅站穩
        df.loc[last_idx, "high"] = round(ema_now + 0.80, 2)
        df.loc[last_idx, "volume"] = 800.0  # 溫和量縮
        # 更新 EMA
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

        res = evaluate_60m_timing(df, daily_bias="BUY_CANDIDATE", preferred_scheme="A")
        self.assertEqual(res["timing_signal"], "ENTER_LONG")
        self.assertEqual(res["scheme"], "SCHEME_A_PULLBACK_EMA20")
        self.assertTrue(res["is_valid"])
        self.assertIsNotNone(res["entry_ref"])
        self.assertIsNotNone(res["stop_ref"])
        self.assertLess(res["stop_ref"], res["entry_ref"])
        self.assertGreater(res["risk_pct"], 0.0)
        self.assertGreater(res["target_1r"], res["entry_ref"])
        self.assertGreater(res["target_2r"], res["target_1r"])

        # 檢驗具體價位原則
        self.assertIn("20 EMA（", res["reason"])
        self.assertIn("做多防守停損", res["reason"])
        self.assertIn("目標一價位", res["reason"])

    def test_exit_alert_when_daily_ema20_breached(self):
        """當 60分K 收盤跌破日K 20 EMA 或日K 關鍵支撐時，觸發 EXIT_ALERT。"""
        df = self._create_base_60m_df(25, base_p=100.0, trend=0.2)
        close_now = float(df["close"].iloc[-1])

        # 設定日K 20 EMA 在現價之上（即跌破日K 20 EMA）
        res = evaluate_60m_timing(
            df, daily_bias="BUY_CANDIDATE", daily_ema20=close_now + 2.0
        )
        self.assertEqual(res["timing_signal"], "EXIT_ALERT")
        self.assertFalse(res["is_valid"])
        self.assertIn("跌破日K 20 EMA", res["reason"])

    def test_churn_exhaustion_blocks_entry(self):
        """當 60分K 出現爆量長上影滯漲陰線時，觸發出貨警訊，不予進場。"""
        df = self._create_base_60m_df(25, base_p=100.0, trend=0.3)
        last_idx = len(df) - 1
        df.loc[last_idx, "volume"] = 2500.0  # 2.5 倍均量（爆量）
        df.loc[last_idx, "open"] = 110.0
        df.loc[last_idx, "close"] = 108.0    # 陰線
        df.loc[last_idx, "high"] = 115.0     # 長上影線 (115 - 110 = 5, 振幅 115 - 107 = 8, 比例 > 50%)
        df.loc[last_idx, "low"] = 107.0

        res = evaluate_60m_timing(df, daily_bias="BUY_CANDIDATE")
        self.assertEqual(res["timing_signal"], "NONE")
        self.assertIn("出貨嫌疑", res["reason"])

    def test_scheme_c_range_breakout(self):
        """方案 C：60分K 放量突破近 10 根整理高點且量增 >= 1.3x。"""
        df = self._create_base_60m_df(25, base_p=100.0, trend=0.0) # 盤整
        high_10 = float(df["high"].iloc[-11:-1].max())
        last_idx = len(df) - 1

        # 突破根：收盤大於近 10 根高點，量增 1.5 倍
        df.loc[last_idx, "close"] = high_10 + 1.5
        df.loc[last_idx, "high"] = high_10 + 1.8
        df.loc[last_idx, "open"] = high_10 - 0.2
        df.loc[last_idx, "low"] = high_10 - 0.5
        df.loc[last_idx, "volume"] = 1500.0  # 1.5x 均量
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

        res = evaluate_60m_timing(df, daily_bias="BUY_CANDIDATE", preferred_scheme="C")
        self.assertEqual(res["timing_signal"], "ENTER_LONG")
        self.assertEqual(res["scheme"], "SCHEME_C_RANGE_BREAKOUT")
        self.assertIn("突破整理區間高點", res["reason"])


if __name__ == "__main__":
    unittest.main()
