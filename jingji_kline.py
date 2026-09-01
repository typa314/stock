"""
晶技（3042.TW）K 線量價分析
-------------------------------
- 使用 yfinance 下載近一年每日 OHLCV
- 計算 5/20/60 日均線、成交量均線
- 識別「放量突破」「量縮回測」「量價背離」三種訊號
- 輸出互動式 HTML 圖表：jingji_kline.html
"""

import sys
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# ── 參數 ────────────────────────────────────────────────
TICKER    = "3042.TW"          # 晶技
DAYS_BACK = 365
MA_DAYS   = [5, 20, 60]        # 均線天數
VOL_MA    = 20                 # 成交量均線天數
MA_COLORS = ["#f59e0b", "#6366f1", "#ec4899"]

# ── 1. 下載資料 ──────────────────────────────────────────
print(f"下載 {TICKER} 資料中...")
end   = datetime.now()
start = end - timedelta(days=DAYS_BACK)
raw = yf.download(TICKER, start=start.strftime("%Y-%m-%d"),
                          end=end.strftime("%Y-%m-%d"), progress=False)

if raw.empty:
    sys.exit(f"❌ 無法取得 {TICKER} 資料，請確認代號或網路連線。")

# 若 columns 為 MultiIndex（yfinance v0.2+）則拍扁
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)

df = raw.reset_index()
df.columns = [c.lower() for c in df.columns]   # 統一小寫欄位名
df = df[["date","open","high","low","close","volume"]].copy()
df = df.dropna().reset_index(drop=True)
print(f"[OK] 取得 {len(df)} 筆資料，{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")

# ── 2. 技術指標 ──────────────────────────────────────────
for n in MA_DAYS:
    df[f"ma{n}"] = df["close"].rolling(n, min_periods=1).mean()

df["vol_ma"] = df["volume"].rolling(VOL_MA, min_periods=1).mean()

# ── 3. 量價訊號（全以純 numpy 操作，避免 pandas 對齊問題） ──
close  = df["close"].values.astype(float).flatten()
high   = df["high"].values.astype(float).flatten()
low    = df["low"].values.astype(float).flatten()
volume = df["volume"].values.astype(float).flatten()
vol_ma = df["vol_ma"].values.astype(float).flatten()

n = len(df)

# 放量突破：收盤創 20 日新高 且 成交量 > 1.5x 均量
high20 = np.array([high[max(0,i-20):i].max() if i > 0 else high[0] for i in range(n)])
breakout = np.zeros(n, dtype=bool)
breakout[1:] = (close[1:] > high20[1:]) & (volume[1:] > 1.5 * vol_ma[1:])

# 量縮回測：5 日均線附近（±1%）且成交量萎縮至均量 70% 以下
ma5 = df["ma5"].values.astype(float).flatten()
pullback = (np.abs(close - ma5) / ma5 < 0.01) & (volume < 0.7 * vol_ma)

# 量價背離：連續 3 日收盤下跌但成交量遞增（警示賣壓）
price_down = np.zeros(n, dtype=bool)
vol_up     = np.zeros(n, dtype=bool)
diverge    = np.zeros(n, dtype=bool)
for i in range(2, n):
    price_down[i] = (close[i] < close[i-1] < close[i-2])
    vol_up[i]     = (volume[i] > volume[i-1] > volume[i-2])
    diverge[i]    = price_down[i] & vol_up[i]

df["breakout"] = breakout
df["pullback"]  = pullback
df["diverge"]   = diverge

# ── 4. 繪圖 ─────────────────────────────────────────────
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    row_heights=[0.7, 0.3],
    vertical_spacing=0.03
)

# K 線
fig.add_trace(go.Candlestick(
    x=df["date"],
    open=df["open"], high=df["high"],
    low=df["low"],   close=df["close"],
    increasing_line_color="#ef4444",
    decreasing_line_color="#22c55e",
    name="K 線"
), row=1, col=1)

# 均線
for n_ma, color in zip(MA_DAYS, MA_COLORS):
    fig.add_trace(go.Scatter(
        x=df["date"], y=df[f"ma{n_ma}"],
        mode="lines", line=dict(color=color, width=1),
        name=f"MA{n_ma}"
    ), row=1, col=1)

