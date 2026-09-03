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

__version__ = "2.5.0"

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

def fetch_from_yfinance(sym, months):
    end   = datetime.now()
    start = end - relativedelta(months=months)
    try:
        raw = yf.download(sym,
                    start=start.strftime("%Y-%m-%d"),
                    end=end.strftime("%Y-%m-%d"),
                    progress=False)
        if raw is not None and not raw.empty:
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            df = raw.reset_index()
            df.columns = [c.lower() for c in df.columns]
            if "date" in df.columns and "close" in df.columns and "volume" in df.columns:
                df["volume"] = df["volume"] / 1000
                return df[["date","open","high","low","close","volume"]].dropna().to_dict("records")
    except Exception as e:
        print(f"  [WARN] yfinance 取得 {sym} 失敗：{e}")
    return []

def fetch_otc(ticker, months):
    return fetch_from_yfinance(f"{ticker}.TWO", months)

# ── 3. 補今日即時與盤中行情（TWSE MIS 官方撮合 + Yahoo 雙軌備援） ───
def fetch_realtime_bar(ticker, market):
    """
    盤中即時股價擷取（雙軌備援架構）：
      1. 第一軌：TWSE MIS 官方撮合 API（延遲 0~5 秒，支援上市/上櫃）
      2. 第二軌：Yahoo Finance 即時報價（備援）
      3. 第三軌：TWSE OpenAPI STOCK_DAY_ALL（盤後定盤結算資料備援）
    """
    # ── 軌道 1：TWSE MIS 官方撮合 API ────────────────────────────
    prefix = "tse" if market == "tse" else "otc"
    mis_url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={prefix}_{ticker}.tw&json=1&delay=0"
    try:
        r = requests.get(mis_url, headers=HEADERS, timeout=5)
        data = r.json().get("msgArray", [])
        if data:
            item = data[0]
            # 優先讀取最新成交價 z；若為 '-' 則 fallback 至委買首檔、委賣首檔或昨收 y
            p_str = item.get("z", "-")
            if not p_str or p_str == "-":
                bids = [b for b in item.get("b", "").split("_") if b]
                asks = [a for a in item.get("a", "").split("_") if a]
                if bids:
                    p_str = bids[0]
                elif asks:
                    p_str = asks[0]
                else:
                    p_str = item.get("y", "-")
            
            if p_str and p_str != "-":
                price = float(p_str)
                open_p = float(item.get("o", price)) if item.get("o") and item.get("o") != "-" else price
                high_p = float(item.get("h", price)) if item.get("h") and item.get("h") != "-" else price
                low_p  = float(item.get("l", price)) if item.get("l") and item.get("l") != "-" else price
                vol    = float(item.get("v", 0)) if item.get("v") and item.get("v") != "-" else 0.0
                d_str  = item.get("d", "")
                t_str  = item.get("t", "")
                d_obj  = pd.to_datetime(d_str, format="%Y%m%d") if d_str else pd.Timestamp.now().normalize()
                return {
                    "date": d_obj,
                    "open": open_p,
                    "high": high_p,
                    "low": low_p,
                    "close": price,
                    "volume": vol,
                    "time": t_str,
                    "is_realtime": True,
                    "source": "TWSE MIS 官方撮合"
                }
    except Exception:
        pass

    # ── 軌道 2：Yahoo Finance 即時行情備援 ────────────────────────
    try:
        sym = f"{ticker}.TW" if market == "tse" else f"{ticker}.TWO"
        y_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d"
        r = requests.get(y_url, headers=HEADERS, timeout=5)
        chart = r.json().get("chart", {}).get("result", [])
        if chart:
            meta = chart[0]["meta"]
            price = float(meta["regularMarketPrice"])
            high_p = float(meta.get("regularMarketDayHigh", price))
            low_p  = float(meta.get("regularMarketDayLow", price))
            open_p = float(meta.get("chartPreviousClose", price))
            vol    = float(meta.get("regularMarketVolume", 0)) / 1000.0
            return {
                "date": pd.Timestamp.now().normalize(),
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": price,
                "volume": vol,
                "time": datetime.now().strftime("%H:%M:%S"),
                "is_realtime": True,
                "source": "Yahoo Finance 即時"
            }
    except Exception:
        pass

    # ── 軌道 3：TWSE OpenAPI（盤後日結報表備援）─────────────────
    if market == "tse":
        try:
            r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
                             headers=HEADERS, timeout=6)
            for row in r.json():
                if row.get("Code") == ticker:
                    raw_d = row["Date"]
                    if len(raw_d) == 7:
                        raw_d = str(int(raw_d[:3]) + 1911) + raw_d[3:]
                    return {
                        "date": pd.to_datetime(raw_d, format="%Y%m%d"),
                        "open": float(row["OpeningPrice"].replace(",","")),
                        "high": float(row["HighestPrice"].replace(",","")),
                        "low": float(row["LowestPrice"].replace(",","")),
                        "close": float(row["ClosingPrice"].replace(",","")),
                        "volume": float(row["TradeVolume"].replace(",","")) / 1000,
                        "time": "收盤定盤",
                        "is_realtime": False,
                        "source": "TWSE OpenAPI 盤後結算"
                    }
        except Exception:
            pass

    return None

