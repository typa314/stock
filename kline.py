# -*- coding: utf-8 -*-
"""
台股專業 K 線量價 + 籌碼 + 技術形態多維研判系統
------------------------------------------------------
核心架構：
  1. 趨勢結構：Stan Weinstein 四階段理論 + 均線斜率（Slope）與排列
  2. 價格行為（Price Action）：多空吞噬、錘子線、流星線、孕線、晨星/暮星
  3. 量價分析（Wyckoff & VPA）：放量突破、量縮回測、窒息量、爆量滯漲、指標頂/底背離
  4. 籌碼結構：三大法人集中度、買賣超佔比、土洋同步/對作研判
  5. 關鍵價位：支撐與壓力矩陣（S1/S2/R1/R2）與動態停損點
"""

import sys
import time
import argparse
import requests
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from dateutil.relativedelta import relativedelta

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
MA_DAYS   = [5, 20, 60]
VOL_MA    = 20
MA_COLORS = ["#f59e0b", "#6366f1", "#ec4899"]

# ── 1. 判斷市場 & 取股票名稱 ────────────────────────────────
def get_info(ticker):
    try:
        import twstock
        info = twstock.codes.get(ticker)
        if info:
            market = "otc" if info.data_source == "tpex" else "tse"
            return market, info.name
    except Exception:
        pass
    return "tse", ticker

# ── 2. 抓歷史資料 ────────────────────────────────────────────
def fetch_twse(ticker, months):
    now   = datetime.now()
    start = now - relativedelta(months=months)
    records = []
    cur = start
    while cur <= now:
        date_str = f"{cur.year}{cur.month:02d}01"
        url = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
        try:
            r = requests.get(url,
                params={"date": date_str, "stockNo": ticker, "response": "json"},
                headers=HEADERS, timeout=10)
            data = r.json()
            for row in data.get("data", []):
                try:
                    yy_tw, mm, dd = row[0].split("/")
                    date_fmt = f"{int(yy_tw)+1911}-{mm}-{dd}"
                    records.append({
                        "date":   date_fmt,
                        "volume": int(row[1].replace(",", "")) / 1000,
                        "open":   float(row[3].replace(",", "")),
                        "high":   float(row[4].replace(",", "")),
                        "low":    float(row[5].replace(",", "")),
                        "close":  float(row[6].replace(",", "")),
                    })
                except Exception:
                    pass
        except Exception as e:
            print(f"  [WARN] {cur.year}/{cur.month} 抓取失敗：{e}")
        time.sleep(0.3)
        cur += relativedelta(months=1)
    return records

def fetch_otc(ticker, months):
    end   = datetime.now()
    start = end - relativedelta(months=months)
    sym   = ticker + ".TWO"
    raw   = yf.download(sym,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False)
    if raw.empty:
        sys.exit(f"[ERROR] yfinance 無法取得 {sym} 資料，請確認代號。")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.reset_index()
    df.columns = [c.lower() for c in df.columns]
    df["volume"] = df["volume"] / 1000
    return df[["date","open","high","low","close","volume"]].to_dict("records")

# ── 3. 補今日即時（TWSE OpenAPI） ────────────────────────────
def fetch_today_tse(ticker):
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
                         headers=HEADERS, timeout=8)
        for row in r.json():
            if row.get("Code") == ticker:
                raw_d = row["Date"]
                if len(raw_d) == 7:
                    raw_d = str(int(raw_d[:3])+1911) + raw_d[3:]
                return {
                    "date":   pd.to_datetime(raw_d, format="%Y%m%d"),
                    "open":   float(row["OpeningPrice"].replace(",","")),
                    "high":   float(row["HighestPrice"].replace(",","")),
                    "low":    float(row["LowestPrice"].replace(",","")),
                    "close":  float(row["ClosingPrice"].replace(",","")),
                    "volume": float(row["TradeVolume"].replace(",","")) / 1000,
                }
    except Exception as e:
        print(f"[WARN] 今日即時資料取得失敗：{e}")
    return None

