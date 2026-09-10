# -*- coding: utf-8 -*-
"""外部資料來源擷取：TWSE 官方 API / yfinance（上櫃 .TWO）/ FinMind（三大法人）/ 基本面。
純粹負責「拿資料」，不做任何策略判讀或評分。
"""
import time
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta

from core.constants import TW_TZ, HEADERS


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
    now   = datetime.now(TW_TZ)
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
    end   = datetime.now(TW_TZ)
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
                "date": pd.Timestamp.now(tz=TW_TZ).normalize().tz_localize(None),
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": price,
                "volume": vol,
                "time": datetime.now(TW_TZ).strftime("%H:%M:%S"),
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
    start = (datetime.now(TW_TZ) - relativedelta(days=days * 3)).strftime("%Y-%m-%d")
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
        d = datetime.now(TW_TZ)
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
    now = datetime.now(TW_TZ)
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
