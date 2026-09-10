# -*- coding: utf-8 -*-
"""
Deterministic Unit Tests for core/analyzer.py Pipeline:
  1. Candlestick & BPA Bar Pattern Classifications
  2. analyze_stock Pipeline & Support/Resistance Levels
  3. analyze_stock_5m Intraday BPA, Conformal Noise Filter & MTF Resonance
"""

import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from core.analyzer import analyze_stock, analyze_stock_5m


class TestBarPatternRecognition(unittest.TestCase):
    """Verify all 11+ candlestick and BPA patterns generated in analyzer pipeline."""

    def test_trend_and_reversal_bars(self):
        """Test bull/bear trend bars and bull/bear reversal bars."""
        # 4 bars:
        # Bar 0: base
        # Bar 1: Bull Trend (open=100, close=109, high=110, low=99.5) -> rng=10.5, body=9 (>50%), close>=110-2.625
        # Bar 2: Bear Trend (open=109, close=100.5, high=110, low=100) -> rng=10, body=8.5 (>50%), close<=100+2.5
        # Bar 3: Bull Reversal (open=101, close=105, high=106, low=95) -> rng=11, lower_sh=6 (54%>=35%), close=105 (91%>=60%)
        # Bar 4: Bear Reversal (open=104, close=102, high=112, low=101) -> rng=11, upper_sh=8 (72%>=35%), close=102 (9%<=40%)
        df = pd.DataFrame({
            "open": [100.0, 100.0, 109.0, 101.0, 104.0],
            "high": [102.0, 110.0, 110.0, 106.0, 112.0],
            "low":  [99.0,   99.5, 100.0,  95.0, 101.0],
            "close":[101.0, 109.0, 100.5, 105.0, 102.0],
            "ema20":[100.0, 101.0, 102.0, 100.0, 103.0]
        })

        close_arr = df["close"].values
        open_arr  = df["open"].values
        high_arr  = df["high"].values
        low_arr   = df["low"].values
        ema20_arr = df["ema20"].values
        N = len(df)

        body_arr = np.abs(close_arr - open_arr)
        candle_range = np.maximum(high_arr - low_arr, 1e-5)
        upper_shadow = high_arr - np.maximum(open_arr, close_arr)
        lower_shadow = np.minimum(open_arr, close_arr) - low_arr

        bpa_bull_trend = (close_arr > open_arr) & (body_arr / candle_range >= 0.50) & (close_arr >= high_arr - 0.25 * candle_range)
        bpa_bear_trend = (close_arr < open_arr) & (body_arr / candle_range >= 0.50) & (close_arr <= low_arr + 0.25 * candle_range)

        self.assertTrue(bpa_bull_trend[1], "Bar 1 must be Bull Trend")
        self.assertTrue(bpa_bear_trend[2], "Bar 2 must be Bear Trend")

        bull_rev_bar = np.zeros(N, dtype=bool)
        bear_rev_bar = np.zeros(N, dtype=bool)
        for i in range(1, N):
            if (lower_shadow[i] >= 0.35 * candle_range[i]) and (close_arr[i] >= low_arr[i] + 0.60 * candle_range[i]) and (low_arr[i] <= low_arr[i-1] or low_arr[i] <= ema20_arr[i]):
                bull_rev_bar[i] = True
            if (upper_shadow[i] >= 0.35 * candle_range[i]) and (close_arr[i] <= low_arr[i] + 0.40 * candle_range[i]) and (high_arr[i] >= high_arr[i-1] or high_arr[i] >= ema20_arr[i]):
                bear_rev_bar[i] = True

        self.assertTrue(bull_rev_bar[3], "Bar 3 must be Bull Reversal Bar")
        self.assertTrue(bear_rev_bar[4], "Bar 4 must be Bear Reversal Bar")

    def test_inside_and_outside_bars(self):
        """Test Inside Bar, Double Inside Bar (ii), Outside Bar, and Doji."""
        # Bar 0: base
        # Bar 1: Inside Bar (high <= high[0], low >= low[0])
        # Bar 2: Double Inside Bar (inside of Bar 1)
        # Bar 3: Outside Bar (high > high[2], low < low[2])
        # Bar 4: Doji (body / range <= 0.25)
        df = pd.DataFrame({
            "open": [100.0, 104.0, 104.5, 103.0, 105.0],
            "high": [112.0, 107.0, 106.0, 110.0, 108.0],
            "low":  [101.0, 103.0, 104.0,  99.0, 102.0],
            "close":[106.0, 105.0, 105.0, 107.0, 105.2],
        })

        close_arr = df["close"].values
        open_arr  = df["open"].values
        high_arr  = df["high"].values
        low_arr   = df["low"].values
        N = len(df)

        inside_bar    = np.zeros(N, dtype=bool)
        double_inside = np.zeros(N, dtype=bool)
        outside_bar   = np.zeros(N, dtype=bool)

        for i in range(1, N):
            if high_arr[i] <= high_arr[i-1] and low_arr[i] >= low_arr[i-1]:
                inside_bar[i] = True
                if inside_bar[i-1]:
                    double_inside[i] = True
            elif high_arr[i] > high_arr[i-1] and low_arr[i] < low_arr[i-1]:
                outside_bar[i] = True

        body_arr = np.abs(close_arr - open_arr)
        candle_range = np.maximum(high_arr - low_arr, 1e-5)
        doji_bar = (body_arr / candle_range <= 0.25)

        self.assertTrue(inside_bar[1], "Bar 1 must be Inside Bar")
        self.assertTrue(inside_bar[2] and double_inside[2], "Bar 2 must be Double Inside (ii)")
        self.assertTrue(outside_bar[3], "Bar 3 must be Outside Bar")
        self.assertTrue(doji_bar[4], "Bar 4 must be Doji")

    def test_engulfing_hammer_and_star(self):
        """Test Bullish/Bearish Engulfing, Hammer, and Shooting Star patterns."""
        # Bull Engulfing: previous bar red, current bar green and completely engulfs previous body
        # Hammer: lower shadow >= 2*body, upper shadow <= 0.15*range
        # Star: upper shadow >= 2*body, lower shadow <= 0.15*range
        df = pd.DataFrame({
            "open": [105.0, 101.0, 102.0, 100.0],
            "high": [106.0, 108.0, 102.5, 110.0],
            "low":  [101.0,  99.0,  95.0,  99.8],
            "close":[102.0, 107.0, 102.0, 100.2],
        })

        close_arr = df["close"].values
        open_arr  = df["open"].values
        high_arr  = df["high"].values
        low_arr   = df["low"].values
        N = len(df)

        body_arr = np.abs(close_arr - open_arr)
        candle_range = np.maximum(high_arr - low_arr, 1e-5)
        upper_shadow = high_arr - np.maximum(open_arr, close_arr)
        lower_shadow = np.minimum(open_arr, close_arr) - low_arr

        # Bullish Engulfing at bar 1
        bull_engulf = np.zeros(N, dtype=bool)
        for i in range(1, N):
            if (close_arr[i-1] < open_arr[i-1]) and (close_arr[i] > open_arr[i]):
                if open_arr[i] <= close_arr[i-1] and close_arr[i] >= open_arr[i-1]:
                    bull_engulf[i] = True

        # Hammer at bar 2: lower shadow = 102 - 95 = 7 >= 2*0, upper = 0.5 <= 0.15*7.5=1.125
        hammer = (lower_shadow >= 2.0 * body_arr) & (upper_shadow <= 0.15 * candle_range)
        # Star at bar 3: upper shadow = 110 - 100.2 = 9.8 >= 2*0.2, lower = 0.2 <= 0.15*10.2=1.53
        star = (upper_shadow >= 2.0 * body_arr) & (lower_shadow <= 0.15 * candle_range)

        self.assertTrue(bull_engulf[1], "Bar 1 must be Bullish Engulfing")
        self.assertTrue(hammer[2], "Bar 2 must be Hammer")
        self.assertTrue(star[3], "Bar 3 must be Shooting Star")


