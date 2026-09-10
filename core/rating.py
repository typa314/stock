# -*- coding: utf-8 -*-
"""綜合評級系統：Minervini 趨勢樣板、CANSLIM 成長動能、BPA 主控特徵、
三大法人與 VPA 量能籌碼動態，整合為 0~100 綜合評分與星級／文字徽章。
"""
import pandas as pd
import yfinance as yf


def get_rating_badge(s):
    if s >= 6:   return "🟢 強烈多頭（動能充沛，偏多操作）"
    if s >= 3:   return "🟢 溫和偏多（震盪盤堅，支撐守穩）"
    if s >= 1:   return "🟡 中性微多（均線整理，等待方向）"
    if s == 0:   return "🟡 中立盤整（多空拉鋸，靜待放量）"
    if s >= -2:  return "🟠 中性微空（反彈無力，下方測底）"
    if s >= -5:  return "🔴 溫和偏空（空頭承壓，反彈宜減碼）"
    return            "🔴 強烈空頭（主跌段，切勿盲目接刀）"




def _bpa_score(bpa_res: dict) -> int:
    """
    細粒度 BPA 分數（0~30）
    - 基礎分來自 Always-In 強度（+2->30, +1->20, 0->14, -1->8, -2->4）
    - 額外分來自 strategy_brooks 的形態加成 bpa_extra_score（限制在 -4 ~ +6）
    - 兼顧向下相容回退
    """
    if not bpa_res:
        return 14
    base_map = {
        2: 30,   # 多頭主控 (滿分30)
        1: 20,   # 偏多整理
        0: 15,   # 箱型震盪
        -1: 8,   # 偏空整理
        -2: 4,   # 空方主導
    }
    if "always_in_score" in bpa_res and bpa_res["always_in_score"] is not None:
        base = base_map.get(bpa_res["always_in_score"], 15)
    else:
        zh = bpa_res.get("always_in_zh", "")
        base = 30 if ("多頭" in zh or "主控" in zh or "主升" in zh) else (20 if "多" in zh else (15 if "震盪" in zh or "整理" in zh else 4))

    extra_raw = bpa_res.get("bpa_extra_score", 0)
    extra = min(6, max(-4, extra_raw * 2))

    return int(min(30, max(0, base + extra)))