# ── 4. 三大法人資料（近5個交易日，支援上市TSE與上櫃OTC） ───────────
def fetch_inst_finmind(ticker, days=5):
    """自 FinMind 取得近 N 日三大法人買賣超（支援上市 TSE 與上櫃 OTC，免 Token，防機房 IP 阻擋）"""
    start = (datetime.now() - relativedelta(days=days * 3)).strftime("%Y-%m-%d")
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={ticker}&start_date={start}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                df = pd.DataFrame(data)
                df["net"] = (df["buy"] - df["sell"]) / 1000.0
                pivot = df.pivot_table(index="date", columns="name", values="net", aggfunc="sum").fillna(0)
                fini = pivot.get("Foreign_Investor", 0)
                if "Foreign_Dealer_Self" in pivot.columns:
                    fini = fini + pivot["Foreign_Dealer_Self"]
                trust = pivot.get("Investment_Trust", 0)
                dealer = pd.Series(0.0, index=pivot.index)
                if "Dealer_self" in pivot.columns:
                    dealer = dealer + pivot["Dealer_self"]
                if "Dealer_Hedging" in pivot.columns:
                    dealer = dealer + pivot["Dealer_Hedging"]
                total = fini + trust + dealer
                res_df = pd.DataFrame({
                    "date": pd.to_datetime(pivot.index.values),
                    "fini": fini.round().astype(int).values,
                    "trust": trust.round().astype(int).values,
                    "dealer": dealer.round().astype(int).values,
                    "total": total.round().astype(int).values
                }).sort_values("date").tail(days).reset_index(drop=True)
                return res_df
    except Exception:
        pass
    return pd.DataFrame()

def fetch_institutional(ticker, market, days=5):
    # ── 第一軌：FinMind 快速接口（涵蓋上市 TSE 與上櫃 OTC，免 Token，防機房阻擋，0.3秒極速） ──
    df_fm = fetch_inst_finmind(ticker, days=days)
    if not df_fm.empty:
        return df_fm

    # ── 第二軌：TWSE 官方 T86 備援（僅上市 TSE） ──
    if market == "tse":
        records = []
        d = datetime.now()
        if d.hour < 15:
            d -= relativedelta(days=1)
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
                    headers=HEADERS, timeout=8)
                data = r.json()
                for row in data.get("data", []):
                    if row[0].strip() == ticker:
                        records.append({
                            "date":   pd.to_datetime(date_str, format="%Y%m%d"),
                            "fini":   int(round(float(row[4].replace(",","")) / 1000)),
                            "trust":  int(round(float(row[10].replace(",","")) / 1000)),
                            "dealer": int(round(float(row[11].replace(",","")) / 1000)),
                            "total":  int(round(float(row[18].replace(",","")) / 1000)),
                        })
                        fetched += 1
                        break
            except Exception:
                pass
            time.sleep(0.3)
            d -= relativedelta(days=1)

        if records:
            return pd.DataFrame(records).sort_values("date").reset_index(drop=True)

    return pd.DataFrame()

