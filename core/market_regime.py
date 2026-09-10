# -*- coding: utf-8 -*-
"""
core/market_regime.py - 大盤體系狀態與熊市防禦過濾器 (Market Regime Filter)
--------------------------------------------------------------------------
職責：
  1. 追蹤台灣加權指數（^TWII）季線（60 MA）與月線（20 MA）之宏觀趨勢。
  2. 當大盤跌破季線且季線下彎時，判定為「熊市/空頭防禦環境（is_market_bear = True）」。
  3. 驅動全系統啟動熊市防禦模式：
     - BUY 建議門檻從 80 分提升至 85 分（寧缺勿濫）。
     - 風控停損從 3xATR (8~15%) 收縮為 2xATR (5~8%)，嚴防深度套牢。
  4. 內建 10 分鐘記憶體快取，避免重複查詢加權指數。
"""

import time
import logging
from datetime import datetime
import pandas as pd
import yfinance as yf

from core.constants import TW_TZ

logger = logging.getLogger("market_regime")

# 記憶體快取 (10 分鐘有效)
_REGIME_CACHE = {}
_REGIME_CACHE_TTL = 600  # 秒


def get_market_regime_status(force_refresh: bool = False) -> dict:
    """
    取得台股大盤環境狀態。
    回傳字典：
      {
        "is_market_bear": bool,       # 是否處於熊市防禦模式
        "market_score": int,          # 大盤健康度評分 (0~100)
        "twii_close": float,          # 當前加權指數收盤/現價
        "twii_ma20": float,           # 加權指數月線
        "twii_ma60": float,           # 加權指數季線
        "twii_ma60_slope": float,     # 季線 10 日斜率 (%)
        "status_desc": str            # 大盤狀態文字摘要
      }
    """
    now_ts = time.time()
    if not force_refresh and "data" in _REGIME_CACHE:
        cached_time, cached_val = _REGIME_CACHE["data"]
        if now_ts - cached_time < _REGIME_CACHE_TTL:
            return cached_val

    # 預設中性/多頭狀態（若無網路或無法抓取時之保底）
    fallback_res = {
        "is_market_bear": False,
        "market_score": 70,
        "twii_close": 0.0,
        "twii_ma20": 0.0,
        "twii_ma60": 0.0,
        "twii_ma60_slope": 0.0,
        "status_desc": "大盤數據離線（維持常態多頭風控）"
    }

    try:
        raw = yf.download("^TWII", period="6mo", progress=False, timeout=8)
        if raw is None or raw.empty:
            _REGIME_CACHE["data"] = (now_ts, fallback_res)
            return fallback_res

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = raw.reset_index()
        df.columns = [c.lower() for c in df.columns]

        if len(df) < 65:
            _REGIME_CACHE["data"] = (now_ts, fallback_res)
            return fallback_res

        c = df["close"]
        ma20 = c.rolling(20).mean().iloc[-1]
        ma60 = c.rolling(60).mean().iloc[-1]
        ma60_10d_ago = c.rolling(60).mean().iloc[-11]
        c_now = float(c.iloc[-1])

        ma60_slope = (ma60 - ma60_10d_ago) / (ma60_10d_ago + 1e-9) * 100

        # 空頭/熊市判定標準：
        # 1. 現價跌破 60 MA 達 1% 以上，且 60 MA 下彎 (slope < 0)
        # 2. 或現價大幅跌破 60 MA 達 3% 以上
        is_bear = (c_now < ma60 * 0.99 and ma60_slope < 0) or (c_now < ma60 * 0.97)

        if is_bear:
            status_desc = f"🔴 大盤空方承壓（加權指數 {c_now:,.0f} 跌破季線 {ma60:,.0f}，啟動熊市防禦模式）"
            m_score = 35
        elif c_now > ma60 and ma60_slope > 0:
            status_desc = f"🟢 大盤多方主控（加權指數 {c_now:,.0f} 站穩季線 {ma60:,.0f}，維持波段進攻）"
            m_score = 85
        else:
            status_desc = f"🟡 大盤高檔震盪（加權指數 {c_now:,.0f} 圍繞季線整理）"
            m_score = 60

        result = {
            "is_market_bear": bool(is_bear),
            "market_score": m_score,
            "twii_close": round(c_now, 2),
            "twii_ma20": round(float(ma20), 2),
            "twii_ma60": round(float(ma60), 2),
            "twii_ma60_slope": round(float(ma60_slope), 2),
            "status_desc": status_desc
        }

        _REGIME_CACHE["data"] = (now_ts, result)
        return result

    except Exception as e:
        logger.warning(f"加權指數行情獲取異常: {e}")
        _REGIME_CACHE["data"] = (now_ts, fallback_res)
        return fallback_res
