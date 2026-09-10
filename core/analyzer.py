# -*- coding: utf-8 -*-
"""主要對外入口：整合資料擷取、指標計算、BPA / VPA / 趨勢 / 綜合評級與繪圖，
組成單一分析結果。這是原 kline.py 的公開 API 表面，其餘模組都是它的實作細節。

對外函式：
  - analyze_stock(ticker, ...)     日線完整分析（含圖表 HTML、報表輸出）
  - analyze_stock_5m(ticker, ...)  5 分鐘線短線複合評估
"""
import sys
import argparse
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from core.constants import MA_DAYS, VOL_MA
from core.data_fetch import (
    get_info, fetch_twse, fetch_from_yfinance, fetch_otc,
    fetch_realtime_bar, fetch_institutional, fetch_fundamentals,
)
from core.indicators import get_tw_tick
from core.strategy_brooks import evaluate_brooks_price_action
from core.strategy_volume import evaluate_volume_price
from core.strategy_trend import evaluate_professional_trend
from core.rating import get_rating_badge, evaluate_composite_rating
from core.charting import build_stock_chart


def classify_candlestick_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """
    對價格序列進行逐根 K 線形態與 Al Brooks 價格行為學（BPA）特徵識別。

    規格說明：
      - 趨勢棒 (Trend Bars)：實體佔比 >= 50%，收於高點或低點 25% 範圍內。
      - 反轉棒 (Reversal Bars)：影線拒絕 >= 35%，收盤朝有利方向 (>= 60% / <= 40%)。
      - 孕線 (i)、雙重孕線 (ii 突破模式)、外部棒 (o)、十字星 (Doji)。
      - 多空推動計數 (H1/H2/H3, L1/L2/L3)：量化系統採用之「10-Bar 滾動回撤波段計數器（Swing-Window Pullback Classifier）」，
        將 Al Brooks 的多空推動與回撤測試原則轉化為確定性離散狀態機，非人工肉眼之 tick-by-tick 微觀計數。
      - 20 EMA Pullback 與 Gap Bar 缺口棒。
      - 窄幅震盪帶 (TTR / Barbwire 鐵絲網)。
      - Wyckoff 放量突破、量縮回踩、窒息量 (Dryup)、高檔換手滯漲 (Churn)。
      - 多空吞噬 (Engulfing)、鎚頭線 (Hammer)、流星線 (Shooting Star)。
      - RSI / MACD 頂底背離。
    """
    df = df.copy()
    close_arr = df["close"].values.astype(float)
    open_arr  = df["open"].values.astype(float)
    high_arr  = df["high"].values.astype(float)
    low_arr   = df["low"].values.astype(float)
    N         = len(df)

    vol_arr    = df["volume"].values.astype(float) if "volume" in df.columns else np.zeros(N, dtype=float)
    vol_ma_arr = df["vol_ma"].values.astype(float) if "vol_ma" in df.columns else (
        df["volume"].rolling(5, min_periods=1).mean().values.astype(float) if "volume" in df.columns else np.ones(N, dtype=float)
    )
    ma5_arr    = df["ma5"].values.astype(float) if "ma5" in df.columns else df["close"].rolling(5, min_periods=1).mean().values.astype(float)
    ema20_arr  = df["ema20"].values.astype(float) if "ema20" in df.columns else df["close"].ewm(span=20, adjust=False).mean().values.astype(float)

    # K 線實體與上下影線
    body_arr     = np.abs(close_arr - open_arr)
    candle_range = np.maximum(high_arr - low_arr, 1e-5)
    upper_shadow = high_arr - np.maximum(open_arr, close_arr)
    lower_shadow = np.minimum(open_arr, close_arr) - low_arr

    # 5.1 BPA K 線逐根分類（Bar-by-Bar Classification）
    # 趨勢棒 (Trend Bars)：實體佔比 >= 50%，收於高點或低點 25% 範圍內
    bpa_bull_trend = (close_arr > open_arr) & (body_arr / candle_range >= 0.50) & (close_arr >= high_arr - 0.25 * candle_range)
    bpa_bear_trend = (close_arr < open_arr) & (body_arr / candle_range >= 0.50) & (close_arr <= low_arr + 0.25 * candle_range)

    # 反轉棒 (Reversal Bars)：影線顯著拒絕 (>=35%)，收盤朝有利方向 (>=60% / <=40%)
    bull_rev_bar = np.zeros(N, dtype=bool)
    bear_rev_bar = np.zeros(N, dtype=bool)
    for i in range(1, N):
        if (lower_shadow[i] >= 0.35 * candle_range[i]) and (close_arr[i] >= low_arr[i] + 0.60 * candle_range[i]) and (low_arr[i] <= low_arr[i-1] or low_arr[i] <= ema20_arr[i]):
            bull_rev_bar[i] = True
        if (upper_shadow[i] >= 0.35 * candle_range[i]) and (close_arr[i] <= low_arr[i] + 0.40 * candle_range[i]) and (high_arr[i] >= high_arr[i-1] or high_arr[i] >= ema20_arr[i]):
            bear_rev_bar[i] = True

    # 孕線 (Inside Bar `i`)、雙重孕線 (`ii 突破模式`)、外部棒 (`o`)、十字星 (Doji)
    inside_bar    = np.zeros(N, dtype=bool)
    double_inside = np.zeros(N, dtype=bool)
    outside_bar   = np.zeros(N, dtype=bool)
    doji_bar      = (body_arr / candle_range <= 0.25)

    for i in range(1, N):
        if high_arr[i] <= high_arr[i-1] and low_arr[i] >= low_arr[i-1]:
            inside_bar[i] = True
            if inside_bar[i-1]:
                double_inside[i] = True
        elif high_arr[i] > high_arr[i-1] and low_arr[i] < low_arr[i-1]:
            outside_bar[i] = True

    # 逐根分類標籤
    bar_types = []
    for i in range(N):
        tags = []
        if double_inside[i]:
            tags.append("雙重孕線(ii 突破模式)")
        elif inside_bar[i]:
            tags.append("孕線(Inside Bar)")
        elif outside_bar[i]:
            tags.append("外部棒(Outside Bar)")

        if bpa_bull_trend[i]:
            tags.append("多頭趨勢棒(Bull Trend)")
        elif bpa_bear_trend[i]:
            tags.append("空頭趨勢棒(Bear Trend)")
        elif bull_rev_bar[i]:
            tags.append("多頭反轉棒(Bull Reversal)")
        elif bear_rev_bar[i]:
            tags.append("空頭反轉棒(Bear Reversal)")
        elif doji_bar[i]:
            tags.append("十字猶豫棒(Doji)")

        if not tags:
            tags.append("普通K線(Trading Bar)")
        bar_types.append(" / ".join(tags))
    df["bpa_bar_type"] = bar_types

    # 5.2 Al Brooks 多空推動計數：High 1/2/3 (H1/H2/H3) 與 Low 1/2/3 (L1/L2/L3)
    bpa_h1 = np.zeros(N, dtype=bool)
    bpa_h2 = np.zeros(N, dtype=bool)
    bpa_h3 = np.zeros(N, dtype=bool)
    bpa_l1 = np.zeros(N, dtype=bool)
    bpa_l2 = np.zeros(N, dtype=bool)
    bpa_l3 = np.zeros(N, dtype=bool)

    h_count = 0
    in_bull_pb = False
    for i in range(1, N):
        recent_high = high_arr[max(0, i-10):i].max()
        if high_arr[i] >= recent_high:
            h_count = 0
            in_bull_pb = False
        elif high_arr[i] < high_arr[i-1]:
            in_bull_pb = True
        elif in_bull_pb and high_arr[i] > high_arr[i-1]:
            h_count += 1
            if h_count == 1:
                bpa_h1[i] = True
            elif h_count == 2:
                bpa_h2[i] = True
            elif h_count >= 3:
                bpa_h3[i] = True
            in_bull_pb = False

    l_count = 0
    in_bear_bounce = False
    for i in range(1, N):
        recent_low = low_arr[max(0, i-10):i].min()
        if low_arr[i] <= recent_low:
            l_count = 0
            in_bear_bounce = False
        elif low_arr[i] > low_arr[i-1]:
            in_bear_bounce = True
        elif in_bear_bounce and low_arr[i] < low_arr[i-1]:
            l_count += 1
            if l_count == 1:
                bpa_l1[i] = True
            elif l_count == 2:
                bpa_l2[i] = True
            elif l_count >= 3:
                bpa_l3[i] = True
            in_bear_bounce = False

    df["bpa_h1"] = bpa_h1
    df["bpa_h2"] = bpa_h2
    df["bpa_h3"] = bpa_h3
    df["bpa_l1"] = bpa_l1
    df["bpa_l2"] = bpa_l2
    df["bpa_l3"] = bpa_l3

    # 5.3 20 EMA Pullback (EMA 20 初次回測)
    bpa_ema_pb = np.zeros(N, dtype=bool)
    for i in range(8, N):
        if np.sum(close_arr[i-8:i] > ema20_arr[i-8:i]) >= 6:
            # 多頭回測守穩：低點碰到 EMA 附近（+0.5% 容差），收盤仍守住 EMA 上方（容忍 0.3% 跌穿）
            if low_arr[i] <= ema20_arr[i] * 1.005 and close_arr[i] >= ema20_arr[i] * 0.997:
                bpa_ema_pb[i] = True
        elif np.sum(close_arr[i-8:i] < ema20_arr[i-8:i]) >= 6:
            # 空頭反彈觸壓：高點觸到 EMA 附近（-0.5% 容差），收盤仍在 EMA 下方（容忍 0.3% 突穿）
            if high_arr[i] >= ema20_arr[i] * 0.995 and close_arr[i] <= ema20_arr[i] * 1.003:
                bpa_ema_pb[i] = True
    df["bpa_ema_pb"] = bpa_ema_pb

    # 5.4 20 EMA Gap Bar (Brooks 缺口棒)
    bpa_bull_gap = np.zeros(N, dtype=bool)
    bpa_bear_gap = np.zeros(N, dtype=bool)
    for i in range(10, N):
        if np.sum(close_arr[i-10:i] > ema20_arr[i-10:i]) >= 7:
            if high_arr[i] < ema20_arr[i] and not (high_arr[i-1] < ema20_arr[i-1]):
                bpa_bull_gap[i] = True
        elif np.sum(close_arr[i-10:i] < ema20_arr[i-10:i]) >= 7:
            if low_arr[i] > ema20_arr[i] and not (low_arr[i-1] > ema20_arr[i-1]):
                bpa_bear_gap[i] = True
    df["bpa_bull_gap"] = bpa_bull_gap
    df["bpa_bear_gap"] = bpa_bear_gap

    # 5.5 Tight Trading Range (TTR / Barbwire 鐵絲網)
    bpa_ttr = np.zeros(N, dtype=bool)
    for i in range(2, N):
        overlap_h = min(high_arr[i], high_arr[i-1], high_arr[i-2])
        overlap_l = max(low_arr[i], low_arr[i-1], low_arr[i-2])
        if overlap_h > overlap_l:
            overlap_range = overlap_h - overlap_l
            avg_range = np.mean(candle_range[i-2:i+1])
            if (overlap_range / avg_range > 0.45) and (np.mean(body_arr[i-2:i+1] / candle_range[i-2:i+1]) < 0.40):
                bpa_ttr[i] = True
    df["bpa_ttr"]        = bpa_ttr
    df["inside_bar"]     = inside_bar
    df["outside_bar"]    = outside_bar
    df["doji_bar"]       = doji_bar
    df["double_inside"]  = double_inside
    df["bull_rev_bar"]   = bull_rev_bar
    df["bear_rev_bar"]   = bear_rev_bar

    # 5.6 經典 Wyckoff & 量價特徵
    high20 = np.array([high_arr[max(0,i-20):i].max() if i > 0 else high_arr[0] for i in range(N)])
    breakout = np.zeros(N, dtype=bool)
    breakout[1:] = (close_arr[1:] > high20[1:]) & (vol_arr[1:] > 1.5 * vol_ma_arr[1:])
    pullback = (np.abs(close_arr - ma5_arr) / ma5_arr < 0.015) & (vol_arr < 0.75 * vol_ma_arr)
    dryup    = vol_arr < 0.45 * vol_ma_arr
    churn    = (vol_arr > 1.8 * vol_ma_arr) & ((upper_shadow / candle_range > 0.4) | (body_arr / candle_range < 0.25))

    # 多空吞噬 (Engulfing)
    bull_engulf = np.zeros(N, dtype=bool)
    bear_engulf = np.zeros(N, dtype=bool)
    for i in range(1, N):
        if (close_arr[i-1] < open_arr[i-1]) and (close_arr[i] > open_arr[i]):
            if open_arr[i] <= close_arr[i-1] and close_arr[i] >= open_arr[i-1]:
                bull_engulf[i] = True
        elif (close_arr[i-1] > open_arr[i-1]) and (close_arr[i] < open_arr[i]):
            if open_arr[i] >= close_arr[i-1] and close_arr[i] <= open_arr[i-1]:
                bear_engulf[i] = True

    hammer = (lower_shadow >= 2.0 * body_arr) & (upper_shadow <= 0.15 * candle_range)
    star   = (upper_shadow >= 2.0 * body_arr) & (lower_shadow <= 0.15 * candle_range)

    # 指標頂底背離
    rsi_arr  = df["rsi"].values.astype(float) if "rsi" in df.columns else np.zeros(N, dtype=float)
    bull_div = np.zeros(N, dtype=bool)
    bear_div = np.zeros(N, dtype=bool)
    for i in range(15, N):
        if close_arr[i] < close_arr[i-15:i].min():
            if rsi_arr[i] > rsi_arr[i-15:i].min() + 2:
                bull_div[i] = True
        if close_arr[i] > close_arr[i-15:i].max():
            if rsi_arr[i] < rsi_arr[i-15:i].max() - 2:
                bear_div[i] = True

    df["breakout"]    = breakout
    df["pullback"]    = pullback
    df["dryup"]       = dryup
    df["churn"]       = churn
    df["bull_engulf"] = bull_engulf
    df["bear_engulf"] = bear_engulf
    df["hammer"]      = hammer
    df["star"]        = star
    df["bull_div"]    = bull_div
    df["bear_div"]    = bear_div

    return df


