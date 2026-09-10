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



def evaluate_composite_rating(df, bpa_res, vol_eval, inst_df, fundamentals, ticker, market, regime_info=None):
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
    total_score = minervini_score + (max(0, c_score) / 5.0) * 25 + (30 if "多" in bpa_zh else (15 if "整理" in bpa_zh or "震盪" in bpa_zh else 5)) + (10 if inst_5d > 0 else 0)
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

    # 5. 核心操盤動作決策（依回測實證優化：80 分為基準，疊加 HMM 市場狀態雙層濾網）
    is_adverse_regime = bool(regime_info.get("is_adverse", False)) if regime_info else False

    if total_score >= 80 and ("多" in bpa_zh or "主升" in badge):
        if is_adverse_regime:
            if total_score >= 85:
                action_tag = "🟢 建議買入"
                action_type = "BUY"
                action_color = "#22c55e"
                action_bg = "rgba(34, 197, 94, 0.18)"
                action_border = "#22c55e"
                action_sub = f"具備 ≥85 分極致飆股體質，雖處震盪市況仍可順應 20 EMA（{ema_val:.2f} 元）守穩嚴設風控佈局"
            else:
                action_tag = "🟡 建議觀望 (市況震盪)"
                action_type = "WAIT"
                action_color = "#fbbf24"
                action_bg = "rgba(245, 158, 11, 0.18)"
                action_border = "#fbbf24"
                action_sub = f"綜合評分達 {total_score} 分，但處於 HMM 高波震盪市況，未達 85 分極致飆股標準，建議防守觀望"
        else:
            action_tag = "🟢 建議買入"
            action_type = "BUY"
            action_color = "#22c55e"
            action_bg = "rgba(34, 197, 94, 0.18)"
            action_border = "#22c55e"
            action_sub = f"主升動能強勁，逢 20 EMA（{ema_val:.2f} 元）拉回守穩或放量突破順勢買進"
    elif total_score >= 60 and "空" not in bpa_zh:
        action_tag = "🟡 建議持有"
        action_type = "HOLD"
        action_color = "#38bdf8"
        action_bg = "rgba(56, 189, 248, 0.18)"
        action_border = "#38bdf8"
        action_sub = f"多頭結構穩健，持股續抱；空手者待回測 20 EMA（{ema_val:.2f} 元）分批佈局"
    elif total_score >= 45:
        action_tag = "🟡 建議觀望"
        action_type = "WAIT"
        action_color = "#fbbf24"
        action_bg = "rgba(245, 158, 11, 0.18)"
        action_border = "#fbbf24"
        action_sub = "箱型震盪打底，多空未明，暫勿追價，靜待帶量表態"
    else:
        action_tag = "🔴 建議賣出"
        action_type = "SELL"
        action_color = "#ef4444"
        action_bg = "rgba(239, 68, 68, 0.18)"
        action_border = "#ef4444"
        action_sub = "跌破關鍵防守線，空方主控，持股逢反彈減碼，嚴禁接刀"

    return {
        "score": total_score,
        "badge": badge,
        "badge_color": b_color,
        "badge_bg": b_bg,
        "action_tag": action_tag,
        "action_type": action_type,
        "action_color": action_color,
        "action_bg": action_bg,
        "action_border": action_border,
        "action_sub": action_sub,
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
        "regime_info": regime_info
    }

