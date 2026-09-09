"""
回測資料抓取：一次性下載長期歷史資料並快取，供 backtest_accuracy.py 做 point-in-time 切片。

- 價格：yfinance（auto_adjust=False）→ 原始 OHLC（與 TWSE 盤後收盤同口徑，供訊號引擎使用）
        另存 adj_close（供計算含息前瞻報酬）
- 三大法人：FinMind TaiwanStockInstitutionalInvestorsBuySell（與 kline.fetch_inst_finmind 同一彙總口徑）
- 基本面：FinMind TaiwanStockMonthRevenue / TaiwanStockFinancialStatements 原始逐筆，
          回測時再依 cutoff 日期＋公告落後期過濾，避免未來資料洩漏

FinMind 免費額度會突發性回 402，因此本腳本採慢速抓取＋可重複執行補齊缺漏。
"""
import os, sys, time, pickle
import pandas as pd
import yfinance as yf
import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}
START = "2018-01-01"
CACHE = os.environ.get("BT_CACHE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cache"))
PACE = float(os.environ.get("BT_PACE", "2.5"))

# 使用者實際持倉／自選（貼近真實使用情境）
USER_UNIVERSE = ["2330", "2454", "3042", "6182", "6446", "6643", "7768", "1717", "3008", "2616"]
# 額外分散樣本（大型權值 + 中小型），降低選樣偏誤
EXTRA_UNIVERSE = [
    "2317", "2308", "2412", "2881", "2882", "1301", "1303", "1216", "2603", "2609",
    "3711", "3034", "2379", "6505", "4938", "2376", "8046", "6415", "2207", "1101",
]
BENCH = ["0050"]
UNIVERSE = USER_UNIVERSE + EXTRA_UNIVERSE

OTC_HINT = {"6643", "6182", "8046"}  # 僅影響 .TWO 優先嘗試順序，最終以實際抓到者為準


def fetch_price(ticker):
    for suffix in ([".TWO", ".TW"] if ticker in OTC_HINT else [".TW", ".TWO"]):
        try:
            raw = yf.download(ticker + suffix, start=START, progress=False,
                              auto_adjust=False, actions=False)
        except Exception as e:
            print(f"    [WARN] {ticker}{suffix} 下載失敗: {e}")
            continue
        if raw is None or raw.empty:
            continue
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = raw.reset_index()
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        if not {"date", "open", "high", "low", "close", "volume"}.issubset(df.columns):
            continue
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        if "adj_close" not in df.columns:
            df["adj_close"] = df["close"]
        df["volume"] = df["volume"] / 1000.0  # 股 → 張（與 kline.py 同口徑）
        df = df[["date", "open", "high", "low", "close", "adj_close", "volume"]]
        df = df.dropna().sort_values("date").drop_duplicates("date").reset_index(drop=True)
        if len(df) < 300:
            continue
        return df, ("otc" if suffix == ".TWO" else "tse")
    return None, None


def finmind(dataset, ticker):
    url = (f"https://api.finmindtrade.com/api/v4/data?dataset={dataset}"
           f"&data_id={ticker}&start_date={START}")
    for attempt in range(5):
        try:
            r = requests.get(url, headers=HEADERS, timeout=40)
            if r.status_code == 200:
                return r.json().get("data", []) or []
            wait = 25 * (attempt + 1)
            print(f"    [WARN] {dataset} {ticker} HTTP {r.status_code}，{wait}s 後重試")
        except Exception as e:
            wait = 25 * (attempt + 1)
            print(f"    [WARN] {dataset} {ticker} {type(e).__name__}，{wait}s 後重試")
        time.sleep(wait)
    return []


def build_inst(rows):
    """完全比照 kline.fetch_inst_finmind 的彙總口徑（外資含外資自營、自營含避險）"""
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["net"] = (df["buy"] - df["sell"]) / 1000.0
    pivot = df.pivot_table(index="date", columns="name", values="net", aggfunc="sum").fillna(0)
    fini = pivot.get("Foreign_Investor", pd.Series(0.0, index=pivot.index))
    if "Foreign_Dealer_Self" in pivot.columns:
        fini = fini + pivot["Foreign_Dealer_Self"]
    trust = pivot.get("Investment_Trust", pd.Series(0.0, index=pivot.index))
    dealer = pd.Series(0.0, index=pivot.index)
    for col in ("Dealer_self", "Dealer_Hedging"):
        if col in pivot.columns:
            dealer = dealer + pivot[col]
    total = fini + trust + dealer
    return pd.DataFrame({
        "date": pd.to_datetime(pivot.index.values),
        "fini": fini.round().astype(int).values,
        "trust": trust.round().astype(int).values,
        "dealer": dealer.round().astype(int).values,
        "total": total.round().astype(int).values,
    }).sort_values("date").reset_index(drop=True)


def load(ticker):
    p = os.path.join(CACHE, f"{ticker}.pkl")
    if os.path.exists(p):
        with open(p, "rb") as f:
            return pickle.load(f)
    return None


def save(ticker, d):
    with open(os.path.join(CACHE, f"{ticker}.pkl"), "wb") as f:
        pickle.dump(d, f)


def main():
    os.makedirs(CACHE, exist_ok=True)
    only = sys.argv[1:] or (UNIVERSE + BENCH)
    for i, t in enumerate(only, 1):
        d = load(t) or {"ticker": t}
        if d.get("price") is None or len(d.get("price", [])) < 300:
            px, market = fetch_price(t)
            if px is None:
                print(f"[{i}/{len(only)}] {t} [SKIP] 無足夠價格資料")
                continue
            d["price"], d["market"] = px, market
        is_bench = t in BENCH
        need_inst = (not is_bench) and (d.get("inst") is None or len(d.get("inst", [])) == 0)
        need_rev = (not is_bench) and not d.get("revenue")
        need_fs = (not is_bench) and not d.get("fs")
        if not (need_inst or need_rev or need_fs):
            print(f"[{i}/{len(only)}] {t} 已完整，跳過")
            continue
        print(f"[{i}/{len(only)}] {t} 補抓 "
              + " ".join([x for x, n in [("法人", need_inst), ("月營收", need_rev), ("財報", need_fs)] if n]))
        if need_inst:
            d["inst"] = build_inst(finmind("TaiwanStockInstitutionalInvestorsBuySell", t))
            time.sleep(PACE)
        if need_rev:
            d["revenue"] = finmind("TaiwanStockMonthRevenue", t)
            time.sleep(PACE)
        if need_fs:
            d["fs"] = finmind("TaiwanStockFinancialStatements", t)
            time.sleep(PACE)
        save(t, d)
        px = d["price"]
        n_inst = 0 if d.get("inst") is None else len(d["inst"])
        print(f"    [OK] {t} ({d['market']}) 價格 {len(px)} 筆 "
              f"{px['date'].iloc[0].date()}~{px['date'].iloc[-1].date()}"
              f" ｜法人 {n_inst} ｜月營收 {len(d.get('revenue') or [])}"
              f" ｜財報 {len(d.get('fs') or [])}")


if __name__ == "__main__":
    main()