# ── 4. 三大法人資料（近5個交易日，僅上市TSE） ──────────────────
def fetch_institutional(ticker, market, days=5):
    if market != "tse":
        return pd.DataFrame()

    records = []
    d = datetime.now()
    fetched = 0
    attempts = 0
    while fetched < days and attempts < days * 2:
        attempts += 1
        if d.weekday() >= 5:
            d -= relativedelta(days=1)
            continue
        date_str = d.strftime("%Y%m%d")
        try:
            r = requests.get("https://www.twse.com.tw/rwd/zh/fund/T86",
                params={"date": date_str, "response": "json", "selectType": "ALL"},
                headers=HEADERS, timeout=10)
            data = r.json()
            for row in data.get("data", []):
                if row[0].strip() == ticker:
                    records.append({
                        "date":   pd.to_datetime(date_str, format="%Y%m%d"),
                        "fini":   int(row[4].replace(",",""))  // 1000,
                        "trust":  int(row[10].replace(",","")) // 1000,
                        "dealer": int(row[11].replace(",","")) // 1000,
                        "total":  int(row[18].replace(",","")) // 1000,
                    })
                    fetched += 1
                    break
        except Exception:
            pass
        time.sleep(0.3)
        d -= relativedelta(days=1)

    if not records:
        return pd.DataFrame()
    inst = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    return inst

# ── 5. Al Brooks 價格行為學（BPA）核心與多維量化 ──────────────
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
    
    # 7.1 Always-In 狀態判定
    if is_ttr or (ema_crosses >= 3 and abs(ema_slope) < 0.3):
        always_in = "Trading Range (TR, 箱型交易區間 / 盤整)"
        always_in_code = "TR"
        always_in_score = 0
    elif c > ema_v and ema_slope > 0.15:
        always_in = "Always In Long (AIL, 恆久做多 / 多頭主控)"
        always_in_code = "AIL"
        always_in_score = +2
    elif c < ema_v and ema_slope < -0.15:
        always_in = "Always In Short (AIS, 恆久做空 / 空頭主控)"
        always_in_code = "AIS"
        always_in_score = -2
    elif c >= ema_v:
        always_in = "Always In Long (AIL, 偏多震盪整理)"
        always_in_code = "AIL"
        always_in_score = +1
    else:
        always_in = "Always In Short (AIS, 偏空震盪整理)"
        always_in_code = "AIS"
        always_in_score = -1
        
    last_bar_type = df["bpa_bar_type"].iloc[-1]
    
    # 7.2 近期 BPA 特徵設定（嚴格遵守 Al Brooks 趨勢環境濾網原則）
    recent_signals = []
    bpa_extra_score = 0
    mid_bb = df["bb_mid"].iloc[-1]
    
    # 7.2.1 多方設定（僅在 AIL 多頭環境 或 TR 區間下半部守穩時採納）
    if always_in_code == "AIL" or (always_in_code == "TR" and c <= mid_bb):
        if df["bpa_h2"].tail(3).any():
            recent_signals.append("觸發 High 2 (H2) 雙重推動回踩買點🔥（Al Brooks 最推崇順勢高勝率設定）")
            bpa_extra_score += 2
        elif df["bpa_h1"].tail(3).any():
            recent_signals.append("觸發 High 1 (H1) 初次推動過前高（順勢多方初探）")
            bpa_extra_score += 1
        elif df["bpa_h3"].tail(3).any():
            recent_signals.append("觸發 High 3 (H3 / 楔形多頭旗形 Wedge Bull Flag)")
            bpa_extra_score += 1
            
        if df["bpa_ema_pb"].tail(2).any():
            recent_signals.append("20 EMA 動態支撐回測確認（20 EMA Pullback 順勢買點）")
            bpa_extra_score += 1
            
        if df["bpa_bull_gap"].tail(2).any():
            recent_signals.append("出現多頭 20 EMA 乖離缺口棒（Bull Gap Bar：通常引發終極測頂，但也是趨勢老化/MTR反轉警訊）⚠️")
            bpa_extra_score += 1
            
    # 7.2.2 空方設定（僅在 AIS 空頭環境 或 TR 區間上半部受阻時採納）
    if always_in_code == "AIS" or (always_in_code == "TR" and c >= mid_bb):
        if df["bpa_l2"].tail(3).any():
            recent_signals.append("觸發 Low 2 (L2) 雙重反彈逢高空點⚠️（Al Brooks 經典空方高勝率設定）")
            bpa_extra_score -= 2
        elif df["bpa_l1"].tail(3).any():
            recent_signals.append("觸發 Low 1 (L1) 初次反彈破前低（空方重新摜壓）")
            bpa_extra_score -= 1
        elif df["bpa_l3"].tail(3).any():
            recent_signals.append("觸發 Low 3 (L3 / 楔形空頭旗形 Wedge Bear Flag)")
            bpa_extra_score -= 1
            
        if df["bpa_ema_pb"].tail(2).any() and always_in_code == "AIS":
            recent_signals.append("20 EMA 動態壓力回測確認（20 EMA Pullback 順勢空點）")
            bpa_extra_score -= 1
            
        if df["bpa_bear_gap"].tail(2).any():
            recent_signals.append("出現空頭 20 EMA 乖離缺口棒（Bear Gap Bar：通常引發終極測底，但也是空方動能耗竭警訊）⚠️")
            bpa_extra_score -= 1

    # 7.2.3 中性結構（形態壓縮與混亂區）
    if df["double_inside"].tail(2).any():
        recent_signals.append("出現雙重孕線（ii Breakout Mode，動能極度壓縮即將變盤噴發）⚑")
    if is_ttr:
        recent_signals.append("陷入 TTR 鐵絲網窄幅交疊（多空雙巴，80% 突破失敗率，嚴禁追價）⛔")
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

