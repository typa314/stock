# -*- coding: utf-8 -*-
"""
台股專業量價 + Al Brooks 價格行為學（BPA）極速輕量行動看盤 Web App
專注 BPA 價格行為學、20 EMA 基準、支撐壓力矩陣與風控掛單指引
"""

import os
import sys

# 確保當前目錄在 Python 模組搜尋路徑第一位（解決 Linux / Streamlit Cloud /mount/src/stock 路徑解析問題）
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

try:
    from kline import analyze_stock, analyze_stock_5m, get_info, get_tw_tick, __version__
except Exception as e:
    import streamlit as st
    st.error(f"❌ 模組載入錯誤 (Import Error): {e}")
    st.exception(e)
    st.stop()

# ── 1. 頁面設定（手機版體驗最佳化） ─────────────────────────
st.set_page_config(
    page_title=f"[DEV] 台股 BPA 價格行為學 v{__version__}",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 自訂 CSS：美化手機端視覺與卡片陰影
st.markdown("""
<style>
    /* 緊湊邊距，適配手機螢幕 */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
        padding-left: 0.8rem;
        padding-right: 0.8rem;
    }
    /* 指標卡片樣式 */
    .metric-card {
        background-color: #1e293b;
        border-radius: 10px;
        padding: 12px 16px;
        margin-bottom: 8px;
        border: 1px solid #334155;
    }
    .metric-title {
        font-size: 0.85rem;
        color: #94a3b8;
        margin-bottom: 4px;
    }
    .metric-value {
        font-size: 1.3rem;
        font-weight: 700;
        color: #f8fafc;
    }
    .metric-sub {
        font-size: 0.78rem;
        color: #cbd5e1;
    }
    /* 操盤掛單指引卡片 */
    .order-box {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border-left: 4px solid #38bdf8;
        border-radius: 8px;
        padding: 14px;
        margin: 10px 0;
    }
    /* 專業圖卡通用樣式（三大法人與量價圖卡） */
    .dashboard-card {
        background: #1e293b;
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 12px;
        border: 1px solid #334155;
    }
    .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
        padding-bottom: 6px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    .card-title {
        font-size: 0.98rem;
        font-weight: 700;
        color: #f8fafc;
    }
    .pill-badge {
        font-size: 0.75rem;
        padding: 2px 8px;
        border-radius: 999px;
        font-weight: 600;
    }
    .grid-4 {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 8px;
        margin-bottom: 8px;
    }
    @media (max-width: 1100px) {
        .grid-4 {
            grid-template-columns: repeat(2, 1fr);
        }
    }
    .grid-cell {
        background: rgba(15, 23, 42, 0.65);
        padding: 8px 6px;
        border-radius: 6px;
        text-align: center;
        border: 1px solid rgba(255,255,255,0.04);
    }
    .cell-label {
        font-size: 0.72rem;
        color: #94a3b8;
        margin-bottom: 2px;
    }
    .cell-val {
        font-size: 1.02rem;
        font-weight: 700;
    }
    .cell-sub {
        font-size: 0.68rem;
        color: #64748b;
        margin-top: 2px;
    }
</style>
""", unsafe_allow_html=True)

# ── 2. 快取分析結果（避免重複計算，手機切換極速流暢） ───────────
# 平日盤中 (09:00~13:35) 設為 20 秒極速更新即時行情，盤後維持 300 秒以省頻寬
def _get_cache_ttl():
    now = datetime.now()
    if now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (13, 35):
        return 20
    return 300

@st.cache_data(ttl=_get_cache_ttl(), show_spinner=False)
def get_cached_analysis(ticker, months, cost, version=__version__):
    return analyze_stock(ticker=ticker, months=months, cost=cost, generate_html=False, print_report=False)

@st.cache_data(ttl=60, show_spinner=False)
def get_cached_5m(ticker, days=3, version=__version__):
    return analyze_stock_5m(ticker=ticker, days=days)

def render_cost_stop_loss_card(cost_price, current_price):
    """現貨強制停損與持股風控監控卡（依據 O'Neil / Minervini -7%~-8% 資本保護鐵律）"""
    if not cost_price or cost_price <= 0:
        return
    c_p = float(cost_price)
    diff = current_price - c_p
    pnl_pct = (diff / c_p) * 100
    pnl_1k = diff * 1000
    stop_7 = round(c_p * 0.93, 2)
    stop_8 = round(c_p * 0.92, 2)
    buf_7 = current_price - stop_7

    if current_price <= stop_8:
        tag = "🚨 觸發極限強制停損"
        card_color = "#ef4444"
        card_bg = "rgba(239, 68, 68, 0.2)"
        pnl_color = "#ef4444"
        advice = "虧損已達 -8% 極限保命線，觸發 Minervini 資本保護鐵律，強烈建議無條件市價全出，嚴防虧損失控！"
    elif current_price <= stop_7:
        tag = "⚠️ 觸發強制停損警戒"
        card_color = "#f59e0b"
        card_bg = "rgba(245, 158, 11, 0.2)"
        pnl_color = "#f59e0b"
        advice = "虧損已觸及 -7% 警戒線，建議立即分批減碼或預掛停損單，切勿凹單加碼。"
    elif diff < 0:
        tag = "🟡 浮動虧損防守中"
        card_color = "#fbbf24"
        card_bg = "rgba(245, 158, 11, 0.15)"
        pnl_color = "#fbbf24"
        advice = f"距 -7% 強制停損尚有 {buf_7:.2f} 元緩衝，緊盯技術防守位，未觸及前按紀律持有。"
    else:
        tag = "🟢 獲利持有中"
        card_color = "#22c55e"
        card_bg = "rgba(34, 197, 94, 0.15)"
        pnl_color = "#22c55e"
        advice = "部位處於獲利狀態，建議以買進成本價（保本線）或月線作為移動停利基準，鎖定獲利。"

    st.markdown(f"""
    <div class="dashboard-card" style="border-left: 4px solid {card_color}; margin-bottom: 12px;">
        <div class="card-header">
            <span class="card-title">🎯 現貨持股風控與強制停損監控</span>
            <span class="pill-badge" style="background: {card_bg}; color: {card_color}; font-weight: 700;">{tag}</span>
        </div>
        <div class="grid-4">
            <div class="grid-cell">
                <div class="cell-label">持股成本 ➔ 現價</div>
                <div class="cell-val" style="color: #f8fafc;">{c_p:.2f} ➔ {current_price:.2f}</div>
                <div class="cell-sub">每張損益 {pnl_1k:+,.0f} 元</div>
            </div>
            <div class="grid-cell">
                <div class="cell-label">浮動損益幅度</div>
                <div class="cell-val" style="color: {pnl_color};">{pnl_pct:+.2f}%</div>
                <div class="cell-sub">{"獲利鎖定中" if diff >= 0 else f"距停損剩 {buf_7:.2f} 元"}</div>
            </div>
            <div class="grid-cell">
                <div class="cell-label">強制停損 (-7% 警戒)</div>
                <div class="cell-val" style="color: #f59e0b;">{stop_7:.2f} 元</div>
                <div class="cell-sub">觸及啟動減碼</div>
            </div>
            <div class="grid-cell">
                <div class="cell-label">極限保命 (-8% 斷頭)</div>
                <div class="cell-val" style="color: #ef4444;">{stop_8:.2f} 元</div>
                <div class="cell-sub">無條件市價全出</div>
            </div>
        </div>
        <div style="font-size: 0.82rem; color: #cbd5e1; background: rgba(0,0,0,0.25); padding: 8px 12px; border-radius: 6px; margin-top: 6px; border-left: 3px solid {card_color};">
            <b>🛡️ 風控指引：</b>{advice}
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── 3. 頂部導覽與股票選擇區 ──────────────────────────────────
st.markdown(f"""
<div style="background: rgba(234, 179, 8, 0.12); border: 1px solid #eab308; color: #facc15; padding: 6px 12px; border-radius: 6px; font-size: 0.82rem; font-weight: 600; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">
    <span>🛠️ <b>DEV 開發驗證環境 (devapp.py)</b>：新功能與介面試驗中，驗證確認無誤後再同步推送到正式環境 (app.py)</span>
    <span style="font-size: 0.72rem; color: #94a3b8; font-weight: normal; background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px;">v{__version__}-dev</span>
</div>
""", unsafe_allow_html=True)
st.markdown(f"### ⚡ 台股 Al Brooks BPA 價格行為研判 <span style='font-size: 0.8rem; color: #94a3b8; font-weight: normal;'>v{__version__}</span>", unsafe_allow_html=True)

# 快捷熱門股按鈕
quick_tickers = [
    ("台積電", "2330"),
    ("晶技", "3042"),
    ("聯發科", "2454"),
    ("鴻海", "2317"),
    ("藥華藥", "6446"),
    ("長榮", "2603")
]

if "ticker_input" not in st.session_state:
    st.session_state["ticker_input"] = "2330"

def select_ticker(t):
    st.session_state["ticker_input"] = str(t).strip()

cols_btn = st.columns(len(quick_tickers))
for i, (qname, qtick) in enumerate(quick_tickers):
    cols_btn[i].button(
        f"{qname}\n{qtick}",
        key=f"btn_{qtick}",
        on_click=select_ticker,
        args=(qtick,),
        use_container_width=True
    )

with st.expander("⚙️ 搜尋股票與自訂參數", expanded=False):
    c1, c2, c3 = st.columns([2, 1, 1])
    input_ticker = c1.text_input("股票代號（上市/上櫃）", key="ticker_input").strip()
    months_opt = c2.selectbox("歷史分析月數", options=[1, 2, 3, 6, 12], index=0)
    cost_opt = c3.number_input("個人持有成本（選填）", value=0.0, step=0.5, format="%.2f")
    cost_val = cost_opt if cost_opt > 0 else None
    if st.button("🔄 清除快取並強制重整最新數據", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

current_ticker = st.session_state["ticker_input"]

# 時間週期切換膠囊
timeframe_mode = st.radio(
    "時間週期選擇",
    options=["📅 日K（波段趨勢）", "⚡ 5分K（日內當沖）"],
    horizontal=True,
    label_visibility="collapsed"
)

if timeframe_mode == "⚡ 5分K（日內當沖）":
    # ── 4. 5分K 日內價格行為分析 ──────────────────────────────
    try:
        with st.spinner(f"正在分析 {current_ticker} 5 分鐘 K 線與 BPA 日內轉折..."):
            res5 = get_cached_5m(current_ticker, days=3, version=__version__)
    except Exception as e:
        st.error(f"⚠️ 無法取得股票代號【{current_ticker}】的 5 分鐘 K 線資料：{e}")
        st.stop()

    stock_name_5m = res5["stock_name"]
    market_txt_5m = "上市 (TSE)" if res5["market"] == "tse" else "上櫃 (OTC)"

    st.markdown(f"""
    <div style="background: rgba(0,0,0,0.3); border: 1.5px solid {res5.get('action_color', '#38bdf8')}; border-left: 6px solid {res5.get('action_color', '#38bdf8')}; padding: 10px 16px; border-radius: 8px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
        <div style="display: flex; align-items: center; gap: 10px;">
            <span style="font-size: 1.25rem; font-weight: 800; color: {res5.get('action_color', '#38bdf8')}; background: {res5.get('bpa_bg', 'rgba(0,0,0,0.2)')}; padding: 4px 12px; border-radius: 6px; border: 1px solid {res5.get('action_color', '#38bdf8')}; letter-spacing: 0.5px;">{res5.get('action_tag', '🟡 建議觀望')}</span>
            <span style="font-size: 0.88rem; color: #f1f5f9; font-weight: 600;">{res5.get('action_sub', '')}</span>
            <span style="font-size: 0.80rem; background: {res5.get('whale_bg', 'rgba(0,0,0,0.2)')}; color: {res5.get('whale_color', '#94a3b8')}; border: 1px solid {res5.get('whale_color', '#94a3b8')}; padding: 2px 8px; border-radius: 4px; font-weight: 700;">{res5.get('whale_tag', '')}</span>
        </div>
        <div style="font-size: 0.78rem; color: #94a3b8;">
            ⚡ <b>5分K 當沖架構</b>（{stock_name_5m} {current_ticker}）｜ 資料時間：{res5['data_time_str']}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 現貨強制停損與持股風控監控卡（當使用者有輸入持有成本時顯示）
    render_cost_stop_loss_card(cost_val, res5["close_now"])

    # 4 關鍵 5分K 指標橫幅
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">5m BPA 市場狀態</div>
            <div class="metric-value" style="color: {res5['bpa_status_color']}; font-size: 1.02rem;">{res5['bpa_status'].split('（')[0]}</div>
            <div class="metric-sub">{res5['bpa_status'].split('（')[1].replace('）','')}</div>
        </div>
        """, unsafe_allow_html=True)

    with k2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">5m 20 EMA 基準</div>
            <div class="metric-value">{res5['ema_now']:.2f} 元</div>
            <div class="metric-sub">乖離 {res5['ema_bias']:+.2f} ({res5['ema_bias_pct']:+.1f}%)</div>
        </div>
        """, unsafe_allow_html=True)

    with k3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">今日高低振幅</div>
            <div class="metric-value">{res5['range_today']:.2f} 元</div>
            <div class="metric-sub">高 {res5['high_today']:.1f} / 低 {res5['low_today']:.1f}</div>
        </div>
        """, unsafe_allow_html=True)

    with k4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">5m 主力量能狀態</div>
            <div class="metric-value" style="color: {res5.get('whale_color', '#94a3b8')}; font-size: 1.02rem;">{res5.get('whale_tag', '⚪ 常態量能')}</div>
            <div class="metric-sub">{res5.get('vol_ratio_5m', 1.0)}倍 5m均量 ｜ {res5['last_bar_type'].split('(')[0].strip()}</div>
        </div>
        """, unsafe_allow_html=True)

    pct_1r_5m = abs(res5['target_1r'] - res5['close_now']) / res5['close_now'] * 100
    pct_2r_5m = abs(res5['target_2r'] - res5['close_now']) / res5['close_now'] * 100
    pct_stop_5m = abs(res5['close_now'] - res5['stop_loss']) / res5['close_now'] * 100
    stop_dir = res5.get('stop_direction', '-')

    # 5m 專屬風控掛單指引卡
    st.markdown(f"""
    <div class="dashboard-card" style="border-left: 4px solid {res5['bpa_status_color']};">
        <div class="card-header">
            <span class="card-title">⚡ 5 分 K 日內風控與掛單指引</span>
            <div style="display: flex; gap: 6px; align-items: center;">
                <span class="pill-badge" style="background: {res5.get('whale_bg', 'rgba(0,0,0,0.2)')}; color: {res5.get('whale_color', '#94a3b8')}; border: 1px solid {res5.get('whale_color', '#94a3b8')}; font-weight: 700;">{res5.get('whale_tag', '')}</span>
                <span class="pill-badge" style="background: {res5['bpa_bg']}; color: {res5['bpa_status_color']};">{res5['bpa_status'].split('（')[0]}</span>
            </div>
        </div>
        <div class="grid-4">
            <div class="grid-cell">
                <div class="cell-label">{res5.get('entry_type', '突破進場價位')}</div>
                <div class="cell-val" style="color: #ef4444;">{res5['buy_stop'] if '多' in res5['bpa_status'] else res5['sell_stop']:.2f} 元</div>
                <div class="cell-sub">{"跌破防守: " + f"{res5['sell_stop']:.2f} 元" if '多' in res5['bpa_status'] else "突破反轉: " + f"{res5['buy_stop']:.2f} 元"}</div>
            </div>
            <div class="grid-cell">
                <div class="cell-label">{res5.get('stop_type', '防守停損價位')}</div>
                <div class="cell-val" style="color: #f59e0b;">{res5['stop_loss']:.2f} 元</div>
                <div class="cell-sub">單筆風險: {stop_dir}{res5['r_val']:.2f} 元 ({stop_dir}{pct_stop_5m:.1f}%)</div>
            </div>
            <div class="grid-cell">
                <div class="cell-label">目標一價位 (1R 等距達標)</div>
                <div class="cell-val" style="color: #38bdf8;">{res5['target_1r']:.2f} 元</div>
                <div class="cell-sub">預期獲利: {pct_1r_5m:+.1f}% ｜ 達標可保本</div>
            </div>
            <div class="grid-cell">
                <div class="cell-label">目標二價位 (2R 擴展獲利)</div>
                <div class="cell-val" style="color: #4ade80;">{res5['target_2r']:.2f} 元</div>
                <div class="cell-sub">預期獲利: {pct_2r_5m:+.1f}% ｜ 波段滿足點</div>
            </div>
        </div>
        <div style="font-size: 0.82rem; color: #cbd5e1; background: rgba(0,0,0,0.25); padding: 8px 12px; border-radius: 6px; margin-top: 6px; border-left: 3px solid {res5.get('whale_color', '#94a3b8')};">
            <b>⚡ 主力量能：</b><span style="color: {res5.get('whale_color', '#94a3b8')}; font-weight: 700;">{res5.get('whale_tag', '')}</span> ｜ {res5.get('whale_advice', '')}
        </div>
        <div style="font-size: 0.82rem; color: #cbd5e1; background: rgba(0,0,0,0.25); padding: 8px 12px; border-radius: 6px; margin-top: 6px;">
            <b>🎯 當沖指引：</b>{res5['bpa_guide']}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 5m 互動圖表
    with st.expander("📈 展開 5 分鐘 K 線互動圖表（含 20 EMA、今日開盤價與高低點）", expanded=True):
        st.plotly_chart(res5["fig"], use_container_width=True)

    # 日內 3 大 BPA 紀律提醒
    current_tick = get_tw_tick(res5['close_now'])
    st.markdown(f"""
    <div style="font-size: 0.78rem; color: #94a3b8; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); padding: 10px 14px; border-radius: 6px; margin-top: 10px; line-height: 1.6;">
        💡 <b>5分K 日內風控心法（{stock_name_5m} 現價 {res5['close_now']:.2f} 元）：</b><br>
        1. <b>早盤定調（09:00~10:30）</b>：觀察開盤前 18 根 K 線確認單邊趨勢或寬幅震盪，確立 Always-In 多空主控權。<br>
        2. <b>順勢回測（M2B / M2S）</b>：順應大趨勢，耐心等待拉回 20 EMA 守穩並出現反轉棒再進場；切忌未見止跌訊號盲目接刀猜底，亦切忌強推升時隨意摸頂放空。<br>
        3. <b>硬停損</b>：{res5.get('stop_type', '防守停損')} <b>{res5['stop_loss']:.2f} 元</b>，單筆虧損嚴格鎖定在 <b>{stop_dir}{res5['r_val']:.2f} 元 ({stop_dir}{pct_stop_5m:.1f}%)</b>，觸及即嚴格停損離場，絕不扛單。
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="text-align: center; color: #64748b; font-size: 0.76rem; margin-top: 2rem; padding: 14px 0; border-top: 1px solid rgba(255,255,255,0.06);">
        台股 BPA 價格行為量化研判系統 <b>v{__version__}</b> ｜ 遵循 SemVer 語意化版本管理規範 ｜ Git Tag 發布管理
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── 4. 日K 執行研判與展示（原既有邏輯） ────────────────────
try:
    with st.spinner(f"正在分析 {current_ticker} BPA 價格行為與位階..."):
        res = get_cached_analysis(current_ticker, months_opt, cost_val, version=__version__)
except Exception as e:
    st.error(f"⚠️ 無法取得股票代號【{current_ticker}】的資料：{e}")
    st.stop()

# 基礎資訊
stock_name = res["stock_name"]
market_txt = "上市 (TSE)" if res["market"] == "tse" else "上櫃 (OTC)"
close_now  = res["close_now"]
df         = res["df"]
inst_df    = res.get("inst_df", pd.DataFrame())
vol_eval   = res.get("vol_eval", {})
realtime_info = res.get("realtime_info")
bpa_res    = res["bpa_res"]
sr         = res["sr_levels"]
trend_score= res["trend_score"]
badge      = res["rating_badge"]

# 計算當日漲跌
prev_close = df["close"].iloc[-2] if len(df) >= 2 else close_now
chg_val = close_now - prev_close
chg_pct = (chg_val / prev_close) * 100
chg_color = "#ef4444" if chg_val > 0 else ("#22c55e" if chg_val < 0 else "#94a3b8")
chg_sign = "+" if chg_val > 0 else ""

# 盤中即時狀態標籤
if realtime_info and realtime_info.get("is_realtime"):
    rt_badge_html = f'<span style="font-size: 0.76rem; background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid rgba(34,197,94,0.4); padding: 2px 7px; border-radius: 4px; margin-left: 6px;">⚡ 盤中即時 {realtime_info.get("time","")}</span>'
else:
    rt_badge_html = '<span style="font-size: 0.76rem; background: rgba(148, 163, 184, 0.2); color: #cbd5e1; border: 1px solid rgba(148,163,184,0.3); padding: 2px 7px; border-radius: 4px; margin-left: 6px;">📅 盤後結算</span>'

# 頂部個股摘要欄
st.markdown(f"""
<div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px;">
    <div>
        <span style="font-size: 1.5rem; font-weight: 800;">{stock_name}</span>
        <span style="font-size: 1.1rem; color: #94a3b8; margin-left: 6px;">{current_ticker}</span>
        <span style="font-size: 0.8rem; background: #334155; color: #cbd5e1; padding: 2px 6px; border-radius: 4px; margin-left: 6px;">{market_txt}</span>
        {rt_badge_html}
    </div>
    <div style="text-align: right;">
        <span style="font-size: 1.6rem; font-weight: 800; color: {chg_color};">{close_now:.2f}</span>
        <span style="font-size: 0.95rem; color: {chg_color}; margin-left: 4px;">{chg_sign}{chg_val:.2f} ({chg_sign}{chg_pct:.2f}%)</span>
    </div>
</div>
""", unsafe_allow_html=True)

# 頂部核心操盤動作橫幅（建議買入 / 建議持有 / 建議觀望 / 建議賣出）
comp = res.get("composite_rating", {})
action_tag = comp.get("action_tag", "🟡 建議觀望")
action_color = comp.get("action_color", "#fbbf24")
action_bg = comp.get("action_bg", "rgba(245, 158, 11, 0.16)")
action_border = comp.get("action_border", "#fbbf24")
action_sub = comp.get("action_sub", "多空拉鋸，靜待方向")

st.markdown(f"""
<div style="background: rgba(0,0,0,0.3); border: 1.5px solid {action_border}; border-left: 6px solid {action_border}; padding: 10px 16px; border-radius: 8px; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
    <div style="display: flex; align-items: center; gap: 10px;">
        <span style="font-size: 1.25rem; font-weight: 800; color: {action_color}; background: {action_bg}; padding: 4px 12px; border-radius: 6px; border: 1px solid {action_border}; letter-spacing: 0.5px;">{action_tag}</span>
        <span style="font-size: 0.90rem; color: #f1f5f9; font-weight: 600;">{action_sub}</span>
    </div>
    <div style="font-size: 0.8rem; color: #94a3b8;">
        綜合評分：<b style="color: {action_color}; font-size: 1.05rem;">{comp.get('score', 0)}</b> / 100 ｜ 體質：<span style="color: {comp.get('badge_color', '#60a5fa')}; font-weight: 600;">{comp.get('badge', '').split('（')[0]}</span>
    </div>
</div>
""", unsafe_allow_html=True)

# 現貨強制停損與持股風控監控卡（當使用者有輸入持有成本時顯示）
render_cost_stop_loss_card(cost_val, close_now)

# ── 4.1 四大關鍵指標橫幅卡片 ─────────────────────────────────
k1, k2, k3, k4 = st.columns(4)

with k1:
    ai_zh = bpa_res.get("always_in_zh", "箱型震盪")
    ai_desc = bpa_res.get("always_in_desc", "區間高出低進（突破易失敗）")
    if "多" in ai_zh:
        ai_color = "#4ade80"
    elif "空" in ai_zh:
        ai_color = "#f87171"
    else:
        ai_color = "#fbbf24"

    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">BPA 市場狀態</div>
        <div class="metric-value" style="font-size: 1.15rem; color: {ai_color}; font-weight: 800;">{ai_zh}</div>
        <div class="metric-sub">{ai_desc}</div>
    </div>
    """, unsafe_allow_html=True)

with k2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">20 EMA 基準位階</div>
        <div class="metric-value">{df['ema20'].iloc[-1]:.2f}</div>
        <div class="metric-sub">乖離率 {bpa_res['bias_ema20']:+.2f}% ｜ 斜率 {bpa_res['ema_slope']:+.2f}%</div>
    </div>
    """, unsafe_allow_html=True)

