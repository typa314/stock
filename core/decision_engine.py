# -*- coding: utf-8 -*-
"""跨時間框架訊號仲裁引擎 (Cross-Timeframe Signal Arbitration Engine)

整合日線（波段趨勢 / Minervini / CANSLIM / 籌碼）與 5 分鐘 K 線（即時動能 / Conformal /
微型形態），解決「短線暫緩開倉 vs 日線建議買入」互相矛盾的決策痛點，
輸出單一主決策標籤、衝突說明與具體等待條件。
"""
from __future__ import annotations
from typing import Any, Dict


def arbitrate_signals(daily_res: Dict[str, Any], res5: Dict[str, Any]) -> Dict[str, Any]:
    """跨時框訊號仲裁核心函式。

    Args:
        daily_res: analyze_stock() 回傳 dict，至少含 composite_rating / bpa_res / close_now / ema20
        res5:      analyze_stock_5m() 回傳 dict，至少含 bpa_status / noise_ratio /
                   action_tag / is_vol_dull / is_noise_extreme / ema_now / high_today / stop_loss

    Returns:
        仲裁後的綜合決策 dict，包含:
            master_tag        - 主決策標籤（帶 emoji）
            master_color      - 主色 hex
            master_bg         - 背景 rgba
            master_border     - 邊框 hex
            decision_code     - 機器可讀決策代碼
            has_conflict      - bool，是否存在跨時框衝突
            conflict_reason   - 衝突原因說明（使用者可讀）
            waiting_conditions - 具體等待條件（使用者可讀，含精確價位）
            daily_score       - 日線綜合評分
            noise_ratio       - 5m 雜訊倍數
            action_5m         - 原始 5m action_tag 字串
            daily_action      - 原始日線 action_type 字串
    """
    daily_res = daily_res or {}
    res5      = res5      or {}

    # 解構日線
    daily_comp   = daily_res.get("composite_rating") or {}
    daily_score  = int(daily_comp.get("score", 0))
    daily_action = str(daily_comp.get("action_type", "WAIT")).upper()
    daily_bpa    = str((daily_res.get("bpa_res") or {}).get("always_in_zh", ""))
    daily_ema    = float(daily_res.get("ema20") or daily_res.get("close_now") or 0.0)

    # 解構 5m（相容 action_tag 與 action_tag_5m 兩種 key）
    action_5m        = str(res5.get("action_tag") or res5.get("action_tag_5m") or "")
    bpa_5m           = str(res5.get("bpa_status") or "")
    noise_ratio      = float(res5.get("noise_ratio") or 1.0)
    is_vol_dull      = bool(res5.get("is_vol_dull", False)) or ("暫緩開倉" in action_5m)
    is_noise_extreme = bool(res5.get("is_noise_extreme", False)) or ("拒絕開倉" in action_5m)
    ema_5m           = float(res5.get("ema_now") or res5.get("close_now") or 0.0)
    high_today       = float(res5.get("high_today") or res5.get("close_now") or 0.0)
    stop_loss_5m     = float(res5.get("stop_loss") or 0.0)

    is_daily_bull = ("多" in daily_bpa) or (daily_score >= 80)
    is_daily_bear = ("空" in daily_bpa) or (daily_action == "SELL")
    is_5m_bull    = "多" in bpa_5m

    # ── 仲裁決策矩陣 ─────────────────────────────────────────────────────────

    # 情境 1: 大時框空方 → 任何 5m 翻多皆為弱彈，嚴禁作多
    if daily_action == "SELL" or is_daily_bear:
        master_tag    = "🔴 建議賣出 / 逢高減碼"
        master_color  = "#ef4444"
        master_bg     = "rgba(239, 68, 68, 0.18)"
        master_border = "#ef4444"
        decision_code = "SELL"
        has_conflict  = is_5m_bull
        _ema_str      = f"{daily_ema:.2f} 元" if daily_ema > 0 else "20 EMA"
        conflict_reason = (
            "大時框日K已跌破中長期均線或空方主控，5m 短線翻紅僅屬跌深反彈，嚴禁逆勢作多。"
            if has_conflict else "雙時框同向偏空，空方壓制。"
        )
        waiting_conditions = (
            f"逢反彈至日線 20 EMA 壓力（{_ema_str}）即為減碼點，"
            "嚴格執行風控認賠，嚴禁盲目摸底。"
        )

    # 情境 2: 日線強勢多頭（Score >= 80）
    elif daily_score >= 80 and is_daily_bull:

        if is_noise_extreme:
            # 2A: 日線多頭 × 5m 盤中劇烈洗盤（>2.8x ATR）
            master_tag    = "🛑 暫停交易 (盤中劇烈洗盤)"
            master_color  = "#f43f5e"
            master_bg     = "rgba(244, 63, 94, 0.18)"
            master_border = "#f43f5e"
            decision_code = "AVOID_HIGH_VOLATILITY"
            has_conflict  = True
            conflict_reason = (
                f"日線架構偏多（{daily_score} 分），但當前 5m 單根震盪達均幅 {noise_ratio:.1f} 倍，"
                "隨機雜訊過高且置信區間發散，插針風險極大。"
            )
            waiting_conditions = (
                "主動放棄即時開倉，嚴防主力插針洗盤；"
                "等待 K 棒波幅收斂（< 1.5x 均幅）後重新評估進場時機。"
            )

        elif is_vol_dull:
            # 2B: 日線多頭 × 5m 暫緩開倉（量縮/動能暫歇）── 核心痛點破解
            master_tag    = "🟡 建議觀望 (趨勢多頭，短線動能暫歇)"
            master_color  = "#fbbf24"
            master_bg     = "rgba(245, 158, 11, 0.18)"
            master_border = "#fbbf24"
            decision_code = "WAIT_PULLBACK_OR_BREAKOUT"
            has_conflict  = True
            conflict_reason = (
                f"日線具備主升體質（評分 {daily_score} 分），"
                f"但當前 5m 動能暫歇（波幅僅 {noise_ratio:.2f}x 均幅），高檔量縮整理中。"
            )
            _ema_str  = f"{ema_5m:.2f} 元"  if ema_5m  > 0 else "20 EMA"
            _high_str = f"{high_today:.2f} 元" if high_today > 0 else "今日高點"
            waiting_conditions = (
                f"切忌市價追高！建議等待 5m 放量突破今日高點（{_high_str}），"
                f"或拉回回踩 20 EMA（{_ema_str}）守穩後再行分批佈局。"
            )

        elif is_5m_bull:
            # 2C: 雙時框多頭共振放量 → 強勢共振買入
            master_tag    = "🟢 雙時框強勢共振買入"
            master_color  = "#22c55e"
            master_bg     = "rgba(34, 197, 94, 0.18)"
            master_border = "#22c55e"
            decision_code = "BUY_RESONANCE"
            has_conflict  = False
            conflict_reason = "日線波段主升 × 5m 即時突破放量，雙時框信號同向共振！"
            _stop_str = (
                f"{stop_loss_5m:.2f} 元"
                if stop_loss_5m > 0
                else f"20 EMA（{ema_5m:.2f} 元）下方"
            )
            waiting_conditions = (
                f"信號共振確認，可依風控指引順勢進場；"
                f"防守停損嚴設於 {_stop_str}，勿輕易移動。"
            )

        else:
            # 2D: 日線強勢，5m 常態震盪
            master_tag    = "🟢 建議買入 (拉回守穩佈局)"
            master_color  = "#22c55e"
            master_bg     = "rgba(34, 197, 94, 0.18)"
            master_border = "#22c55e"
            decision_code = "BUY_NORMAL"
            has_conflict  = False
            conflict_reason = f"日線多頭排列（{daily_score} 分），5m 處於常態波動區間。"
            _ema_str = f"{ema_5m:.2f} 元" if ema_5m > 0 else "20 EMA"
            waiting_conditions = (
                f"逢拉回 20 EMA（{_ema_str}）守穩分批買進，"
                "停損嚴設於最近波段結構低點下方 1 Tick。"
            )

    # 情境 3: 日線持有（70~79 分）
    elif daily_score >= 70 and not is_daily_bear:
        master_tag    = "🔵 建議持有 (守穩支撐續抱)"
        master_color  = "#38bdf8"
        master_bg     = "rgba(56, 189, 248, 0.18)"
        master_border = "#38bdf8"
        decision_code = "HOLD"
        has_conflict  = is_vol_dull
        conflict_reason = (
            f"波段架構健全（{daily_score} 分），短線處於整理波，暫無追價時機。"
            if is_vol_dull else "多頭結構穩健，籌碼持穩。"
        )
        _ema_str = f"{daily_ema:.2f} 元" if daily_ema > 0 else "20 EMA"
        waiting_conditions = (
            f"持股者以日線 20 EMA（{_ema_str}）為移動防守線續抱；"
            "空手者暫勿追價，等待帶量突破或明確表態後再跟進。"
        )

    # 情境 4: 日線偏弱，5m 短線翻紅（誘多/逆日線弱彈）
    elif is_5m_bull and daily_score < 70:
        master_tag    = "🟡 建議觀望 (逆日線短線弱彈)"
        master_color  = "#fbbf24"
        master_bg     = "rgba(245, 158, 11, 0.18)"
        master_border = "#fbbf24"
        decision_code = "WAIT_COUNTER_TREND"
        has_conflict  = True
        conflict_reason = (
            f"5m 短線雖翻紅，但日線綜合評分僅 {daily_score} 分，"
            "缺乏波段結構保護傘，逆勢勝率偏低。"
        )
        waiting_conditions = (
            "嚴防主力拉高倒貨，嚴禁盲目追漲接刀；"
            "靜待日線 BPA 結構轉多且評分達 80 分以上，再考慮進場。"
        )

    # 情境 5: 區間整理 / 一般觀望
    else:
        master_tag    = "🟡 建議觀望 (等待動能表態)"
        master_color  = "#fbbf24"
        master_bg     = "rgba(245, 158, 11, 0.18)"
        master_border = "#fbbf24"
        decision_code = "WAIT_NORMAL"
        has_conflict  = False
        conflict_reason = "均線糾結且量能未明，處於區間震盪。"
        waiting_conditions = (
            "箱型整理未突破前多看少做；"
            "等待帶量長紅突破上緣或帶量長黑跌破下緣後，再擇向跟進。"
        )

    return {
        "master_tag":         master_tag,
        "master_color":       master_color,
        "master_bg":          master_bg,
        "master_border":      master_border,
        "decision_code":      decision_code,
        "has_conflict":       has_conflict,
        "conflict_reason":    conflict_reason,
        "waiting_conditions": waiting_conditions,
        "daily_score":        daily_score,
        "noise_ratio":        noise_ratio,
        "action_5m":          action_5m,
        "daily_action":       daily_action,
    }
