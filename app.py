# -*- coding: utf-8 -*-
"""
台股專業量價 + Al Brooks 價格行為學（BPA）極速輕量行動看盤 Web App
專注 BPA 價格行為學、20 EMA 基準、支撐壓力矩陣與風控掛單指引
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from kline import analyze_stock, get_info

# ── 1. 頁面設定（手機版體驗最佳化） ─────────────────────────
st.set_page_config(
    page_title="台股 BPA 價格行為學",
    page_icon="⚡",
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
</style>
""", unsafe_allow_html=True)

# ── 2. 快取分析結果（避免重複計算，手機切換極速流暢） ───────────
@st.cache_data(ttl=300, show_spinner=False)
def get_cached_analysis(ticker, months, cost):
    return analyze_stock(ticker=ticker, months=months, cost=cost, generate_html=False, print_report=False)

# ── 3. 頂部導覽與股票選擇區 ──────────────────────────────────
st.markdown("### ⚡ 台股 Al Brooks BPA 價格行為研判")

# 快捷熱門股按鈕
quick_tickers = [
    ("台積電", "2330"),
    ("晶技", "3042"),
    ("聯發科", "2454"),
    ("鴻海", "2317"),
    ("藥華藥", "6446"),
    ("長榮", "2603")
]

if "ticker" not in st.session_state:
    st.session_state["ticker"] = "2330"

cols_btn = st.columns(len(quick_tickers))
for i, (qname, qtick) in enumerate(quick_tickers):
    if cols_btn[i].button(f"{qname}\n{qtick}", key=f"btn_{qtick}", use_container_width=True):
        st.session_state["ticker"] = qtick

with st.expander("⚙️ 搜尋股票與自訂參數", expanded=False):
    c1, c2, c3 = st.columns([2, 1, 1])
    input_ticker = c1.text_input("股票代號（上市/上櫃）", value=st.session_state["ticker"]).strip()
    months_opt = c2.selectbox("歷史分析月數", options=[1, 2, 3, 6, 12], index=0)
    cost_opt = c3.number_input("個人持有成本（選填）", value=0.0, step=0.5, format="%.2f")
    cost_val = cost_opt if cost_opt > 0 else None
    
    if input_ticker != st.session_state["ticker"]:
        st.session_state["ticker"] = input_ticker

current_ticker = st.session_state["ticker"]

# ── 4. 執行研判與展示 ──────────────────────────────────────
try:
    with st.spinner(f"正在分析 {current_ticker} BPA 價格行為與位階..."):
        res = get_cached_analysis(current_ticker, months_opt, cost_val)
except Exception as e:
    st.error(f"⚠️ 無法取得股票代號【{current_ticker}】的資料：{e}")
    st.stop()

# 基礎資訊
stock_name = res["stock_name"]
market_txt = "上市 (TSE)" if res["market"] == "tse" else "上櫃 (OTC)"
close_now  = res["close_now"]
df         = res["df"]
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

