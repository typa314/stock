# -*- coding: utf-8 -*-
"""Al Brooks 價格行為學（Price Action, BPA）核心判讀：
Always-In 市場狀態、20 EMA 動態基準、經典高勝率設定（H1/H2/L1/L2/EMA PB/TTR 等）、
K 線逐根分類與掛單/停損/等距測量計算。

輸入：帶有 close/high/low/ema20 等欄位的技術指標 DataFrame。
輸出：純資料（dict），不涉及任何外部資料擷取或繪圖。
"""
from core.indicators import get_tw_tick


def evaluate_brooks_price_action(df):
    """
    Al Brooks 價格行為學（BPA）核心架構評估：
      - Always-In 市場狀態（AIL / AIS / TR）
      - 20 EMA 動態位階、斜率與乖離
      - 經典高勝率設定（H1/H2, L1/L2, EMA PB, EMA Gap Bar, ii, TTR）
      - 突破停損掛單價、防守停損價與等距測量目標（Measured Move）
    """
    N = len(df)
    c = df["close"].iloc[-1]
    ema_v = df["ema20"].iloc[-1]
    
    # 20 EMA 近 5 日斜率
    ema_prev = df["ema20"].iloc[-5] if N >= 5 else ema_v
    ema_slope = (ema_v - ema_prev) / (ema_prev + 1e-9) * 100
    
    # 近 10 根穿越 EMA 次數（判斷是否進入交疊震盪）
    ema_crosses = 0
    for i in range(max(1, N-10), N):
        if (df["close"].iloc[i] - df["ema20"].iloc[i]) * (df["close"].iloc[i-1] - df["ema20"].iloc[i-1]) < 0:
            ema_crosses += 1
            
    is_ttr = bool(df["bpa_ttr"].iloc[-1] or (df["bpa_ttr"].iloc[-2] if N >= 2 else False))
    
    # 7.1 Always-In 狀態判定（純中文語意標註）
    if is_ttr or (ema_crosses >= 3 and abs(ema_slope) < 0.3):
        always_in = "箱型震盪（區間盤整）"
        always_in_zh = "箱型震盪"
        always_in_desc = "區間高出低進（突破易失敗）"
        always_in_code = "TR"
        always_in_score = 0
    elif c > ema_v and ema_slope > 0.15:
        always_in = "多頭主控（逢低做多）"
        always_in_zh = "多頭主控"
        always_in_desc = "拉回逢低做多（順勢主控）"
        always_in_code = "AIL"
        always_in_score = +2
    elif c < ema_v and ema_slope < -0.15:
        always_in = "空方主導（逢高做空）"
        always_in_zh = "空方主導"
        always_in_desc = "反彈逢高做空（空方主控）"
        always_in_code = "AIS"
        always_in_score = -2
    elif c >= ema_v:
        always_in = "偏多整理（守穩支撐）"
        always_in_zh = "偏多整理"
        always_in_desc = "震盪守穩支撐（偏多看待）"
        always_in_code = "AIL"
        always_in_score = +1
    else:
        always_in = "偏空整理（反彈遇壓）"
        always_in_zh = "偏空整理"
        always_in_desc = "震盪反彈遇壓（偏空看待）"
        always_in_code = "AIS"
        always_in_score = -1
        
    last_bar_type = df["bpa_bar_type"].iloc[-1]
    
    # 7.2 近期 BPA 特徵設定（嚴格遵守 Al Brooks 趨勢環境濾網原則）
    recent_signals = []
    bpa_extra_score = 0
    mid_bb = df["bb_mid"].iloc[-1]
    
    # 7.2.1 多方設定（僅在 AIL 多頭環境 或 TR 區間下半部守穩時採納，時效 1~2 根 K 棒）
    if always_in_code == "AIL" or (always_in_code == "TR" and c <= mid_bb):
        if df["bpa_h2"].tail(2).any():
            idx_list = df.index[df["bpa_h2"]].tolist()
            last_idx = idx_list[-1] if idx_list else len(df) - 1
            prev_h = float(df["high"].iloc[last_idx - 1]) if last_idx >= 1 else float(df["high"].iloc[last_idx])
            tick_val = get_tw_tick(float(df["close"].iloc[last_idx - 1])) if last_idx >= 1 else 0.5
            trig_p = prev_h + tick_val
            recent_signals.append(f"觸發 High 2 (H2) 雙重推動買點🔥（突破價位: {trig_p:.2f} 元，前高: {prev_h:.2f} 元）")
            bpa_extra_score += 2
        elif df["bpa_h1"].tail(2).any():
            idx_list = df.index[df["bpa_h1"]].tolist()
            last_idx = idx_list[-1] if idx_list else len(df) - 1
            prev_h = float(df["high"].iloc[last_idx - 1]) if last_idx >= 1 else float(df["high"].iloc[last_idx])
            tick_val = get_tw_tick(float(df["close"].iloc[last_idx - 1])) if last_idx >= 1 else 0.5
            trig_p = prev_h + tick_val
            recent_signals.append(f"觸發 High 1 (H1) 初次推動過前高（突破價位: {trig_p:.2f} 元，前高: {prev_h:.2f} 元）")
            bpa_extra_score += 1
        elif df["bpa_h3"].tail(2).any():
            idx_list = df.index[df["bpa_h3"]].tolist()
            last_idx = idx_list[-1] if idx_list else len(df) - 1
            prev_h = float(df["high"].iloc[last_idx - 1]) if last_idx >= 1 else float(df["high"].iloc[last_idx])
            tick_val = get_tw_tick(float(df["close"].iloc[last_idx - 1])) if last_idx >= 1 else 0.5
            trig_p = prev_h + tick_val
            recent_signals.append(f"觸發 High 3 (H3) 楔形多頭旗形突破警訊⚠️（突破價位: {trig_p:.2f} 元，推動末端不追多）")
            # H3 視為末端推動警訊，不給予額外做多加分

        if df["bpa_ema_pb"].tail(2).any():
            recent_signals.append(f"20 EMA 動態支撐回測確認（支撐價: {ema_v:.2f} 元，順勢買點）")
            bpa_extra_score += 1

        if df["bpa_bull_gap"].tail(2).any():
            recent_signals.append(f"出現多頭 20 EMA 乖離缺口棒（當前乖離率: +{(c-ema_v)/ema_v*100:.1f}%，留意高檔測頂反轉）⚠️")
            bpa_extra_score += 1

    # 7.2.2 空方設定（僅在 AIS 空頭環境 或 TR 區間上半部受阻時採納，時效 1~2 根 K 棒）
    if always_in_code == "AIS" or (always_in_code == "TR" and c >= mid_bb):
        if df["bpa_l2"].tail(2).any():
            idx_list = df.index[df["bpa_l2"]].tolist()
            last_idx = idx_list[-1] if idx_list else len(df) - 1
            prev_l = float(df["low"].iloc[last_idx - 1]) if last_idx >= 1 else float(df["low"].iloc[last_idx])
            tick_val = get_tw_tick(float(df["close"].iloc[last_idx - 1])) if last_idx >= 1 else 0.5
            trig_p = prev_l - tick_val
            recent_signals.append(f"觸發 Low 2 (L2) 雙重反彈逢高空點⚠️（跌破價位: {trig_p:.2f} 元，前低: {prev_l:.2f} 元）")
            bpa_extra_score -= 2
        elif df["bpa_l1"].tail(2).any():
            idx_list = df.index[df["bpa_l1"]].tolist()
            last_idx = idx_list[-1] if idx_list else len(df) - 1
            prev_l = float(df["low"].iloc[last_idx - 1]) if last_idx >= 1 else float(df["low"].iloc[last_idx])
            tick_val = get_tw_tick(float(df["close"].iloc[last_idx - 1])) if last_idx >= 1 else 0.5
            trig_p = prev_l - tick_val
            recent_signals.append(f"觸發 Low 1 (L1) 初次反彈破前低（跌破價位: {trig_p:.2f} 元，前低: {prev_l:.2f} 元）")
            bpa_extra_score -= 1
        elif df["bpa_l3"].tail(2).any():
            idx_list = df.index[df["bpa_l3"]].tolist()
            last_idx = idx_list[-1] if idx_list else len(df) - 1
            prev_l = float(df["low"].iloc[last_idx - 1]) if last_idx >= 1 else float(df["low"].iloc[last_idx])
            tick_val = get_tw_tick(float(df["close"].iloc[last_idx - 1])) if last_idx >= 1 else 0.5
            trig_p = prev_l - tick_val
            recent_signals.append(f"觸發 Low 3 (L3) 楔形空頭旗形跌破（跌破價位: {trig_p:.2f} 元）")
            bpa_extra_score -= 1
            
        if df["bpa_ema_pb"].tail(2).any() and always_in_code == "AIS":
            recent_signals.append(f"20 EMA 動態壓力回測確認（反壓價: {ema_v:.2f} 元，順勢放空點）")
            bpa_extra_score -= 1
            
        if df["bpa_bear_gap"].tail(2).any():
            recent_signals.append(f"出現空頭 20 EMA 乖離缺口棒（當前負乖離: {(c-ema_v)/ema_v*100:.1f}%，留意動能竭盡反彈）⚠️")
            bpa_extra_score -= 1

    # 7.2.3 中性結構（形態壓縮與混亂區）
    if df["double_inside"].tail(2).any():
        recent_signals.append(f"出現雙重孕線（ii 壓縮區間: {df['low'].iloc[-1]:.2f} ~ {df['high'].iloc[-1]:.2f} 元，變盤在即）⚑")
    if is_ttr:
        ttr_l = df['low'].tail(5).min()
        ttr_h = df['high'].tail(5).max()
        recent_signals.append(f"陷入 TTR 窄幅震盪整理（區間: {ttr_l:.2f} ~ {ttr_h:.2f} 元，突破易失敗，嚴禁追價）⛔")
        bpa_extra_score -= 1
        
    # 7.3 最新訊號棒（Signal Bar）與掛單風控價位
    sig_high = df["high"].iloc[-1]
    sig_low  = df["low"].iloc[-1]
    tick = get_tw_tick(c)
    
    buy_stop  = round(sig_high + tick, 2)
    sell_stop = round(sig_low - tick, 2)
    risk_long = round(buy_stop - sell_stop, 2)
    target_long_1r = round(buy_stop + risk_long, 2)
    target_long_2r = round(buy_stop + 2 * risk_long, 2)
    
    risk_short = round(buy_stop - sell_stop, 2)
    target_short_1r = round(sell_stop - risk_short, 2)
    target_short_2r = round(sell_stop - 2 * risk_short, 2)
    
    return {
        "always_in": always_in,
        "always_in_code": always_in_code,
        "always_in_zh": always_in_zh,
        "always_in_desc": always_in_desc,
        "always_in_score": always_in_score,
        "last_bar_type": last_bar_type,
        "signals": recent_signals,
        "bpa_extra_score": bpa_extra_score,
        "ema_slope": ema_slope,
        "bias_ema20": (c - ema_v) / ema_v * 100,
        "sig_high": sig_high,
        "sig_low": sig_low,
        "tick": tick,
        "buy_stop": buy_stop,
        "sell_stop": sell_stop,
        "risk_long": risk_long,
        "target_long_1r": target_long_1r,
        "target_long_2r": target_long_2r,
        "risk_short": risk_short,
        "target_short_1r": target_short_1r,
        "target_short_2r": target_short_2r,
        "is_ttr": is_ttr
    }

