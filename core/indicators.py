# -*- coding: utf-8 -*-
"""純數值指標計算：台股 tick 級距、ATR 波動度、波動度自適應風控停損價。"""
import pandas as pd
import numpy as np
from datetime import datetime

from core.constants import (
    TW_TZ, STOP_ATR_MULT, STOP_PCT_MIN, STOP_PCT_MAX,
    STOP_PCT_FALLBACK, STOP_PCT_DB_DEFAULT,
)

# 同一檔股票同一天的停損價快取（供 60 秒巡邏迴圈重複呼叫時避免重算）
_STOP_LEVEL_CACHE = {}


def get_tw_tick(price):
    """台股委託與升降單位（Tick Size）精確級距規則"""
    if price < 10:
        return 0.01
    elif price < 50:
        return 0.05
    elif price < 100:
        return 0.10
    elif price < 500:
        return 0.50
    elif price < 1000:
        return 1.00
    else:
        return 5.00

# ── 風控警戒價位（波動度自適應停損） ─────────────────────────
# 回測實證（2020-01~2026-06，28 檔、21,896 筆訊號）：
#   固定 -7% 停損在本系統的 BUY 訊號下為淨損失 —— 持有 60 日時有 53% 的交易被掃出場，
#   每筆平均報酬從不停損的 +9.83% 腰斬至 +6.54%；持有 20 日為 +2.69% vs +2.12%。
#   主因是台股個股 20 日內本來就有約 29% 機率隨機晃到 -7%（與訊號好壞無關）。
#   停損幅度掃描結果（每筆平均報酬，持有 60 日）：
#     -7% 6.54% < 2.0xATR 6.60% < 2.5xATR 7.60% < 3.0xATR 7.98% < 不設價格停損 9.83%
#   故改以 20 日 ATR 縮放，並限制上下界：低波動股不被雜訊掃出、高波動股不至於風控失效。
# （實際數值定義於 core.constants，此處匯入沿用，見檔案開頭 import）


def compute_atr_pct(df, period=20):
    """以 True Range 的 N 日均值除以現價，得到「每日波動佔股價的比例」"""
    if df is None or len(df) < 5:
        return None
    need = {"high", "low", "close"}
    if not need.issubset(df.columns):
        return None
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.tail(period).mean())
    close_now = float(df["close"].iloc[-1])
    if not np.isfinite(atr) or atr <= 0 or close_now <= 0:
        return None
    return atr / close_now




def compute_risk_stop(ticker, cost_price, market="tse", user_pct=None, analysis_res=None):
    """
    計算持倉的浮虧警戒價位（取代原本三處各自硬寫的 cost * 0.93）。

    回傳 (警戒價, 警戒幅度小數, 依據說明)：
      - user_pct 若為使用者自訂（不等於 STOP_PCT_DB_DEFAULT）則優先採用
      - 否則以 3 x ATR20 縮放，夾在 -8% ~ -15% 之間
      - 取不到 ATR 時退回 -7%
    同一檔股票同一天只計算一次（記憶體快取），供 60 秒巡邏迴圈重複呼叫。
    """
    cost_price = float(cost_price)
    if user_pct is not None:
        try:
            up = float(user_pct)
        except (TypeError, ValueError):
            up = STOP_PCT_DB_DEFAULT
        if abs(up - STOP_PCT_DB_DEFAULT) > 1e-6:
            pct = abs(up) / 100.0
            return round(cost_price * (1 - pct), 2), pct, f"使用者自訂 -{pct * 100:.1f}%"

    key = (str(ticker).strip(), datetime.now(TW_TZ).strftime("%Y-%m-%d"))
    if key in _STOP_LEVEL_CACHE:
        pct, basis = _STOP_LEVEL_CACHE[key]
    else:
        pct, basis = STOP_PCT_FALLBACK, f"固定 -{STOP_PCT_FALLBACK * 100:.0f}%（無法取得 ATR）"
        try:
            if analysis_res is not None:
                res = analysis_res
            else:
                # 延遲匯入以避免 core.analyzer <-> core.indicators 的循環匯入
                # （analyzer 在模組層級 import 本模組，本模組只在需要時才反向呼叫 analyzer）
                from core.analyzer import analyze_stock
                res = analyze_stock(ticker, months=12, generate_html=False,
                                     print_report=False, quick_mode=True)
            atr_pct = compute_atr_pct(res.get("df") if res else None)
            if atr_pct:
                pct = min(STOP_PCT_MAX, max(STOP_PCT_MIN, STOP_ATR_MULT * atr_pct))
                basis = f"{STOP_ATR_MULT:.0f}×ATR20（日波動 {atr_pct * 100:.2f}%）"
                # 僅在成功算出波動度時快取；暫時性失敗不鎖住整天的警戒價位
                _STOP_LEVEL_CACHE[key] = (pct, basis)
        except Exception as e:
            print(f"  [WARN] {ticker} 波動度停損計算失敗，沿用固定 -7%：{e}")
    return round(cost_price * (1 - pct), 2), pct, basis