def evaluate_professional_trend(df, inst_df, bpa_res):
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
        inst_ratio = abs(total_last) / (vol_v + 1e-9) * 100

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
        factors.append("【法人籌碼】 0分 | 上櫃/無即時法人數據")

    return score, stage, factors

def get_rating_badge(s):
    if s >= 6:   return "🟢 強烈多頭（動能充沛，偏多操作）"
    if s >= 3:   return "🟢 溫和偏多（震盪盤堅，支撐守穩）"
    if s >= 1:   return "🟡 中性微多（均線整理，等待方向）"
    if s == 0:   return "🟡 中立盤整（多空拉鋸，靜待放量）"
    if s >= -2:  return "🟠 中性微空（反彈無力，下方測底）"
    if s >= -5:  return "🔴 溫和偏空（空頭承壓，反彈宜減碼）"
    return            "🔴 強烈空頭（主跌段，切勿盲目接刀）"

# ── 6. 核心分析主函數 ─────────────────────────────────────────
def analyze_stock(ticker, months=2, cost=None, custom_name=None, generate_html=True, print_report=True):
    ticker = str(ticker).strip()
    market, auto_name = get_info(ticker)
    stock_name = custom_name if custom_name else auto_name
    if print_report:
        print(f"[INFO] {ticker}（{stock_name}）| {'上市(TSE)' if market=='tse' else '上櫃(OTC)'}")
        print(f"下載近 {months} 個月歷史資料中...")

    if market == "tse":
        records = fetch_twse(ticker, months)
    else:
        records = fetch_otc(ticker, months)

    if not records:
        raise ValueError(f"查無 {ticker} 資料，請確認代號。")

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna().sort_values("date").drop_duplicates("date").reset_index(drop=True)
    if print_report:
        print(f"[OK] 取得 {len(df)} 筆，{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")

    if market == "tse":
        today_row = fetch_today_tse(ticker)
        if today_row and today_row["date"] > df["date"].iloc[-1]:
            df = pd.concat([df, pd.DataFrame([today_row])], ignore_index=True)
            if print_report:
                print(f"[OK] 補上今日收盤 {today_row['date'].date()}：{today_row['close']:.2f} 元")

    # ── 4. 技術指標計算 ───────────────────────────────────────────
    # 移動平均線
    for n in MA_DAYS:
        df[f"ma{n}"] = df["close"].rolling(n, min_periods=1).mean()
    df["vol_ma"] = df["volume"].rolling(VOL_MA, min_periods=1).mean()

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
    _low9  = df["low"].rolling(9, min_periods=1).min()
    _high9 = df["high"].rolling(9, min_periods=1).max()
    df["kd_rsv"] = (df["close"] - _low9) / (_high9 - _low9 + 1e-9) * 100
    df["kd_k"]   = df["kd_rsv"].ewm(com=2, adjust=False).mean()
    df["kd_d"]   = df["kd_k"].ewm(com=2, adjust=False).mean()

    # Bollinger Bands(20, ±2σ)
    df["bb_mid"]   = df["close"].rolling(20, min_periods=1).mean()
    _bb_std        = df["close"].rolling(20, min_periods=1).std(ddof=0).fillna(0)
    df["bb_upper"] = df["bb_mid"] + 2 * _bb_std
    df["bb_lower"] = df["bb_mid"] - 2 * _bb_std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / (df["bb_mid"] + 1e-9) * 100

    # ── 5. Al Brooks 價格行為學（BPA）形態識別與量價特徵 ──────────────
    close_arr = df["close"].values.astype(float)
    open_arr  = df["open"].values.astype(float)
    high_arr  = df["high"].values.astype(float)
    low_arr   = df["low"].values.astype(float)
    vol_arr   = df["volume"].values.astype(float)
    vol_ma_arr= df["vol_ma"].values.astype(float)
    ma5_arr   = df["ma5"].values.astype(float)
    ema20_arr = df["ema20"].values.astype(float)
    N         = len(df)

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
            if low_arr[i] <= ema20_arr[i] * 1.005 and close_arr[i] >= ema20_arr[i] * 0.985:
                bpa_ema_pb[i] = True
        elif np.sum(close_arr[i-8:i] < ema20_arr[i-8:i]) >= 6:
            if high_arr[i] >= ema20_arr[i] * 0.995 and close_arr[i] <= ema20_arr[i] * 1.015:
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
    rsi_arr  = df["rsi"].values.astype(float)
    macd_arr = df["macd"].values.astype(float)
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

    if print_report:
        print("\n抓取三大法人資料中（近5個交易日）...")
    inst_df = fetch_institutional(ticker, market, days=5)
    if print_report:
        if not inst_df.empty:
            print(f"[OK] 取得 {len(inst_df)} 筆法人資料")
        else:
            print("[WARN] 無法取得三大法人資料（OTC 股票或資料不可用）")

    bpa_res = evaluate_brooks_price_action(df)
    trend_score, trend_stage, trend_factors = evaluate_professional_trend(df, inst_df, bpa_res)
    rating_badge = get_rating_badge(trend_score)

    close_now = df["close"].iloc[-1]
    r1 = round(df["high"].tail(20).max(), 2)
    r2 = round(df["bb_upper"].iloc[-1], 2)
    s1 = round(df["ma20"].iloc[-1], 2)
    s2 = round(df["low"].tail(20).min(), 2)
    stop_loss = round(s2 * 0.985, 2)

    # ── 8. Plotly 互動圖表繪製 ──────────────────────────────────
    n_inst = 1 if not inst_df.empty else 0
    n_rows = 4 + n_inst
    if n_inst:
        row_heights = [0.38, 0.12, 0.18, 0.18, 0.14]
        subplot_titles = ["K 線 + 20 EMA(BPA) + 均線 + 布林帶", "三大法人（張）", "MACD(12,26,9)", "RSI(14)", "成交量（張）"]
    else:
        row_heights = [0.42, 0.22, 0.22, 0.14]
        subplot_titles = ["K 線 + 20 EMA(BPA) + 均線 + 布林帶", "MACD(12,26,9)", "RSI(14)", "成交量（張）"]

    fig = make_subplots(rows=n_rows, cols=1, shared_xaxes=True,
                        row_heights=row_heights, vertical_spacing=0.025,
                        subplot_titles=subplot_titles)

    # Row 1：K 線 + EMA20 + 均線 + 布林帶
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        increasing_line_color="#ef4444", decreasing_line_color="#22c55e",
        name="K 線"), row=1, col=1)

    # 20 EMA (Al Brooks 核心基準線)
    fig.add_trace(go.Scatter(x=df["date"], y=df["ema20"],
        mode="lines", line=dict(color="#06b6d4", width=1.8), name="EMA20 (BPA核心)"), row=1, col=1)

    for n_ma, color in zip(MA_DAYS, MA_COLORS):
        fig.add_trace(go.Scatter(x=df["date"], y=df[f"ma{n_ma}"],
            mode="lines", line=dict(color=color, width=1.1, dash="dash" if n_ma==20 else "solid"),
            name=f"MA{n_ma}"), row=1, col=1)

    # 布林帶
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["bb_upper"], mode="lines",
        line=dict(color="rgba(148,163,184,0.45)", width=1, dash="dot"),
        name="BB上軌"), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["bb_lower"], mode="lines",
        line=dict(color="rgba(148,163,184,0.45)", width=1, dash="dot"),
        fill="tonexty", fillcolor="rgba(148,163,184,0.07)",
        name="BB下軌"), row=1, col=1)

    if cost is not None:
        fig.add_hline(y=cost, line=dict(color="#facc15", width=1.5, dash="dash"),
            annotation_text=f"持股成本 {cost:.1f}", annotation_position="right", row=1, col=1)

    # BPA 與量價形態標註
    for _, row in df[df["breakout"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["high"], text="▲ 放量突破",
            showarrow=True, arrowhead=2, ax=0, ay=-35,
            bgcolor="#fef08a", font=dict(size=10, color="#92400e"), row=1, col=1)
    for _, row in df[df["bpa_h2"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["low"], text="★ H2 買點",
            showarrow=True, arrowhead=2, ax=0, ay=35,
            bgcolor="#10b981", font=dict(size=10, color="#ffffff"), row=1, col=1)
    for _, row in df[df["bpa_l2"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["high"], text="▼ L2 賣點",
            showarrow=True, arrowhead=2, ax=0, ay=-35,
            bgcolor="#ef4444", font=dict(size=10, color="#ffffff"), row=1, col=1)
    for _, row in df[df["bpa_bull_gap"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["low"], text="🚀 EMA 缺口棒",
            showarrow=True, arrowhead=2, ax=0, ay=45,
            bgcolor="#0284c7", font=dict(size=10, color="#ffffff"), row=1, col=1)
    for _, row in df[df["bpa_bear_gap"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["high"], text="⚠️ EMA 缺口棒",
            showarrow=True, arrowhead=2, ax=0, ay=-45,
            bgcolor="#b91c1c", font=dict(size=10, color="#ffffff"), row=1, col=1)
    for _, row in df[df["double_inside"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["high"], text="⚑ ii 突破",
            showarrow=True, arrowhead=2, ax=0, ay=-25,
            bgcolor="#8b5cf6", font=dict(size=10, color="#ffffff"), row=1, col=1)
    for _, row in df[df["bull_div"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["low"], text="★ 底背離",
            showarrow=True, arrowhead=2, ax=0, ay=35,
            bgcolor="#bbf7d0", font=dict(size=10, color="#166534"), row=1, col=1)
    for _, row in df[df["bear_div"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["high"], text="⚠ 頂背離",
            showarrow=True, arrowhead=2, ax=0, ay=-35,
            bgcolor="#fecdd3", font=dict(size=10, color="#991b1b"), row=1, col=1)
    for _, row in df[df["churn"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["high"], text="⚡ 爆量滯漲",
            showarrow=True, arrowhead=2, ax=0, ay=-35,
            bgcolor="#fed7aa", font=dict(size=10, color="#9a3412"), row=1, col=1)

    # Row 2（選）：三大法人
    if not inst_df.empty:
        inst_row = 2
        fig.add_trace(go.Bar(
            x=inst_df["date"], y=inst_df["fini"],
            marker_color=np.where(inst_df["fini"] >= 0, "#3b82f6", "#f87171"),
            name="外資", opacity=0.85), row=inst_row, col=1)
        fig.add_trace(go.Bar(
            x=inst_df["date"], y=inst_df["trust"],
            marker_color=np.where(inst_df["trust"] >= 0, "#22c55e", "#f87171"),
            name="投信", opacity=0.85), row=inst_row, col=1)
        fig.add_trace(go.Bar(
            x=inst_df["date"], y=inst_df["dealer"],
            marker_color=np.where(inst_df["dealer"] >= 0, "#f59e0b", "#f87171"),
            name="自營商", opacity=0.85), row=inst_row, col=1)
        fig.update_layout(barmode="group")

    # MACD 子圖
    macd_row = 2 + n_inst
    hist_colors = np.where(df["macd_hist"].values >= 0, "#ef4444", "#22c55e")
    fig.add_trace(go.Bar(x=df["date"], y=df["macd_hist"],
        marker_color=hist_colors, name="MACD 柱", showlegend=False, opacity=0.7), row=macd_row, col=1)
    fig.add_trace(go.Scatter(x=df["date"], y=df["macd"],
        mode="lines", line=dict(color="#f59e0b", width=1.5), name="MACD"), row=macd_row, col=1)
    fig.add_trace(go.Scatter(x=df["date"], y=df["macd_signal"],
        mode="lines", line=dict(color="#a78bfa", width=1.5), name="Signal"), row=macd_row, col=1)
    fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.2)", width=1), row=macd_row, col=1)

    # RSI 子圖
    rsi_row = 3 + n_inst
    fig.add_trace(go.Scatter(x=df["date"], y=df["rsi"],
        mode="lines", line=dict(color="#38bdf8", width=1.5), name="RSI(14)"), row=rsi_row, col=1)
    fig.add_hline(y=70, line=dict(color="#f87171", width=1, dash="dash"),
        annotation_text="超買 70", annotation_position="right", row=rsi_row, col=1)
    fig.add_hline(y=30, line=dict(color="#4ade80", width=1, dash="dash"),
        annotation_text="超賣 30", annotation_position="right", row=rsi_row, col=1)
    fig.add_hline(y=50, line=dict(color="rgba(255,255,255,0.15)", width=1), row=rsi_row, col=1)
    fig.update_yaxes(range=[0, 100], row=rsi_row, col=1)

    # 成交量子圖
    vol_row = 4 + n_inst
    vol_colors = np.where(df["close"].values >= df["open"].values, "#ef4444", "#22c55e")
    fig.add_trace(go.Bar(x=df["date"], y=df["volume"], marker_color=vol_colors,
        name="成交量", showlegend=False), row=vol_row, col=1)
    fig.add_trace(go.Scatter(x=df["date"], y=df["vol_ma"], mode="lines",
        line=dict(color="#f59e0b", width=1, dash="dot"), name=f"VOL MA{VOL_MA}"), row=vol_row, col=1)

    # ── 支撐與壓力矩陣（S/R 水平線）可視化 ────────────────────────────
    # 以色調區分：壓力 = 橙/紅色調；支撐 = 綠/青色調；停損 = 紫紅色虛線

    sr_levels = [
        (r2,        f"R2 布林上軌  {r2:.2f}",  "#f97316", "solid",  2.0),   # 壓力二 橘
        (r1,        f"R1 近期高點  {r1:.2f}",  "#ef4444", "dash",   1.5),   # 壓力一 紅虛線
        (s1,        f"S1 月線支撐  {s1:.2f}",  "#22c55e", "dash",   1.5),   # 支撐一 綠虛線
        (s2,        f"S2 近期低點  {s2:.2f}",  "#06b6d4", "solid",  2.0),   # 支撐二 青
        (stop_loss, f"停損 Pivot   {stop_loss:.2f}", "#a855f7", "dot", 1.5), # 停損線 紫虛線
    ]

    for level, label, color, dash_style, lw in sr_levels:
        fig.add_hline(
            y=level,
            line=dict(color=color, width=lw, dash=dash_style),
            annotation_text=label,
            annotation_position="right",
            annotation_font=dict(color=color, size=11),
            row=1, col=1
        )

    # 當前收盤價水平虛線（白色半透明）
    fig.add_hline(
        y=close_now,
        line=dict(color="rgba(255,255,255,0.55)", width=1.2, dash="dot"),
        annotation_text=f"現價 {close_now:.2f}",
        annotation_position="left",
        annotation_font=dict(color="rgba(255,255,255,0.75)", size=11),
        row=1, col=1
    )

    # 版面設定
    last_date  = df["date"].iloc[-1].strftime("%Y-%m-%d")
    title_text = (f"{stock_name}（{ticker}）多維量價籌碼 + Al Brooks BPA 研判 | "
                  f"最新收盤 {close_now:.2f} 元（{last_date}）| "
                  f"總評 {trend_score:+d}分 → {rating_badge}")
    if cost is not None:
        pnl = (close_now - cost) / cost * 100
        sign = "+" if pnl >= 0 else ""
        title_text += f" | 成本 {cost:.1f}（{sign}{pnl:.1f}%）"

    fig.update_layout(
        title=dict(text=title_text, font=dict(size=13)),
        xaxis_rangeslider_visible=False,
        yaxis_title="股價（元）",
        legend=dict(orientation="h", y=1.02, x=1, xanchor="right"),
        height=950 if n_inst else 850,
        template="plotly_dark",
        margin=dict(t=70, b=40, l=60, r=20)
    )
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat","mon"])])

    output = f"{ticker}_kline.html"
    if generate_html:
        fig.write_html(output)
        if print_report:
            print(f"\n[OK] 圖表已輸出 -> {output}")

    if print_report:
        # ── 9. 專業多維研判報表輸出 ───────────────────────────────────
        print("\n" + "="*70)
        print(f"  📊 {stock_name}（{ticker}）專業多維量價籌碼 + Al Brooks BPA 研判報表")
        print("="*70)
        print(f"  📅 分析區間 ：{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")
        print(f"  💰 最新收盤 ：{close_now:.2f} 元")
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
            print(f"  BPA 關鍵型態與設定   ：近幾日無高勝率特殊設定，順應 20 EMA 趨勢動態運行")

        print(f"\n  ── 🎯 Brooks 操盤訂單與停損風控指引 ───────────────────────")
        if bpa_res['always_in_code'] == 'AIL':
            print(f"  偏多操作策略 (AIL)   ：多頭主控，拉回逢支撐尋找 H1/H2 買點，或以 Signal Bar 突破進場")
            print(f"  • 訊號棒極值 (Signal Bar)   ：高 {bpa_res['sig_high']:.2f} ｜ 低 {bpa_res['sig_low']:.2f} ｜ 震幅 {bpa_res['sig_high']-bpa_res['sig_low']:.2f} 元")
            print(f"  • 多方突破進場 (Buy Stop)   ：{bpa_res['buy_stop']:.2f} 元（突破訊號棒高點啟動）")
            print(f"  • 多方防守停損 (Prot Stop)  ：{bpa_res['sell_stop']:.2f} 元（跌破訊號棒低點，風險 {bpa_res['risk_long']:.2f} 元）")
            print(f"  • 等距測量目標 (MM 1R / 2R) ：目標一 {bpa_res['target_long_1r']:.2f} 元 ｜ 目標二 {bpa_res['target_long_2r']:.2f} 元")
        elif bpa_res['always_in_code'] == 'AIS':
            print(f"  偏空操作策略 (AIS)   ：空方主控，反彈尋找 L1/L2 空點，持股者逢高調節，空方設 Stop 單")
            print(f"  • 訊號棒極值 (Signal Bar)   ：高 {bpa_res['sig_high']:.2f} ｜ 低 {bpa_res['sig_low']:.2f} ｜ 震幅 {bpa_res['sig_high']-bpa_res['sig_low']:.2f} 元")
            print(f"  • 空方跌破進場 (Sell Stop)  ：{bpa_res['sell_stop']:.2f} 元（跌破訊號棒低點啟動）")
            print(f"  • 空方防守停損 (Prot Stop)  ：{bpa_res['buy_stop']:.2f} 元（突破訊號棒高點，風險 {bpa_res['risk_short']:.2f} 元）")
            print(f"  • 等距測量目標 (MM 1R / 2R) ：目標一 {bpa_res['target_short_1r']:.2f} 元 ｜ 目標二 {bpa_res['target_short_2r']:.2f} 元")
        else:
            print(f"  區間震盪策略 (TR)    ：【80% 法則】80% 的區間突破會失敗！嚴禁盲目追高殺低")
            print(f"  • 操作準則 (BLSHS)   ：Buy Low, Sell High, Scalp（低買高賣短沖，接近 S1/S2 買，接近 R1/R2 賣）")
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
        print(f"  綜合評分 ：{trend_score:+d} 分 ｜ 評級：{rating_badge}")
        for f_item in trend_factors:
            print(f"  • {f_item}")

        print(f"\n  ── 💡 操盤行動指引 ─────────────────────────────────────")
        if trend_score >= 3:
            print("  【持股者】趨勢偏多，多頭結構穩健，建議續抱並以 S1 作為移動停利點。")
            print("  【空手者】逢拉回量縮測試 S1 守穩時可分批建立部位，突破 R1 加碼。")
        elif trend_score <= -3:
            print("  【持股者】趨勢偏空且空方動能增強，反彈遇 R1/MA60 宜逢高減碼，跌破防守線務必停損。")
            print("  【空手者】暫勿盲目猜底接刀，靜待打底完成或出現帶量底背離反轉再進場。")
        else:
            print("  【持股者】短線處於區間震盪打底，未跌破防守線前可暫時觀望，密切留意法人籌碼延續性。")
            print("  【空手者】觀望為主，靜待帶量突破 R1 壓力或回測 S2 底部確認再行佈局。")
        print("="*70)

    return {
        "ticker": ticker,
        "stock_name": stock_name,
        "market": market,
        "df": df,
        "inst_df": inst_df,
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
        "output_html": output if generate_html else None
    }

# ── 7. 命令列執行入口 ─────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="台股專業 K 線量價 + 籌碼 + 技術形態多維研判系統")
    parser.add_argument("ticker",       type=str,               help="股票代號，例如 3042")
    parser.add_argument("--months",     type=int,  default=2,   help="分析月數（預設 2）")
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