# 成交量（收漲紅、收跌綠）
vol_colors = np.where(df["close"].values >= df["open"].values, "#ef4444", "#22c55e")
fig.add_trace(go.Bar(
    x=df["date"], y=df["volume"],
    marker_color=vol_colors,
    name="成交量",
    showlegend=False
), row=2, col=1)

# 成交量均線
fig.add_trace(go.Scatter(
    x=df["date"], y=df["vol_ma"],
    mode="lines", line=dict(color="#f59e0b", width=1, dash="dot"),
    name=f"VOL MA{VOL_MA}"
), row=2, col=1)

# ── 訊號標註 ────────────────────────────────────────────
for _, row in df[df["breakout"]].iterrows():
    fig.add_annotation(x=row["date"], y=row["high"],
        text="▲ 放量突破", showarrow=True,
        arrowhead=2, ax=0, ay=-35,
        bgcolor="#fef08a", font=dict(size=10, color="#92400e"),
        row=1, col=1)

for _, row in df[df["pullback"]].iterrows():
    fig.add_annotation(x=row["date"], y=row["low"],
        text="◆ 量縮回測", showarrow=True,
        arrowhead=2, ax=0, ay=35,
        bgcolor="#bfdbfe", font=dict(size=10, color="#1e40af"),
        row=1, col=1)

for _, row in df[df["diverge"]].iterrows():
    fig.add_annotation(x=row["date"], y=row["low"],
        text="⚠ 量價背離", showarrow=True,
        arrowhead=2, ax=0, ay=50,
        bgcolor="#fecdd3", font=dict(size=10, color="#991b1b"),
        row=1, col=1)

# ── 版面 ─────────────────────────────────────────────────
last_close = df["close"].iloc[-1]
last_date  = df["date"].iloc[-1].strftime("%Y-%m-%d")
fig.update_layout(
    title=dict(
        text=f"晶技（{TICKER}）K 線量價分析｜最新收盤 {last_close:.2f} 元（{last_date}）",
        font=dict(size=16)
    ),
    xaxis_rangeslider_visible=False,
    xaxis2_title="日期",
    yaxis_title="股價（元）",
    yaxis2_title="成交量（張）",
    legend=dict(orientation="h", y=1.02, x=1, xanchor="right"),
    height=700,
    template="plotly_dark",
    margin=dict(t=60, b=40, l=60, r=20)
)
fig.update_xaxes(
    rangebreaks=[dict(bounds=["sat","mon"])]  # 隱藏週末空白
)

output = "jingji_kline.html"
fig.write_html(output)
print(f"\n✅ 圖表已輸出 → {output}")
print("   請用瀏覽器開啟該檔案查看互動式 K 線圖。")

# ── 5. 文字摘要 ──────────────────────────────────────────
print("\n" + "="*50)
print(f"  晶技（{TICKER}）量價分析摘要")
print("="*50)
print(f"  分析區間：{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")
print(f"  最新收盤：{last_close:.2f} 元")
print(f"  近期最高：{df['high'].tail(60).max():.2f} 元")
print(f"  近期最低：{df['low'].tail(60).min():.2f} 元")
print(f"  MA5     ：{df['ma5'].iloc[-1]:.2f}  MA20：{df['ma20'].iloc[-1]:.2f}  MA60：{df['ma60'].iloc[-1]:.2f}")
print(f"  今日量  ：{df['volume'].iloc[-1]:,.0f}  量均：{df['vol_ma'].iloc[-1]:,.0f}")
print(f"  放量突破次數（近60日）：{df['breakout'].tail(60).sum()}")
print(f"  量價背離次數（近60日）：{df['diverge'].tail(60).sum()}")

# 趨勢判斷
ma5_last  = df["ma5"].iloc[-1]
ma20_last = df["ma20"].iloc[-1]
ma60_last = df["ma60"].iloc[-1]
if ma5_last > ma20_last > ma60_last:
    trend = "📈 多頭排列（MA5 > MA20 > MA60），趨勢偏多"
elif ma5_last < ma20_last < ma60_last:
    trend = "📉 空頭排列（MA5 < MA20 < MA60），趨勢偏空"
else:
    trend = "⚖️ 均線糾結，趨勢尚不明朗"
print(f"\n  趨勢研判：{trend}")
print("="*50)
