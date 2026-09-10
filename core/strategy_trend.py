# -*- coding: utf-8 -*-
"""Stan Weinstein 四階段趨勢結構 + 專業趨勢研判：
以 MA20 / MA60 近 5 日斜率與排列，判定築底 / 主升 / 做頭 / 主跌四階段。
"""
def evaluate_professional_trend(df, inst_df, bpa_res, vol_eval=None):
    score = 0
    factors = []
    
    close_v   = df["close"].iloc[-1]
    ma5_v     = df["ma5"].iloc[-1]
    ma20_v    = df["ma20"].iloc[-1]
    ma60_v    = df["ma60"].iloc[-1]
    rsi_v     = df["rsi"].iloc[-1]
    macd_v    = df["macd"].iloc[-1]
    sig_v     = df["macd_signal"].iloc[-1]
    hist_v    = df["macd_hist"].iloc[-1]
    vol_v     = df["volume"].iloc[-1]
    vol_ma_v  = df["vol_ma"].iloc[-1]

    # 1. Stan Weinstein 趨勢四階段
    ma20_5d_ago = df["ma20"].iloc[-5] if len(df) >= 5 else ma20_v
    ma60_5d_ago = df["ma60"].iloc[-5] if len(df) >= 5 else ma60_v
    slope_ma20  = (ma20_v - ma20_5d_ago) / (ma20_5d_ago + 1e-9) * 100
    slope_ma60  = (ma60_v - ma60_5d_ago) / (ma60_5d_ago + 1e-9) * 100

    if ma20_v > ma60_v and slope_ma20 > 0.3 and slope_ma60 >= 0:
        stage = "第 2 階段（主升/多頭推進）"
        stage_score = +2
        stage_desc = f"MA20與MA60向上發散（月線斜率 +{slope_ma20:.2f}%）"
    elif ma20_v < ma60_v and slope_ma20 < -0.3 and slope_ma60 <= 0:
        stage = "第 4 階段（主跌/空頭修正）"
        stage_score = -2
        stage_desc = f"MA20與MA60向下發散（月線斜率 {slope_ma20:.2f}%）"
    elif slope_ma60 < 0 and ma20_v < ma60_v and slope_ma20 >= -0.2:
        stage = "第 1 階段（打底築底/跌勢收斂）"
        stage_score = 0
        stage_desc = "季線下彎但月線開始走平，進入區間打底"
    else:
        stage = "第 3 階段（高檔做頭/震盪分價）"
        stage_score = -1
        stage_desc = "均線糾結鈍化，方向性暫不明朗"

    score += stage_score
    factors.append(f"【趨勢結構】{stage_score:+d}分 | {stage}：{stage_desc}")

    # 2. Al Brooks 價格行為學（BPA 核心評價）
    bpa_score = bpa_res["always_in_score"] + bpa_res["bpa_extra_score"]
    score += bpa_score
    bpa_sig_text = bpa_res["signals"][0] if bpa_res["signals"] else "順應趨勢動態運行"
    factors.append(f"【Brooks PA】{bpa_score:+d}分 | {bpa_res['always_in']} ｜ K線：{bpa_res['last_bar_type']} ｜ {bpa_sig_text}")

    # 3. 均線位階與乖離
    bias_ma20 = (close_v - ma20_v) / ma20_v * 100
    if close_v > ma5_v and close_v > ma20_v:
        score += 1
        factors.append(f"【均線位階】+1分 | 站上 5MA 與 20MA（月線乖離率 {bias_ma20:+.1f}%）")
    elif close_v < ma5_v and close_v < ma20_v:
        score -= 1
        factors.append(f"【均線位階】-1分 | 跌破 5MA 與 20MA，短線失守動態支撐")
    else:
        factors.append(f"【均線位階】 0分 | 夾於 5MA 與 20MA 之間震盪")

    # 4. 動量指標 (MACD / RSI)
    macd_cross = "黃金交叉🔔" if (len(df)>=2 and df["macd"].iloc[-2] < df["macd_signal"].iloc[-2] and macd_v > sig_v) else \
                 "死亡交叉⚠️" if (len(df)>=2 and df["macd"].iloc[-2] > df["macd_signal"].iloc[-2] and macd_v < sig_v) else ""

    if macd_v > 0 and hist_v > 0:
        m_score = +2 if "黃金" in macd_cross else +1
        factors.append(f"【動量指標】{m_score:+d}分 | MACD 零軸上多方擴張（DIF={macd_v:+.2f}，柱體={hist_v:+.2f} {macd_cross}）")
    elif macd_v < 0 and hist_v < 0:
        m_score = -2 if "死亡" in macd_cross else -1
        factors.append(f"【動量指標】{m_score:+d}分 | MACD 零軸下空方主導（DIF={macd_v:+.2f}，柱體={hist_v:+.2f} {macd_cross}）")
    elif hist_v > 0:
        m_score = +1
        factors.append(f"【動量指標】+1分 | MACD 柱體轉正收紅（DIF={macd_v:+.2f}）")
    else:
        m_score = -1
        factors.append(f"【動量指標】-1分 | MACD 柱體轉負翻綠（DIF={macd_v:+.2f}）")
    score += m_score

    # RSI 位階
    if 50 <= rsi_v <= 68:
        score += 1; factors.append(f"【強弱擺盪】+1分 | RSI={rsi_v:.1f}（多方健康強勢區 50~68）")
    elif rsi_v > 68:
        factors.append(f"【強弱擺盪】 0分 | RSI={rsi_v:.1f}（進入過熱超買區 >68，防拉回）")
    elif 32 <= rsi_v < 50:
        score -= 1; factors.append(f"【強弱擺盪】-1分 | RSI={rsi_v:.1f}（空方弱勢整理區 32~50）")
    else:
        factors.append(f"【強弱擺盪】 0分 | RSI={rsi_v:.1f}（進入超賣區 <32，隨時具反彈力道）")

    # 5. 籌碼面深度分析 (三大法人)
    if not inst_df.empty:
        last_inst = inst_df.iloc[-1]
        fini_last = last_inst["fini"]
        trust_last= last_inst["trust"]
        total_last= last_inst["total"]
        total_5d  = inst_df.tail(5)["total"].sum()
        # 籌碼集中度：對比該法人公告日當天的成交量（而非盤中即時部分成交量）
        match_vol = df[df["date"].dt.date == last_inst["date"].date()]
        ref_vol   = match_vol["volume"].iloc[0] if not match_vol.empty else vol_v
        inst_ratio = abs(total_last) / (ref_vol + 1e-9) * 100

        if fini_last > 100 and trust_last > 50:
            c_desc = f"外資({fini_last:+,}) 與 投信({trust_last:+,}) 雙作多，土洋聯手看多"
            c_score = +2
        elif fini_last < -100 and trust_last < -50:
            c_desc = f"外資({fini_last:+,}) 與 投信({trust_last:+,}) 雙賣超，土洋聯手提款"
            c_score = -2
        elif fini_last > 500:
            c_desc = f"外資單日大幅加碼 {fini_last:+,} 張（佔量 {inst_ratio:.1f}%）"
            c_score = +1
        elif fini_last < -500:
            c_desc = f"外資單日沈重調節 {fini_last:+,} 張（佔量 {inst_ratio:.1f}%）"
            c_score = -1
        else:
            c_desc = f"5日法人合計 {total_5d:+,} 張，單日動向中性"
            c_score = 0

        score += c_score
        factors.append(f"【法人籌碼】{c_score:+d}分 | {c_desc}")
    else:
        factors.append("【法人籌碼】 0分 | 上櫃/無盤後法人公告數據")

    # 6. 量價結構與動能評估 (Wyckoff & VPA)
    if vol_eval is not None:
        score += vol_eval["score"]
        factors.append(f"【量價表現】{vol_eval['score']:+d}分 | {vol_eval['status']}：{vol_eval['desc']}")

    return score, stage, factors

