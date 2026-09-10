# -*- coding: utf-8 -*-
"""
Deterministic Unit & Regression Test Suite for Core Strategies
Targeting: core/indicators.py, core/strategy_trend.py, core/strategy_volume.py,
          core/strategy_brooks.py, core/rating.py

Zero network calls, 100% synthetic deterministic fixtures.
"""

import os
import unittest
from unittest.mock import patch
import pandas as pd

from core.indicators import get_tw_tick, compute_atr_pct, compute_risk_stop, _STOP_LEVEL_CACHE
from core.strategy_trend import evaluate_professional_trend
from core.strategy_volume import evaluate_volume_price
from core.strategy_brooks import evaluate_brooks_price_action
from core.rating import get_rating_badge, evaluate_composite_rating, check_anti_chase


# =====================================================================
# 1. Indicator & Tick Math Tests
# =====================================================================
class TestIndicators(unittest.TestCase):
    def setUp(self):
        _STOP_LEVEL_CACHE.clear()

    def tearDown(self):
        _STOP_LEVEL_CACHE.clear()

    def test_get_tw_tick_boundaries(self):
        """Verify TWSE tick rules at all boundary edges."""
        cases = [
            (0.01, 0.01),
            (9.99, 0.01),
            (10.00, 0.05),
            (49.95, 0.05),
            (50.00, 0.10),
            (99.90, 0.10),
            (100.00, 0.50),
            (499.50, 0.50),
            (500.00, 1.00),
            (999.00, 1.00),
            (1000.00, 5.00),
            (2500.00, 5.00),
        ]
        for price, expected in cases:
            with self.subTest(price=price):
                self.assertAlmostEqual(get_tw_tick(price), expected, places=5)

    def test_compute_atr_pct_deterministic(self):
        """Verify ATR(20) calculation with deterministic constant TR."""
        # 30 bars, high=105, low=95, close=100 -> TR is exactly 10 every bar
        n = 30
        df = pd.DataFrame({
            "high": [105.0] * n,
            "low": [95.0] * n,
            "close": [100.0] * n
        })
        atr_pct = compute_atr_pct(df, period=20)
        # Expected ATR = 10.0, close = 100.0 -> atr_pct = 10.0 / 100.0 = 0.10 (10%)
        self.assertAlmostEqual(atr_pct, 0.10, places=4)

    def test_compute_risk_stop_user_override(self):
        """User DB override takes absolute precedence if != -7.0%."""
        stop_p, stop_pct, note = compute_risk_stop(
            ticker="2330",
            cost_price=100.0,
            user_pct=-12.5
        )
        self.assertAlmostEqual(stop_pct, 0.125, places=3)
        self.assertAlmostEqual(stop_p, 87.5, places=2)
        self.assertIn("使用者自訂 -12.5%", note)

    @patch("core.indicators.compute_atr_pct")
    def test_compute_risk_stop_clamping(self, mock_atr):
        """Test 3*ATR clamping between -8% and -15%."""
        dummy_df = pd.DataFrame({"close": [100.0]})

        # Case A: Low ATR = 0.01 (1.0%) -> 3*ATR = 3.0% -> clamped to -8.0% (0.08)
        mock_atr.return_value = 0.01
        stop_p, stop_pct, note = compute_risk_stop(
            ticker="2330_A", cost_price=200.0, analysis_res={"df": dummy_df}
        )
        self.assertAlmostEqual(stop_pct, 0.08, places=3)
        self.assertAlmostEqual(stop_p, 184.0, places=2)

        # Case B: High ATR = 0.06 (6.0%) -> 3*ATR = 18.0% -> clamped to -15.0% (0.15)
        mock_atr.return_value = 0.06
        stop_p, stop_pct, note = compute_risk_stop(
            ticker="2330_B", cost_price=200.0, analysis_res={"df": dummy_df}
        )
        self.assertAlmostEqual(stop_pct, 0.15, places=3)
        self.assertAlmostEqual(stop_p, 170.0, places=2)

        # Case C: Medium ATR = 0.035 (3.5%) -> 3*ATR = 10.5% (0.105) -> in range [0.08, 0.15]
        mock_atr.return_value = 0.035
        stop_p, stop_pct, note = compute_risk_stop(
            ticker="2330_C", cost_price=100.0, analysis_res={"df": dummy_df}
        )
        self.assertAlmostEqual(stop_pct, 0.105, places=3)
        self.assertAlmostEqual(stop_p, 89.5, places=2)


