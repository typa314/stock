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

# ── 解析命令列參數 ────────────────────────────────────────
parser = argparse.ArgumentParser(description="台股專業 K 線量價 + 籌碼 + 技術形態多維研判系統")
parser.add_argument("ticker",       type=str,               help="股票代號，例如 3042")
parser.add_argument("--months",     type=int,  default=12,  help="分析月數（預設 12）")
parser.add_argument("--cost",       type=float,default=None, help="持有成本（元）")
parser.add_argument("--name",       type=str,  default=None, help="自訂股票名稱")
args = parser.parse_args()

TICKER    = args.ticker.strip()
MONTHS    = args.months
COST      = args.cost
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

MARKET, AUTO_NAME = get_info(TICKER)
STOCK_NAME = args.name if args.name else AUTO_NAME
print(f"[INFO] {TICKER}（{STOCK_NAME}）| {'上市(TSE)' if MARKET=='tse' else '上櫃(OTC)'}")

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

print(f"下載近 {MONTHS} 個月歷史資料中...")
if MARKET == "tse":
    records = fetch_twse(TICKER, MONTHS)
else:
    records = fetch_otc(TICKER, MONTHS)

if not records:
    sys.exit(f"[ERROR] 查無 {TICKER} 資料，請確認代號。")

df = pd.DataFrame(records)
df["date"] = pd.to_datetime(df["date"])
df = df.dropna().sort_values("date").drop_duplicates("date").reset_index(drop=True)
print(f"[OK] 取得 {len(df)} 筆，{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")

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

if MARKET == "tse":
    today_row = fetch_today_tse(TICKER)
    if today_row and today_row["date"] > df["date"].iloc[-1]:
        df = pd.concat([df, pd.DataFrame([today_row])], ignore_index=True)
        print(f"[OK] 補上今日收盤 {today_row['date'].date()}：{today_row['close']:.2f} 元")

# ── 4. 技術指標計算 ───────────────────────────────────────────
# 移動平均線
for n in MA_DAYS:
    df[f"ma{n}"] = df["close"].rolling(n, min_periods=1).mean()
df["vol_ma"] = df["volume"].rolling(VOL_MA, min_periods=1).mean()

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

# ── 5. 專業量價與 Price Action 形態識別 ─────────────────────────
close_arr = df["close"].values.astype(float)
open_arr  = df["open"].values.astype(float)
high_arr  = df["high"].values.astype(float)
low_arr   = df["low"].values.astype(float)
vol_arr   = df["volume"].values.astype(float)
vol_ma_arr= df["vol_ma"].values.astype(float)
ma5_arr   = df["ma5"].values.astype(float)
N         = len(df)

# K 線實體與上下影線
body_arr     = np.abs(close_arr - open_arr)
candle_range = np.maximum(high_arr - low_arr, 1e-5)
upper_shadow = high_arr - np.maximum(open_arr, close_arr)
lower_shadow = np.minimum(open_arr, close_arr) - low_arr

# 5.1 放量突破 (Volume Breakout)
high20 = np.array([high_arr[max(0,i-20):i].max() if i > 0 else high_arr[0] for i in range(N)])
breakout = np.zeros(N, dtype=bool)
breakout[1:] = (close_arr[1:] > high20[1:]) & (vol_arr[1:] > 1.5 * vol_ma_arr[1:])

# 5.2 量縮回測 (Low Volume Pullback)
pullback = (np.abs(close_arr - ma5_arr) / ma5_arr < 0.015) & (vol_arr < 0.75 * vol_ma_arr)

# 5.3 窒息量 (Volume Dry-Up, 變盤前夕)
dryup = vol_arr < 0.45 * vol_ma_arr

# 5.4 爆量滯漲 / 出貨警訊 (Volume Churning / Distribution)
churn = (vol_arr > 1.8 * vol_ma_arr) & ((upper_shadow / candle_range > 0.4) | (body_arr / candle_range < 0.25))

# 5.5 多頭吞噬 (Bullish Engulfing) & 空頭吞噬 (Bearish Engulfing)
bull_engulf = np.zeros(N, dtype=bool)
bear_engulf = np.zeros(N, dtype=bool)
for i in range(1, N):
    if (close_arr[i-1] < open_arr[i-1]) and (close_arr[i] > open_arr[i]):
        if open_arr[i] <= close_arr[i-1] and close_arr[i] >= open_arr[i-1]:
            bull_engulf[i] = True
    elif (close_arr[i-1] > open_arr[i-1]) and (close_arr[i] < open_arr[i]):
        if open_arr[i] >= close_arr[i-1] and close_arr[i] <= open_arr[i-1]:
            bear_engulf[i] = True

