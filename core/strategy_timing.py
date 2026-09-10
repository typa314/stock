# -*- coding: utf-8 -*-
"""60分K 時機層評估模組（Timing Layer）：
在日K 方向層許可（daily_bias == 'BUY_CANDIDATE'）的前提下，
透過 60 分鐘 K 線捕捉最佳波段進場時機與初始防守停損價位。

核心方案：
  - 方案 A（優先）：回測 20 EMA 守穩確認（量縮回踩或下影線拒絕）
  - 方案 B：H1 / H2 推動過前高確認
  - 方案 C：盤整區間帶量突破（量增 >= 1.3x）
嚴格遵循 Zero Speculation 與技術術語必附具體價位原則。
"""
from typing import Optional, Dict, Any, List
import pandas as pd
from core.indicators import get_tw_tick


def evaluate_60m_timing(
    df_60m: pd.DataFrame,
    daily_bias: str = "BUY_CANDIDATE",
    daily_ema20: Optional[float] = None,
    daily_key_support: Optional[float] = None,
    preferred_scheme: str = "A"
) -> Dict[str, Any]:
    """
    評估 60 分鐘 K 線進場時機與初始防守位。

    參數：
      df_60m: 包含 60 分鐘 K 線數據之 DataFrame（需有 open, high, low, close, volume）
      daily_bias: 日K 方向層許可證（'BUY_CANDIDATE' | 'WAIT' | 'SELL'）
      daily_ema20: 日K 20 EMA 關鍵支撐價位（選填）
      daily_key_support: 日K 波段前低或重要支撐價位（選填）
      preferred_scheme: 偏好方案 ('A': 回測20EMA守穩, 'B': H1/H2, 'C': 帶量突破, 'ALL': 綜合判定)

    回傳：
      dict 包含 timing_signal, scheme, entry_ref, stop_ref, risk_pct, target_1r, target_2r, reason, signals 等
    """
    # ── 1. 長週期定方向：日K 許可證硬門檻 ──
    if daily_bias != "BUY_CANDIDATE":
        return {
            "timing_signal": "NONE",
            "scheme": None,
            "entry_ref": None,
            "stop_ref": None,
            "risk_pct": None,
            "target_1r": None,
            "target_2r": None,
            "is_valid": False,
            "reason": f"日K 方向層未達買入許可（當前狀態: {daily_bias}），依多時間框架紀律，嚴禁短週期逆勢開多！",
            "signals": []
        }

    # ── 2. 資料完備性檢驗 ──
    if df_60m is None or len(df_60m) < 5:
        return {
            "timing_signal": "NONE",
            "scheme": None,
            "entry_ref": None,
            "stop_ref": None,
            "risk_pct": None,
            "target_1r": None,
            "target_2r": None,
            "is_valid": False,
            "reason": "60分K 資料長度不足（至少需 5 根以上），暫無法進行時機研判",
            "signals": []
        }

    df = df_60m.copy()
    c = df["close"].astype(float)
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    v = df["volume"].astype(float)

    # 確保 20 EMA 與 20 均量
    if "ema20" not in df.columns:
        df["ema20"] = c.ewm(span=20, adjust=False).mean()
    if "vol_ma20" not in df.columns:
        df["vol_ma20"] = v.rolling(20, min_periods=1).mean()

    ema20_now = float(df["ema20"].iloc[-1])
    vol_ma20_now = float(df["vol_ma20"].iloc[-1])
    close_now = float(c.iloc[-1])
    open_now = float(o.iloc[-1])
    high_now = float(h.iloc[-1])
    low_now = float(l.iloc[-1])
    vol_now = float(v.iloc[-1])

    prev_close = float(c.iloc[-2])
    prev_open = float(o.iloc[-2])
    prev_high = float(h.iloc[-2])
    prev_low = float(l.iloc[-2])
    prev_ema20 = float(df["ema20"].iloc[-2])

    tick = get_tw_tick(close_now)

    # ── 3. 日K 結構破壞即刻失效過濾（Exit Alert） ──
    if daily_ema20 is not None and close_now < daily_ema20:
        return {
            "timing_signal": "EXIT_ALERT",
            "scheme": None,
            "entry_ref": None,
            "stop_ref": None,
            "risk_pct": None,
            "target_1r": None,
            "target_2r": None,
            "is_valid": False,
            "reason": f"60分K 收盤價（{close_now:.2f} 元）跌破日K 20 EMA 關鍵防守線（{daily_ema20:.2f} 元），結構轉弱，觸發警示！",
            "signals": [f"跌破日K 20 EMA（{daily_ema20:.2f} 元）"]
        }
    if daily_key_support is not None and close_now < daily_key_support:
        return {
            "timing_signal": "EXIT_ALERT",
            "scheme": None,
            "entry_ref": None,
            "stop_ref": None,
            "risk_pct": None,
            "target_1r": None,
            "target_2r": None,
            "is_valid": False,
            "reason": f"60分K 收盤價（{close_now:.2f} 元）跌破日K 波段支撐低點（{daily_key_support:.2f} 元），觸發風控警示！",
            "signals": [f"跌破日K 關鍵支撐（{daily_key_support:.2f} 元）"]
        }

    # ── 4. 單根 K 線形態計算 ──
    rng_now = max(high_now - low_now, 1e-4)
    body_now = abs(close_now - open_now)
    lower_sh_now = min(open_now, close_now) - low_now
    upper_sh_now = high_now - max(open_now, close_now)
    lower_ratio_now = lower_sh_now / rng_now
    upper_ratio_now = upper_sh_now / rng_now

    rng_prev = max(prev_high - prev_low, 1e-4)
    lower_sh_prev = min(prev_open, prev_close) - prev_low
    lower_ratio_prev = lower_sh_prev / rng_prev

    vol_ratio_now = vol_now / (vol_ma20_now + 1e-9)

    # 爆量長上影出貨檢驗（滯漲硬攔截）
    is_churn = (vol_ratio_now > 1.8) and (upper_ratio_now > 0.40 or body_now / rng_now < 0.25)
    if is_churn and close_now <= open_now:
        return {
            "timing_signal": "NONE",
            "scheme": None,
            "entry_ref": None,
            "stop_ref": None,
            "risk_pct": None,
            "target_1r": None,
            "target_2r": None,
            "is_valid": False,
            "reason": f"60分K 爆量（{vol_ratio_now*100:.0f}% 均量）且留長上影線（{upper_ratio_now*100:.0f}% 振幅），有高檔出貨嫌疑，取消進場！",
            "signals": ["60分K 爆量滯漲警戒"]
        }

    # ── 5. 時機方案檢驗 ──
    signals: List[str] = []

    # ── 方案 A：回測 20 EMA 守穩確認（優先主推） ──
    # 條件 1：當根或前根低點回踩 60分K 20 EMA（容差約 +0.3% 且不深跌破 -1.5%）
    touch_now = (low_now <= ema20_now * 1.003) and (low_now >= ema20_now * 0.985)
    touch_prev = (prev_low <= prev_ema20 * 1.003) and (prev_low >= prev_ema20 * 0.985)
    ema_tested = touch_now or touch_prev

    # 條件 2：收盤重新站穩 20 EMA 之上
    reclaimed = close_now >= ema20_now

    # 條件 3：當根或前根出現下影線拒絕（>= 35%）或多頭趨勢棒（收上半部）
    bull_bar_now = (close_now > open_now) and ((close_now - low_now) / rng_now >= 0.55)
    has_rejection = (lower_ratio_now >= 0.35) or (lower_ratio_prev >= 0.35) or bull_bar_now

    # 條件 4：量能未出現恐慌或爆量出貨（量比 <= 1.6 或多頭實體放量推進）
    vol_ok_a = (vol_ratio_now <= 1.6) or (bull_bar_now and close_now >= prev_high)

    if preferred_scheme in ("A", "ALL") and ema_tested and reclaimed and has_rejection and vol_ok_a:
        # 停損設在回測波段低點或 20 EMA 下方 1 Tick
        pattern_low = min(low_now, prev_low, ema20_now)
        stop_ref = round(pattern_low - tick, 2)
        entry_ref = round(close_now, 2)
        risk = round(entry_ref - stop_ref, 2)
        risk_pct = round(risk / entry_ref * 100, 2) if entry_ref > 0 else 0.0
        target_1r = round(entry_ref + risk, 2)
        target_2r = round(entry_ref + 2 * risk, 2)

        signals.append(f"60分K 順勢回測 20 EMA（{ema20_now:.2f} 元）守穩確認")
        reason = (
            f"日K 方向偏多許可下，60分K 成功回測 20 EMA（{ema20_now:.2f} 元）並守穩收紅 "
            f"（當根收 {close_now:.2f} 元，下影線比率 {lower_ratio_now*100:.1f}%），"
            f"建議進場參考價: {entry_ref:.2f} 元，"
            f"做多防守停損 {stop_ref:.2f} 元 (跌破下方認賠，風險 {risk_pct:.2f}%)，"
            f"目標一價位 (1R 等距達標): {target_1r:.2f} 元，目標二價位 (2R): {target_2r:.2f} 元。"
        )

        return {
            "timing_signal": "ENTER_LONG",
            "scheme": "SCHEME_A_PULLBACK_EMA20",
            "entry_ref": entry_ref,
            "stop_ref": stop_ref,
            "risk_pct": risk_pct,
            "target_1r": target_1r,
            "target_2r": target_2r,
            "is_valid": True,
            "reason": reason,
            "signals": signals
        }

    # ── 方案 B：H1 / H2 推動過前高確認 ──
    # 前一根有回檔（高點降低），當根突破前一根高點且收盤站上前高
    is_h_trigger = (close_now > prev_high) and (close_now >= ema20_now)
    if preferred_scheme in ("B", "ALL") and is_h_trigger and (vol_ratio_now >= 0.8):
        stop_ref = round(min(low_now, prev_low) - tick, 2)
        entry_ref = round(close_now, 2)
        risk = round(entry_ref - stop_ref, 2)
        risk_pct = round(risk / entry_ref * 100, 2) if entry_ref > 0 else 0.0
        target_1r = round(entry_ref + risk, 2)
        target_2r = round(entry_ref + 2 * risk, 2)

        signals.append(f"60分K 出現多頭推動突破前高（前高: {prev_high:.2f} 元）")
        reason = (
            f"60分K 出現順勢推動買點，收盤價（{close_now:.2f} 元）站上 20 EMA（{ema20_now:.2f} 元）並突破前根高點（{prev_high:.2f} 元），"
            f"建議進場參考價: {entry_ref:.2f} 元，"
            f"做多防守停損 {stop_ref:.2f} 元 (跌破下方認賠，風險 {risk_pct:.2f}%)，"
            f"目標一價位 (1R 等距達標): {target_1r:.2f} 元。"
        )

        return {
            "timing_signal": "ENTER_LONG",
            "scheme": "SCHEME_B_H_PUSH",
            "entry_ref": entry_ref,
            "stop_ref": stop_ref,
            "risk_pct": risk_pct,
            "target_1r": target_1r,
            "target_2r": target_2r,
            "is_valid": True,
            "reason": reason,
            "signals": signals
        }

    # ── 方案 C：盤整區間帶量突破（突破近 8~12 根 60分高點且量增 >= 1.3x） ──
    if len(df) >= 10:
        high_range = float(h.iloc[-10:-1].max())
        is_breakout_range = (close_now > high_range) and (vol_ratio_now >= 1.3) and (close_now >= ema20_now)
        if preferred_scheme in ("C", "ALL") and is_breakout_range:
            stop_ref = round(high_range - tick, 2)
            entry_ref = round(close_now, 2)
            risk = round(entry_ref - stop_ref, 2)
            risk_pct = round(risk / entry_ref * 100, 2) if entry_ref > 0 else 0.0
            target_1r = round(entry_ref + risk, 2)
            target_2r = round(entry_ref + 2 * risk, 2)

            signals.append(f"60分K 放量突破近 10 根整理高點（{high_range:.2f} 元）")
            reason = (
                f"60分K 放量突破整理區間高點（{high_range:.2f} 元），量能達均量 {vol_ratio_now*100:.0f}%，"
                f"建議進場參考價: {entry_ref:.2f} 元，"
                f"做多防守停損 {stop_ref:.2f} 元 (跌破下方認賠，風險 {risk_pct:.2f}%)，"
                f"目標一價位 (1R 等距達標): {target_1r:.2f} 元。"
            )

            return {
                "timing_signal": "ENTER_LONG",
                "scheme": "SCHEME_C_RANGE_BREAKOUT",
                "entry_ref": entry_ref,
                "stop_ref": stop_ref,
                "risk_pct": risk_pct,
                "target_1r": target_1r,
                "target_2r": target_2r,
                "is_valid": True,
                "reason": reason,
                "signals": signals
            }

    # ── 6. 無時機觸發（靜待時機） ──
    dist_to_ema = (close_now - ema20_now) / (ema20_now + 1e-9) * 100
    return {
        "timing_signal": "NONE",
        "scheme": None,
        "entry_ref": None,
        "stop_ref": None,
        "risk_pct": None,
        "target_1r": None,
        "target_2r": None,
        "is_valid": False,
        "reason": f"日K 具買入候選資格，但 60分K 尚未觸發進場時機（現價 {close_now:.2f} 元，距離 60分 20 EMA 乖離 {dist_to_ema:+.2f}%，等待回測 20 EMA 守穩或突破）",
        "signals": []
    }