# =====================================================================
# 2. Stan Weinstein Trend & Composite Trend Analysis Tests
# =====================================================================
class TestStrategyTrend(unittest.TestCase):
    def _create_base_df(self, n=60):
        dates = pd.date_range("2026-01-01", periods=n, freq="B")
        return pd.DataFrame({
            "date": dates,
            "open": [100.0] * n,
            "high": [102.0] * n,
            "low": [98.0] * n,
            "close": [100.0] * n,
            "volume": [1000.0] * n,
            "ma5": [100.0] * n,
            "ma20": [100.0] * n,
            "ma60": [100.0] * n,
            "vol_ma": [1000.0] * n,
            "rsi": [55.0] * n,
            "macd": [0.5] * n,
            "macd_signal": [0.3] * n,
            "macd_hist": [0.2] * n,
        })

    def _default_bpa_res(self):
        return {
            "always_in": "多頭主控 (Always In Long)",
            "always_in_zh": "多頭主控",
            "always_in_score": 2,
            "bpa_extra_score": 0,
            "last_bar_type": "多頭趨勢棒",
            "signals": ["20 EMA 守穩順勢攻擊"],
            "setups": []
        }

    def _default_vol_eval(self):
        return {
            "score": 2,
            "status": "價量齊揚",
            "status_code": "BULL_EXP",
            "desc": "放量攻擊"
        }

    def test_weinstein_stage_2_bull_advance(self):
        """Stage 2: MA20 > MA60, slope_ma20 > 0.003, slope_ma60 >= 0 (+2 pts)."""
        df = self._create_base_df(60)
        df.loc[:55, "ma20"] = 100.0
        df.loc[59, "ma20"] = 105.0   # slope = 5% > 0.3%
        df.loc[:55, "ma60"] = 90.0
        df.loc[59, "ma60"] = 92.0    # slope = 2.2% >= 0, ma20 > ma60

        score, stage, factors = evaluate_professional_trend(
            df, pd.DataFrame(), self._default_bpa_res(), self._default_vol_eval()
        )
        self.assertIn("第 2 階段", stage)
        self.assertTrue(any("【趨勢結構】+2分" in f and "第 2 階段" in f for f in factors))

    def test_weinstein_stage_4_bear_decline(self):
        """Stage 4: MA20 < MA60, slope_ma20 < -0.3%, slope_ma60 <= 0 (-2 pts)."""
        df = self._create_base_df(60)
        df.loc[:55, "ma20"] = 100.0
        df.loc[59, "ma20"] = 95.0    # slope = -5% < -0.3%
        df.loc[:55, "ma60"] = 110.0
        df.loc[59, "ma60"] = 108.0   # slope = -1.8% <= 0, ma20 < ma60

        bpa_res = self._default_bpa_res()
        bpa_res["always_in_score"] = -2
        vol_eval = self._default_vol_eval()
        vol_eval["score"] = -2

        score, stage, factors = evaluate_professional_trend(
            df, pd.DataFrame(), bpa_res, vol_eval
        )
        self.assertIn("第 4 階段", stage)
        self.assertTrue(any("【趨勢結構】-2分" in f and "第 4 階段" in f for f in factors))

    def test_weinstein_stage_1_base_building(self):
        """Stage 1: slope_ma60 < 0 and MA20 < MA60 and slope_ma20 >= -0.2% (0 pts)."""
        df = self._create_base_df(60)
        df.loc[:55, "ma20"] = 80.0
        df.loc[59, "ma20"] = 80.0    # slope = 0 >= -0.2%
        df.loc[:55, "ma60"] = 100.0
        df.loc[59, "ma60"] = 98.0    # slope = -2% < 0, ma20 < ma60

        score, stage, factors = evaluate_professional_trend(
            df, pd.DataFrame(), self._default_bpa_res(), self._default_vol_eval()
        )
        self.assertIn("第 1 階段", stage)
        self.assertTrue(any("【趨勢結構】+0分" in f and "第 1 階段" in f for f in factors))

    def test_weinstein_stage_3_top_distribution(self):
        """Stage 3: Otherwise fallback (-1 pt)."""
        df = self._create_base_df(60)
        df.loc[54, "ma20"] = 105.0
        df.loc[59, "ma20"] = 102.0  # slope < 0
        df.loc[54, "ma60"] = 95.0
        df.loc[59, "ma60"] = 96.0

        score, stage, factors = evaluate_professional_trend(
            df, pd.DataFrame(), self._default_bpa_res(), self._default_vol_eval()
        )
        self.assertIn("第 3 階段", stage)
        self.assertTrue(any("【趨勢結構】-1分 | 第 3 階段" in f for f in factors))

    def test_ma_bias_bull_and_bear(self):
        """Short-term MA bias: close > ma5 & ma20 (+1) vs close < ma5 & ma20 (-1)."""
        df = self._create_base_df(60)
        # Bull (+1)
        df.loc[59, "close"] = 110.0
        df.loc[59, "ma5"] = 105.0
        df.loc[59, "ma20"] = 100.0
        _, _, factors = evaluate_professional_trend(
            df, pd.DataFrame(), self._default_bpa_res(), self._default_vol_eval()
        )
        self.assertTrue(any("【均線位階】+1分" in f for f in factors))

        # Bear (-1)
        df.loc[59, "close"] = 90.0
        df.loc[59, "ma5"] = 95.0
        df.loc[59, "ma20"] = 100.0
        _, _, factors = evaluate_professional_trend(
            df, pd.DataFrame(), self._default_bpa_res(), self._default_vol_eval()
        )
        self.assertTrue(any("【均線位階】-1分" in f for f in factors))

    def test_institutional_scoring(self):
        """Test Foreign & Trust buying/selling scores."""
        df = self._create_base_df(60)
        last_date = df["date"].iloc[-1]

        # Both positive (fini > 100 & trust > 50) -> +2 pts
        inst_df_bull = pd.DataFrame([{
            "date": last_date,
            "fini": 200,
            "trust": 100,
            "total": 300
        }])
        _, _, factors = evaluate_professional_trend(
            df, inst_df_bull, self._default_bpa_res(), self._default_vol_eval()
        )
        self.assertTrue(any("【法人籌碼】+2分" in f for f in factors))

        # Both negative (fini < -100 & trust < -50) -> -2 pts
        inst_df_bear = pd.DataFrame([{
            "date": last_date,
            "fini": -200,
            "trust": -100,
            "total": -300
        }])
        _, _, factors = evaluate_professional_trend(
            df, inst_df_bear, self._default_bpa_res(), self._default_vol_eval()
        )
        self.assertTrue(any("【法人籌碼】-2分" in f for f in factors))

        # Foreign massive single buy (fini > 500) -> +1 pt
        inst_df_fini = pd.DataFrame([{
            "date": last_date,
            "fini": 600,
            "trust": 10,
            "total": 610
        }])
        _, _, factors = evaluate_professional_trend(
            df, inst_df_fini, self._default_bpa_res(), self._default_vol_eval()
        )
        self.assertTrue(any("【法人籌碼】+1分" in f for f in factors))

    def test_rating_badge_thresholds(self):
        """Test get_rating_badge mapping."""
        self.assertIn("強烈多頭", get_rating_badge(6))
        self.assertIn("強烈多頭", get_rating_badge(8))
        self.assertIn("溫和偏多", get_rating_badge(3))
        self.assertIn("溫和偏多", get_rating_badge(5))
        self.assertIn("中性微多", get_rating_badge(1))
        self.assertIn("中性微多", get_rating_badge(2))
        self.assertIn("中立盤整", get_rating_badge(0))
        self.assertIn("中性微空", get_rating_badge(-1))
        self.assertIn("中性微空", get_rating_badge(-2))
        self.assertIn("溫和偏空", get_rating_badge(-3))
        self.assertIn("溫和偏空", get_rating_badge(-5))
        self.assertIn("強烈空頭", get_rating_badge(-6))
        self.assertIn("強烈空頭", get_rating_badge(-10))