# 5.6 錘子線 (Hammer, 探底回升) & 流星線 (Shooting Star, 高檔反壓)
hammer = (lower_shadow >= 2.0 * body_arr) & (upper_shadow <= 0.15 * candle_range)
star   = (upper_shadow >= 2.0 * body_arr) & (lower_shadow <= 0.15 * candle_range)

# 5.7 指標頂背離 (Bearish Divergence) 與底背離 (Bullish Divergence)
rsi_arr  = df["rsi"].values.astype(float)
macd_arr = df["macd"].values.astype(float)
bull_div = np.zeros(N, dtype=bool)
bear_div = np.zeros(N, dtype=bool)

for i in range(15, N):
    # 底背離：股價破 15 日新低，但 RSI 或 MACD 低點未破新低
    if close_arr[i] < close_arr[i-15:i].min():
        if rsi_arr[i] > rsi_arr[i-15:i].min() + 2:
            bull_div[i] = True
    # 頂背離：股價創 15 日新高，但 RSI 或 MACD 高點未破新高
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

# ── 6. 三大法人資料（近5個交易日，僅上市TSE） ──────────────────
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

print("\n抓取三大法人資料中（近5個交易日）...")
inst_df = fetch_institutional(TICKER, MARKET, days=5)
if not inst_df.empty:
    print(f"[OK] 取得 {len(inst_df)} 筆法人資料")
else:
    print("[WARN] 無法取得三大法人資料（OTC 股票或資料不可用）")

# ── 7. 專業趨勢研判體系 (Professional Trend Evaluation) ───────────
def evaluate_professional_trend(df, inst_df):
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
    k_v       = df["kd_k"].iloc[-1]
    d_v       = df["kd_d"].iloc[-1]
    bb_mid_v  = df["bb_mid"].iloc[-1]
    bb_upper_v= df["bb_upper"].iloc[-1]
    bb_lower_v= df["bb_lower"].iloc[-1]
    vol_v     = df["volume"].iloc[-1]
    vol_ma_v  = df["vol_ma"].iloc[-1]

    # 7.1 均線斜率與階段分析 (Weinstein Stage Analysis)
    # 計算 MA20 & MA60 近 5 日斜率
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

    # 7.2 均線支撐壓力位置與乖離率 (Bias)
    bias_ma20 = (close_v - ma20_v) / ma20_v * 100
    if close_v > ma5_v and close_v > ma20_v:
        score += 1
        factors.append(f"【均線位階】+1分 | 站上 5MA 與 20MA（乖離率 {bias_ma20:+.1f}%）")
    elif close_v < ma5_v and close_v < ma20_v:
        score -= 1
        factors.append(f"【均線位階】-1分 | 跌破 5MA 與 20MA，短線失守支撐")
    else:
        factors.append(f"【均線位階】 0分 | 夾於 5MA 與 20MA 之間震盪")

    # 7.3 動量與指標結構 (MACD / RSI / KD)
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

    # 7.4 Price Action 與量價特徵 (近 3 日)
    pa_signals = []
    if df["bull_div"].tail(3).any():
        score += 2; pa_signals.append("出現指標底背離（潛在反轉）🔥")
    if df["bear_div"].tail(3).any():
        score -= 2; pa_signals.append("出現指標頂背離（高檔誘多）⚠️")
    if df["breakout"].tail(3).any():
        score += 2; pa_signals.append("放量長陽突破 20 日高點🚀")
    if df["churn"].tail(3).any():
        score -= 2; pa_signals.append("爆量滯漲/上影線沉重（籌碼鬆動）⚠️")
    if df["bull_engulf"].tail(2).any():
        score += 1; pa_signals.append("多頭吞噬（陽包陰）")
    if df["bear_engulf"].tail(2).any():
        score -= 1; pa_signals.append("空頭吞噬（陰包陽）")
    if df["hammer"].tail(2).any():
        score += 1; pa_signals.append("長下影錘子線（低接承接強）")
    if df["star"].tail(2).any():
        score -= 1; pa_signals.append("長上影流星線（上方解套賣壓大）")
    if df["dryup"].tail(2).any():
        pa_signals.append("出現極度窒息量（變盤前夕）")

    if pa_signals:
        factors.append(f"【K線形態】{' / '.join(pa_signals)}")
    else:
        factors.append("【K線形態】近幾日無特殊反轉或突破形態")

    # 7.5 籌碼面深度分析 (三大法人)
    if not inst_df.empty:
        last_inst = inst_df.iloc[-1]
        fini_last = last_inst["fini"]
        trust_last= last_inst["trust"]
        total_last= last_inst["total"]
        total_5d  = inst_df.tail(5)["total"].sum()
        
        # 法人買賣佔成交量比重 (集中度)
        inst_ratio = abs(total_last) / (vol_v + 1e-9) * 100

        # 土洋同步 / 對作分析
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