# 頂部個股摘要欄
st.markdown(f"""
<div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px;">
    <div>
        <span style="font-size: 1.5rem; font-weight: 800;">{stock_name}</span>
        <span style="font-size: 1.1rem; color: #94a3b8; margin-left: 6px;">{current_ticker}</span>
        <span style="font-size: 0.8rem; background: #334155; color: #cbd5e1; padding: 2px 6px; border-radius: 4px; margin-left: 6px;">{market_txt}</span>
    </div>
    <div style="text-align: right;">
        <span style="font-size: 1.6rem; font-weight: 800; color: {chg_color};">{close_now:.2f}</span>
        <span style="font-size: 0.95rem; color: {chg_color}; margin-left: 4px;">{chg_sign}{chg_val:.2f} ({chg_sign}{chg_pct:.2f}%)</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ── 4.1 四大關鍵指標橫幅卡片 ─────────────────────────────────
k1, k2, k3, k4 = st.columns(4)

with k1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">BPA 市場狀態 (Always-In)</div>
        <div class="metric-value" style="font-size: 1.05rem; color: #38bdf8;">{bpa_res['always_in_code']}</div>
        <div class="metric-sub">{bpa_res['always_in'].split('(')[0].strip()}</div>
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

# ── 4.2 Al Brooks 操盤掛單與風控指引 ─────────────────────────
st.markdown("#### 🎯 Brooks 操盤訂單與停損指引")
if bpa_res['always_in_code'] == 'AIL':
    strat_title = "偏多操作策略 (AIL) ── 多頭主控"
    strat_desc = "順應 20 EMA 多頭架構，拉回尋找 H1/H2 買點，或以突破停損單（Buy Stop）進場"
    strat_color = "#10b981"
elif bpa_res['always_in_code'] == 'AIS':
    strat_title = "偏空操作策略 (AIS) ── 空方主控"
    strat_desc = "反彈尋找 L1/L2 空點，持股者逢高調節，空方設 Sell Stop 順勢佈局"
    strat_color = "#ef4444"
else:
    strat_title = "區間震盪策略 (TR) ── 80% 突破失敗法則"
    strat_desc = "遵守 BLSHS（低買高賣短沖），嚴禁於箱型中間盲目追價，防範鐵絲網多空雙巴"
    strat_color = "#f59e0b"

st.markdown(f"""
<div class="order-box" style="border-left-color: {strat_color};">
    <div style="font-weight: 700; color: {strat_color}; margin-bottom: 4px;">{strat_title}</div>
    <div style="font-size: 0.88rem; color: #cbd5e1; margin-bottom: 8px;">{strat_desc}</div>
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; font-size: 0.82rem; background: rgba(0,0,0,0.25); padding: 8px; border-radius: 6px;">
        <div><b>訊號棒極值：</b>高 {bpa_res['sig_high']:.2f} / 低 {bpa_res['sig_low']:.2f}</div>
        <div><b>進場掛單價：</b>{'Buy Stop ' + str(bpa_res['buy_stop']) if bpa_res['always_in_code']=='AIL' else 'Sell Stop ' + str(bpa_res['sell_stop'])}</div>
        <div><b>防守停損價：</b>{'Prot Stop ' + str(bpa_res['sell_stop']) if bpa_res['always_in_code']=='AIL' else 'Prot Stop ' + str(bpa_res['buy_stop'])}</div>
        <div><b>等距測量 MM 1R：</b>{bpa_res['target_long_1r'] if bpa_res['always_in_code']=='AIL' else bpa_res['target_short_1r']:.2f} 元</div>
    </div>
</div>
""", unsafe_allow_html=True)

if bpa_res["signals"]:
    st.info("💡 **近期觸發之 BPA 關鍵設定：** " + " ｜ ".join(bpa_res["signals"]))

# ── 4.3 核心分析分頁（支撐壓力 / 趨勢與BPA細項 / 操盤行動指引） ────────
tab1, tab2, tab3 = st.tabs(["🎯 支撐壓力矩陣", "🧭 趨勢與 BPA 評估明細", "💡 操盤行動指引"])

with tab1:
    s_col1, s_col2 = st.columns(2)
    with s_col1:
        st.write("##### 🔺 壓力位階 (Resistance)")
        st.markdown(f"- **R2（布林上軌/波段頂）**：`{sr['r2']:.2f} 元`")
        st.markdown(f"- **R1（近20日高點）**：`{sr['r1']:.2f} 元`")
        st.markdown(f"- **當前收盤現價**：`{close_now:.2f} 元`")
    with s_col2:
        st.write("##### 🔻 支撐位階 (Support)")
        st.markdown(f"- **S1（20MA 月線支撐）**：`{sr['s1']:.2f} 元`")
        st.markdown(f"- **S2（近20日低點）**：`{sr['s2']:.2f} 元`")
        st.markdown(f"- **防守停損線 (Stop-Loss Pivot)**：`{sr['stop_loss']:.2f} 元`")

with tab2:
    st.write(f"**綜合評級：** `{badge}` ｜ **總得分：** `{trend_score:+d} 分`")
    # 過濾只保留純價格行為、趨勢與均線位階相關因子
    clean_factors = [f for f in res["trend_factors"] if "法人" not in f and "MACD" not in f and "量" not in f]
    for factor in clean_factors:
        st.markdown(f"- {factor}")

with tab3:
    if trend_score >= 3:
        st.success("🟢 **【持股者】** 趨勢偏多，多頭結構穩健，建議續抱並以 S1（月線）作為移動停利點。\n\n"
                   "🟢 **【空手者】** 逢拉回量縮測試 S1 守穩時可分批建立部位，突破 R1 放量加碼。")
    elif trend_score <= -3:
        st.error("🔴 **【持股者】** 趨勢偏空且空方動能增強，反彈遇 R1/MA60 宜逢高減碼，跌破防守線務必停損。\n\n"
                 "🔴 **【空手者】** 暫勿盲目猜底接刀，靜待打底完成或出現帶量底背離反轉再進場。")
    else:
        st.warning("🟡 **【持股者】** 短線處於區間震盪打底，未跌破防守線前可暫時觀望，密切留意多空延續性。\n\n"
                   "🟡 **【空手者】** 觀望為主，靜待帶量突破 R1 壓力或回測 S2 底部確認再行佈局。")

# ── 5. iPhone 主畫面捷徑說明 ─────────────────────────────────
with st.expander("📱 如何在 iPhone 上將此頁面變成原生 App？", expanded=False):
    st.markdown("""
    1. 在 **iPhone** 上使用 **Safari** 瀏覽器開啟此網頁。
    2. 點選螢幕底部的 **「分享」按鈕**（帶箭頭的方框圖示）。
    3. 向下滑動找到並點擊 **「加入主畫面」(Add to Home Screen)**。
    4. 自訂名稱（例如：`台股BPA看盤`），點擊右上角 **「新增」**。
    5. 返回桌面即可看到專屬圖示，點開後將享有**極速、無網址列的全螢幕原生 App 體驗**！
    """)