# =====================================================================
# 3. Wyckoff / VPA Volume-Price Analysis Tests
# =====================================================================
class TestStrategyVolume(unittest.TestCase):
    def test_churn_detection(self):
        """CHURN (爆量滯漲): vol_ratio > 1.8 & upper shadow > 0.4*rng -> -1 pt."""
        df = pd.DataFrame({
            "open": [100.0, 102.0],
            "high": [102.0, 115.0],   # rng = 115 - 100 = 15
            "low": [98.0, 100.0],
            "close": [100.0, 103.0],  # upper_shadow = 115 - 103 = 12 (12/15 = 0.8 > 0.4)
            "volume": [1000.0, 2000.0],
            "vol_ma": [1000.0, 1000.0], # ratio = 2.0 > 1.8
            "ma20": [100.0, 100.0]
        })
        res = evaluate_volume_price(df)
        self.assertEqual(res["status_code"], "CHURN")
        self.assertEqual(res["score"], -1)

    def test_breakout_detection(self):
        """BREAKOUT (帶量突破): df['breakout'][-1] is True -> +2 pts."""
        df = pd.DataFrame({
            "open": [100.0, 105.0],
            "high": [102.0, 112.0],
            "low": [99.0, 104.0],
            "close": [101.0, 111.0],
            "volume": [1000.0, 2500.0],
            "vol_ma": [1000.0, 1000.0],
            "breakout": [False, True],
            "ma20": [100.0, 101.0]
        })
        res = evaluate_volume_price(df)
        self.assertEqual(res["status_code"], "BREAKOUT")
        self.assertEqual(res["score"], 2)

    def test_dryup_detection(self):
        """DRYUP (窒息量打底): vol_now < 0.45 * vol_ma20 -> 0 pts."""
        df = pd.DataFrame({
            "open": [100.0, 100.2],
            "high": [101.0, 100.5],
            "low": [99.0, 99.8],
            "close": [100.0, 100.1],
            "volume": [1000.0, 400.0],
            "vol_ma": [1000.0, 1000.0], # 400 < 450
            "ma20": [100.0, 100.0]
        })
        res = evaluate_volume_price(df)
        self.assertEqual(res["status_code"], "DRYUP")
        self.assertEqual(res["score"], 0)

    def test_bullish_expansion(self):
        """BULL_EXP (價量齊揚): chg > 0 and vol_ratio >= 1.25 -> +2 pts."""
        df = pd.DataFrame({
            "open": [100.0, 101.0],
            "high": [102.0, 106.0],
            "low": [99.0, 100.5],
            "close": [100.0, 105.0], # chg = +5%
            "volume": [1000.0, 1300.0],
            "vol_ma": [1000.0, 1000.0], # ratio = 1.3 >= 1.25
            "ma20": [100.0, 100.0]
        })
        res = evaluate_volume_price(df)
        self.assertEqual(res["status_code"], "BULL_EXP")
        self.assertEqual(res["score"], 2)

    def test_bullish_divergence(self):
        """BULL_DIV (量價背離): chg > 0 and vol_ratio <= 0.75 -> 0 pts."""
        df = pd.DataFrame({
            "open": [100.0, 101.0],
            "high": [102.0, 104.0],
            "low": [99.0, 100.5],
            "close": [100.0, 103.0], # chg > 0
            "volume": [1000.0, 700.0],
            "vol_ma": [1000.0, 1000.0], # ratio = 0.7 <= 0.75
            "ma20": [100.0, 100.0]
        })
        res = evaluate_volume_price(df)
        self.assertEqual(res["status_code"], "BULL_DIV")
        self.assertEqual(res["score"], 0)

    def test_bearish_expansion(self):
        """BEAR_EXP (放量重挫): chg < 0 and vol_ratio >= 1.25 -> -2 pts."""
        df = pd.DataFrame({
            "open": [100.0, 99.0],
            "high": [101.0, 99.5],
            "low": [98.0, 93.0],
            "close": [100.0, 94.0], # chg = -6%
            "volume": [1000.0, 1500.0],
            "vol_ma": [1000.0, 1000.0], # ratio = 1.5 >= 1.25
            "ma20": [100.0, 100.0]
        })
        res = evaluate_volume_price(df)
        self.assertEqual(res["status_code"], "BEAR_EXP")
        self.assertEqual(res["score"], -2)

    def test_bearish_ret_above_and_below_ma20(self):
        """BEAR_RET (價跌量縮): chg < 0 & vol_ratio <= 0.75 -> +1 if >= MA20 else -1."""
        # Above MA20 (+1)
        df_above = pd.DataFrame({
            "open": [100.0, 105.0],
            "high": [101.0, 105.5],
            "low": [98.0, 103.0],
            "close": [105.0, 103.5], # chg < 0
            "volume": [1000.0, 600.0],
            "vol_ma": [1000.0, 1000.0], # ratio = 0.6 <= 0.75
            "ma20": [100.0, 100.0] # close 103.5 >= ma20 100.0
        })
        res_above = evaluate_volume_price(df_above)
        self.assertEqual(res_above["status_code"], "BEAR_RET")
        self.assertEqual(res_above["score"], 1)

        # Below MA20 (-1)
        df_below = pd.DataFrame({
            "open": [100.0, 95.0],
            "high": [101.0, 95.5],
            "low": [98.0, 92.0],
            "close": [95.0, 93.0], # chg < 0
            "volume": [1000.0, 600.0],
            "vol_ma": [1000.0, 1000.0], # ratio = 0.6 <= 0.75
            "ma20": [100.0, 100.0] # close 93.0 < ma20 100.0
        })
        res_below = evaluate_volume_price(df_below)
        self.assertEqual(res_below["status_code"], "BEAR_RET")
        self.assertEqual(res_below["score"], -1)