trend_score, trend_stage, trend_factors = evaluate_professional_trend(df, inst_df)

# 評級映射
def get_rating_badge(s):
    if s >= 6:   return "🟢 強烈多頭（動能充沛，偏多操作）"
    if s >= 3:   return "🟢 溫和偏多（震盪盤堅，支撐守穩）"
    if s >= 1:   return "🟡 中性微多（均線整理，等待方向）"
    if s == 0:   return "🟡 中立盤整（多空拉鋸，靜待放量）"
    if s >= -2:  return "🟠 中性微空（反彈無力，下方測底）"
    if s >= -5:  return "🔴 溫和偏空（空頭承壓，反彈宜減碼）"
    return            "🔴 強烈空頭（主跌段，切勿盲目接刀）"

rating_badge = get_rating_badge(trend_score)

# ── 7.6 關鍵支撐壓力矩陣 (Support & Resistance) ───────────────
close_now = df["close"].iloc[-1]
r1 = round(df["high"].tail(20).max(), 2)
r2 = round(df["bb_upper"].iloc[-1], 2)
s1 = round(df["ma20"].iloc[-1], 2)
s2 = round(df["low"].tail(20).min(), 2)
stop_loss = round(s2 * 0.985, 2)

# ── 8. 繪圖 ──────────────────────────────────────────────
n_inst = 1 if not inst_df.empty else 0
n_rows = 4 + n_inst
if n_inst:
    row_heights = [0.38, 0.12, 0.18, 0.18, 0.14]
    subplot_titles = ["K 線 + 均線 + 布林帶", "三大法人（張）", "MACD(12,26,9)", "RSI(14)", "成交量（張）"]
else:
    row_heights = [0.42, 0.22, 0.22, 0.14]
    subplot_titles = ["K 線 + 均線 + 布林帶", "MACD(12,26,9)", "RSI(14)", "成交量（張）"]

fig = make_subplots(rows=n_rows, cols=1, shared_xaxes=True,
                    row_heights=row_heights, vertical_spacing=0.025,
                    subplot_titles=subplot_titles)

# ── Row 1：K 線 + 均線 + 布林帶 ──────────────────────────
fig.add_trace(go.Candlestick(
    x=df["date"], open=df["open"], high=df["high"],
    low=df["low"], close=df["close"],
    increasing_line_color="#ef4444", decreasing_line_color="#22c55e",
    name="K 線"), row=1, col=1)

for n_ma, color in zip(MA_DAYS, MA_COLORS):
    fig.add_trace(go.Scatter(x=df["date"], y=df[f"ma{n_ma}"],
        mode="lines", line=dict(color=color, width=1.2), name=f"MA{n_ma}"), row=1, col=1)

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
fig.add_trace(go.Scatter(
    x=df["date"], y=df["bb_mid"], mode="lines",
    line=dict(color="rgba(148,163,184,0.6)", width=1),
    name="BB中軌(20MA)"), row=1, col=1)

if COST is not None:
    fig.add_hline(y=COST, line=dict(color="#facc15", width=1.5, dash="dash"),
        annotation_text=f"持股成本 {COST:.1f}", annotation_position="right", row=1, col=1)

# 形態標註
for _, row in df[df["breakout"]].iterrows():
    fig.add_annotation(x=row["date"], y=row["high"], text="▲ 放量突破",
        showarrow=True, arrowhead=2, ax=0, ay=-35,
        bgcolor="#fef08a", font=dict(size=10, color="#92400e"), row=1, col=1)
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

# ── Row 2（選）：三大法人 ─────────────────────────────────
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

# ── MACD 子圖 ─────────────────────────────────────────────
macd_row = 2 + n_inst
hist_colors = np.where(df["macd_hist"].values >= 0, "#ef4444", "#22c55e")
fig.add_trace(go.Bar(x=df["date"], y=df["macd_hist"],
    marker_color=hist_colors, name="MACD 柱", showlegend=False, opacity=0.7), row=macd_row, col=1)
fig.add_trace(go.Scatter(x=df["date"], y=df["macd"],
    mode="lines", line=dict(color="#f59e0b", width=1.5), name="MACD"), row=macd_row, col=1)
fig.add_trace(go.Scatter(x=df["date"], y=df["macd_signal"],
    mode="lines", line=dict(color="#a78bfa", width=1.5), name="Signal"), row=macd_row, col=1)
fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.2)", width=1), row=macd_row, col=1)