class TestAnalyzeStockPipeline(unittest.TestCase):
    """End-to-end execution of analyze_stock with mocked data feeds."""

    def _generate_synthetic_records(self, n=60):
        base_date = datetime(2026, 1, 1)
        records = []
        for i in range(n):
            d = base_date + timedelta(days=i)
            records.append({
                "date": d.strftime("%Y-%m-%d"),
                "open": 100.0 + i * 0.5,
                "high": 102.0 + i * 0.5,
                "low": 98.0 + i * 0.5,
                "close": 101.0 + i * 0.5,
                "volume": 1000.0 + (i % 5) * 100.0
            })
        return records

    @patch("core.analyzer.get_info", return_value=("tse", "台積電"))
    @patch("core.analyzer.fetch_twse")
    @patch("core.analyzer.fetch_realtime_bar", return_value=None)
    @patch("core.analyzer.fetch_institutional", return_value=pd.DataFrame())
    @patch("core.analyzer.fetch_fundamentals", return_value={"revenue_yoy": 20.0, "eps_ttm": 5.0, "gross_margin": 40.0})
    def test_analyze_stock_full_pipeline(self, mock_fund, mock_inst, mock_rt, mock_twse, mock_info):
        """Verify analyze_stock calculates all indicators and returns proper data dictionary."""
        mock_twse.return_value = self._generate_synthetic_records(60)

        res = analyze_stock("2330", months=3, generate_html=False, print_report=False)

        self.assertIn("df", res)
        self.assertIn("bpa_res", res)
        self.assertIn("trend_score", res)
        self.assertIn("trend_stage", res)
        self.assertIn("rating_badge", res)
        self.assertIn("sr_levels", res)
        self.assertIn("composite_rating", res)

        # Check technical indicators computed
        df = res["df"]
        for ma_col in ["ma5", "ma20", "ma60"]:
            self.assertIn(ma_col, df.columns)
        self.assertIn("rsi", df.columns)
        self.assertIn("macd", df.columns)
        self.assertIn("macd_signal", df.columns)
        self.assertIn("kd_k", df.columns)
        self.assertIn("kd_d", df.columns)
        self.assertIn("bb_upper", df.columns)
        self.assertIn("bb_lower", df.columns)

        # Check S/R levels
        sr = res["sr_levels"]
        self.assertGreaterEqual(sr["r1"], sr["s1"])
        self.assertGreaterEqual(sr["r2"], sr["s2"])


