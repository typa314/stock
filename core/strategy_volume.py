# -*- coding: utf-8 -*-
"""Wyckoff / VPA（Volume Price Analysis）量價結構評估：
價量齊揚、帶量突破、價跌量縮、量價背離、窒息量打底、爆量滯漲、放量重挫等六大量價形態判讀與評分。
"""
def evaluate_volume_price(df):
    """
    量價結構與動能深度評估（Wyckoff & Volume Price Analysis）：
      - 判定量價配合關係（價漲量增、價跌量縮、量價背離、放量下殺、爆量滯漲、窒息量打底）
      - 量能均線倍數（20MA 均量比、5MA 均量比）
      - 結合 Wyckoff 特徵（突破、拉回、背離）
      - 提供結構狀態、得分、量價診斷與操盤應對建議
    """
    N = len(df)
    vol_now = float(df["volume"].iloc[-1])
    vol_ma20 = float(df["vol_ma"].iloc[-1]) if "vol_ma" in df else vol_now
    vol_ma5 = float(df["volume"].rolling(5, min_periods=1).mean().iloc[-1])
    vol_ratio_20 = vol_now / (vol_ma20 + 1e-9)
    vol_ratio_5 = vol_now / (vol_ma5 + 1e-9)
    
    close_now = float(df["close"].iloc[-1])
    open_now = float(df["open"].iloc[-1])
    high_now = float(df["high"].iloc[-1])
    low_now = float(df["low"].iloc[-1])
    prev_close = float(df["close"].iloc[-2]) if N >= 2 else close_now
    chg = close_now - prev_close
    chg_pct = (chg / (prev_close + 1e-9)) * 100
    
    # 蠟燭結構與影線
    candle_rng = max(high_now - low_now, 1e-5)
    body = abs(close_now - open_now)
    upper_sh = high_now - max(open_now, close_now)
    
    # 特殊量價與 Wyckoff 標記（帶量突破必須嚴格驗收成交量 >= 1.5 倍 20MA 均量）
    if "breakout" in df:
        is_breakout = bool(df["breakout"].iloc[-1]) and (vol_ratio_20 >= 1.5)
    else:
        is_breakout = (len(df) >= 21) and (close_now > df["high"].iloc[-21:-1].max()) and (vol_ratio_20 >= 1.5)
    is_dryup = bool(df["dryup"].iloc[-1]) if "dryup" in df else (vol_now < 0.45 * vol_ma20)
    is_churn = bool(df["churn"].iloc[-1]) if "churn" in df else (vol_ratio_20 > 1.8 and (upper_sh / candle_rng > 0.4 or body / candle_rng < 0.25))
    is_pullback = bool(df["pullback"].iloc[-1]) if "pullback" in df else False
    bull_div = bool(df["bull_div"].iloc[-1]) if "bull_div" in df else False
    bear_div = bool(df["bear_div"].iloc[-1]) if "bear_div" in df else False

    # 量價型態診斷
    if is_churn:
        status = "爆量滯漲（主力調節警戒）"
        status_code = "CHURN"
        score = -1
        desc = f"成交量達 20MA 的 {vol_ratio_20*100:.0f}%（爆量），但漲勢受阻留長上影線或實體窄小，顯示主力逢高調節或高檔換手分歧"
        advice = "短線追高風險極大，提防主力誘多出貨，持股者宜逢高分批減碼"
    elif is_breakout:
        status = "帶量突破（主力放量表態）"
        status_code = "BREAKOUT"
        score = +2
        desc = f"放量突破近 20 日高點（成交量為 20MA 的 {vol_ratio_20*100:.0f}%），多方強勢表態展開波段攻勢"
        advice = "量價俱佳，順勢偏多操作，可以突破價或前波高點作為動態防守位"
    elif is_dryup:
        status = "窒息量打底（沉澱沉寂變盤前夕）"
        status_code = "DRYUP"
        score = 0
        desc = f"成交量僅 20MA 的 {vol_ratio_20*100:.0f}%（極致萎縮），市場浮額大幅洗淨，殺盤動能衰竭"
        advice = "量能萎縮至波段極低水平，往往孕育變盤反轉，空手者可密切留意帶量起漲訊號"
    elif chg > 0 and vol_ratio_20 >= 1.25:
        status = "價量齊揚（健康放量推升）"
        status_code = "BULL_EXP"
        score = +2
        desc = f"股價上揚 {chg_pct:+.2f}% 伴隨量能放大至 20MA 的 {vol_ratio_20*100:.0f}%，買盤積極推升，多方架構扎實"
        advice = "量能配合良好，多頭動能充沛，持股續抱，空手者可待短線回踩守穩時分批佈局"
    elif chg > 0 and vol_ratio_20 <= 0.75:
        status = "量價背離（縮量推升動能趨緩）"
        status_code = "BULL_DIV"
        score = 0
        desc = f"股價上漲 {chg_pct:+.2f}% 但成交量僅為 20MA 的 {vol_ratio_20*100:.0f}%，追價力道跟進不足"
        advice = "無量上漲易引發震盪回測，嚴禁追高，持股者宜提高警戒並緊盯支撐線"
    elif chg < 0 and vol_ratio_20 >= 1.25:
        status = "放量重挫（空方賣壓湧現）"
        status_code = "BEAR_EXP"
        score = -2
        desc = f"股價下跌 {chg_pct:+.2f}% 且成交量放大至 20MA 的 {vol_ratio_20*100:.0f}%，空方帶量摜壓，恐慌性賣盤出籠"
        advice = "帶量破線殺傷力大，短線跌勢恐未止，持股者嚴守停損，空手者切勿急於猜底接刀"
    elif chg < 0 and vol_ratio_20 <= 0.75:
        ma20_val = float(df["ma20"].iloc[-1]) if "ma20" in df else close_now
        status = "價跌量縮（多頭良性拉回洗盤）" if close_now >= ma20_val else "陰跌量縮（買盤觀望人氣退潮）"
        status_code = "BEAR_RET"
        score = +1 if close_now >= ma20_val else -1
        desc = f"股價拉回 {chg_pct:+.2f}% 且成交量萎縮至 20MA 的 {vol_ratio_20*100:.0f}%，無恐慌性失血賣壓"
        advice = "拉回量縮代表籌碼相對安定，若守穩月線支撐可視為良性洗盤買點；反之若跌破均線則需防陰跌"
    else:
        status = "量價平穩（常態量能震盪）"
        status_code = "NORMAL"
        score = 0
        desc = f"今日成交量為 20MA 的 {vol_ratio_20*100:.0f}%，量能與價格變動處於常態合理區間"
        advice = "量能無失控或突變跡象，維持既有技術面支撐壓力紀律操作"

    if bull_div:
        desc += " ｜ 【技術指標底背離】跌勢趨緩醞釀反彈"
    if bear_div:
        desc += " ｜ 【技術指標頂背離】漲勢趨疲提防獲利了結"

    return {
        "status": status,
        "status_code": status_code,
        "score": score,
        "vol_now": vol_now,
        "vol_ma20": vol_ma20,
        "vol_ma5": vol_ma5,
        "vol_ratio_20": vol_ratio_20,
        "vol_ratio_5": vol_ratio_5,
        "desc": desc,
        "advice": advice,
        "is_breakout": is_breakout,
        "is_dryup": is_dryup,
        "is_churn": is_churn,
        "is_pullback": is_pullback,
        "bull_div": bull_div,
        "bear_div": bear_div
    }