# ── RSI 子圖 ──────────────────────────────────────────────
rsi_row = 3 + n_inst
fig.add_trace(go.Scatter(x=df["date"], y=df["rsi"],
    mode="lines", line=dict(color="#38bdf8", width=1.5), name="RSI(14)"), row=rsi_row, col=1)
fig.add_hline(y=70, line=dict(color="#f87171", width=1, dash="dash"),
    annotation_text="超買 70", annotation_position="right", row=rsi_row, col=1)
fig.add_hline(y=30, line=dict(color="#4ade80", width=1, dash="dash"),
    annotation_text="超賣 30", annotation_position="right", row=rsi_row, col=1)
fig.add_hline(y=50, line=dict(color="rgba(255,255,255,0.15)", width=1), row=rsi_row, col=1)
fig.update_yaxes(range=[0, 100], row=rsi_row, col=1)

# ── 成交量子圖 ────────────────────────────────────────────
vol_row = 4 + n_inst
vol_colors = np.where(df["close"].values >= df["open"].values, "#ef4444", "#22c55e")
fig.add_trace(go.Bar(x=df["date"], y=df["volume"], marker_color=vol_colors,
    name="成交量", showlegend=False), row=vol_row, col=1)
fig.add_trace(go.Scatter(x=df["date"], y=df["vol_ma"], mode="lines",
    line=dict(color="#f59e0b", width=1, dash="dot"), name=f"VOL MA{VOL_MA}"), row=vol_row, col=1)

# ── 版面設定 ──────────────────────────────────────────────
last_close = df["close"].iloc[-1]
last_date  = df["date"].iloc[-1].strftime("%Y-%m-%d")
title_text = (f"{STOCK_NAME}（{TICKER}）多維量價籌碼評估系統 | "
              f"最新收盤 {last_close:.2f} 元（{last_date}）| "
              f"總評 {trend_score:+d}分 → {rating_badge}")
if COST is not None:
    pnl = (last_close - COST) / COST * 100
    sign = "+" if pnl >= 0 else ""
    title_text += f" | 成本 {COST:.1f}（{sign}{pnl:.1f}%）"

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

output = f"{TICKER}_kline.html"
fig.write_html(output)
print(f"\n[OK] 圖表已輸出 -> {output}")

# ── 9. 專業研判報表輸出 ───────────────────────────────────
print("\n" + "="*68)
print(f"  📊 {STOCK_NAME}（{TICKER}）專業多維量價籌碼研判報表")
print("="*68)
print(f"  📅 分析區間 ：{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")
print(f"  💰 最新收盤 ：{last_close:.2f} 元")
if COST is not None:
    pnl_amt = last_close - COST
    pnl_pct = pnl_amt / COST * 100
    sign = "+" if pnl_amt >= 0 else ""
    print(f"  🎯 持有成本 ：{COST:.2f} 元 ｜ 浮動損益：{sign}{pnl_amt:.2f} 元（{sign}{pnl_pct:.1f}%）")

print(f"\n  ── 📌 核心技術指標數據 ─────────────────────────────────")
print(f"  均線位階  ：MA5={df['ma5'].iloc[-1]:.2f} ｜ MA20={df['ma20'].iloc[-1]:.2f} ｜ MA60={df['ma60'].iloc[-1]:.2f}")
print(f"  布林通道  ：上軌={r2:.2f} ｜ 中軌={df['bb_mid'].iloc[-1]:.2f} ｜ 下軌={df['bb_lower'].iloc[-1]:.2f}（頻寬={df['bb_width'].iloc[-1]:.1f}%）")
print(f"  動量指標  ：MACD={df['macd'].iloc[-1]:+.2f} ｜ Signal={df['macd_signal'].iloc[-1]:+.2f} ｜ 柱體={df['macd_hist'].iloc[-1]:+.2f}")
print(f"  震盪指標  ：RSI(14)={df['rsi'].iloc[-1]:.1f} ｜ KD(9,3,3) K={df['kd_k'].iloc[-1]:.1f} / D={df['kd_d'].iloc[-1]:.1f}")
print(f"  成交量能  ：今日={df['volume'].iloc[-1]:,.0f} 張 ｜ 20日均量={df['vol_ma'].iloc[-1]:,.0f} 張")

if not inst_df.empty:
    print(f"\n  ── 🏛️ 近 5 日三大法人籌碼分佈（張）───────────────────")
    for _, r in inst_df.tail(5).iterrows():
        sign_t = "+" if r["total"] >= 0 else ""
        print(f"  {r['date'].strftime('%m/%d')}  "
              f"外資:{r['fini']:>+6,} ｜ 投信:{r['trust']:>+5,} ｜ 自營:{r['dealer']:>+5,} ｜ "
              f"三大合計:{sign_t}{r['total']:>+6,}")

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
print("="*68)