with k3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">多維量化評級</div>
        <div class="metric-value" style="font-size: 1.05rem;">{trend_score:+d} 分</div>
        <div class="metric-sub">{badge.split('（')[0]}</div>
    </div>
    """, unsafe_allow_html=True)

with k4:
    last_bar = bpa_res["last_bar_type"].split("/")[0].strip()
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">當前 K 線結構</div>
        <div class="metric-value" style="font-size: 1.05rem;">{last_bar}</div>
        <div class="metric-sub">{res['trend_stage'].split('（')[0]}</div>
    </div>
    """, unsafe_allow_html=True)

# ── 4.2 巨星多維綜合評級圖卡（Minervini + CANSLIM + BPA + 法人量價） ─────────
comp = res.get("composite_rating", {})
if comp:
    st.markdown(f"""
    <div class="dashboard-card" style="border-left: 4px solid {comp.get('badge_color', '#38bdf8')};">
        <div class="card-header">
            <span class="card-title">🌟 多維綜合評級 <span style="font-size: 0.78rem; color: #94a3b8; font-weight: normal; margin-left: 6px;">綜合評分：<b style="color: {comp.get('badge_color', '#38bdf8')}; font-size: 1.05rem;">{comp.get('score', 0)}</b> / 100</span></span>
            <div style="display: flex; gap: 6px; align-items: center;">
                <span class="pill-badge" style="background: {comp.get('action_bg', 'rgba(59,130,246,0.2)')}; color: {comp.get('action_color', '#38bdf8')}; border: 1px solid {comp.get('action_border', '#38bdf8')}; font-weight: 700;">{comp.get('action_tag', '🟡 建議觀望')}</span>
                <span class="pill-badge" style="background: {comp.get('badge_bg', 'rgba(59, 130, 246, 0.2)')}; color: {comp.get('badge_color', '#60a5fa')};">{comp.get('badge', '')}</span>
            </div>
        </div>
        <div class="grid-4">
            <div class="grid-cell">
                <div class="cell-label">趨勢樣板 (Minervini)</div>
                <div class="cell-val" style="color: {comp.get('minervini_color', '#cbd5e1')};">{comp.get('minervini_passed', 0)}/7 項</div>
                <div class="cell-sub">{comp.get('minervini_status', '')}</div>
            </div>
            <div class="grid-cell">
                <div class="cell-label">成長動能 (CANSLIM)</div>
                <div class="cell-val" style="color: {comp.get('canslim_color', '#cbd5e1')};">{comp.get('canslim_grade', '--')}</div>
                <div class="cell-sub">{comp.get('canslim_sub', '')}</div>
            </div>
            <div class="grid-cell">
                <div class="cell-label">價格行為 (BPA)</div>
                <div class="cell-val" style="color: {comp.get('bpa_color', '#cbd5e1')};">{comp.get('bpa_zh', '--')}</div>
                <div class="cell-sub">{comp.get('bpa_sub', '')}</div>
            </div>
            <div class="grid-cell">
                <div class="cell-label">量能籌碼 (VPA/法人)</div>
                <div class="cell-val" style="color: {comp.get('chip_color', '#cbd5e1')};">{comp.get('chip_zh', '--')}</div>
                <div class="cell-sub">{comp.get('chip_sub', '')}</div>
            </div>
        </div>
        <div style="font-size: 0.82rem; color: #cbd5e1; background: rgba(0,0,0,0.25); padding: 8px 12px; border-radius: 6px; margin-top: 6px;">
            <b>🎯 操盤方針：</b><b style="color: {comp.get('action_color', '#38bdf8')};">{comp.get('action_tag', '')}</b> ｜ {comp.get('summary_advice', '')}
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── 4.3 三大法人籌碼、量價結構與基本面財報獲利圖卡 ─────────────
col_inst, col_vol, col_fund = st.columns(3)
fundamentals = res.get("fundamentals", {})

with col_inst:
    if not inst_df.empty:
        last_inst = inst_df.iloc[-1]
        fini_val = int(last_inst["fini"])
        trust_val = int(last_inst["trust"])
        dealer_val = int(last_inst["dealer"])
        total_val = int(last_inst["total"])
        inst_date = last_inst["date"].strftime("%m/%d")

        fini_5d = int(inst_df.tail(5)["fini"].sum())
        trust_5d = int(inst_df.tail(5)["trust"].sum())
        dealer_5d = int(inst_df.tail(5)["dealer"].sum())
        total_5d = int(inst_df.tail(5)["total"].sum())

        if fini_val > 0 and trust_val > 0:
            inst_tag = "🟢 土洋聯手買超"
            tag_bg = "rgba(34, 197, 94, 0.2)"
            tag_color = "#4ade80"
        elif fini_val < 0 and trust_val < 0:
            inst_tag = "🔴 土洋聯手賣超"
            tag_bg = "rgba(239, 68, 68, 0.2)"
            tag_color = "#f87171"
        elif fini_val > 0:
            inst_tag = "🔵 外資獨買/投信調節"
            tag_bg = "rgba(59, 130, 246, 0.2)"
            tag_color = "#60a5fa"
        elif trust_val > 0:
            inst_tag = "🟣 投信作多/外資調節"
            tag_bg = "rgba(168, 85, 247, 0.2)"
            tag_color = "#c084fc"
        else:
            inst_tag = "🟡 法人偏空/動向分歧"
            tag_bg = "rgba(245, 158, 11, 0.2)"
            tag_color = "#fbbf24"

        # 台股慣例：買超為正（紅字）、賣超為負（綠字）
        def fmt_inst_html(val):
            color = "#ef4444" if val > 0 else ("#22c55e" if val < 0 else "#94a3b8")
            sign = "+" if val > 0 else ""
            return f'<span style="color: {color}; font-weight: 700;">{sign}{val:,}</span>'

        # 籌碼集中度：比對該法人公告日當天之成交量（而非盤中即時部分成交量）
        match_row = df[df["date"].dt.date == last_inst["date"].date()]
        inst_day_vol = match_row["volume"].iloc[0] if not match_row.empty else (df["volume"].iloc[-2] if len(df) >= 2 else df["volume"].iloc[-1])
        inst_conc = abs(total_val) / (inst_day_vol + 1e-9) * 100

        st.markdown(f"""
        <div class="dashboard-card">
            <div class="card-header">
                <span class="card-title">🏛️ 三大法人籌碼圖卡 <span style="font-size: 0.76rem; color: #94a3b8; font-weight: normal; background: rgba(255,255,255,0.06); padding: 2px 6px; border-radius: 4px; margin-left: 4px;">📅 {inst_date} 盤後公告</span></span>
                <span class="pill-badge" style="background: {tag_bg}; color: {tag_color};">{inst_tag}</span>
            </div>
            <div class="grid-4">
                <div class="grid-cell">
                    <div class="cell-label">外資單日</div>
                    <div class="cell-val">{fmt_inst_html(fini_val)}</div>
                    <div class="cell-sub">5日 {fmt_inst_html(fini_5d)}</div>
                </div>
                <div class="grid-cell">
                    <div class="cell-label">投信單日</div>
                    <div class="cell-val">{fmt_inst_html(trust_val)}</div>
                    <div class="cell-sub">5日 {fmt_inst_html(trust_5d)}</div>
                </div>
                <div class="grid-cell">
                    <div class="cell-label">自營商單日</div>
                    <div class="cell-val">{fmt_inst_html(dealer_val)}</div>
                    <div class="cell-sub">5日 {fmt_inst_html(dealer_5d)}</div>
                </div>
                <div class="grid-cell">
                    <div class="cell-label">三大合計</div>
                    <div class="cell-val">{fmt_inst_html(total_val)}</div>
                    <div class="cell-sub">5日 {fmt_inst_html(total_5d)}</div>
                </div>
            </div>
            <div style="font-size: 0.8rem; color: #cbd5e1; background: rgba(0,0,0,0.25); padding: 8px 10px; border-radius: 6px; margin-top: 6px;">
                <b>近 5 日三大法人合計：</b> {fmt_inst_html(total_5d)} 張 ｜ 公告日佔量集中度 <b>{inst_conc:.1f}%</b>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="dashboard-card">
            <div class="card-header">
                <span class="card-title">🏛️ 三大法人籌碼圖卡</span>
                <span class="pill-badge" style="background: rgba(148, 163, 184, 0.2); color: #cbd5e1;">上櫃 / 暫無數據</span>
            </div>
            <div style="font-size: 0.85rem; color: #94a3b8; padding: 16px 8px; text-align: center;">
                ℹ️ 該個股為上櫃 (OTC) 股票或非上市法人資料。<br>
                三大法人買賣超為證交所盤後（每日約 15:00）公布之日結數據，盤中無法人即時數據；技術面與量價指標皆維持盤中即時動態研判。
            </div>
        </div>
        """, unsafe_allow_html=True)

with col_vol:
    v_now = float(vol_eval.get("vol_now", df["volume"].iloc[-1]))
    v_ma20 = float(vol_eval.get("vol_ma20", df["vol_ma"].iloc[-1]))
    v_ma5 = float(vol_eval.get("vol_ma5", df["volume"].rolling(5, min_periods=1).mean().iloc[-1]))
    v_ratio_20 = float(vol_eval.get("vol_ratio_20", v_now / (v_ma20 + 1e-9)))
    v_status = vol_eval.get("status", "量價常態")
    v_desc = vol_eval.get("desc", "今日量價結構平穩")
    v_advice = vol_eval.get("advice", "維持紀律操作")
    v_score = vol_eval.get("score", 0)

    if v_score > 0:
        vol_badge_bg = "rgba(34, 197, 94, 0.2)"
        vol_badge_color = "#4ade80"
    elif v_score < 0:
        vol_badge_bg = "rgba(239, 68, 68, 0.2)"
        vol_badge_color = "#f87171"
    else:
        vol_badge_bg = "rgba(245, 158, 11, 0.2)"
        vol_badge_color = "#fbbf24"

    ratio_color = "#ef4444" if v_ratio_20 >= 1.25 else ("#22c55e" if v_ratio_20 <= 0.75 else "#f8fafc")

    st.markdown(f"""
    <div class="dashboard-card">
        <div class="card-header">
            <span class="card-title">📊 量價結構與動能圖卡</span>
            <span class="pill-badge" style="background: {vol_badge_bg}; color: {vol_badge_color};">{v_status.split('（')[0]}</span>
        </div>
        <div class="grid-4">
            <div class="grid-cell">
                <div class="cell-label">今日成交量</div>
                <div class="cell-val" style="color: #f8fafc;">{v_now:,.0f} <span style="font-size: 0.72rem; font-weight: normal; color: #94a3b8;">張</span></div>
                <div class="cell-sub">最新交易日</div>
            </div>
            <div class="grid-cell">
                <div class="cell-label">20MA 均量</div>
                <div class="cell-val" style="color: #cbd5e1;">{v_ma20:,.0f} <span style="font-size: 0.72rem; font-weight: normal; color: #94a3b8;">張</span></div>
                <div class="cell-sub">月均量基準</div>
            </div>
            <div class="grid-cell">
                <div class="cell-label">量能比率</div>
                <div class="cell-val" style="color: {ratio_color};">{v_ratio_20*100:.1f}%</div>
                <div class="cell-sub">{v_ratio_20:.2f} 倍 20MA</div>
            </div>
            <div class="grid-cell">
                <div class="cell-label">5MA 均量</div>
                <div class="cell-val" style="color: #cbd5e1;">{v_ma5:,.0f} <span style="font-size: 0.72rem; font-weight: normal; color: #94a3b8;">張</span></div>
                <div class="cell-sub">週均量水準</div>
            </div>
        </div>
        <div style="font-size: 0.8rem; color: #cbd5e1; background: rgba(0,0,0,0.25); padding: 8px 10px; border-radius: 6px; margin-top: 6px;">
            <b>量價診斷：</b>{v_desc}<br>
            <b>操盤應對：</b><span style="color: {vol_badge_color};">{v_advice}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col_fund:
    if fundamentals.get("has_data"):
        per = fundamentals.get("per")
        pbr = fundamentals.get("pbr")
        dy = fundamentals.get("dividend_yield")
        eps_ttm = fundamentals.get("eps_ttm")
        latest_eps = fundamentals.get("latest_eps")
        lq = fundamentals.get("latest_quarter", "")
        gm = fundamentals.get("gross_margin")
        om = fundamentals.get("operating_margin")
        rev_val = fundamentals.get("latest_revenue_val")
        rev_d = fundamentals.get("revenue_date", "")
        rev_yoy = fundamentals.get("revenue_yoy")

        if per is not None:
            if per < 15:
                fund_tag = "🟢 價值低估 (P/E<15)"
                f_bg = "rgba(34, 197, 94, 0.2)"
                f_color = "#4ade80"
            elif per <= 30:
                fund_tag = "🔵 估值合理 (P/E 15~30)"
                f_bg = "rgba(59, 130, 246, 0.2)"
                f_color = "#60a5fa"
            else:
                fund_tag = "🟡 成長溢價 (P/E>30)"
                f_bg = "rgba(245, 158, 11, 0.2)"
                f_color = "#fbbf24"
        else:
            fund_tag = "⚪ 穩健營運"
            f_bg = "rgba(148, 163, 184, 0.2)"
            f_color = "#cbd5e1"

        per_str = f"{per:.1f} 倍" if per is not None else "--"
        pbr_str = f"{pbr:.2f} 倍" if pbr is not None else "--"
        dy_str = f"{dy:.2f}%" if dy is not None else "--"
        eps_str = f"{eps_ttm:.2f} 元" if eps_ttm is not None else "--"
        lq_str = f"最新單季 {latest_eps:.2f} 元" if latest_eps is not None else "--"
        gm_str = f"{gm:.1f}%" if gm is not None else "--"
        om_str = f"營益率 {om:.1f}%" if om is not None else "--"

        if rev_val is not None:
            y_color = "#ef4444" if (rev_yoy is not None and rev_yoy >= 0) else "#22c55e"
            y_sign = "+" if (rev_yoy is not None and rev_yoy >= 0) else ""
            yoy_str = f"{y_sign}{rev_yoy:.1f}%" if rev_yoy is not None else "--"
            yoy_html = f"<b>{rev_d} 營收：</b>{rev_val:,.1f} 億 ｜ 年增率 (YoY) <span style='color: {y_color}; font-weight: 700;'>{yoy_str}</span>"
        else:
            yoy_html = "<b>財報說明：</b>臺灣證交所與官方公開觀測站最新公佈申報資料"

        st.markdown(f"""
        <div class="dashboard-card">
            <div class="card-header">
                <span class="card-title">🏢 基本面與財報獲利 <span style="font-size: 0.76rem; color: #94a3b8; font-weight: normal; background: rgba(255,255,255,0.06); padding: 2px 6px; border-radius: 4px; margin-left: 4px;">📅 {lq} 季報</span></span>
                <span class="pill-badge" style="background: {f_bg}; color: {f_color};">{fund_tag}</span>
            </div>
            <div class="grid-4">
                <div class="grid-cell">
                    <div class="cell-label">近四季 EPS</div>
                    <div class="cell-val" style="color: #f8fafc;">{eps_str}</div>
                    <div class="cell-sub">{lq_str}</div>
                </div>
                <div class="grid-cell">
                    <div class="cell-label">本益比 (P/E)</div>
                    <div class="cell-val" style="color: #cbd5e1;">{per_str}</div>
                    <div class="cell-sub">淨值比 {pbr_str}</div>
                </div>
                <div class="grid-cell">
                    <div class="cell-label">現金殖利率</div>
                    <div class="cell-val" style="color: #4ade80;">{dy_str}</div>
                    <div class="cell-sub">最新日結估算</div>
                </div>
                <div class="grid-cell">
                    <div class="cell-label">單季毛利率</div>
                    <div class="cell-val" style="color: #cbd5e1;">{gm_str}</div>
                    <div class="cell-sub">{om_str}</div>
                </div>
            </div>
            <div style="font-size: 0.8rem; color: #cbd5e1; background: rgba(0,0,0,0.25); padding: 8px 10px; border-radius: 6px; margin-top: 6px;">
                {yoy_html}
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="dashboard-card">
            <div class="card-header">
                <span class="card-title">🏢 基本面與財報獲利</span>
                <span class="pill-badge" style="background: rgba(148, 163, 184, 0.2); color: #cbd5e1;">ETF / 無財報</span>
            </div>
            <div style="font-size: 0.85rem; color: #94a3b8; padding: 16px 8px; text-align: center;">
                ℹ️ 此標的為 ETF、指數或尚未公告財報之個股，暫無每股盈餘 (EPS) 與本益比數據。<br>
                技術面與量價指標皆維持完整動態研判。
            </div>
        </div>
        """, unsafe_allow_html=True)

# ── 4.3 完整互動 K 線圖表（下拉折疊選單，電腦端方便檢視，手機端預設收合保持清爽） ────
if "fig" in res and res["fig"] is not None:
    with st.expander("📈 展開完整互動 K 線圖表（含 BPA 支撐壓力線、20 EMA、布林通道與技術指標）", expanded=False):
        st.plotly_chart(
            res["fig"],
            use_container_width=True,
            config={
                "scrollZoom": True,
                "displaylogo": False,
                "modeBarButtonsToRemove": ["lasso2d", "select2d"]
            }
        )

# ── 4.4 Al Brooks 操盤掛單與風控指引 ─────────────────────────
st.markdown("#### 🎯 Brooks 操盤訂單與停損指引")
if bpa_res['always_in_code'] == 'AIL':
    strat_title = "多頭主控策略 ── 順勢偏多操作"
    strat_desc = "順應 20 EMA 多頭架構，拉回尋找 H1/H2 買點，或以突破掛單進場"
    strat_color = "#10b981"
    entry_lbl = f"突破買進 {bpa_res['buy_stop']:.2f} 元"
    stop_lbl = f"做多防守停損 {bpa_res['sell_stop']:.2f} 元 (跌破下方認賠，風險 {bpa_res['risk_long']:.2f} 元)"
    t1_val = bpa_res['target_long_1r']
    t2_val = bpa_res['target_long_2r']
    t1_lbl = f"{t1_val:.2f} 元 (預期 +{(t1_val - close_now) / close_now * 100:+.1f}%)"
    t2_lbl = f"{t2_val:.2f} 元 (預期 +{(t2_val - close_now) / close_now * 100:+.1f}%)"
elif bpa_res['always_in_code'] == 'AIS':
    strat_title = "空方主導策略 ── 順勢偏空操作"
    strat_desc = "反彈尋找 L1/L2 空點，持股者逢高調節，空方設跌破放空單順勢佈局"
    strat_color = "#ef4444"
    entry_lbl = f"跌破放空 {bpa_res['sell_stop']:.2f} 元"
    stop_lbl = f"放空防守停損 {bpa_res['buy_stop']:.2f} 元 (突破上方停損，風險 {bpa_res['risk_short']:.2f} 元)"
    t1_val = bpa_res['target_short_1r']
    t2_val = bpa_res['target_short_2r']
    t1_lbl = f"{t1_val:.2f} 元 (預期 {(t1_val - close_now) / close_now * 100:+.1f}%)"
    t2_lbl = f"{t2_val:.2f} 元 (預期 {(t2_val - close_now) / close_now * 100:+.1f}%)"
else:
    strat_title = "區間震盪策略 ── 80% 突破失敗法則"
    strat_desc = f"箱型區間高出低進：接近支撐 S1/S2（{sr['s1']:.2f} / {sr['s2']:.2f} 元）低接，接近壓力 R1/R2（{sr['r1']:.2f} / {sr['r2']:.2f} 元）調節，嚴禁在箱型中間追價，防範來回侵蝕本金"
    strat_color = "#f59e0b"
    entry_lbl = f"支撐區逢低買進 {sr['s1']:.2f} 元"
    stop_lbl = f"跌破防守停損 {sr['stop_loss']:.2f} 元"
    t1_val = (sr['r1'] + sr['s1']) / 2
    t2_val = sr['r1']
    t1_lbl = f"{t1_val:.2f} 元 (箱型中軸)"
    t2_lbl = f"{t2_val:.2f} 元 (箱型壓力)"

st.markdown(f"""
<div class="order-box" style="border-left-color: {strat_color};">
    <div style="font-weight: 700; color: {strat_color}; margin-bottom: 4px;">{strat_title}</div>
    <div style="font-size: 0.88rem; color: #cbd5e1; margin-bottom: 8px;">{strat_desc}</div>
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(135px, 1fr)); gap: 8px; font-size: 0.82rem; background: rgba(0,0,0,0.25); padding: 10px; border-radius: 6px;">
        <div><b>訊號棒區間：</b>高 {bpa_res['sig_high']:.2f} / 低 {bpa_res['sig_low']:.2f}</div>
        <div><b>進場掛單價：</b>{entry_lbl}</div>
        <div><b>防守停損價：</b>{stop_lbl}</div>
        <div><b>目標一價位 (1R等距)：</b><span style="color: #38bdf8; font-weight: 700;">{t1_lbl}</span></div>
        <div><b>目標二價位 (2R擴展)：</b><span style="color: #4ade80; font-weight: 700;">{t2_lbl}</span></div>
    </div>
</div>
""", unsafe_allow_html=True)

if bpa_res["signals"]:
    st.info("💡 **近期觸發之關鍵訊號：** " + " ｜ ".join(bpa_res["signals"]))

# ── 4.4 核心分析分頁（支撐壓力 / 趨勢與BPA細項 / 操盤行動指引） ────────
tab1, tab2, tab3 = st.tabs(["🎯 支撐壓力矩陣", "🧭 趨勢與 BPA 評估明細", "💡 操盤行動指引"])

with tab1:
    s_col1, s_col2 = st.columns(2)
    with s_col1:
        st.write("##### 🔺 壓力位階")
        st.markdown(f"- **R2（布林上軌/波段頂）**：`{sr['r2']:.2f} 元`")
        st.markdown(f"- **R1（近20日高點）**：`{sr['r1']:.2f} 元`")
        st.markdown(f"- **當前收盤現價**：`{close_now:.2f} 元`")
    with s_col2:
        st.write("##### 🔻 支撐位階")
        st.markdown(f"- **S1（20MA 月線支撐）**：`{sr['s1']:.2f} 元`")
        st.markdown(f"- **S2（近20日低點）**：`{sr['s2']:.2f} 元`")
        st.markdown(f"- **防守停損線**：`{sr['stop_loss']:.2f} 元`")

with tab2:
    st.write(f"**綜合評級：** `{badge}` ｜ **總得分：** `{trend_score:+d} 分`")
    for factor in res["trend_factors"]:
        st.markdown(f"- {factor}")

with tab3:
    st.markdown(f"""
    <div style="background: rgba(0,0,0,0.25); border: 1.5px solid {action_border}; border-left: 6px solid {action_border}; padding: 8px 14px; border-radius: 6px; margin-bottom: 12px; display: flex; align-items: center; gap: 10px;">
        <span style="font-size: 1.15rem; font-weight: 800; color: {action_color}; background: {action_bg}; padding: 2px 10px; border-radius: 4px; border: 1px solid {action_border};">{action_tag}</span>
        <span style="font-size: 0.85rem; color: #f1f5f9; font-weight: 600;">{action_sub}</span>
    </div>
    """, unsafe_allow_html=True)
    s1_p = sr['s1']
    s2_p = sr['s2']
    r1_p = sr['r1']
    r2_p = sr['r2']
    sl_p = sr['stop_loss']
    ma60_p = df['ma60'].iloc[-1]

    if trend_score >= 3:
        st.success(f"🟢 **【持股者】** 趨勢偏多，多頭結構穩健，建議續抱並以 **S1（{s1_p:.2f} 元，月線）** 作為移動停利點。\n\n"
                   f"🟢 **【空手者】** 逢拉回量縮測試 **S1（{s1_p:.2f} 元）** 守穩時可分批建立部位，突破 **R1（{r1_p:.2f} 元）** 放量加碼。")
    elif trend_score <= -3:
        st.error(f"🔴 **【持股者】** 趨勢偏空且空方動能增強，反彈遇 **R1（{r1_p:.2f} 元）** 或 **季線MA60（{ma60_p:.2f} 元）** 宜逢高減碼，跌破**防守停損線（{sl_p:.2f} 元）**務必停損。\n\n"
                 f"🔴 **【空手者】** 暫勿盲目猜底接刀，靜待打底完成或出現帶量底背離反轉再進場。")
    else:
        st.warning(f"🟡 **【持股者】** 短線處於區間震盪打底，未跌破**防守停損線（{sl_p:.2f} 元）**前可暫時觀望，密切留意多空延續性。\n\n"
                   f"🟡 **【空手者】** 觀望為主，靜待帶量突破 **R1（{r1_p:.2f} 元）** 壓力或回測 **S2（{s2_p:.2f} 元）** 底部確認再行佈局。")

# ── 5. iPhone 主畫面捷徑說明 ─────────────────────────────────
with st.expander("📱 如何在 iPhone 上將此頁面變成原生 App？", expanded=False):
    st.markdown("""
    1. 在 **iPhone** 上使用 **Safari** 瀏覽器開啟此網頁。
    2. 點選螢幕底部的 **「分享」按鈕**（帶箭頭的方框圖示）。
    3. 向下滑動找到並點擊 **「加入主畫面」(Add to Home Screen)**。
    4. 自訂名稱（例如：`台股BPA看盤`），點擊右上角 **「新增」**。
    5. 返回桌面即可看到專屬圖示，點開後將享有**極速、無網址列的全螢幕原生 App 體驗**！
    """)

st.markdown(f"""
<div style="text-align: center; color: #64748b; font-size: 0.76rem; margin-top: 2rem; padding: 14px 0; border-top: 1px solid rgba(255,255,255,0.06);">
    台股 BPA 價格行為量化研判系統 <b>v{__version__}</b> ｜ 遵循 SemVer 語意化版本管理規範 ｜ Git Tag 發布管理
</div>
""", unsafe_allow_html=True)