def analyze_stock(ticker, months=12, cost=None, custom_name=None, generate_html=True, print_report=True, quick_mode=False, display_months=None, **kwargs):
    ticker = str(ticker).strip()
    market, auto_name = get_info(ticker)
    stock_name = custom_name if custom_name else auto_name

    # 確保技術指標載入充足歷史資料（固定至少 12 個月以避免 MA60/MACD/RSI 計算失真）
    fetch_months = max(months, 12) if months else 12
    # 若未指定 display_months，則預設 display_months 為 1（圖表只顯示近 1 個月保持清爽）
    if display_months is None:
        display_months = months if (months and months <= 6) else 1

    if print_report:
        print(f"[INFO] {ticker}（{stock_name}）| {'上市(TSE)' if market=='tse' else '上櫃(OTC)'}")
        print(f"下載近 {fetch_months} 個月歷史資料運算指標（圖表呈現近 {display_months} 個月）...")

    records = []
    if market == "tse":
        records = fetch_twse(ticker, fetch_months)
        if not records:
            if print_report:
                print(f"[WARN] TWSE 官方 API 未能取得 {ticker} 資料，啟動 yfinance (.TW) 備援...")
            records = fetch_from_yfinance(f"{ticker}.TW", fetch_months)
    else:
        records = fetch_otc(ticker, fetch_months)
        if not records:
            if print_report:
                print(f"[WARN] yfinance (.TWO) 未能取得 {ticker} 資料，嘗試 (.TW)...")
            records = fetch_from_yfinance(f"{ticker}.TW", fetch_months)

    # 交叉最後備援：若仍無資料，嘗試對向市場代號
    if not records:
        alt_sym = f"{ticker}.TWO" if market == "tse" else f"{ticker}.TW"
        records = fetch_from_yfinance(alt_sym, fetch_months)
        if records:
            market = "otc" if alt_sym.endswith(".TWO") else "tse"

    if not records:
        raise ValueError(f"查無 {ticker} 資料，請確認代號是否正確。")

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna().sort_values("date").drop_duplicates("date").reset_index(drop=True)
    if print_report:
        print(f"[OK] 取得 {len(df)} 筆，{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")

    realtime_info = None
    rt_row = fetch_realtime_bar(ticker, market)
    if rt_row:
        if rt_row["date"] > df["date"].iloc[-1]:
            df = pd.concat([df, pd.DataFrame([{
                "date": rt_row["date"],
                "open": rt_row["open"],
                "high": rt_row["high"],
                "low": rt_row["low"],
                "close": rt_row["close"],
                "volume": rt_row["volume"]
            }])], ignore_index=True)
            realtime_info = rt_row
            if print_report:
                tag = f"盤中即時 {rt_row['time']}" if rt_row["is_realtime"] else "收盤定盤"
                print(f"[OK] 補上今日最新行情（{tag}，來自 {rt_row['source']}）：{rt_row['close']:.2f} 元 ｜ 成交量 {rt_row['volume']:,.0f} 張")
        elif rt_row["date"] == df["date"].iloc[-1] and rt_row.get("is_realtime"):
            idx = len(df) - 1
            df.loc[idx, "close"] = rt_row["close"]
            df.loc[idx, "high"] = max(df.loc[idx, "high"], rt_row["high"])
            df.loc[idx, "low"] = min(df.loc[idx, "low"], rt_row["low"])
            df.loc[idx, "volume"] = rt_row["volume"]
            realtime_info = rt_row
            if print_report:
                print(f"[OK] 動態更新今日盤中即時行情（{rt_row['time']}，來自 {rt_row['source']}）：{rt_row['close']:.2f} 元 ｜ 成交量 {rt_row['volume']:,.0f} 張")

    # ── 4. 技術指標計算 ───────────────────────────────────────────
    # 移動平均線
    for n in MA_DAYS:
        df[f"ma{n}"] = df["close"].rolling(n, min_periods=min(n, 20)).mean()
    df["vol_ma"] = df["volume"].rolling(VOL_MA, min_periods=min(VOL_MA, 5)).mean()

    # 20 EMA（Al Brooks 唯一指定核心基準線）
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

    # RSI(14)
    _delta    = df["close"].diff()
    _gain     = _delta.clip(lower=0)
    _loss     = -_delta.clip(upper=0)
    _avg_gain = _gain.ewm(com=13, adjust=False).mean()
    _avg_loss = _loss.ewm(com=13, adjust=False).mean()
    df["rsi"] = 100 - (100 / (1 + _avg_gain / (_avg_loss + 1e-9)))

    # MACD(12, 26, 9)
    _ema12 = df["close"].ewm(span=12, adjust=False).mean()
    _ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"]        = _ema12 - _ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]

    # KD(9, 3, 3)
    _low9  = df["low"].rolling(9, min_periods=9).min()
    _high9 = df["high"].rolling(9, min_periods=9).max()
    df["kd_rsv"] = (df["close"] - _low9) / (_high9 - _low9 + 1e-9) * 100
    df["kd_k"]   = df["kd_rsv"].ewm(com=2, adjust=False).mean()
    df["kd_d"]   = df["kd_k"].ewm(com=2, adjust=False).mean()

    # Bollinger Bands(20, ±2σ)
    df["bb_mid"]   = df["close"].rolling(20, min_periods=20).mean()
    _bb_std        = df["close"].rolling(20, min_periods=20).std(ddof=0).fillna(0)
    df["bb_upper"] = df["bb_mid"] + 2 * _bb_std
    df["bb_lower"] = df["bb_mid"] - 2 * _bb_std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / (df["bb_mid"] + 1e-9) * 100

    # ── 5. Al Brooks 價格行為學（BPA）形態識別與量價特徵 ──────────────
    df = classify_candlestick_patterns(df)

    if quick_mode:
        inst_df = pd.DataFrame()
    else:
        if print_report:
            print("\n抓取三大法人資料中（近5個交易日）...")
        inst_df = fetch_institutional(ticker, market, days=5)
        if print_report:
            if not inst_df.empty:
                print(f"[OK] 取得 {len(inst_df)} 筆法人資料")
            else:
                print("[WARN] 無法取得三大法人資料（OTC 股票或資料不可用）")

    vol_eval = evaluate_volume_price(df)
    bpa_res = evaluate_brooks_price_action(df)
    import hmm_regime
    regime_info = hmm_regime.detect_market_regime(df)
    try:
        from core.market_regime import get_market_regime_status
        market_regime = get_market_regime_status()
    except Exception:
        market_regime = {}

    if quick_mode:
        fundamentals = {}
        composite_rating = None
    else:
        fundamentals = fetch_fundamentals(ticker, market=market)
        composite_rating = evaluate_composite_rating(df, bpa_res, vol_eval, inst_df, fundamentals, ticker, market, regime_info=regime_info, market_regime=market_regime)


    trend_score, trend_stage, trend_factors = evaluate_professional_trend(df, inst_df, bpa_res, vol_eval)
    rating_badge = get_rating_badge(trend_score)

    close_now = df["close"].iloc[-1]
    r1 = round(df["high"].tail(20).max(), 2)
    r2 = round(df["bb_upper"].iloc[-1], 2)
    s1 = round(df["ma20"].iloc[-1], 2)
    s2 = round(df["low"].tail(20).min(), 2)
    stop_loss = round(s2 * 0.985, 2)

    # ── 8. Plotly 互動圖表繪製 ──────────────────────────────────
    fig = None
    if not quick_mode:
        fig = build_stock_chart(ticker, stock_name, df, cost, close_now, trend_score, rating_badge, r1, r2, s1, s2, stop_loss, display_months=display_months)

    output = f"{ticker}_kline.html"
    if generate_html and fig is not None:
        fig.write_html(output)
        if print_report:
            print(f"\n[OK] 圖表已輸出 -> {output}")

    if print_report:
        # ── 9. 專業多維研判報表輸出 ───────────────────────────────────
        print("\n" + "="*70)
        rt_badge = f" [⚡ 盤中即時 {realtime_info['time']}]" if (realtime_info and realtime_info.get("is_realtime")) else " [📅 盤後結算]"
        print(f"  📊 {stock_name}（{ticker}）專業多維量價籌碼 + Al Brooks BPA 研判報表{rt_badge}")
        print("="*70)
        print(f"  📅 分析區間 ：{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}{rt_badge}")
        price_label = f"最新盤中現價（{realtime_info['time']}）" if (realtime_info and realtime_info.get("is_realtime")) else "最新收盤"
        print(f"  💰 {price_label} ：{close_now:.2f} 元")
        if cost is not None:
            pnl_amt = close_now - cost
            pnl_pct = pnl_amt / cost * 100
            sign = "+" if pnl_amt >= 0 else ""
            print(f"  🎯 持有成本 ：{cost:.2f} 元 ｜ 浮動損益：{sign}{pnl_amt:.2f} 元（{sign}{pnl_pct:.1f}%）")

        print(f"\n  ── 📌 核心技術指標數據 ─────────────────────────────────")
        print(f"  均線位階  ：EMA20={df['ema20'].iloc[-1]:.2f} ｜ MA5={df['ma5'].iloc[-1]:.2f} ｜ MA20={df['ma20'].iloc[-1]:.2f} ｜ MA60={df['ma60'].iloc[-1]:.2f}")
        print(f"  布林通道  ：上軌={r2:.2f} ｜ 中軌={df['bb_mid'].iloc[-1]:.2f} ｜ 下軌={df['bb_lower'].iloc[-1]:.2f}（頻寬={df['bb_width'].iloc[-1]:.1f}%）")
        print(f"  動量指標  ：MACD={df['macd'].iloc[-1]:+.2f} ｜ Signal={df['macd_signal'].iloc[-1]:+.2f} ｜ 柱體={df['macd_hist'].iloc[-1]:+.2f}")
        print(f"  震盪指標  ：RSI(14)={df['rsi'].iloc[-1]:.1f} ｜ KD(9,3,3) K={df['kd_k'].iloc[-1]:.1f} / D={df['kd_d'].iloc[-1]:.1f}")
        print(f"  成交量能  ：今日={df['volume'].iloc[-1]:,.0f} 張 ｜ 20日均量={df['vol_ma'].iloc[-1]:,.0f} 張")

        print(f"\n  ── 📊 量價關係與動能深度評估 ──────────────────────────")
        print(f"  量價狀態  ：{vol_eval['status']}（評分 {vol_eval['score']:+d}分）")
        print(f"  成交量能  ：今日={vol_eval['vol_now']:,.0f} 張 ｜ 20MA均量={vol_eval['vol_ma20']:,.0f} 張（量比 {vol_eval['vol_ratio_20']*100:.1f}%） ｜ 5MA均量={vol_eval['vol_ma5']:,.0f} 張")
        print(f"  量價診斷  ：{vol_eval['desc']}")
        print(f"  操盤建議  ：{vol_eval['advice']}")

        if not inst_df.empty:
            print(f"\n  ── 🏛️ 近 5 日三大法人籌碼分佈（張）───────────────────")
            for _, r in inst_df.tail(5).iterrows():
                print(f"  {r['date'].strftime('%m/%d')}  "
                      f"外資:{r['fini']:>+6,} ｜ 投信:{r['trust']:>+5,} ｜ 自營:{r['dealer']:>+5,} ｜ "
                      f"三大合計:{r['total']:>+6,}")

        print(f"\n  ── 📘 Al Brooks 價格行為學（BPA）量化研判 ───────────────")
        print(f"  市場狀態 (Always-In) ：{bpa_res['always_in']}")
        print(f"  當前 K 線結構        ：{bpa_res['last_bar_type']}")
        print(f"  20 EMA 動態位階      ：現價 {close_now:.2f} ｜ 20 EMA={df['ema20'].iloc[-1]:.2f}（乖離率 {bpa_res['bias_ema20']:+.2f}%，斜率 {bpa_res['ema_slope']:+.2f}%）")
        if bpa_res['signals']:
            print(f"  BPA 關鍵型態與設定   ：")
            for sig in bpa_res['signals']:
                print(f"    • {sig}")
        else:
            print(f"  BPA 關鍵型態與設定   ：近幾日無高勝率特殊設定，順應 20 EMA（{df['ema20'].iloc[-1]:.2f} 元）趨勢動態運行")

        print(f"\n  ── 🎯 Brooks 操盤訂單與停損風控指引 ───────────────────────")
        if bpa_res['always_in_code'] == 'AIL':
            print(f"  偏多操作策略 (AIL)   ：多頭主控，順應 20 EMA（{df['ema20'].iloc[-1]:.2f} 元）架構，拉回逢低佈局，或以突破買進價 {bpa_res['buy_stop']:.2f} 元進場")
            print(f"  • 訊號棒極值 (Signal Bar)   ：高 {bpa_res['sig_high']:.2f} ｜ 低 {bpa_res['sig_low']:.2f} ｜ 震幅 {bpa_res['sig_high']-bpa_res['sig_low']:.2f} 元")
            print(f"  • 多方突破進場 (Buy Stop)   ：{bpa_res['buy_stop']:.2f} 元（突破訊號棒高點啟動）")
            print(f"  • 多方防守停損 (Prot Stop)  ：{bpa_res['sell_stop']:.2f} 元（跌破訊號棒低點，風險 {bpa_res['risk_long']:.2f} 元）")
            print(f"  • 等距測量目標 (MM 1R / 2R) ：目標一 {bpa_res['target_long_1r']:.2f} 元 ｜ 目標二 {bpa_res['target_long_2r']:.2f} 元")
        elif bpa_res['always_in_code'] == 'AIS':
            print(f"  偏空操作策略 (AIS)   ：空方主控，受制 20 EMA（{df['ema20'].iloc[-1]:.2f} 元）反壓，持股者逢高調節，空方以跌破放空價 {bpa_res['sell_stop']:.2f} 元順勢佈局")
            print(f"  • 訊號棒極值 (Signal Bar)   ：高 {bpa_res['sig_high']:.2f} ｜ 低 {bpa_res['sig_low']:.2f} ｜ 震幅 {bpa_res['sig_high']-bpa_res['sig_low']:.2f} 元")
            print(f"  • 空方跌破進場 (Sell Stop)  ：{bpa_res['sell_stop']:.2f} 元（跌破訊號棒低點啟動）")
            print(f"  • 空方防守停損 (Prot Stop)  ：{bpa_res['buy_stop']:.2f} 元（突破訊號棒高點，風險 {bpa_res['risk_short']:.2f} 元）")
            print(f"  • 等距測量目標 (MM 1R / 2R) ：目標一 {bpa_res['target_short_1r']:.2f} 元 ｜ 目標二 {bpa_res['target_short_2r']:.2f} 元")
        else:
            print(f"  區間震盪策略 (TR)    ：【80% 法則】80% 的區間突破會失敗！嚴禁盲目追高殺低")
            print(f"  • 操作準則 (BLSHS)   ：Buy Low, Sell High, Scalp（低買高賣短沖，接近 S1/S2（{s1:.2f} / {s2:.2f} 元）買，接近 R1/R2（{r1:.2f} / {r2:.2f} 元）賣）")
            if bpa_res['is_ttr']:
                print(f"  • 鐵絲網警示 (Barbwire)：目前處於密集重疊區，多空雙巴機率極高，強烈建議空手觀望！")

        print(f"\n  ── 🎯 關鍵支撐與壓力矩陣 ───────────────────────────────")
        print(f"  壓力二 (R2 - 布林上軌/波段頂)：{r2:.2f} 元")
        print(f"  壓力一 (R1 - 近20日高點)    ：{r1:.2f} 元")
        print(f"  目前現價                    ：{close_now:.2f} 元")
        print(f"  支撐一 (S1 - 月線支撐)      ：{s1:.2f} 元")
        print(f"  支撐二 (S2 - 近20日低點)    ：{s2:.2f} 元")
        print(f"  防守停損線 (Stop-Loss Pivot)：{stop_loss:.2f} 元（跌破宜果斷執行）")

        print(f"\n  ── 🧭 多維量化評估綜合研判 ─────────────────────────────")
        print(f"  綜合評分 ：{trend_score:+d} 分 ｜ 評級：{rating_badge} (參考指標)")
        for f_item in trend_factors:
            print(f"  • {f_item}")
        if composite_rating and composite_rating.get("is_stage4_bear"):
            print(f"  • ⚠️ [標的池風控硬警示] 本標的處於 Stage 4 衰退/空頭形態（年線下彎且股價在年線下），依風控規範禁止開多單！")
        if market_regime and market_regime.get("status_desc"):
            print(f"  • 宏觀環境：{market_regime['status_desc']}")
        print(f"  • 建議評估週期：40 ~ 60 個交易日（中線波段動能策略，非極短線當沖）")

        print(f"\n  ── 💡 操盤行動指引 ─────────────────────────────────────")
        ma60_val = df['ma60'].iloc[-1]
        if trend_score >= 3:
            print(f"  【持股者】趨勢偏多，多頭結構穩健，建議續抱並以 S1（{s1:.2f} 元，月線）作為移動停利點。")
            print(f"  【空手者】逢拉回量縮測試 S1（{s1:.2f} 元）守穩時可分批建立部位，突破 R1（{r1:.2f} 元）放量加碼。")
        elif trend_score <= -3:
            print(f"  【持股者】趨勢偏空且空方動能增強，反彈遇 R1（{r1:.2f} 元）/ MA60季線（{ma60_val:.2f} 元）宜逢高減碼，跌破防守線（{stop_loss:.2f} 元）務必停損。")
            print(f"  【空手者】暫勿盲目猜底接刀，靜待打底完成或出現帶量底背離反轉再進場。")
        else:
            print(f"  【持股者】短線處於區間震盪打底，未跌破防守線（{stop_loss:.2f} 元）前可暫時觀望，密切留意法人籌碼延續性。")
            print(f"  【空手者】觀望為主，靜待帶量突破 R1（{r1:.2f} 元）壓力或回測 S2（{s2:.2f} 元）底部確認再行佈局。")
        print("="*70)

    return {
        "ticker": ticker,
        "stock_name": stock_name,
        "market": market,
        "df": df,
        "inst_df": inst_df,
        "vol_eval": vol_eval,
        "fundamentals": fundamentals,
        "composite_rating": composite_rating,
        "realtime_info": realtime_info,
        "fig": fig,
        "close_now": close_now,
        "cost": cost,
        "trend_score": trend_score,
        "rating_badge": rating_badge,
        "trend_stage": trend_stage,
        "trend_factors": trend_factors,
        "bpa_res": bpa_res,
        "sr_levels": {
            "r2": r2, "r1": r1, "s1": s1, "s2": s2, "stop_loss": stop_loss, "close_now": close_now
        },
        "regime_info": regime_info,
        "market_regime": market_regime,
        "time_horizon": "40~60 交易日（波段動能跟隨策略）",
        "is_stage4_bear": composite_rating.get("is_stage4_bear", False) if composite_rating else False,
        "is_market_bear": market_regime.get("is_market_bear", False) if market_regime else False,
        "display_months": display_months,
        "output_html": output if generate_html else None
    }




