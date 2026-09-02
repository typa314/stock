"""
台股 K 線量價分析工具
--------------------------------------------
資料來源：
  上市（TSE） → TWSE 官方 rwd API
  上櫃（OTC） → yfinance（代號自動加 .TWO）

用法：
  python kline.py 3042
  python kline.py 6643 --months 12
  python kline.py 3042 --name 晶技 --cost 190
  python kline.py 2330 --name 台積電 --cost 850 --months 6

參數：
  ticker        股票代號（必填，純數字）
  --months N    分析月數，預設 12
  --cost   N    持有成本（元），圖表顯示成本線
  --name   STR  自訂股票名稱（選填）
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
parser = argparse.ArgumentParser(description="台股 K 線量價分析")
parser.add_argument("ticker",       type=str,               help="股票代號，例如 3042")
parser.add_argument("--months",     type=int,  default=1,   help="分析月數（預設 1）")
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
    """上市：TWSE rwd API 逐月抓取"""
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
                        "volume": int(row[1].replace(",", "")) / 1000,  # 股→張
                        "open":   float(row[3].replace(",", "")),
                        "high":   float(row[4].replace(",", "")),
                        "low":    float(row[5].replace(",", "")),
                        "close":  float(row[6].replace(",", "")),
                    })
                except Exception:
                    pass
        except Exception as e:
            print(f"  [WARN] {cur.year}/{cur.month} 抓取失敗：{e}")
        time.sleep(0.3)   # 避免頻繁請求被擋
        cur += relativedelta(months=1)
    return records

def fetch_otc(ticker, months):
    """上櫃：yfinance .TWO 後綴"""
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
    df["volume"] = df["volume"] / 1000  # 股→張
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
                raw_d = row["Date"]   # e.g. "20260901" or "1150901"
                if len(raw_d) == 7:   # 民國
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

# ── 4. 技術指標 ───────────────────────────────────────────
for n in MA_DAYS:
    df[f"ma{n}"] = df["close"].rolling(n, min_periods=1).mean()
df["vol_ma"] = df["volume"].rolling(VOL_MA, min_periods=1).mean()

# ── 5. 量價訊號 ───────────────────────────────────────────
close  = df["close"].values.astype(float)
high   = df["high"].values.astype(float)
low    = df["low"].values.astype(float)
volume = df["volume"].values.astype(float)
vol_ma = df["vol_ma"].values.astype(float)
ma5    = df["ma5"].values.astype(float)
N      = len(df)

high20 = np.array([high[max(0,i-20):i].max() if i > 0 else high[0] for i in range(N)])
breakout = np.zeros(N, dtype=bool)
breakout[1:] = (close[1:] > high20[1:]) & (volume[1:] > 1.5 * vol_ma[1:])

pullback = (np.abs(close - ma5) / ma5 < 0.01) & (volume < 0.7 * vol_ma)

diverge = np.zeros(N, dtype=bool)
for i in range(2, N):
    diverge[i] = (close[i] < close[i-1] < close[i-2]) and (volume[i] > volume[i-1] > volume[i-2])

df["breakout"] = breakout
df["pullback"]  = pullback
df["diverge"]   = diverge

# ── 6. 三大法人資料（近5個交易日，僅上市TSE） ──────────────────

def fetch_institutional(ticker, market, days=5):
    """從 TWSE T86 API 逐日抓取個股三大法人買賣超（張），回傳 DataFrame"""
    if market != "tse":
        return pd.DataFrame()   # OTC 暫不支援

    records = []
    d = datetime.now()
    fetched = 0
    attempts = 0
    while fetched < days and attempts < days * 2:
        attempts += 1
        if d.weekday() >= 5:  # 跳過週末
            d -= __import__('datetime').timedelta(days=1)
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
                        "fini":   int(row[4].replace(",",""))  // 1000,   # 外資（張）
                        "trust":  int(row[10].replace(",","")) // 1000,   # 投信（張）
                        "dealer": int(row[11].replace(",","")) // 1000,   # 自營商（張）
                        "total":  int(row[18].replace(",","")) // 1000,   # 三大合計（張）
                    })
                    fetched += 1
                    break
        except Exception:
            pass
        time.sleep(0.3)
        d -= __import__('datetime').timedelta(days=1)

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

# ── 7. 法人訊號評估 ───────────────────────────────────────
inst_signal = "N/A"
inst_consecutive_buy = 0
inst_consecutive_sell = 0
if not inst_df.empty:
    recent = inst_df.tail(5)
    fini_5d   = recent["fini"].sum()
    trust_5d  = recent["trust"].sum()
    total_5d  = recent["total"].sum()

    # 連續買超/賣超天數
    for v in reversed(inst_df["total"].values):
        if v > 0:
            inst_consecutive_buy += 1
            if inst_consecutive_sell > 0:
                break
        elif v < 0:
            inst_consecutive_sell += 1
            if inst_consecutive_buy > 0:
                break
        else:
            break

    if total_5d > 1000:
        inst_signal = "強力買超（5日合計 >{:,}張）".format(total_5d)
    elif total_5d > 0:
        inst_signal = "小幅買超（5日合計 +{:,}張）".format(total_5d)
    elif total_5d < -1000:
        inst_signal = "強力賣超（5日合計 {:,}張）".format(total_5d)
    else:
        inst_signal = "小幅賣超（5日合計 {:,}張）".format(total_5d)

# ── 8. 繪圖 ──────────────────────────────────────────────
n_rows = 3 if not inst_df.empty else 2
row_heights = [0.55, 0.25, 0.20] if n_rows == 3 else [0.7, 0.3]
subplot_titles = (["K 線", "三大法人（張）", "成交量（張）"] if n_rows == 3
                  else ["K 線", "成交量（張）"])

fig = make_subplots(rows=n_rows, cols=1, shared_xaxes=True,
                    row_heights=row_heights, vertical_spacing=0.03,
                    subplot_titles=subplot_titles)

# K 線
fig.add_trace(go.Candlestick(
    x=df["date"], open=df["open"], high=df["high"],
    low=df["low"], close=df["close"],
    increasing_line_color="#ef4444", decreasing_line_color="#22c55e",
    name="K 線"), row=1, col=1)

for n_ma, color in zip(MA_DAYS, MA_COLORS):
    fig.add_trace(go.Scatter(x=df["date"], y=df[f"ma{n_ma}"],
        mode="lines", line=dict(color=color, width=1), name=f"MA{n_ma}"), row=1, col=1)

if COST is not None:
    fig.add_hline(y=COST, line=dict(color="#facc15", width=1.5, dash="dash"),
        annotation_text=f"成本 {COST:.1f}", annotation_position="right", row=1, col=1)

# 訊號標註
for _, row in df[df["breakout"]].iterrows():
    fig.add_annotation(x=row["date"], y=row["high"], text="▲ 放量突破",
        showarrow=True, arrowhead=2, ax=0, ay=-35,
        bgcolor="#fef08a", font=dict(size=10, color="#92400e"), row=1, col=1)
for _, row in df[df["pullback"]].iterrows():
    fig.add_annotation(x=row["date"], y=row["low"], text="◆ 量縮回測",
        showarrow=True, arrowhead=2, ax=0, ay=35,
        bgcolor="#bfdbfe", font=dict(size=10, color="#1e40af"), row=1, col=1)
for _, row in df[df["diverge"]].iterrows():
    fig.add_annotation(x=row["date"], y=row["low"], text="! 量價背離",
        showarrow=True, arrowhead=2, ax=0, ay=50,
        bgcolor="#fecdd3", font=dict(size=10, color="#991b1b"), row=1, col=1)

# 三大法人
if not inst_df.empty:
    inst_row = 2
    # 外資（藍色）
    fig.add_trace(go.Bar(
        x=inst_df["date"], y=inst_df["fini"],
        marker_color=np.where(inst_df["fini"] >= 0, "#3b82f6", "#f87171"),
        name="外資", opacity=0.85), row=inst_row, col=1)
    # 投信（綠色）
    fig.add_trace(go.Bar(
        x=inst_df["date"], y=inst_df["trust"],
        marker_color=np.where(inst_df["trust"] >= 0, "#22c55e", "#f87171"),
        name="投信", opacity=0.85), row=inst_row, col=1)
    # 自營商（橘色）
    fig.add_trace(go.Bar(
        x=inst_df["date"], y=inst_df["dealer"],
        marker_color=np.where(inst_df["dealer"] >= 0, "#f59e0b", "#f87171"),
        name="自營商", opacity=0.85), row=inst_row, col=1)
    fig.update_layout(barmode="group")

# 成交量
vol_row = 3 if not inst_df.empty else 2
vol_colors = np.where(df["close"].values >= df["open"].values, "#ef4444", "#22c55e")
fig.add_trace(go.Bar(x=df["date"], y=df["volume"], marker_color=vol_colors,
    name="成交量", showlegend=False), row=vol_row, col=1)
fig.add_trace(go.Scatter(x=df["date"], y=df["vol_ma"], mode="lines",
    line=dict(color="#f59e0b", width=1, dash="dot"), name=f"VOL MA{VOL_MA}"),
    row=vol_row, col=1)

# 版面
last_close = df["close"].iloc[-1]
last_date  = df["date"].iloc[-1].strftime("%Y-%m-%d")
title_text = f"{STOCK_NAME}（{TICKER}）K線量價+法人分析 | 收盤 {last_close:.2f} 元（{last_date}）"
if COST is not None:
    pnl = (last_close - COST) / COST * 100
    sign = "+" if pnl >= 0 else ""
    title_text += f" | 成本 {COST:.1f}（{sign}{pnl:.1f}%）"

fig.update_layout(
    title=dict(text=title_text, font=dict(size=14)),
    xaxis_rangeslider_visible=False,
    yaxis_title="股價（元）",
    legend=dict(orientation="h", y=1.02, x=1, xanchor="right"),
    height=850, template="plotly_dark", margin=dict(t=70, b=40, l=60, r=20))
fig.update_xaxes(rangebreaks=[dict(bounds=["sat","mon"])])

output = f"{TICKER}_kline.html"
fig.write_html(output)
print(f"\n[OK] 圖表已輸出 -> {output}")

# ── 9. 文字摘要 ───────────────────────────────────────────
print("\n" + "="*60)
print(f"  {STOCK_NAME}（{TICKER}）量價 + 法人分析摘要")
print("="*60)
print(f"  分析區間 ：{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")
print(f"  最新收盤 ：{last_close:.2f} 元")
if COST is not None:
    pnl_amt = last_close - COST
    pnl_pct = pnl_amt / COST * 100
    sign = "+" if pnl_amt >= 0 else ""
    print(f"  持有成本 ：{COST:.2f} 元  損益：{sign}{pnl_amt:.2f} 元（{sign}{pnl_pct:.1f}%）")
print(f"  近60日高 ：{df['high'].tail(60).max():.2f} 元")
print(f"  近60日低 ：{df['low'].tail(60).min():.2f} 元")
print(f"  MA5/20/60：{df['ma5'].iloc[-1]:.2f} / {df['ma20'].iloc[-1]:.2f} / {df['ma60'].iloc[-1]:.2f}")
print(f"  今日量   ：{df['volume'].iloc[-1]:,.0f} 張  均量(20)：{df['vol_ma'].iloc[-1]:,.0f} 張")
print(f"  放量突破（近60日）：{df['breakout'].tail(60).sum()} 次")
print(f"  量價背離（近60日）：{df['diverge'].tail(60).sum()} 次")

# 法人摘要
if not inst_df.empty:
    print()
    print("  ─── 近5日三大法人（張）───────────────────")
    for _, r in inst_df.tail(5).iterrows():
        sign_t = "+" if r["total"] >= 0 else ""
        print(f"  {r['date'].strftime('%m/%d')}  "
              f"外資:{r['fini']:+,}  投信:{r['trust']:+,}  自營:{r['dealer']:+,}  "
              f"合計:{sign_t}{r['total']:,}")
    print()
    if inst_consecutive_buy > 0:
        print(f"  法人動向 ：連續 {inst_consecutive_buy} 日買超 -> {inst_signal}")
    else:
        print(f"  法人動向 ：連續 {inst_consecutive_sell} 日賣超 -> {inst_signal}")

ma5_v, ma20_v, ma60_v = df["ma5"].iloc[-1], df["ma20"].iloc[-1], df["ma60"].iloc[-1]
if ma5_v > ma20_v > ma60_v:
    trend = "多頭排列（MA5>MA20>MA60），趨勢偏多"
elif ma5_v < ma20_v < ma60_v:
    trend = "空頭排列（MA5<MA20<MA60），趨勢偏空"
else:
    trend = "均線糾結，趨勢尚不明朗"
print(f"\n  趨勢研判 ：{trend}")
print("="*60)



