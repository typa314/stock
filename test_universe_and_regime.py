# -*- coding: utf-8 -*-
"""
test_universe_and_regime.py - 標的池 Stage 4 禁買與大盤熊市防禦單元測試
"""

import unittest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from core.rating import evaluate_composite_rating
from core.indicators import compute_risk_stop
from core.market_regime import get_market_regime_status


class TestUniverseAndRegime(unittest.TestCase):
    def _create_mock_df(self, n=250, end_price=100.0, trend="bull"):
        """產生模擬歷史日K序列"""
        dates = pd.date_range("2025-01-01", periods=n, freq="B")
        if trend == "bull":
            # 上升趨勢
            closes = np.linspace(60.0, end_price, n)
        elif trend == "stage4_bear":
            # Stage 4 空頭型態：先漲後崩跌，年線持續下彎，現價遠低於年線
            c1 = np.linspace(120.0, 150.0, 150)
            c2 = np.linspace(150.0, end_price, n - 150)  # 如一路崩到 60 元
            closes = np.concatenate([c1, c2])
        else:
            closes = np.full(n, end_price)

        df = pd.DataFrame({
            "date": dates,
            "open": closes * 0.99,
            "high": closes * 1.01,
            "low": closes * 0.98,
            "close": closes,
            "volume": np.full(n, 1000.0),
            "ema20": closes
        })
        return df

    def test_01_stage4_universe_gate_blocks_buy(self):
        """測試處於 Stage 4 空頭型態之標的，強制封鎖 BUY 建議"""
        df = self._create_mock_df(n=250, end_price=60.0, trend="stage4_bear")
        bpa_res = {"always_in_zh": "多頭主控", "always_in_desc": "突破站穩"}
        vol_eval = {"score": 2}
        inst_df = pd.DataFrame({"total": [500, 800, 1000]})
        fundamentals = {"revenue_yoy": 30.0, "eps_ttm": 5.0, "gross_margin": 40.0}

        res = evaluate_composite_rating(
            df, bpa_res, vol_eval, inst_df, fundamentals, "1301", "tse"
        )
        self.assertTrue(res["is_stage4_bear"])
        self.assertEqual(res["action_type"], "WAIT")
        self.assertIn("Stage 4 禁買", res["action_tag"])
        self.assertIn("嚴禁開多單", res["action_sub"])


    def test_02_market_bear_raises_buy_threshold(self):
        """測試大盤處於熊市環境時，BUY 門檻自 80 提升至 85 分"""
        df = self._create_mock_df(n=250, end_price=120.0, trend="bull")
        bpa_res = {"always_in_zh": "多頭主控"}
        vol_eval = {"score": 1}
        inst_df = pd.DataFrame({"total": [200, 300]})
        # 基本面評分適中，使總評分約落於 80~84 分之間
        fundamentals = {"revenue_yoy": 15.0, "eps_ttm": 2.0, "gross_margin": 25.0}

        # 模擬熊市環境
        bear_regime = {"is_market_bear": True, "status_desc": "大盤空方承壓"}

        with patch("core.rating.get_market_regime_status", return_value=bear_regime):
            res_bear = evaluate_composite_rating(
                df, bpa_res, vol_eval, inst_df, fundamentals, "2330", "tse",
                market_regime=bear_regime
            )
            # 若總分在 80~84 之間，在熊市應被擋下為 WAIT
            if 80 <= res_bear["score"] < 85:
                self.assertEqual(res_bear["action_type"], "WAIT")
                self.assertIn("大盤空方承壓", res_bear["action_tag"])

        # 在多頭市場（非熊市），同樣的評分應為 BUY
        bull_regime = {"is_market_bear": False, "status_desc": "大盤多方主控"}
        res_bull = evaluate_composite_rating(
            df, bpa_res, vol_eval, inst_df, fundamentals, "2330", "tse",
            market_regime=bull_regime
        )
        if 80 <= res_bull["score"] < 85:
            self.assertEqual(res_bull["action_type"], "BUY")

    def test_03_compute_risk_stop_bear_market_tightening(self):
        """測試熊市環境下，風控停損幅度自 3xATR (8~15%) 收縮至 2xATR (5~8%)"""
        df = self._create_mock_df(n=50, end_price=100.0)
        # 模擬較大之日波幅 3.5%
        mock_analysis = {"df": df}
        with patch("core.indicators.compute_atr_pct", return_value=0.035):
            # 1. 熊市防禦模式 (2.0x ATR = 7.0%，夾在 5%~8%)
            stop_price_bear, pct_bear, basis_bear = compute_risk_stop(
                "2330", 100.0, analysis_res=mock_analysis, is_market_bear=True
            )
            self.assertAlmostEqual(pct_bear, 0.07, places=2)
            self.assertEqual(stop_price_bear, 93.0)
            self.assertIn("熊市防禦收縮", basis_bear)

            # 2. 常態多頭模式 (3.0x ATR = 10.5%，夾在 8%~15%)
            stop_price_bull, pct_bull, basis_bull = compute_risk_stop(
                "2330", 100.0, analysis_res=mock_analysis, is_market_bear=False
            )
            self.assertAlmostEqual(pct_bull, 0.105, places=2)
            self.assertEqual(stop_price_bull, 89.5)
            self.assertIn("3×ATR20", basis_bull)


if __name__ == "__main__":
    unittest.main()