def analyze_stock_5m(ticker, days=3, custom_name=None):
    """
    台股 5 分鐘 K 線 Al Brooks 價格行為學（BPA）極速日內分析
    包含：5m 20 EMA、開盤區間、反轉棒識別、Always-In 多空定調與 Tick 級風控掛單
    """
    ticker = str(ticker).strip()
    market, auto_name = get_info(ticker)
    stock_name = custom_name if custom_name else auto_name

    sym = f"{ticker}.TW" if market == "tse" else f"{ticker}.TWO"
    raw = yf.download(sym, interval="5m", period=f"{days}d", progress=False)
    if raw is None or raw.empty:
        sym_alt = f"{ticker}.TWO" if market == "tse" else f"{ticker}.TW"
        raw = yf.download(sym_alt, interval="5m", period=f"{days}d", progress=False)
    if raw is None or raw.empty:
        raise ValueError(f"無法取得 {ticker} 的 5 分鐘 K 線數據。")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [c.lower() for c in raw.columns]
    df = raw.reset_index()

    # 轉為台灣時區 (Asia/Taipei)
    if "Datetime" in df.columns:
        dt_col = "Datetime"
    elif "datetime" in df.columns:
        dt_col = "datetime"
    else:
        dt_col = df.columns[0]

    if df[dt_col].dt.tz is None:
        df["date"] = df[dt_col].dt.tz_localize("UTC").dt.tz_convert("Asia/Taipei")
    else:
        df["date"] = df[dt_col].dt.tz_convert("Asia/Taipei")

    df["volume"] = df["volume"] / 1000.0  # 轉為張數
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

    # 今日數據統計
    today_date = df["date"].iloc[-1].date()
    df_today = df[df["date"].dt.date == today_date]

    close_now = float(df["close"].iloc[-1])
    open_today = float(df_today["open"].iloc[0]) if not df_today.empty else close_now
    high_today = float(df_today["high"].max()) if not df_today.empty else close_now
    low_today = float(df_today["low"].min()) if not df_today.empty else close_now
    range_today = round(high_today - low_today, 2)
    change_today = round(close_now - open_today, 2)
    change_today_pct = round(change_today / (open_today + 1e-9) * 100, 2)

    # 5m 20 EMA 乖離
    ema_now = float(df["ema20"].iloc[-1])
    ema_bias = round(close_now - ema_now, 2)
    ema_bias_pct = round(ema_bias / (ema_now + 1e-9) * 100, 2)

    # 5m BPA Always-In 多空動態狀態
    c = df["close"]
    ema = df["ema20"]
    # 使用 8 根棒（≈40分鐘）斜率，避免 4 根（15分鐘）過短導致多空頻繁翻轉
    # 閾值提升至 ±0.15%，與日K evaluate_brooks_price_action 標準一致
    slope = (ema.iloc[-1] - ema.iloc[-8]) / (ema.iloc[-8] + 1e-9) * 100 if len(ema) >= 8 else 0

    if c.iloc[-1] > ema.iloc[-1] and slope > 0.15:
        bpa_status = "多頭主控（拉回逢低做多）"
        bpa_status_color = "#4ade80"
        bpa_bg = "rgba(34, 197, 94, 0.2)"
        bpa_guide = f"目前 5 分K 處於順勢多方軌道，站穩 20 EMA（{ema_now:.2f} 元）之上，拉回守穩可順勢佈局。"
    elif c.iloc[-1] < ema.iloc[-1] and slope < -0.15:
        bpa_status = "空方主導（反彈逢高做空）"
        bpa_status_color = "#f87171"
        bpa_bg = "rgba(239, 68, 68, 0.2)"
        bpa_guide = f"目前 5 分K 受制 20 EMA（{ema_now:.2f} 元）反壓，空方主控，反彈未突破均線前切忌急搶反彈。"
    else:
        bpa_status = "箱型震盪（區間高出低進）"
        bpa_status_color = "#fbbf24"
        bpa_bg = "rgba(245, 158, 11, 0.2)"
        bpa_guide = f"目前 5 分K 圍繞 20 EMA（{ema_now:.2f} 元）兩側走平，屬區間整理，嚴禁追高殺低。"

    # 最新 5 分K 棒形態分析
    last_bar = df.iloc[-1]
    bar_h = float(last_bar["high"])
    bar_l = float(last_bar["low"])
    bar_c = float(last_bar["close"])
    bar_o = float(last_bar["open"])
    rng = max(0.01, bar_h - bar_l)
    body = abs(bar_c - bar_o)

    # ── Conformal Prediction 符合預測：動態真實波幅 (ATR20_5m) 與雜訊非對稱度 ──
    # 計算近 20 根 5m 棒的真實波幅 True Range
    if len(df) >= 2:
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - df["close"].shift(1)).abs()
        tr3 = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr20_5m = float(tr.tail(20).mean()) if len(tr) >= 5 else rng
    else:
        atr20_5m = rng
    atr20_5m = max(0.01, atr20_5m)
    
    # 計算當前信號棒相對於常態波動的雜訊比 (Noise Ratio)
    noise_ratio = round(rng / atr20_5m, 2)
    # 置信度狀態評估 (Conformal Uncertainty Quantification)
    is_noise_extreme = noise_ratio > 2.8   # 單根波幅大於均幅 2.8 倍：失控巨震，置信區間過寬
    is_vol_dull = noise_ratio < 0.35      # 單根波幅小於均幅 0.35 倍：過度鈍化，假突破機率極高

    if body / rng >= 0.6:
        bar_type = "🟢 多頭趨勢棒 (Bull Trend)" if bar_c > bar_o else "🔴 空頭趨勢棒 (Bear Trend)"
    elif (min(bar_c, bar_o) - bar_l >= 0.5 * rng) and (bar_h - max(bar_c, bar_o) < 0.25 * rng):
        # 長下影線 + 短上影線，確認是真正的多頭反轉棒（排除 Spinning Top）
        bar_type = "🔨 多頭反轉下影棒 (Bull Reversal)"
    elif (bar_h - max(bar_c, bar_o) >= 0.5 * rng) and (min(bar_c, bar_o) - bar_l < 0.25 * rng):
        # 長上影線 + 短下影線，確認是真正的空頭反轉棒（排除 Spinning Top）
        bar_type = "☄️ 空頭反轉上影棒 (Bear Reversal)"
    elif body / rng <= 0.2:
        bar_type = "⚖️ 十字猶豫棒 (Doji)"
    else:
        bar_type = "⚪ 普通震盪棒 (Trading Bar)"

    # 台股 Tick 級風控與結構性波段掛單建議（結合波段擺動低點與防高頻超短線摩擦保護）
    tick = get_tw_tick(close_now)
    buy_stop = round(bar_h + tick, 2)
    sell_stop = round(bar_l - tick, 2)
    
    # 嚴防高頻微幅刷單（Anti-Scalping Protection）：
    # 台股交易摩擦成本（手續費+證交稅）約 0.45%~0.585%，單筆波段 R 空間必須至少為 1.8%，
    # 以確保扣除交易成本與滑價後仍具備健康正期望值，徹底拒絕 0.5%~0.71% 之微小高頻噪音。
    MIN_SWING_R_PCT = 0.018  # 1.8% 最低健康波段空間門檻
    min_buffer = max(3 * tick, round(close_now * MIN_SWING_R_PCT, 2))

    # 取得近 12 根 5m 棒（約 1 小時）之結構性波段低點 (Swing Low) 與高點 (Swing High)
    sw_len = min(len(df), 12)
    recent_sw_l = float(df["low"].tail(sw_len).min()) if sw_len > 0 else bar_l
    recent_sw_h = float(df["high"].tail(sw_len).max()) if sw_len > 0 else bar_h

    if "多" in bpa_status:
        # 多方防守停損：錨定結構性波段低點 (Swing Low)，並確保至少有 1.8% 波段防護空間
        raw_stop = min(bar_l - tick, recent_sw_l - tick)
        stop_loss = round(min(raw_stop, close_now - min_buffer), 2)
        r_val = round(max(min_buffer, close_now - stop_loss), 2)
        target_1r = round(close_now + r_val, 2)
        target_2r = round(close_now + 2 * r_val, 2)
        stop_type = "做多波段防守停損 (跌破結構低點認賠)"
        stop_direction = "-"
        entry_type = "突破買進價位 (Buy Stop)"
    elif "空" in bpa_status:
        # 空方防守停損：錨定結構性波段高點 (Swing High)，並確保至少有 1.8% 波段防護空間
        raw_stop = max(bar_h + tick, recent_sw_h + tick)
        stop_loss = round(max(raw_stop, close_now + min_buffer), 2)
        r_val = round(max(min_buffer, stop_loss - close_now), 2)
        target_1r = round(close_now - r_val, 2)
        target_2r = round(close_now - 2 * r_val, 2)
        stop_type = "放空波段防守停損 (突破結構高點停損)"
        stop_direction = "+"
        entry_type = "跌破放空價位 (Sell Stop)"
    else:
        # 震盪整理：以波段低點或最小緩衝防守
        stop_loss = round(close_now - min_buffer, 2)
        r_val = round(min_buffer, 2)
        target_1r = round(close_now + r_val, 2)
        target_2r = round(close_now + 2 * r_val, 2)
        stop_type = "區間波段防守停損 (跌破下緣停損)"
        stop_direction = "-"
        entry_type = "區間高出低進價位"

    # ── 多時框對齊 (Multi-Timeframe Alignment: MTF) ──
    # 取得日K級別核心架構與籌碼，落實大時框箝制小時框，嚴禁逆大趨勢盲目做多
    daily_res = None
    daily_always_code = "TR"
    daily_ma20 = close_now
    daily_trend_score = 0
    inst_net_3d = 0
    try:
        daily_res = analyze_stock(ticker, months=3, generate_html=False, print_report=False, quick_mode=True)
        if daily_res:
            b_res = daily_res.get("bpa_res", {})
            daily_always_code = b_res.get("always_in_code", "TR")
            daily_trend_score = daily_res.get("trend_score", 0)
            df_d = daily_res.get("df")
            if df_d is not None and not df_d.empty and "ma20" in df_d.columns:
                daily_ma20 = float(df_d["ma20"].iloc[-1])
            inst_df = daily_res.get("inst_df")
            if inst_df is not None and not inst_df.empty and "total" in inst_df.columns:
                inst_net_3d = int(inst_df["total"].tail(3).sum())
    except Exception as e:
        # kline.py 未引入 logging，統一沿用本檔既有的 print 警示風格；
        # 原本誤用未定義的 logger 會在此拋出 NameError，反而蓋掉真正的例外。
        print(f"  [WARN] 5分K多時框讀取日線異常：{e}")

    # 日線是否處於空方破線架構（AIS 或跌破日MA20達0.5%以上，或波段評分 <= -2）
    is_daily_bear = (daily_always_code == "AIS") or (close_now < daily_ma20 * 0.995) or (daily_trend_score <= -2)
    # 日線是否處於多頭主控架構（AIL 且站穩日MA20）
    is_daily_bull = (daily_always_code == "AIL") and (close_now >= daily_ma20 * 0.995)

    # ── 5m 當沖動作決策（多時框硬門檻 + Conformal 拒絕開倉機制） ──
    mtf_status = "中性整理"
    conformal_status = "充足 (合格)"
    
    if is_noise_extreme:
        # 情況 1: 雜訊波幅過大 (> 2.8x ATR)，置信區間發散，依符合預測原則主動拒絕交易
        action_tag_5m = "🛑 拒絕開倉 (雜訊過大)"
        action_sub_5m = f"當前 5m 波幅達均幅 {noise_ratio:.1f} 倍，隨機雜訊過大且置信區間發散，主動放棄開倉，嚴禁追價！"
        action_color_5m = "#f43f5e"
        conformal_status = f"⚠️ 雜訊過大 ({noise_ratio:.1f}x 均幅)"
    elif is_vol_dull:
        # 情況 2: 波動過度鈍化 (< 0.35x ATR)，動能不足，假突破風險高，波段空間狹窄
        action_tag_5m = "🛑 暫緩開倉 (動能不足/空間狹窄)"
        action_sub_5m = f"當前 5m 波幅僅均幅 {noise_ratio:.1f} 倍且波動過窄，扣除摩擦成本期望值偏低，拒絕高頻刷單，建議觀望。"
        action_color_5m = "#94a3b8"
        conformal_status = f"💤 波動過低 ({noise_ratio:.1f}x 均幅)"
    elif "多" in bpa_status:
        if is_daily_bear:
            # 日線空方架構下，5m 短彈禁止給出買進掛單，強制定調為逆勢弱彈，防誘多
            action_tag_5m = "⚠️ 逆日線弱彈 (觀望)"
            action_sub_5m = f"5m 短線雖在均線上，但受制日線空方架構 (日MA20: {daily_ma20:.2f}元)，嚴防假突破，切忌搶反彈！"
            action_color_5m = "#f59e0b"
            mtf_status = "⚠️ 逆日線弱彈（空方趨勢中的反彈）"
        elif is_daily_bull:
            action_tag_5m = "🔥 建議順勢做多"
            action_sub_5m = f"日線與 5m 雙時框多方共振！站穩 5m 20 EMA（{ema_now:.2f}元），拉回守穩可順勢佈局"
            action_color_5m = "#22c55e"
            mtf_status = "🟢 雙時框多方共振 (高勝率)"
        else:
            action_tag_5m = "🟢 建議偏多買進"
            action_sub_5m = f"順應 5m 20 EMA（{ema_now:.2f} 元）支撐拉回逢低買進"
            action_color_5m = "#22c55e"
            mtf_status = "🟢 偏多整理"
    elif "空" in bpa_status:
        if is_daily_bear:
            action_tag_5m = "🔴 雙時框順勢做空"
            action_sub_5m = f"日線與 5m 均處空方軌道，反彈逢 5m 20 EMA（{ema_now:.2f}元）反壓或破底順勢放空"
            action_color_5m = "#ef4444"
            mtf_status = "🔴 雙時框空方共振"
        else:
            action_tag_5m = "🔴 建議逢高做空"
            action_sub_5m = f"受制 5m 20 EMA（{ema_now:.2f} 元）反壓，反彈逢高或破底順勢放空"
            action_color_5m = "#ef4444"
            mtf_status = "🔴 偏空整理"
    else:
        action_tag_5m = "🟡 建議觀望整理"
        action_sub_5m = "日內箱型均線糾結，高出低進或暫不開倉"
        action_color_5m = "#fbbf24"
        mtf_status = "🟡 區間震盪整理"

    # 5m 20MA 成交量均線與主力爆量異動檢測
    df["vol_ma20"] = df["volume"].rolling(20, min_periods=1).mean()
    vol_now = float(df["volume"].iloc[-1])
    vol_ma20_5m = float(df["vol_ma20"].iloc[-1])
    vol_ratio_5m = round(vol_now / (vol_ma20_5m + 1e-9), 1)

    is_above_ema = close_now > ema_now
    is_bull_bar = bar_c > bar_o
    lower_sh = min(bar_c, bar_o) - bar_l
    upper_sh = bar_h - max(bar_c, bar_o)

    if vol_ratio_5m >= 1.8:
        if is_above_ema and slope > 0 and is_bull_bar and body / rng >= 0.5:
            whale_tag = "⚡ 主力放量推升"
            whale_color = "#38bdf8"
            whale_bg = "rgba(56, 189, 248, 0.16)"
            whale_advice = f"大單推升動能強勁，切忌追高，靜待回踩 20 EMA（{ema_now:.2f} 元）守穩再行介入。"
        elif not is_above_ema and is_bull_bar and body / rng >= 0.5:
            whale_tag = "⚠️ 空方反彈誘多"
            whale_color = "#fbbf24"
            whale_bg = "rgba(245, 158, 11, 0.16)"
            whale_advice = f"放量強彈但受制 20 EMA（{ema_now:.2f} 元）反壓（承壓率 70%），嚴防假突破，切勿搶反彈。"
        elif not is_above_ema and not is_bull_bar and body / rng >= 0.5:
            whale_tag = "🚨 主力爆量摜壓"
            whale_color = "#ef4444"
            whale_bg = "rgba(239, 68, 68, 0.16)"
            whale_advice = "大單摜壓長黑破線，空方動能強烈，嚴格落實風控停損。"
        elif (lower_sh / rng >= 0.45) and (abs(bar_l - ema_now) / (ema_now + 1e-9) < 0.015 or (not df_today.empty and bar_l <= df_today["low"].min())):
            # 接近 EMA 容差 0.8%→1.5%，5分K 尺度波幅更大，需要更寬的護盤識別窗口
            whale_tag = "🔨 主力爆量護盤"
            whale_color = "#22c55e"
            whale_bg = "rgba(34, 197, 94, 0.16)"
            whale_advice = "回踩支撐放量收長下影線，主力低檔承接，守穩留意反彈。"
        elif upper_sh / rng >= 0.4 or body / rng <= 0.25:
            whale_tag = "⚠️ 爆量高檔滯漲"
            whale_color = "#f59e0b"
            whale_bg = "rgba(245, 158, 11, 0.16)"
            whale_advice = "衝高受阻留下長上影線，主力逢高調節分歧，提防換手拉回。"
        else:
            whale_tag = f"⚡ 主力爆量異動 ({vol_ratio_5m}倍量)"
            whale_color = "#a855f7"
            whale_bg = "rgba(168, 85, 247, 0.16)"
            whale_advice = f"爆出 5m 均量 {vol_ratio_5m} 倍巨量，多空劇烈分歧，密切關注 20 EMA（{ema_now:.2f} 元）支撐。"
    else:
        whale_tag = "⚪ 常態量能流動"
        whale_color = "#94a3b8"
        whale_bg = "rgba(148, 163, 184, 0.12)"
        whale_advice = "量能處於常態合理區間，無失控或突發大單異動。"

    # 繪製 Plotly 5 分K 互動圖表
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.75, 0.25], vertical_spacing=0.03,
        subplot_titles=[f"{stock_name} ({ticker}) 5 分鐘 K 線 + 20 EMA", "5 分鐘成交量與主力爆量標記（張）"]
    )

    fig.add_trace(go.Candlestick(
        x=df["date"],
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="5分K",
        increasing_line_color="#ef4444", increasing_fillcolor="#ef4444",
        decreasing_line_color="#22c55e", decreasing_fillcolor="#22c55e"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["ema20"],
        line=dict(color="#6366f1", width=2),
        name="20 EMA"
    ), row=1, col=1)

    # 標記今日開盤價、最高價、最低價
    if not df_today.empty:
        fig.add_hline(y=open_today, line_dash="dash", line_color="#94a3b8", row=1, col=1,
                      annotation_text=f"今日開盤 {open_today}", annotation_position="top left", annotation_font_size=10)
        fig.add_hline(y=high_today, line_dash="dot", line_color="#ef4444", row=1, col=1,
                      annotation_text=f"今日最高 {high_today}", annotation_position="top right", annotation_font_size=10)
        fig.add_hline(y=low_today, line_dash="dot", line_color="#22c55e", row=1, col=1,
                      annotation_text=f"今日最低 {low_today}", annotation_position="bottom right", annotation_font_size=10)

    # 成交量副圖（爆量 >= 1.8x 特殊高亮標記）
    vol_colors = []
    for i in range(len(df)):
        v = df["volume"].iloc[i]
        v_ma = df["vol_ma20"].iloc[i]
        c_i = df["close"].iloc[i]
        o_i = df["open"].iloc[i]
        if v >= 1.8 * v_ma:
            vol_colors.append("#38bdf8" if c_i >= o_i else "#f43f5e") # 爆量高亮 (藍色/桃紅)
        else:
            vol_colors.append("#ef4444" if c_i >= o_i else "#22c55e")

    fig.add_trace(go.Bar(
        x=df["date"], y=df["volume"],
        marker_color=vol_colors, name="成交量"
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["vol_ma20"],
        line=dict(color="#f59e0b", width=1.5),
        name="20均量"
    ), row=2, col=1)

    fig.update_layout(
        template="plotly_dark",
        height=560,
        margin=dict(t=50, b=30, l=50, r=20),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02, x=1, xanchor="right")
    )
    # 過濾非交易時段（每日 13:30 ~ 隔日 09:00 及週末）
    fig.update_xaxes(rangebreaks=[
        dict(bounds=[13.5, 9], pattern="hour"),
        dict(bounds=["sat", "mon"])
    ])

    data_time_str = df["date"].iloc[-1].strftime("%Y/%m/%d %H:%M")

    return {
        "ticker": ticker,
        "stock_name": stock_name,
        "market": market,
        "df": df,
        "fig": fig,
        "close_now": close_now,
        "open_today": open_today,
        "high_today": high_today,
        "low_today": low_today,
        "range_today": range_today,
        "change_today": change_today,
        "change_today_pct": change_today_pct,
        "ema_now": ema_now,
        "ema_bias": ema_bias,
        "ema_bias_pct": ema_bias_pct,
        "bpa_status": bpa_status,
        "bpa_status_color": bpa_status_color,
        "bpa_bg": bpa_bg,
        "bpa_guide": bpa_guide,
        "last_bar_type": bar_type,
        "buy_stop": buy_stop,
        "sell_stop": sell_stop,
        "stop_loss": stop_loss,
        "stop_type": stop_type,
        "stop_direction": stop_direction,
        "entry_type": entry_type,
        "r_val": r_val,
        "target_1r": target_1r,
        "target_2r": target_2r,
        "action_tag": action_tag_5m,
        "action_sub": action_sub_5m,
        "action_color": action_color_5m,
        "whale_tag": whale_tag,
        "whale_color": whale_color,
        "whale_bg": whale_bg,
        "whale_advice": whale_advice,
        "vol_now": vol_now,
        "vol_ma20_5m": vol_ma20_5m,
        "vol_ratio_5m": vol_ratio_5m,
        "mtf_status": mtf_status,
        "daily_always_code": daily_always_code,
        "daily_ma20": daily_ma20,
        "inst_net_3d": inst_net_3d,
        "noise_ratio": noise_ratio,
        "atr20_5m": atr20_5m,
        "conformal_status": conformal_status,
        "data_time_str": data_time_str,
        "data_cutoff_time": df["date"].iloc[-1].strftime("%H:%M:%S") if not df.empty else "",
        "is_delayed": True,
        "data_source": "Yahoo Finance (5分K)"
    }

# ── 7. 命令列執行入口 ─────────────────────────────────────────


# ── 命令列執行入口 ─────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="台股專業 K 線量價 + 籌碼 + 技術形態多維研判系統")
    parser.add_argument("ticker",       type=str,               help="股票代號，例如 3042")
    parser.add_argument("--months",     type=int,  default=1,   help="分析月數（預設 1）")
    parser.add_argument("--cost",       type=float,default=None, help="持有成本（元）")
    parser.add_argument("--name",       type=str,  default=None, help="自訂股票名稱")
    args = parser.parse_args()

    analyze_stock(
        ticker=args.ticker,
        months=args.months,
        cost=args.cost,
        custom_name=args.name,
        generate_html=True,
        print_report=True
    )