def evaluate_composite_rating(df, bpa_res, vol_eval, inst_df, fundamentals, ticker, market, regime_info=None, market_regime=None):
    """
    多維綜合評級：融合 Minervini 趨勢樣板 + CANSLIM 成長動能 + BPA 價格行為 + 法人量價結構 + HMM 市場狀態
    保持乾淨精簡，輸出高訊號比之綜合評級卡片資料
    """

    c = df["close"]
    ma50 = ma150 = ma200 = ma200_20d = low_52w = high_52w = None
    if len(c) >= 200:
        ma50 = c.rolling(50).mean().iloc[-1]
        ma150 = c.rolling(150).mean().iloc[-1]
        ma200 = c.rolling(200).mean().iloc[-1]
        ma200_20d = c.rolling(200).mean().iloc[-22] if len(c) >= 222 else ma200
        low_52w = c.tail(250).min()
        high_52w = c.tail(250).max()
    else:
        try:
            sym = f"{ticker}.TW" if market == "tse" else f"{ticker}.TWO"
            raw = yf.download(sym, period="15mo", progress=False)
            if raw is None or raw.empty:
                sym_alt = f"{ticker}.TWO" if market == "tse" else f"{ticker}.TW"
                raw = yf.download(sym_alt, period="15mo", progress=False)
            if raw is not None and not raw.empty:
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = [col[0].lower() for col in raw.columns]
                else:
                    raw.columns = [col.lower() for col in raw.columns]
                c_long = raw["close"]
                if len(c_long) >= 50:
                    ma50 = c_long.rolling(50).mean().iloc[-1]
                if len(c_long) >= 150:
                    ma150 = c_long.rolling(150).mean().iloc[-1]
                if len(c_long) >= 200:
                    ma200 = c_long.rolling(200).mean().iloc[-1]
                    ma200_20d = c_long.rolling(200).mean().iloc[-22] if len(c_long) >= 222 else ma200
                low_52w = c_long.tail(250).min()
                high_52w = c_long.tail(250).max()
        except Exception:
            pass

    c_now = float(c.iloc[-1])
    m_checks = []
    if ma50 is not None and ma150 is not None and ma200 is not None and low_52w is not None and high_52w is not None:
        m_checks.append(c_now > ma150 and c_now > ma200)
        m_checks.append(ma150 > ma200)
        m_checks.append(ma200 >= ma200_20d * 0.995)
        m_checks.append(ma50 > ma150 and ma50 > ma200)
        m_checks.append(c_now > ma50)
        m_checks.append((c_now - low_52w) / (low_52w + 1e-9) >= 0.25)
        m_checks.append((high_52w - c_now) / (high_52w + 1e-9) <= 0.25)
        m_passed = sum(m_checks)
        m_status = "Stage 2 主升段" if m_passed >= 6 else ("符合多數樣板" if m_passed >= 4 else "弱勢整理型態")
        m_color = "#4ade80" if m_passed >= 5 else ("#fbbf24" if m_passed >= 4 else "#f87171")
    else:
        m_passed = None
        m_status = "資料不足（無法評估）"
        m_color = "#94a3b8"

    # 2. CANSLIM 成長動能評分
    rev_yoy = fundamentals.get("revenue_yoy") if fundamentals else None
    eps_ttm = fundamentals.get("eps_ttm") if fundamentals else None
    gm = fundamentals.get("gross_margin") if fundamentals else None
    
    c_score = 0
    if rev_yoy is not None:
        if rev_yoy >= 20: c_score += 2
        elif rev_yoy >= 0: c_score += 1
        else: c_score -= 1
    if eps_ttm is not None and eps_ttm > 0:
        c_score += 2
    if gm is not None and gm >= 30:
        c_score += 1
        
    if c_score >= 4:
        canslim_grade = "A+ 卓越"
        canslim_sub = "營收盈餘高速成長"
        c_color = "#4ade80"
    elif c_score >= 2:
        canslim_grade = "A 優質"
        canslim_sub = "基本面穩健成長"
        c_color = "#60a5fa"
    elif c_score >= 0:
        canslim_grade = "B 中性"
        canslim_sub = "獲利動能平穩"
        c_color = "#fbbf24"
    else:
        canslim_grade = "C 偏弱"
        canslim_sub = "動能趨緩或虧損"
        c_color = "#f87171"

    # 3. BPA 價格行為
    ema_val = float(df["ema20"].iloc[-1]) if "ema20" in df.columns else float(df["close"].ewm(span=20, adjust=False).mean().iloc[-1])
    bpa_zh = bpa_res.get("always_in_zh", "箱型震盪")
    if "多" in bpa_zh:
        bpa_sub = f"站穩 20 EMA ({ema_val:.2f}元)"
        bpa_color = "#4ade80"
    elif "空" in bpa_zh:
        bpa_sub = f"受制 20 EMA ({ema_val:.2f}元)"
        bpa_color = "#f87171"
    else:
        bpa_sub = "區間高出低進"
        bpa_color = "#fbbf24"

    # 4. 籌碼與量價結構
    v_score = vol_eval.get("score", 0) if vol_eval else 0
    inst_5d = int(inst_df.tail(5)["total"].sum()) if (inst_df is not None and not inst_df.empty) else 0
    if inst_5d > 0 and v_score >= 0:
        chip_zh = "法人主力加碼"
        chip_sub = f"5日買超 {inst_5d:,}張"
        chip_color = "#4ade80"
    elif inst_5d < 0 and v_score <= 0:
        chip_zh = "法人主力調節"
        chip_sub = f"5日賣超 {abs(inst_5d):,}張"
        chip_color = "#f87171"
    elif inst_5d > 0:
        chip_zh = "籌碼偏多支撐"
        chip_sub = "內外資偏多佈局"
        chip_color = "#60a5fa"
    else:
        chip_zh = "籌碼動向觀望"
        chip_sub = "多空分歧整理"
        chip_color = "#fbbf24"

    # 綜合評分與操盤定位
    minervini_score = (m_passed / 7.0) * 35 if m_passed is not None else 0.0
    bpa_score_val = _bpa_score(bpa_res)
    total_score = minervini_score + (max(0, c_score) / 5.0) * 25 + bpa_score_val + (10 if inst_5d > 0 else 0)
    total_score = int(round(total_score))

    if total_score >= 80 and (m_passed is not None and m_passed >= 5):
        badge = "⭐⭐⭐⭐⭐ 頂級飆股體質（Stage 2 主升）"
        b_color = "#4ade80"
        b_bg = "rgba(34, 197, 94, 0.2)"
        summary_advice = f"多頭排列且基本面強勁，順應 20 EMA（{ema_val:.2f} 元）拉回守穩順勢佈局。"
    elif total_score >= 65:
        badge = "⭐⭐⭐⭐ 優質多頭（穩健推升中）"
        b_color = "#60a5fa"
        b_bg = "rgba(59, 130, 246, 0.2)"
        summary_advice = "中期架構偏多且守穩支撐，持股續抱，空手者待回測守穩分批佈局。"
    elif total_score >= 45:
        badge = "⭐⭐⭐ 區間震盪（待動能表態）"
        b_color = "#fbbf24"
        b_bg = "rgba(245, 158, 11, 0.2)"
        summary_advice = "箱型整理均線糾結，突破前暫勿追價，低買高賣或靜待帶量表態。"
    else:
        badge = "⚠️ 空頭承壓（弱勢修正中）"
        b_color = "#f87171"
        b_bg = "rgba(239, 68, 68, 0.2)"
        summary_advice = "跌破中長期均線，空方主導，持股逢反彈嚴格風控，嚴禁盲目猜底。"

    # 5. 核心操盤動作決策（依回測實證重新校準：BPA偏多 + Stage 4 標的池過濾 + 熊市防禦）
    is_adverse_regime = bool(regime_info.get("is_adverse", False)) if regime_info else False
    if market_regime is None and regime_info:
        market_regime = regime_info.get("market_regime")
    if market_regime is None:
        try:
            from core.market_regime import get_market_regime_status
            market_regime = get_market_regime_status()
        except Exception:
            market_regime = {}
    is_market_bear = bool(market_regime.get("is_market_bear", False)) if market_regime else False

    # Stan Weinstein Stage 4 空頭型態判定：股價在年線下且年線下彎
    is_stage4_bear = bool(ma200 is not None and c_now < ma200 * 0.98 and ma200 < ma200_20d)

    is_bullish_bpa = ("多" in bpa_zh) or (bpa_res.get("always_in_score", 0) > 0)
    is_strong_bull = (bpa_res.get("always_in_score", 0) >= 2) or ("主控" in bpa_zh)

    # 1. 建議買入：高分 + 實質偏多結構
    if total_score >= 80 and is_bullish_bpa:
        if is_stage4_bear:
            # Stan Weinstein 標的池過濾：Stage 4 空頭主跌段強制禁買，防範牛皮/衰退股假突破
            action_tag = "🟡 建議觀望 (Stage 4 禁買)"
            action_type = "WAIT"
            action_color = "#fbbf24"
            action_bg = "rgba(245, 158, 11, 0.18)"
            action_border = "#fbbf24"
            action_sub = "長期年線（200 MA）下彎且股價處於年線之下，屬 Stage 4 衰退空頭形態，依風控架構嚴禁開多單，嚴防假突破！"
        elif is_adverse_regime or is_market_bear:
            reason = "大盤空方承壓" if is_market_bear else "市況震盪"
            if total_score >= 85 and is_strong_bull:
                action_tag = "🟢 建議買入 (防禦佈局)" if is_market_bear else "🟢 建議買入"
                action_type = "BUY"
                action_color = "#22c55e"
                action_bg = "rgba(34, 197, 94, 0.18)"
                action_border = "#22c55e"
                action_sub = f"具備 ≥85 分極致飆股體質且多頭主控，雖處{reason}仍可順應 20 EMA（{ema_val:.2f} 元）守穩嚴設防禦停損佈局"
            else:
                action_tag = f"🟡 建議觀望 ({reason})"
                action_type = "WAIT"
                action_color = "#fbbf24"
                action_bg = "rgba(245, 158, 11, 0.18)"
                action_border = "#fbbf24"
                action_sub = f"綜合評分達 {total_score} 分，但處於 {reason}，未達 85 分多頭主控標準，建議防守觀望"
        else:
            action_tag = "🟢 建議買入"
            action_type = "BUY"
            action_color = "#22c55e"
            action_bg = "rgba(34, 197, 94, 0.18)"
            action_border = "#22c55e"
            action_sub = f"主升動能強勁且 BPA 偏多，逢 20 EMA（{ema_val:.2f} 元）拉回守穩或放量突破順勢買進"

    # 2. 建議持有：收緊至 70 分以上非空方結構（65~69 分依回測實證無邊緣，併入 WAIT 觀望）
    elif total_score >= 70 and "空" not in bpa_zh:
        if is_stage4_bear:
            action_tag = "🟡 建議觀望 (Stage 4 禁買)"
            action_type = "WAIT"
            action_color = "#fbbf24"
            action_bg = "rgba(245, 158, 11, 0.18)"
            action_border = "#fbbf24"
            action_sub = "長期年線（200 MA）下彎且股價處於年線之下，屬 Stage 4 衰退空頭形態，依風控架構嚴禁開多單，嚴防假突破！"
        else:
            action_tag = "🔵 建議持有"
            action_type = "HOLD"
            action_color = "#38bdf8"
            action_bg = "rgba(56, 189, 248, 0.18)"
            action_border = "#38bdf8"
            action_sub = f"多頭架構穩健（評分 {total_score}），持股續抱；空手者待回測 20 EMA（{ema_val:.2f} 元）分批佈局"

    # 3. 建議觀望：50~69 分（65~69 分已併入觀望，消除無超額模糊區間）
    elif total_score >= 50:
        if is_stage4_bear:
            action_tag = "🟡 建議觀望 (Stage 4 禁買)"
            action_type = "WAIT"
            action_color = "#fbbf24"
            action_bg = "rgba(245, 158, 11, 0.18)"
            action_border = "#fbbf24"
            action_sub = "長期年線（200 MA）下彎且股價處於年線之下，屬 Stage 4 衰退空頭形態，依風控架構嚴禁開多單，嚴防假突破！"
        else:
            action_tag = "🟡 建議觀望"
            action_type = "WAIT"
            action_color = "#fbbf24"
            action_bg = "rgba(245, 158, 11, 0.18)"
            action_border = "#fbbf24"
            action_sub = f"綜合評分 {total_score} 分，動能與形態未達明朗標準，多空未明，建議空手觀望靜待帶量表態"

    # 4. 建議賣出：< 50 分或空方主控
    else:
        action_tag = "🔴 建議賣出"
        action_type = "SELL"
        action_color = "#ef4444"
        action_bg = "rgba(239, 68, 68, 0.18)"
        action_border = "#ef4444"
        action_sub = "跌破關鍵防守線或空方主控，持股逢反彈減碼避險，嚴禁逆勢接刀"

    suggested_hold_days = 60 if action_type == "BUY" else (40 if action_type == "HOLD" else None)

    if action_type == "BUY":
        daily_bias = "BUY_CANDIDATE"
    elif action_type in ("HOLD", "WAIT"):
        daily_bias = "WAIT"
    else:
        daily_bias = "SELL"

    return {
        "score": total_score,
        "badge": badge,
        "badge_color": b_color,
        "badge_bg": b_bg,
        "action_tag": action_tag,
        "action_type": action_type,
        "daily_bias": daily_bias,
        "action_color": action_color,
        "action_bg": action_bg,
        "action_border": action_border,
        "action_sub": action_sub,
        "suggested_hold_days": suggested_hold_days,
        "minervini_passed": m_passed,
        "minervini_status": m_status,
        "minervini_color": m_color,
        "canslim_grade": canslim_grade,
        "canslim_sub": canslim_sub,
        "canslim_color": c_color,
        "bpa_zh": bpa_zh,
        "bpa_sub": bpa_sub,
        "bpa_color": bpa_color,
        "chip_zh": chip_zh,
        "chip_sub": chip_sub,
        "chip_color": chip_color,
        "summary_advice": summary_advice,
        "regime_info": regime_info,
        "market_regime": market_regime,
        "is_stage4_bear": is_stage4_bear,
        "is_market_bear": is_market_bear,
        "time_horizon": "40~60 交易日（波段動能跟隨）"
    }


def check_anti_chase(signal_close: float, next_open: float, max_chase_pct: float = 1.5) -> dict:
    """
    次日開盤追價限制檢查（Anti-Chase Rule）：
    若次日開盤價大於訊號日收盤價之 (1 + max_chase_pct%)，
    判定為過度追價，取消當日追高進場，改等回測 20 EMA 或前波支撐。
    """
    if signal_close <= 0:
        return {"allow_entry": True, "chase_pct": 0.0, "reason": "收盤價異常，無追價限制"}
    chase_pct = ((next_open - signal_close) / signal_close) * 100.0
    if chase_pct > max_chase_pct:
        return {
            "allow_entry": False,
            "chase_pct": round(chase_pct, 2),
            "reason": f"次日開盤跳空漲幅達 +{chase_pct:.2f}%，超過追價上限 +{max_chase_pct:.1f}%，依紀律取消追高，改等回測 20 EMA 或支撐"
        }
    return {
        "allow_entry": True,
        "chase_pct": round(chase_pct, 2),
        "reason": f"開盤漲幅 +{chase_pct:.2f}% 處於允許追價範圍（<={max_chase_pct:.1f}%）"
    }



