# -*- coding: utf-8 -*-
"""Plotly 多層互動式圖表繪製：K 線 + 均線 + 布林通道 + 支撐壓力矩陣（Row 1）、
三大法人買賣超（Row 2）、MACD（Row 3）、RSI（Row 4）、成交量（Row 5）。
純繪圖模組：只吃已計算好的 DataFrame 與數值，不做任何指標計算或資料擷取。
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from core.constants import MA_DAYS, VOL_MA, MA_COLORS


def build_stock_chart(ticker, stock_name, df, cost, close_now, trend_score, rating_badge, r1, r2, s1, s2, stop_loss, display_months=None):
    # 依使用者需求切片圖表顯示範圍（預設呈現近 1 個月，底層所有指標維持 12 個月完整運算無誤差）
    if display_months is not None and display_months > 0:
        cutoff = df["date"].iloc[-1] - pd.DateOffset(months=display_months)
        df_chart = df[df["date"] >= cutoff].copy()
        if len(df_chart) < 5:
            df_chart = df.tail(max(5, int(display_months * 22))).copy()
    else:
        df_chart = df

    row_heights = [0.46, 0.20, 0.18, 0.16]
    subplot_titles = ["K 線 + 20 EMA(BPA) + 均線 + 布林帶", "MACD(12,26,9)", "RSI(14)", "成交量（張）"]

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True,
                        row_heights=row_heights, vertical_spacing=0.025,
                        subplot_titles=subplot_titles)

    # Row 1：K 線 + EMA20 + 均線 + 布林帶
    fig.add_trace(go.Candlestick(
        x=df_chart["date"], open=df_chart["open"], high=df_chart["high"],
        low=df_chart["low"], close=df_chart["close"],
        increasing_line_color="#ef4444", decreasing_line_color="#22c55e",
        name="K 線"), row=1, col=1)

    # 20 EMA (Al Brooks 核心基準線)
    fig.add_trace(go.Scatter(x=df_chart["date"], y=df_chart["ema20"],
        mode="lines", line=dict(color="#06b6d4", width=1.8), name="EMA20 (BPA核心)"), row=1, col=1)

    for n_ma, color in zip(MA_DAYS, MA_COLORS):
        fig.add_trace(go.Scatter(x=df_chart["date"], y=df_chart[f"ma{n_ma}"],
            mode="lines", line=dict(color=color, width=1.1, dash="dash" if n_ma==20 else "solid"),
            name=f"MA{n_ma}"), row=1, col=1)

    # 布林帶
    fig.add_trace(go.Scatter(
        x=df_chart["date"], y=df_chart["bb_upper"], mode="lines",
        line=dict(color="rgba(148,163,184,0.45)", width=1, dash="dot"),
        name="BB上軌"), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df_chart["date"], y=df_chart["bb_lower"], mode="lines",
        line=dict(color="rgba(148,163,184,0.45)", width=1, dash="dot"),
        fill="tonexty", fillcolor="rgba(148,163,184,0.07)",
        name="BB下軌"), row=1, col=1)

    if cost is not None:
        fig.add_hline(y=cost, line=dict(color="#facc15", width=1.5, dash="dash"),
            annotation_text=f"持股成本 {cost:.1f}", annotation_position="right", row=1, col=1)

    # BPA 與量價形態標註
    for _, row in df_chart[df_chart["breakout"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["high"], text="▲ 放量突破",
            showarrow=True, arrowhead=2, ax=0, ay=-35,
            bgcolor="#fef08a", font=dict(size=10, color="#92400e"), row=1, col=1)
    for _, row in df_chart[df_chart["bpa_h2"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["low"], text="★ H2 買點",
            showarrow=True, arrowhead=2, ax=0, ay=35,
            bgcolor="#10b981", font=dict(size=10, color="#ffffff"), row=1, col=1)
    for _, row in df_chart[df_chart["bpa_l2"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["high"], text="▼ L2 賣點",
            showarrow=True, arrowhead=2, ax=0, ay=-35,
            bgcolor="#ef4444", font=dict(size=10, color="#ffffff"), row=1, col=1)
    for _, row in df_chart[df_chart["bpa_bull_gap"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["low"], text="🚀 EMA 缺口棒",
            showarrow=True, arrowhead=2, ax=0, ay=45,
            bgcolor="#0284c7", font=dict(size=10, color="#ffffff"), row=1, col=1)
    for _, row in df_chart[df_chart["bpa_bear_gap"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["high"], text="⚠️ EMA 缺口棒",
            showarrow=True, arrowhead=2, ax=0, ay=-45,
            bgcolor="#b91c1c", font=dict(size=10, color="#ffffff"), row=1, col=1)
    for _, row in df_chart[df_chart["double_inside"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["high"], text="⚑ ii 突破",
            showarrow=True, arrowhead=2, ax=0, ay=-25,
            bgcolor="#8b5cf6", font=dict(size=10, color="#ffffff"), row=1, col=1)
    for _, row in df_chart[df_chart["bull_div"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["low"], text="★ 底背離",
            showarrow=True, arrowhead=2, ax=0, ay=35,
            bgcolor="#bbf7d0", font=dict(size=10, color="#166534"), row=1, col=1)
    for _, row in df_chart[df_chart["bear_div"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["high"], text="⚠ 頂背離",
            showarrow=True, arrowhead=2, ax=0, ay=-35,
            bgcolor="#fecdd3", font=dict(size=10, color="#991b1b"), row=1, col=1)
    for _, row in df_chart[df_chart["churn"]].iterrows():
        fig.add_annotation(x=row["date"], y=row["high"], text="⚡ 爆量滯漲",
            showarrow=True, arrowhead=2, ax=0, ay=-35,
            bgcolor="#fed7aa", font=dict(size=10, color="#9a3412"), row=1, col=1)

    # Row 2：MACD 子圖
    macd_row = 2
    hist_colors = np.where(df_chart["macd_hist"].values >= 0, "#ef4444", "#22c55e")
    fig.add_trace(go.Bar(x=df_chart["date"], y=df_chart["macd_hist"],
        marker_color=hist_colors, name="MACD 柱", showlegend=False, opacity=0.7), row=macd_row, col=1)
    fig.add_trace(go.Scatter(x=df_chart["date"], y=df_chart["macd"],
        mode="lines", line=dict(color="#f59e0b", width=1.5), name="MACD"), row=macd_row, col=1)
    fig.add_trace(go.Scatter(x=df_chart["date"], y=df_chart["macd_signal"],
        mode="lines", line=dict(color="#a78bfa", width=1.5), name="Signal"), row=macd_row, col=1)
    fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.2)", width=1), row=macd_row, col=1)

    # Row 3：RSI 子圖
    rsi_row = 3
    fig.add_trace(go.Scatter(x=df_chart["date"], y=df_chart["rsi"],
        mode="lines", line=dict(color="#38bdf8", width=1.5), name="RSI(14)"), row=rsi_row, col=1)
    fig.add_hline(y=70, line=dict(color="#f87171", width=1, dash="dash"),
        annotation_text="超買 70", annotation_position="right", row=rsi_row, col=1)
    fig.add_hline(y=30, line=dict(color="#4ade80", width=1, dash="dash"),
        annotation_text="超賣 30", annotation_position="right", row=rsi_row, col=1)
    fig.add_hline(y=50, line=dict(color="rgba(255,255,255,0.15)", width=1), row=rsi_row, col=1)
    fig.update_yaxes(range=[0, 100], row=rsi_row, col=1)

    # Row 4：成交量子圖
    vol_row = 4
    vol_colors = np.where(df_chart["close"].values >= df_chart["open"].values, "#ef4444", "#22c55e")
    fig.add_trace(go.Bar(x=df_chart["date"], y=df_chart["volume"], marker_color=vol_colors,
        name="成交量", showlegend=False), row=vol_row, col=1)
    fig.add_trace(go.Scatter(x=df_chart["date"], y=df_chart["vol_ma"], mode="lines",
        line=dict(color="#f59e0b", width=1, dash="dot"), name=f"VOL MA{VOL_MA}"), row=vol_row, col=1)

    # ── 支撐與壓力矩陣（S/R 水平線）可視化 ────────────────────────────
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
        height=820,
        template="plotly_dark",
        margin=dict(t=70, b=40, l=60, r=20)
    )
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat","mon"])])
    return fig

# ── 6. 核心分析主函數 ─────────────────────────────────────────