# =====================================================================
# 4. Al Brooks Price Action (BPA) Strategy Tests
# =====================================================================
class TestStrategyBrooks(unittest.TestCase):
    def _create_bpa_df(self, n=30, close_base=100.0, trend_step=0.5):
        closes = [close_base + i * trend_step for i in range(n)]
        ema20 = closes
        return pd.DataFrame({
            "open": [c - 0.2 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "ema20": ema20,
            "bb_mid": closes,
            "bb_upper": [c + 5.0 for c in closes],
            "bb_lower": [c - 5.0 for c in closes],
            "bpa_ttr": [False] * n,
            "double_inside": [False] * n,
            "bull_rev_bar": [False] * n,
            "bear_rev_bar": [False] * n,
            "bpa_bar_type": ["普通K線(Trading Bar)"] * n,
            "bpa_h1": [False] * n,
            "bpa_h2": [False] * n,
            "bpa_h3": [False] * n,
            "bpa_l1": [False] * n,
            "bpa_l2": [False] * n,
            "bpa_l3": [False] * n,
            "bpa_ema_pb": [False] * n,
            "bpa_bull_gap": [False] * n,
            "bpa_bear_gap": [False] * n,
        })

    def test_always_in_long(self):
        """AIL: close > ema20 and slope > 0.15% -> score = 2."""
        df = self._create_bpa_df(n=30, close_base=100.0, trend_step=1.0)
        df["close"] = df["ema20"] + 1.0
        res = evaluate_brooks_price_action(df)
        self.assertIn("多頭主控", res["always_in_zh"])
        self.assertEqual(res["always_in_score"], 2)

    def test_always_in_short(self):
        """AIS: close < ema20 and slope < -0.15% -> score = -2."""
        df = self._create_bpa_df(n=30, close_base=100.0, trend_step=-1.0)
        df["close"] = df["ema20"] - 1.0
        res = evaluate_brooks_price_action(df)
        self.assertIn("空方主導", res["always_in_zh"])
        self.assertEqual(res["always_in_score"], -2)

    def test_trading_range_ttr(self):
        """Trading Range triggered by bpa_ttr = True -> score = 0."""
        df = self._create_bpa_df(n=30, close_base=100.0, trend_step=0.0)
        df.loc[29, "bpa_ttr"] = True
        res = evaluate_brooks_price_action(df)
        self.assertIn("箱型震盪", res["always_in_zh"])
        self.assertEqual(res["always_in_score"], 0)

    def test_h1_setup_validation(self):
        """H1 setup is valid in AIL or in TR when close <= bb_mid."""
        df = self._create_bpa_df(n=30, close_base=100.0, trend_step=1.0)
        df["close"] = df["ema20"] + 1.0
        df.loc[29, "bpa_h1"] = True
        df.loc[29, "high"] = 135.0
        df.loc[29, "low"] = 130.0
        df.loc[29, "close"] = 133.0
        res = evaluate_brooks_price_action(df)

        self.assertTrue(any("High 1 (H1)" in s for s in res["signals"]))
        # Price is 133.0 -> tick is 0.50
        # Buy Stop = high + tick = 135.0 + 0.50 = 135.50
        # Sell Stop = low - tick = 130.0 - 0.50 = 129.50
        # Risk = 135.50 - 129.50 = 6.00
        self.assertAlmostEqual(res["buy_stop"], 135.50, places=2)
        self.assertAlmostEqual(res["sell_stop"], 129.50, places=2)
        self.assertAlmostEqual(res["target_long_1r"], 141.50, places=2)
        self.assertAlmostEqual(res["target_long_2r"], 147.50, places=2)

    def test_l1_setup_validation(self):
        """L1 setup is valid in AIS or in TR when close >= bb_mid."""
        df = self._create_bpa_df(n=30, close_base=100.0, trend_step=-1.0)
        df["close"] = df["ema20"] - 1.0
        df.loc[29, "bpa_l1"] = True
        df.loc[29, "high"] = 75.0
        df.loc[29, "low"] = 70.0
        df.loc[29, "close"] = 70.5   # below ema20 (71.0)
        res = evaluate_brooks_price_action(df)

        self.assertTrue(any("Low 1 (L1)" in s for s in res["signals"]))
        # Price is 72.0 -> tick is 0.10
        # Buy Stop = high + tick = 75.0 + 0.10 = 75.10
        # Sell Stop = low - tick = 70.0 - 0.10 = 69.90
        # Risk = 75.10 - 69.90 = 5.20
        self.assertAlmostEqual(res["buy_stop"], 75.10, places=2)
        self.assertAlmostEqual(res["sell_stop"], 69.90, places=2)
        self.assertAlmostEqual(res["target_short_1r"], 64.70, places=2)
        self.assertAlmostEqual(res["target_short_2r"], 59.50, places=2)

    def test_h2_expiration_after_two_bars(self):
        """H2 pattern is only valid within last 1~2 bars (tail(2)), expiring if 3 bars ago."""
        # Case 1: H2 happened 3 bars ago (index 27 in 30 bars) -> should NOT trigger H2
        df_expired = self._create_bpa_df(n=30, close_base=100.0, trend_step=1.0)
        df_expired["close"] = df_expired["ema20"] + 1.0
        df_expired.loc[27, "bpa_h2"] = True
        res_expired = evaluate_brooks_price_action(df_expired)
        self.assertFalse(any("High 2 (H2)" in s for s in res_expired["signals"]))

        # Case 2: H2 happened 2 bars ago (index 28 in 30 bars) -> valid and triggers
        df_valid = self._create_bpa_df(n=30, close_base=100.0, trend_step=1.0)
        df_valid["close"] = df_valid["ema20"] + 1.0
        df_valid.loc[28, "bpa_h2"] = True
        res_valid = evaluate_brooks_price_action(df_valid)
        self.assertTrue(any("High 2 (H2)" in s for s in res_valid["signals"]))


# =====================================================================
# 5. Composite Rating & Decision Engine Tests
# =====================================================================
class TestRatingAndDecisions(unittest.TestCase):
    def _create_synthetic_rating_env(self, canslim_score=5, bpa_zh="多頭主控", inst_pos=True):
        n = 260
        base_price = 100.0
        closes = [base_price + i * 0.5 for i in range(n)]
        df = pd.DataFrame({
            "close": closes,
            "ema20": closes
        })
        bpa_res = {"always_in_zh": bpa_zh}
        vol_eval = {"score": 2}
        inst_df = pd.DataFrame([{"total": 500 if inst_pos else -500}] * 5)
        fundamentals = {
            "revenue_yoy": 25.0 if canslim_score >= 4 else -10.0,
            "eps_ttm": 3.5 if canslim_score >= 2 else -0.5,
            "gross_margin": 35.0 if canslim_score >= 1 else 15.0
        }
        return df, bpa_res, vol_eval, inst_df, fundamentals

    def test_composite_rating_full_bullish_score(self):
        """When Minervini passes 7/7, CANSLIM=5, BPA=多頭, Inst=+500, score should be 100."""
        df, bpa_res, vol_eval, inst_df, fundamentals = self._create_synthetic_rating_env()
        res = evaluate_composite_rating(df, bpa_res, vol_eval, inst_df, fundamentals, "2330", "tse")

        self.assertEqual(res["minervini_passed"], 7)
        self.assertEqual(res["canslim_grade"], "A+ 卓越")
        # Total score: (7/7)*35 + (5/5)*25 + 30 (bpa) + 10 (inst) = 100
        self.assertEqual(res["score"], 100)
        self.assertIn("Stage 2 主升", res["badge"])
        self.assertEqual(res["action_type"], "BUY")

    def test_adverse_hmm_regime_threshold_filter(self):
        """Under adverse HMM regime, BUY requires >= 85 points. Score < 85 drops to WAIT."""
        df, bpa_res, vol_eval, inst_df, fundamentals = self._create_synthetic_rating_env()

        # Adjust fundamentals to score = 80
        fundamentals["revenue_yoy"] = 10.0   # +1 instead of +2
        fundamentals["gross_margin"] = 20.0  # 0 instead of +1 -> c_score = 3 -> 15 pts
        # Minervini: 35 pts, BPA: 30 pts, Inst: 0 pts -> Total = 35 + 15 + 30 + 0 = 80
        inst_df_neg = pd.DataFrame([{"total": -100}] * 5)

        # Normal regime -> BUY
        res_normal = evaluate_composite_rating(
            df, bpa_res, vol_eval, inst_df_neg, fundamentals, "2330", "tse",
            regime_info={"is_adverse": False}
        )
        self.assertEqual(res_normal["score"], 80)
        self.assertEqual(res_normal["action_type"], "BUY")

        # Adverse regime -> WAIT (since score is 80 < 85)
        res_adverse = evaluate_composite_rating(
            df, bpa_res, vol_eval, inst_df_neg, fundamentals, "2330", "tse",
            regime_info={"is_adverse": True}
        )
        self.assertEqual(res_adverse["score"], 80)
        self.assertEqual(res_adverse["action_type"], "WAIT")
        self.assertIn("市況震盪", res_adverse["action_tag"])

        # Adverse regime with score >= 85 (e.g. Inst positive -> score = 90) -> BUY
        res_adverse_high = evaluate_composite_rating(
            df, bpa_res, vol_eval, pd.DataFrame([{"total": 100}] * 5), fundamentals, "2330", "tse",
            regime_info={"is_adverse": True}
        )
        self.assertEqual(res_adverse_high["score"], 90)
        self.assertEqual(res_adverse_high["action_type"], "BUY")

    def test_action_decision_hold_wait_sell(self):
        """Verify HOLD (>=70), WAIT (50~69), SELL (<50), and daily_bias output."""
        df, _, vol_eval, _, _ = self._create_synthetic_rating_env()

        # Score around 65: previously HOLD, now WAIT under Phase 1 (65~69 merged to WAIT)
        bpa_res_neutral = {"always_in_zh": "震盪盤整"}
        fund_65 = {"revenue_yoy": 10, "eps_ttm": 1.0, "gross_margin": 10}  # c_score=3 -> 15 pts
        # (7/7)*35 + 15 + 15 (bpa) + 0 = 65
        res_65 = evaluate_composite_rating(
            df, bpa_res_neutral, vol_eval, pd.DataFrame([{"total": -50}] * 5),
            fund_65, "2330", "tse"
        )
        self.assertEqual(res_65["score"], 65)
        self.assertEqual(res_65["action_type"], "WAIT")
        self.assertEqual(res_65["daily_bias"], "WAIT")

        # Score around 70: triggers HOLD (>=70)
        fund_70 = {"revenue_yoy": 25, "eps_ttm": 1.0, "gross_margin": 10}  # c_score=4 -> 20 pts
        # (7/7)*35 + 20 + 15 (bpa) + 0 = 70
        res_70 = evaluate_composite_rating(
            df, bpa_res_neutral, vol_eval, pd.DataFrame([{"total": -50}] * 5),
            fund_70, "2330", "tse"
        )
        self.assertEqual(res_70["score"], 70)
        self.assertEqual(res_70["action_type"], "HOLD")
        self.assertEqual(res_70["daily_bias"], "WAIT")
        self.assertEqual(res_70["suggested_hold_days"], 40)

        # SELL test: score < 50
        bpa_res_sell = {"always_in_zh": "空方主導"}
        fund_sell = {"revenue_yoy": -20, "eps_ttm": -1.0, "gross_margin": 5}  # c_score=-1 -> 0 pts
        df_bear = pd.DataFrame({
            "close": [200.0 - i * 0.5 for i in range(260)],
            "ema20": [200.0 - i * 0.5 for i in range(260)]
        })
        res_sell = evaluate_composite_rating(
            df_bear, bpa_res_sell, vol_eval, pd.DataFrame([{"total": -500}] * 5),
            fund_sell, "2330", "tse"
        )
        self.assertLess(res_sell["score"], 50)
        self.assertEqual(res_sell["action_type"], "SELL")
        self.assertEqual(res_sell["daily_bias"], "SELL")

    def test_anti_chase_rule(self):
        """Test anti-chase rule blocks entries when next open is > 1.5% above signal close."""
        # 1. Normal gap (< 1.5%): allowed
        res_ok = check_anti_chase(signal_close=100.0, next_open=101.0, max_chase_pct=1.5)
        self.assertTrue(res_ok["allow_entry"])
        self.assertAlmostEqual(res_ok["chase_pct"], 1.0)

        # 2. Excessive gap (> 1.5%): blocked
        res_blocked = check_anti_chase(signal_close=100.0, next_open=102.5, max_chase_pct=1.5)
        self.assertFalse(res_blocked["allow_entry"])
        self.assertAlmostEqual(res_blocked["chase_pct"], 2.5)
        self.assertIn("取消追高", res_blocked["reason"])


    @patch("yfinance.download", return_value=None)
    def test_composite_rating_insufficient_data_fallback(self, mock_yf):
        """When historical bars < 200 and yfinance fallback is empty, minervini_passed should be None and not fake 4."""
        df_short = pd.DataFrame({
            "close": [100.0 + i for i in range(50)],
            "ema20": [100.0 + i for i in range(50)]
        })
        bpa_res = {"always_in_zh": "多頭主控"}
        vol_eval = {"status": "NORMAL"}
        inst_df = pd.DataFrame([{"total": 100}] * 5)
        fundamentals = {"revenue_yoy": 20.0, "eps_ttm": 3.0, "gross_margin": 35.0}

        res = evaluate_composite_rating(
            df_short, bpa_res, vol_eval, inst_df, fundamentals, "9999", "tse"
        )
        self.assertIsNone(res["minervini_passed"])
        self.assertEqual(res["minervini_status"], "資料不足（無法評估）")
        self.assertEqual(res["minervini_color"], "#94a3b8")
        # Minervini gives 0 pts; c_score=5 -> 25 pts, bpa=30 pts, inst=10 pts -> Total = 65
        self.assertEqual(res["score"], 65)


# =====================================================================
# 6. Data Fetching & Realtime Fallback Tests
# =====================================================================
class TestDataFetch(unittest.TestCase):
    """Test data fetching tracks, Yahoo realtime fallback open handling."""

    @patch("requests.get")
    def test_yahoo_realtime_fallback_open_price(self, mock_get):
        """Verify Yahoo Finance fallback extracts quote.open[0] rather than chartPreviousClose."""
        from core.data_fetch import fetch_realtime_bar

        def fake_get(url, *args, **kwargs):
            m = unittest.mock.MagicMock()
            if "mis.twse.com.tw" in url:
                m.json.return_value = {"msgArray": []}
            elif "query1.finance.yahoo.com" in url:
                m.json.return_value = {
                    "chart": {
                        "result": [{
                            "meta": {
                                "regularMarketPrice": 985.0,
                                "regularMarketDayHigh": 990.0,
                                "regularMarketDayLow": 975.0,
                                "chartPreviousClose": 960.0,  # Yesterday close: MUST NOT be used!
                                "regularMarketVolume": 15000000
                            },
                            "indicators": {
                                "quote": [{
                                    "open": [978.0, 980.0, 982.0]  # True session open is 978.0!
                                }]
                            }
                        }]
                    }
                }
            return m

        mock_get.side_effect = fake_get

        bar = fetch_realtime_bar("2330", "tse")
        self.assertIsNotNone(bar)
        self.assertEqual(bar["close"], 985.0)
        self.assertEqual(bar["open"], 978.0, "Realtime open MUST be 978.0 from quote.open[0], NOT 960.0 from chartPreviousClose")
        self.assertEqual(bar["high"], 990.0)
        self.assertEqual(bar["low"], 975.0)


# =====================================================================
# 7. Static Quality & Pyflakes Check across core/ modules
# =====================================================================
class TestStaticQualityCore(unittest.TestCase):
    def test_pyflakes_all_core_files(self):
        """Zero undefined variable errors across all core package modules."""
        import io
        from pyflakes.api import checkPath
        from pyflakes.reporter import Reporter

        core_dir = os.path.join(os.path.dirname(__file__), "core")
        py_files = [
            os.path.join(core_dir, f)
            for f in os.listdir(core_dir)
            if f.endswith(".py")
        ]
        self.assertGreater(len(py_files), 5, "Core modules should be present")

        for filepath in py_files:
            stdout = io.StringIO()
            stderr = io.StringIO()
            reporter = Reporter(stdout, stderr)
            checkPath(filepath, reporter)
            out = stdout.getvalue() + stderr.getvalue()
            undefined = [l for l in out.splitlines() if "undefined name" in l]
            self.assertEqual(
                len(undefined), 0,
                f"Undefined names found in {filepath}:\n" + "\n".join(undefined)
            )


if __name__ == "__main__":
    unittest.main()