# ── 4.1 基本面與財報獲利數據（FinMind CDN + Yahoo 雙軌極速備援） ──
def fetch_fundamentals(ticker, market="tse"):
    """取得台股個股基本面數據（近四季 EPS、本益比、殖利率、淨值比、雙率與月營收 YoY）"""
    now = datetime.now()
    start_1y = (now - relativedelta(years=1, months=6)).strftime("%Y-%m-%d")
    start_recent = (now - relativedelta(days=15)).strftime("%Y-%m-%d")
    start_rev = (now - relativedelta(months=14)).strftime("%Y-%m-%d")

    res = {
        "per": None,
        "pbr": None,
        "dividend_yield": None,
        "eps_ttm": None,
        "latest_eps": None,
        "latest_quarter": "",
        "gross_margin": None,
        "operating_margin": None,
        "latest_revenue_val": None,
        "revenue_date": "",
        "revenue_yoy": None,
        "has_data": False
    }

    def get_per():
        try:
            r = requests.get(f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPER&data_id={ticker}&start_date={start_recent}", headers=HEADERS, timeout=5)
            return ("per", r.json().get("data", []) if r.status_code == 200 else [])
        except Exception:
            return ("per", [])

    def get_fs():
        try:
            r = requests.get(f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockFinancialStatements&data_id={ticker}&start_date={start_1y}", headers=HEADERS, timeout=5)
            return ("fs", r.json().get("data", []) if r.status_code == 200 else [])
        except Exception:
            return ("fs", [])

    def get_rev():
        try:
            r = requests.get(f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id={ticker}&start_date={start_rev}", headers=HEADERS, timeout=5)
            return ("rev", r.json().get("data", []) if r.status_code == 200 else [])
        except Exception:
            return ("rev", [])

    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as executor:
            data_map = dict(executor.map(lambda f: f(), [get_per, get_fs, get_rev]))
    except Exception:
        data_map = {"per": [], "fs": [], "rev": []}

    # 1. PER, PBR, 殖利率
    per_data = data_map.get("per", [])
    if per_data:
        last_per = per_data[-1]
        res["per"] = last_per.get("PER")
        res["pbr"] = last_per.get("PBR")
        res["dividend_yield"] = last_per.get("dividend_yield")
        res["has_data"] = True

    # 2. 季報 EPS 與雙率
    fs_data = data_map.get("fs", [])
    if fs_data:
        eps_list = [x for x in fs_data if x.get("type") == "EPS"]
        if eps_list:
            eps_list = sorted(eps_list, key=lambda x: x["date"])
            res["latest_eps"] = eps_list[-1]["value"]
            res["latest_quarter"] = eps_list[-1]["date"][:7]
            recent_4 = eps_list[-4:]
            res["eps_ttm"] = round(sum(x["value"] for x in recent_4), 2)
            res["has_data"] = True

        latest_date = eps_list[-1]["date"] if eps_list else None
        if latest_date:
            q_items = {x["type"]: x["value"] for x in fs_data if x.get("date") == latest_date}
            rev = q_items.get("Revenue", 0)
            gp = q_items.get("GrossProfit", 0)
            op = q_items.get("OperatingIncome", 0)
            if rev > 0:
                res["gross_margin"] = round(gp / rev * 100, 1)
                res["operating_margin"] = round(op / rev * 100, 1)

    # 3. 月營收與 YoY
    rev_data = data_map.get("rev", [])
    if len(rev_data) >= 12:
        latest_r = rev_data[-1]
        same_m_ly = [x for x in rev_data[:-1] if x.get("revenue_month") == latest_r.get("revenue_month")]
        if same_m_ly:
            ly = same_m_ly[-1]
            if ly.get("revenue", 0) > 0:
                res["revenue_yoy"] = round((latest_r["revenue"] - ly["revenue"]) / ly["revenue"] * 100, 2)
        res["latest_revenue_val"] = round(latest_r["revenue"] / 1e8, 1)
        res["revenue_date"] = f"{latest_r['revenue_year']}/{latest_r['revenue_month']}"
        res["has_data"] = True

    # 4. 備援軌道：若 FinMind 因雲端 IP 頻率限制 (429) 或無資料，啟動 Yahoo Finance 備援
    if not res["has_data"] or res["eps_ttm"] is None:
        try:
            sym = f"{ticker}.TW" if market == "tse" else f"{ticker}.TWO"
            t_obj = yf.Ticker(sym)
            info = t_obj.info
            if not info or not info.get("trailingEps"):
                sym_alt = f"{ticker}.TWO" if market == "tse" else f"{ticker}.TW"
                info = yf.Ticker(sym_alt).info
            if info and (info.get("trailingEps") is not None or info.get("trailingPE") is not None):
                if res["eps_ttm"] is None and info.get("trailingEps") is not None:
                    res["eps_ttm"] = round(float(info["trailingEps"]), 2)
                    res["latest_quarter"] = "近四季"
                if res["per"] is None and info.get("trailingPE") is not None:
                    res["per"] = round(float(info["trailingPE"]), 2)
                if res["pbr"] is None and info.get("priceToBook") is not None:
                    res["pbr"] = round(float(info["priceToBook"]), 2)
                if res["dividend_yield"] is None and info.get("dividendYield") is not None:
                    res["dividend_yield"] = round(float(info["dividendYield"]) * 100, 2)
                if res["gross_margin"] is None and info.get("grossMargins") is not None:
                    res["gross_margin"] = round(float(info["grossMargins"]) * 100, 1)
                if res["operating_margin"] is None and info.get("operatingMargins") is not None:
                    res["operating_margin"] = round(float(info["operatingMargins"]) * 100, 1)
                if res["revenue_yoy"] is None and info.get("revenueGrowth") is not None:
                    res["revenue_yoy"] = round(float(info["revenueGrowth"]) * 100, 2)
                res["has_data"] = True
        except Exception:
            pass

    return res

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

def evaluate_volume_price(df):
    """
    量價結構與動能深度評估（Wyckoff & Volume Price Analysis）：
      - 判定量價配合關係（價漲量增、價跌量縮、量價背離、放量下殺、爆量滯漲、窒息量打底）
      - 量能均線倍數（20MA 均量比、5MA 均量比）
      - 結合 Wyckoff 特徵（突破、拉回、背離）
      - 提供結構狀態、得分、量價診斷與操盤應對建議
    """
    N = len(df)
    vol_now = float(df["volume"].iloc[-1])
    vol_ma20 = float(df["vol_ma"].iloc[-1]) if "vol_ma" in df else vol_now
    vol_ma5 = float(df["volume"].rolling(5, min_periods=1).mean().iloc[-1])
    vol_ratio_20 = vol_now / (vol_ma20 + 1e-9)
    vol_ratio_5 = vol_now / (vol_ma5 + 1e-9)
    
    close_now = float(df["close"].iloc[-1])
    open_now = float(df["open"].iloc[-1])
    high_now = float(df["high"].iloc[-1])
    low_now = float(df["low"].iloc[-1])
    prev_close = float(df["close"].iloc[-2]) if N >= 2 else close_now
    chg = close_now - prev_close
    chg_pct = (chg / (prev_close + 1e-9)) * 100
    
    # 蠟燭結構與影線
    candle_rng = max(high_now - low_now, 1e-5)
    body = abs(close_now - open_now)
    upper_sh = high_now - max(open_now, close_now)
    lower_sh = min(open_now, close_now) - low_now
    
    # 特殊量價與 Wyckoff 標記
    is_breakout = bool(df["breakout"].iloc[-1]) if "breakout" in df else False
    is_dryup = bool(df["dryup"].iloc[-1]) if "dryup" in df else (vol_now < 0.45 * vol_ma20)
    is_churn = bool(df["churn"].iloc[-1]) if "churn" in df else (vol_ratio_20 > 1.8 and (upper_sh / candle_rng > 0.4 or body / candle_rng < 0.25))
    is_pullback = bool(df["pullback"].iloc[-1]) if "pullback" in df else False
    bull_div = bool(df["bull_div"].iloc[-1]) if "bull_div" in df else False
    bear_div = bool(df["bear_div"].iloc[-1]) if "bear_div" in df else False

    # 量價型態診斷
    if is_churn:
        status = "爆量滯漲（主力調節警戒）"
        status_code = "CHURN"
        score = -1
        desc = f"成交量達 20MA 的 {vol_ratio_20*100:.0f}%（爆量），但漲勢受阻留長上影線或實體窄小，顯示主力逢高調節或高檔換手分歧"
        advice = "短線追高風險極大，提防主力誘多出貨，持股者宜逢高分批減碼"
    elif is_breakout:
        status = "帶量突破（主力放量表態）"
        status_code = "BREAKOUT"
        score = +2
        desc = f"放量突破近 20 日高點（成交量為 20MA 的 {vol_ratio_20*100:.0f}%），多方強勢表態展開波段攻勢"
        advice = "量價俱佳，順勢偏多操作，可以突破價或前波高點作為動態防守位"
    elif is_dryup:
        status = "窒息量打底（沉澱沉寂變盤前夕）"
        status_code = "DRYUP"
        score = 0
        desc = f"成交量僅 20MA 的 {vol_ratio_20*100:.0f}%（極致萎縮），市場浮額大幅洗淨，殺盤動能衰竭"
        advice = "量能萎縮至波段極低水平，往往孕育變盤反轉，空手者可密切留意帶量起漲訊號"
    elif chg > 0 and vol_ratio_20 >= 1.25:
        status = "價量齊揚（健康放量推升）"
        status_code = "BULL_EXP"
        score = +2
        desc = f"股價上揚 {chg_pct:+.2f}% 伴隨量能放大至 20MA 的 {vol_ratio_20*100:.0f}%，買盤積極推升，多方架構扎實"
        advice = "量能配合良好，多頭動能充沛，持股續抱，空手者可待短線回踩守穩時分批佈局"
    elif chg > 0 and vol_ratio_20 <= 0.75:
        status = "量價背離（縮量推升動能趨緩）"
        status_code = "BULL_DIV"
        score = 0
        desc = f"股價上漲 {chg_pct:+.2f}% 但成交量僅為 20MA 的 {vol_ratio_20*100:.0f}%，追價力道跟進不足"
        advice = "無量上漲易引發震盪回測，嚴禁追高，持股者宜提高警戒並緊盯支撐線"
    elif chg < 0 and vol_ratio_20 >= 1.25:
        status = "放量重挫（空方賣壓湧現）"
        status_code = "BEAR_EXP"
        score = -2
        desc = f"股價下跌 {chg_pct:+.2f}% 且成交量放大至 20MA 的 {vol_ratio_20*100:.0f}%，空方帶量摜壓，恐慌性賣盤出籠"
        advice = "帶量破線殺傷力大，短線跌勢恐未止，持股者嚴守停損，空手者切勿急於猜底接刀"
    elif chg < 0 and vol_ratio_20 <= 0.75:
        ma20_val = float(df["ma20"].iloc[-1]) if "ma20" in df else close_now
        status = "價跌量縮（多頭良性拉回洗盤）" if close_now >= ma20_val else "陰跌量縮（買盤觀望人氣退潮）"
        status_code = "BEAR_RET"
        score = +1 if close_now >= ma20_val else -1
        desc = f"股價拉回 {chg_pct:+.2f}% 且成交量萎縮至 20MA 的 {vol_ratio_20*100:.0f}%，無恐慌性失血賣壓"
        advice = "拉回量縮代表籌碼相對安定，若守穩月線支撐可視為良性洗盤買點；反之若跌破均線則需防陰跌"
    else:
        status = "量價平穩（常態量能震盪）"
        status_code = "NORMAL"
        score = 0
        desc = f"今日成交量為 20MA 的 {vol_ratio_20*100:.0f}%，量能與價格變動處於常態合理區間"
        advice = "量能無失控或突變跡象，維持既有技術面支撐壓力紀律操作"

    if bull_div:
        desc += " ｜ 【技術指標底背離】跌勢趨緩醞釀反彈"
    if bear_div:
        desc += " ｜ 【技術指標頂背離】漲勢趨疲提防獲利了結"

    return {
        "status": status,
        "status_code": status_code,
        "score": score,
        "vol_now": vol_now,
        "vol_ma20": vol_ma20,
        "vol_ma5": vol_ma5,
        "vol_ratio_20": vol_ratio_20,
        "vol_ratio_5": vol_ratio_5,
        "desc": desc,
        "advice": advice,
        "is_breakout": is_breakout,
        "is_dryup": is_dryup,
        "is_churn": is_churn,
        "is_pullback": is_pullback,
        "bull_div": bull_div,
        "bear_div": bear_div
    }

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

def get_rating_badge(s):
    if s >= 6:   return "🟢 強烈多頭（動能充沛，偏多操作）"
    if s >= 3:   return "🟢 溫和偏多（震盪盤堅，支撐守穩）"
    if s >= 1:   return "🟡 中性微多（均線整理，等待方向）"
    if s == 0:   return "🟡 中立盤整（多空拉鋸，靜待放量）"
    if s >= -2:  return "🟠 中性微空（反彈無力，下方測底）"
    if s >= -5:  return "🔴 溫和偏空（空頭承壓，反彈宜減碼）"
    return            "🔴 強烈空頭（主跌段，切勿盲目接刀）"

def evaluate_composite_rating(df, bpa_res, vol_eval, inst_df, fundamentals, ticker, market):
    """
    多維綜合評級：融合 Minervini 趨勢樣板 + CANSLIM 成長動能 + BPA 價格行為 + 法人量價結構
    保持乾淨精簡，輸出高訊號比之綜合評級卡片資料
    """
    c = df["close"]
    ma50 = ma150 = ma200 = ma200_20d = low_52w = high_52w = None
    if len(c) >= 200:
        ma50 = c.rolling(50).mean().iloc[-1]
        ma150 = c.rolling(150).mean().iloc[-1]
        ma200 = c.rolling(200).mean().iloc[-1]
        ma200_20d = c.rolling(200).mean().iloc[-22] if len(c) >= 222 else ma200
        low_52w = c.tail(250).min()
        high_52w = c.tail(250).max()
    else:
        try:
            sym = f"{ticker}.TW" if market == "tse" else f"{ticker}.TWO"
            raw = yf.download(sym, period="15mo", progress=False)
            if raw is None or raw.empty:
                sym_alt = f"{ticker}.TWO" if market == "tse" else f"{ticker}.TW"
                raw = yf.download(sym_alt, period="15mo", progress=False)
            if raw is not None and not raw.empty:
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = [col[0].lower() for col in raw.columns]
                else:
                    raw.columns = [col.lower() for col in raw.columns]
                c_long = raw["close"]
                if len(c_long) >= 50:
                    ma50 = c_long.rolling(50).mean().iloc[-1]
                if len(c_long) >= 150:
                    ma150 = c_long.rolling(150).mean().iloc[-1]
                if len(c_long) >= 200:
                    ma200 = c_long.rolling(200).mean().iloc[-1]
                    ma200_20d = c_long.rolling(200).mean().iloc[-22] if len(c_long) >= 222 else ma200
                low_52w = c_long.tail(250).min()
                high_52w = c_long.tail(250).max()
        except Exception:
            pass

    c_now = float(c.iloc[-1])
    m_checks = []
    if ma50 is not None and ma150 is not None and ma200 is not None and low_52w is not None and high_52w is not None:
        m_checks.append(c_now > ma150 and c_now > ma200)
        m_checks.append(ma150 > ma200)
        m_checks.append(ma200 >= ma200_20d * 0.995)
        m_checks.append(ma50 > ma150 and ma50 > ma200)
        m_checks.append(c_now > ma50)
        m_checks.append((c_now - low_52w) / (low_52w + 1e-9) >= 0.25)
        m_checks.append((high_52w - c_now) / (high_52w + 1e-9) <= 0.25)
        m_passed = sum(m_checks)
    else:
        m_passed = 4

    # 2. CANSLIM 成長動能評分
    rev_yoy = fundamentals.get("revenue_yoy") if fundamentals else None
    eps_ttm = fundamentals.get("eps_ttm") if fundamentals else None
    gm = fundamentals.get("gross_margin") if fundamentals else None
    
    c_score = 0
    if rev_yoy is not None:
        if rev_yoy >= 20: c_score += 2
        elif rev_yoy >= 0: c_score += 1
        else: c_score -= 1
    if eps_ttm is not None and eps_ttm > 0:
        c_score += 2
    if gm is not None and gm >= 30:
        c_score += 1
        
    if c_score >= 4:
        canslim_grade = "A+ 卓越"
        canslim_sub = "營收盈餘高速成長"
        c_color = "#4ade80"
    elif c_score >= 2:
        canslim_grade = "A 優質"
        canslim_sub = "基本面穩健成長"
        c_color = "#60a5fa"
    elif c_score >= 0:
        canslim_grade = "B 中性"
        canslim_sub = "獲利動能平穩"
        c_color = "#fbbf24"
    else:
        canslim_grade = "C 偏弱"
        canslim_sub = "動能趨緩或虧損"
        c_color = "#f87171"

    # 3. BPA 價格行為
    bpa_zh = bpa_res.get("always_in_zh", "箱型震盪")
    if "多" in bpa_zh:
        bpa_sub = "20 EMA 順勢多方"
        bpa_color = "#4ade80"
    elif "空" in bpa_zh:
        bpa_sub = "20 EMA 順勢空方"
        bpa_color = "#f87171"
    else:
        bpa_sub = "區間高出低進"
        bpa_color = "#fbbf24"

    # 4. 籌碼與量價結構
    v_score = vol_eval.get("score", 0) if vol_eval else 0
    inst_5d = int(inst_df.tail(5)["total"].sum()) if (inst_df is not None and not inst_df.empty) else 0
    if inst_5d > 0 and v_score >= 0:
        chip_zh = "法人主力加碼"
        chip_sub = f"5日買超 {inst_5d:,}張"
        chip_color = "#4ade80"
    elif inst_5d < 0 and v_score <= 0:
        chip_zh = "法人主力調節"
        chip_sub = f"5日賣超 {abs(inst_5d):,}張"
        chip_color = "#f87171"
    elif inst_5d > 0:
        chip_zh = "籌碼偏多支撐"
        chip_sub = "內外資偏多佈局"
        chip_color = "#60a5fa"
    else:
        chip_zh = "籌碼動向觀望"
        chip_sub = "多空分歧整理"
        chip_color = "#fbbf24"

    # 綜合評分與操盤定位
    total_score = (m_passed / 7.0) * 35 + (max(0, c_score) / 5.0) * 25 + (30 if "多" in bpa_zh else (15 if "整理" in bpa_zh or "震盪" in bpa_zh else 5)) + (10 if inst_5d > 0 else 0)
    total_score = int(round(total_score))

    if total_score >= 80 and m_passed >= 5:
        badge = "⭐⭐⭐⭐⭐ 頂級飆股體質（Stage 2 主升）"
        b_color = "#4ade80"
        b_bg = "rgba(34, 197, 94, 0.2)"
        summary_advice = "長中短均線呈多頭排列，基本面盈餘與營收高成長，順應 20 EMA 拉回守穩皆為絕佳順勢佈局點。"
    elif total_score >= 65:
        badge = "⭐⭐⭐⭐ 優質多頭（穩健推升中）"
        b_color = "#60a5fa"
        b_bg = "rgba(59, 130, 246, 0.2)"
        summary_advice = "中期架構偏多且守穩關鍵支撐，基本面具支撐力道，持股者續抱，空手者尋找量縮回踩點分批佈局。"
    elif total_score >= 45:
        badge = "⭐⭐⭐ 區間震盪（待動能表態）"
        b_color = "#fbbf24"
        b_bg = "rgba(245, 158, 11, 0.2)"
        summary_advice = "短線處於箱型整理或均線糾結階段，突破前切忌追價，嚴格遵守低買高賣或靜待帶量表態。"
    else:
        badge = "⚠️ 空頭承壓（弱勢修正中）"
        b_color = "#f87171"
        b_bg = "rgba(239, 68, 68, 0.2)"
        summary_advice = "跌破中長期均線或基本面動能放緩，空方主導格局，嚴禁盲目猜底接刀，持股者逢反彈宜嚴格風控。"

    # 5. 核心操盤動作決策（建議買入 / 建議持有 / 建議觀望 / 建議賣出）
    if total_score >= 75 and ("多" in bpa_zh or "主升" in badge):
        action_tag = "🟢 建議買入"
        action_type = "BUY"
        action_color = "#22c55e"
        action_bg = "rgba(34, 197, 94, 0.18)"
        action_border = "#22c55e"
        action_sub = "強烈主升動能，逢 20 EMA 支撐拉回或放量突破為高勝率買點"
    elif total_score >= 60 and "空" not in bpa_zh:
        action_tag = "🟡 建議持有"
        action_type = "HOLD"
        action_color = "#38bdf8"
        action_bg = "rgba(56, 189, 248, 0.18)"
        action_border = "#38bdf8"
        action_sub = "多頭架構穩健守穩支撐，持股續抱享受利潤；空手者尋找回踩點分批佈局"
    elif total_score >= 45:
        action_tag = "🟡 建議觀望"
        action_type = "WAIT"
        action_color = "#fbbf24"
        action_bg = "rgba(245, 158, 11, 0.18)"
        action_border = "#fbbf24"
        action_sub = "處於箱型震盪或打底整理階段，多空不明，空手者切忌追高，靜待帶量表態"
    else:
        action_tag = "🔴 建議賣出"
        action_type = "SELL"
        action_color = "#ef4444"
        action_bg = "rgba(239, 68, 68, 0.18)"
        action_border = "#ef4444"
        action_sub = "跌破關鍵均線或防守停損線，空方主導，持股者逢反彈宜嚴格減碼，切勿盲目接刀"

    return {
        "score": total_score,
        "badge": badge,
        "badge_color": b_color,
        "badge_bg": b_bg,
        "action_tag": action_tag,
        "action_type": action_type,
        "action_color": action_color,
        "action_bg": action_bg,
        "action_border": action_border,
        "action_sub": action_sub,
        "minervini_passed": m_passed,
        "minervini_status": "Stage 2 主升段" if m_passed >= 6 else ("符合多數樣板" if m_passed >= 4 else "弱勢整理型態"),
        "minervini_color": "#4ade80" if m_passed >= 5 else ("#fbbf24" if m_passed >= 4 else "#f87171"),
        "canslim_grade": canslim_grade,
        "canslim_sub": canslim_sub,
        "canslim_color": c_color,
        "bpa_zh": bpa_zh,
        "bpa_sub": bpa_sub,
        "bpa_color": bpa_color,
        "chip_zh": chip_zh,
        "chip_sub": chip_sub,
        "chip_color": chip_color,
        "summary_advice": summary_advice
    }

# ── 6. 核心分析主函數 ─────────────────────────────────────────
def analyze_stock(ticker, months=1, cost=None, custom_name=None, generate_html=True, print_report=True):
    ticker = str(ticker).strip()
    market, auto_name = get_info(ticker)
    stock_name = custom_name if custom_name else auto_name
    if print_report:
        print(f"[INFO] {ticker}（{stock_name}）| {'上市(TSE)' if market=='tse' else '上櫃(OTC)'}")
        print(f"下載近 {months} 個月歷史資料中...")

    records = []
    if market == "tse":
        records = fetch_twse(ticker, months)
        if not records:
            if print_report:
                print(f"[WARN] TWSE 官方 API 未能取得 {ticker} 資料，啟動 yfinance (.TW) 備援...")
            records = fetch_from_yfinance(f"{ticker}.TW", months)
    else:
        records = fetch_otc(ticker, months)
        if not records:
            if print_report:
                print(f"[WARN] yfinance (.TWO) 未能取得 {ticker} 資料，嘗試 (.TW)...")
            records = fetch_from_yfinance(f"{ticker}.TW", months)

    # 交叉最後備援：若仍無資料，嘗試對向市場代號
    if not records:
        alt_sym = f"{ticker}.TWO" if market == "tse" else f"{ticker}.TW"
        records = fetch_from_yfinance(alt_sym, months)
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

    vol_eval = evaluate_volume_price(df)
    bpa_res = evaluate_brooks_price_action(df)
    fundamentals = fetch_fundamentals(ticker, market=market)
    trend_score, trend_stage, trend_factors = evaluate_professional_trend(df, inst_df, bpa_res, vol_eval)
    rating_badge = get_rating_badge(trend_score)
    composite_rating = evaluate_composite_rating(df, bpa_res, vol_eval, inst_df, fundamentals, ticker, market)

    close_now = df["close"].iloc[-1]
    r1 = round(df["high"].tail(20).max(), 2)
    r2 = round(df["bb_upper"].iloc[-1], 2)
    s1 = round(df["ma20"].iloc[-1], 2)
    s2 = round(df["low"].tail(20).min(), 2)
    stop_loss = round(s2 * 0.985, 2)

    # ── 8. Plotly 互動圖表繪製 ──────────────────────────────────
    # ── 8. Plotly 互動圖表繪製（專注價格行為、均線、動能與量能，法人數據由專屬圖卡呈現） ──────
    row_heights = [0.46, 0.20, 0.18, 0.16]
    subplot_titles = ["K 線 + 20 EMA(BPA) + 均線 + 布林帶", "MACD(12,26,9)", "RSI(14)", "成交量（張）"]

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True,
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

    # Row 2：MACD 子圖
    macd_row = 2
    hist_colors = np.where(df["macd_hist"].values >= 0, "#ef4444", "#22c55e")
    fig.add_trace(go.Bar(x=df["date"], y=df["macd_hist"],
        marker_color=hist_colors, name="MACD 柱", showlegend=False, opacity=0.7), row=macd_row, col=1)
    fig.add_trace(go.Scatter(x=df["date"], y=df["macd"],
        mode="lines", line=dict(color="#f59e0b", width=1.5), name="MACD"), row=macd_row, col=1)
    fig.add_trace(go.Scatter(x=df["date"], y=df["macd_signal"],
        mode="lines", line=dict(color="#a78bfa", width=1.5), name="Signal"), row=macd_row, col=1)
    fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.2)", width=1), row=macd_row, col=1)

    # Row 3：RSI 子圖
    rsi_row = 3
    fig.add_trace(go.Scatter(x=df["date"], y=df["rsi"],
        mode="lines", line=dict(color="#38bdf8", width=1.5), name="RSI(14)"), row=rsi_row, col=1)
    fig.add_hline(y=70, line=dict(color="#f87171", width=1, dash="dash"),
        annotation_text="超買 70", annotation_position="right", row=rsi_row, col=1)
    fig.add_hline(y=30, line=dict(color="#4ade80", width=1, dash="dash"),
        annotation_text="超賣 30", annotation_position="right", row=rsi_row, col=1)
    fig.add_hline(y=50, line=dict(color="rgba(255,255,255,0.15)", width=1), row=rsi_row, col=1)
    fig.update_yaxes(range=[0, 100], row=rsi_row, col=1)

    # Row 4：成交量子圖
    vol_row = 4
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
        height=820,
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
        print(f"  綜合評分 ：{trend_score:+d} 分 ｜ 評級：{rating_badge}")
        for f_item in trend_factors:
            print(f"  • {f_item}")

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
    slope = (ema.iloc[-1] - ema.iloc[-4]) / (ema.iloc[-4] + 1e-9) * 100 if len(ema) >= 4 else 0

    if c.iloc[-1] > ema.iloc[-1] and slope > 0.05:
        bpa_status = "多頭主控（拉回逢低做多）"
        bpa_status_color = "#4ade80"
        bpa_bg = "rgba(34, 197, 94, 0.2)"
        bpa_guide = "目前 5 分K 處於順勢多方軌道，站在 20 EMA 之上，逢拉回回測 20 EMA 出現陽棒可順勢佈局。"
    elif c.iloc[-1] < ema.iloc[-1] and slope < -0.05:
        bpa_status = "空方主導（反彈逢高做空）"
        bpa_status_color = "#f87171"
        bpa_bg = "rgba(239, 68, 68, 0.2)"
        bpa_guide = "目前 5 分K 受制於 20 EMA 反壓，空方主控，反彈無力突破均線前切忌急於搶反彈。"
    else:
        bpa_status = "箱型震盪（區間高出低進）"
        bpa_status_color = "#fbbf24"
        bpa_bg = "rgba(245, 158, 11, 0.2)"
        bpa_guide = "目前 5 分K 均線走平，穿梭於 20 EMA 兩側，屬於典型日內區間整理，嚴禁追高殺低。"

    # 最新 5 分K 棒形態分析
    last_bar = df.iloc[-1]
    bar_h = float(last_bar["high"])
    bar_l = float(last_bar["low"])
    bar_c = float(last_bar["close"])
    bar_o = float(last_bar["open"])
    rng = max(0.01, bar_h - bar_l)
    body = abs(bar_c - bar_o)

    if body / rng >= 0.6:
        bar_type = "🟢 多頭趨勢棒 (Bull Trend)" if bar_c > bar_o else "🔴 空頭趨勢棒 (Bear Trend)"
    elif min(bar_c, bar_o) - bar_l >= 0.5 * rng:
        bar_type = "🔨 多頭反轉下影棒 (Bull Reversal)"
    elif bar_h - max(bar_c, bar_o) >= 0.5 * rng:
        bar_type = "☄️ 空頭反轉上影棒 (Bear Reversal)"
    elif body / rng <= 0.2:
        bar_type = "⚖️ 十字猶豫棒 (Doji)"
    else:
        bar_type = "⚪ 普通震盪棒 (Trading Bar)"

    # 台股 Tick 級風控與掛單建議
    tick = get_tw_tick(close_now)
    buy_stop = round(bar_h + tick, 2)
    sell_stop = round(bar_l - tick, 2)

    if "多" in bpa_status:
        stop_loss = round(bar_l - tick, 2)
        r_val = round(max(tick, close_now - stop_loss), 2)
        target_1r = round(close_now + r_val, 2)
        target_2r = round(close_now + 2 * r_val, 2)
    else:
        stop_loss = round(bar_h + tick, 2)
        r_val = round(max(tick, stop_loss - close_now), 2)
        target_1r = round(close_now - r_val, 2)
        target_2r = round(close_now - 2 * r_val, 2)

    # 5m 當沖動作決策
    if "多" in bpa_status:
        action_tag_5m = "🟢 建議偏多買進"
        action_sub_5m = "順應 5m 20 EMA 支撐拉回逢低買進"
        action_color_5m = "#22c55e"
    elif "空" in bpa_status:
        action_tag_5m = "🔴 建議逢高做空"
        action_sub_5m = "受制 5m 20 EMA 反壓，反彈逢高或破底順勢放空"
        action_color_5m = "#ef4444"
    else:
        action_tag_5m = "🟡 建議觀望整理"
        action_sub_5m = "日內箱型均線糾結，高出低進或暫不開倉"
        action_color_5m = "#fbbf24"

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
            whale_advice = f"當前 5 分K 成交量達 5m 均量的 {vol_ratio_5m} 倍（大單點火推升）。衝刺動能強勁但切忌盲目追高，靜待拉回 20 EMA 守穩再行介入。"
        elif not is_above_ema and is_bull_bar and body / rng >= 0.5:
            whale_tag = "⚠️ 空方反彈誘多"
            whale_color = "#fbbf24"
            whale_bg = "rgba(245, 158, 11, 0.16)"
            whale_advice = f"當前 5 分K 成交量達 5m 均量的 {vol_ratio_5m} 倍，但受制於 5m 20 EMA 反壓。統計上 70% 易受阻回落，嚴防假突破，切勿盲目搶反彈。"
        elif not is_above_ema and not is_bull_bar and body / rng >= 0.5:
            whale_tag = "🚨 主力爆量摜壓"
            whale_color = "#ef4444"
            whale_bg = "rgba(239, 68, 68, 0.16)"
            whale_advice = f"當前 5 分K 成交量達 5m 均量的 {vol_ratio_5m} 倍且長黑破線。大單出貨或停損殺盤出籠，跌破均線防守，嚴格落實風控停損。"
        elif (lower_sh / rng >= 0.45) and (abs(bar_l - ema_now) / (ema_now + 1e-9) < 0.008 or (not df_today.empty and bar_l <= df_today["low"].min())):
            whale_tag = "🔨 主力爆量護盤"
            whale_color = "#22c55e"
            whale_bg = "rgba(34, 197, 94, 0.16)"
            whale_advice = f"當前 5 分K 成交量達 5m 均量的 {vol_ratio_5m} 倍，回踩支撐留下顯著長下影線，顯示主力在低檔積極承接，守穩可留意反彈。"
        elif upper_sh / rng >= 0.4 or body / rng <= 0.25:
            whale_tag = "⚠️ 爆量高檔滯漲"
            whale_color = "#f59e0b"
            whale_bg = "rgba(245, 158, 11, 0.16)"
            whale_advice = f"當前 5 分K 成交量達 5m 均量的 {vol_ratio_5m} 倍，但衝高受阻留下長上影線或窄實體，顯示主力高檔逢高調節，短線提防換手拉回。"
        else:
            whale_tag = f"⚡ 主力爆量異動 ({vol_ratio_5m}倍量)"
            whale_color = "#a855f7"
            whale_bg = "rgba(168, 85, 247, 0.16)"
            whale_advice = f"當前 5 分K 爆出 5m 均量的 {vol_ratio_5m} 倍巨量，多空交火劇烈，密切關注能否守穩 20 EMA。"
    else:
        whale_tag = "⚪ 常態量能流動"
        whale_color = "#94a3b8"
        whale_bg = "rgba(148, 163, 184, 0.12)"
        whale_advice = f"當前 5 分K 成交量為 5m 均量的 {vol_ratio_5m} 倍，量能處於常態合理區間，無失控或突發大單異動。"

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
        "data_time_str": data_time_str
    }

# ── 7. 命令列執行入口 ─────────────────────────────────────────
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