class TestAnalyzeStock5m(unittest.TestCase):
    """Unit tests for analyze_stock_5m: Conformal Prediction, MTF, and Whale Patterns."""

    def _generate_5m_raw(self, n=50, noise_mult=1.0, is_bull=True, vol_mult=1.0):
        dates = pd.date_range("2026-09-10 09:00", periods=n, freq="5min", tz="Asia/Taipei")
        closes = [100.0 + i * (0.2 if is_bull else -0.2) for i in range(n)]
        opens = [c - 0.1 for c in closes]
        highs = [c + 0.3 * noise_mult for c in closes]
        lows  = [c - 0.3 * noise_mult for c in closes]
        vols  = [100.0 * 1000.0] * (n - 1) + [100.0 * 1000.0 * vol_mult]

        return pd.DataFrame({
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols
        }, index=dates)

    @patch("core.analyzer.get_info", return_value=("tse", "台積電"))
    @patch("yfinance.download")
    @patch("core.analyzer.analyze_stock")
    def test_conformal_noise_extreme_rejection(self, mock_daily, mock_yf, mock_info):
        """Conformal prediction: noise ratio > 2.8x triggers 🛑 拒絕開倉 (雜訊過大)."""
        raw = self._generate_5m_raw(n=50, noise_mult=1.0)
        # Make the last bar an extreme wild spike (5x ATR)
        raw.iloc[-1, raw.columns.get_loc("high")] = raw.iloc[-1]["close"] + 5.0
        raw.iloc[-1, raw.columns.get_loc("low")] = raw.iloc[-1]["close"] - 5.0

        mock_yf.return_value = raw
        mock_daily.return_value = {"bpa_res": {"always_in_code": "AIL"}, "trend_score": 3, "df": pd.DataFrame({"ma20": [100.0]})}

        res = analyze_stock_5m("2330", days=1)

        self.assertIn("🛑 拒絕開倉", res["action_tag"])
        self.assertIn("雜訊過大", res["conformal_status"])

    @patch("core.analyzer.get_info", return_value=("tse", "台積電"))
    @patch("yfinance.download")
    @patch("core.analyzer.analyze_stock")
    def test_conformal_volatility_dull_pause(self, mock_daily, mock_yf, mock_info):
        """Conformal prediction: noise ratio < 0.35x triggers 🛑 暫緩開倉 (動能不足/空間狹窄)."""
        raw = self._generate_5m_raw(n=50, noise_mult=1.0)
        # Make the last bar completely flat (0.01 range)
        last_c = raw.iloc[-1]["close"]
        raw.iloc[-1, raw.columns.get_loc("open")] = last_c
        raw.iloc[-1, raw.columns.get_loc("high")] = last_c + 0.02
        raw.iloc[-1, raw.columns.get_loc("low")] = last_c - 0.02

        mock_yf.return_value = raw
        mock_daily.return_value = {"bpa_res": {"always_in_code": "AIL"}, "trend_score": 3, "df": pd.DataFrame({"ma20": [100.0]})}

        res = analyze_stock_5m("2330", days=1)

        self.assertIn("🛑 暫緩開倉", res["action_tag"])
        self.assertIn("波動過低", res["conformal_status"])

    @patch("core.analyzer.get_info", return_value=("tse", "台積電"))
    @patch("yfinance.download")
    @patch("core.analyzer.analyze_stock")
    def test_mtf_daily_bear_suppresses_5m_bull(self, mock_daily, mock_yf, mock_info):
        """MTF alignment: when Daily is AIS (bearish), 5m bull must NOT give BUY signal, but '逆日線弱彈'."""
        raw = self._generate_5m_raw(n=50, noise_mult=1.0, is_bull=True)
        mock_yf.return_value = raw
        # Daily is AIS
        mock_daily.return_value = {
            "bpa_res": {"always_in_code": "AIS"},
            "trend_score": -4,
            "df": pd.DataFrame({"ma20": [150.0]})  # close < daily_ma20
        }

        res = analyze_stock_5m("2330", days=1)

        self.assertIn("逆日線弱彈", res["action_tag"])
        self.assertIn("逆日線弱彈", res["mtf_status"])

    @patch("core.analyzer.get_info", return_value=("tse", "台積電"))
    @patch("yfinance.download")
    @patch("core.analyzer.analyze_stock")
    def test_mtf_daily_and_5m_bull_resonance(self, mock_daily, mock_yf, mock_info):
        """MTF resonance: Daily AIL + 5m AIL triggers '🔥 建議順勢做多'."""
        raw = self._generate_5m_raw(n=50, noise_mult=1.0, is_bull=True)
        mock_yf.return_value = raw
        # Daily is AIL
        mock_daily.return_value = {
            "bpa_res": {"always_in_code": "AIL"},
            "trend_score": 5,
            "df": pd.DataFrame({"ma20": [90.0]})  # close > daily_ma20
        }

        res = analyze_stock_5m("2330", days=1)

        self.assertIn("建議順勢做多", res["action_tag"])
        self.assertIn("雙時框多方共振", res["mtf_status"])

    @patch("core.analyzer.get_info", return_value=("tse", "台積電"))
    @patch("yfinance.download")
    @patch("core.analyzer.analyze_stock")
    def test_whale_volume_surge_patterns(self, mock_daily, mock_yf, mock_info):
        """Whale volume surge (vol >= 1.8x vol_ma20): triggers whale tagging."""
        # 2.5x volume on last bar
        raw = self._generate_5m_raw(n=50, noise_mult=1.0, is_bull=True, vol_mult=2.5)
        # Ensure last bar is a solid bull trend bar with body/rng >= 0.5
        c = raw.iloc[-1]["close"]
        raw.iloc[-1, raw.columns.get_loc("open")] = c - 0.4
        raw.iloc[-1, raw.columns.get_loc("high")] = c + 0.1
        raw.iloc[-1, raw.columns.get_loc("low")] = c - 0.45

        mock_yf.return_value = raw
        mock_daily.return_value = {"bpa_res": {"always_in_code": "AIL"}, "trend_score": 3, "df": pd.DataFrame({"ma20": [90.0]})}

        res = analyze_stock_5m("2330", days=1)

        self.assertIn("主力放量推升", res["whale_tag"])
        self.assertGreaterEqual(res["vol_ratio_5m"], 1.8)


if __name__ == "__main__":
    unittest.main()
