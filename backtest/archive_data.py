"""
把 fetch_history.py 下載的原始資料歸檔成可重複使用、可跨工具查找的形式。

產出（皆位於 backtest/data/）：
  cache/                            每檔一個 .pkl，回測腳本的工作快取（原 _cache/）
  twstock_prices.parquet            全部個股日線 OHLCV + 還原收盤（長格式）
  twstock_institutional.parquet     三大法人買賣超（張）
  twstock_monthly_revenue.parquet   月營收
  twstock_financial_statements.parquet  財報逐項（EPS／營收／毛利／營業利益…）
  coverage.csv                      每檔資料涵蓋範圍與筆數，快速查找用
  MANIFEST.md                       資料來源、口徑、涵蓋範圍、載入方式、擴充方式

Parquet 為開放格式（pandas / polars / DuckDB / R 皆可直讀），作為歸檔的正式格式；
pickle 僅作為回測腳本的加速快取，可由 Parquet 重建。

用法：python archive_data.py
"""
import os
import sys
import glob
import pickle
import shutil
from datetime import datetime

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
OLD_CACHE = os.path.join(HERE, "_cache")
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(DATA, "cache")


def migrate_cache():
    """把舊的 _cache/ 搬到 data/cache/（已搬過則跳過）"""
    os.makedirs(DATA, exist_ok=True)
    if os.path.isdir(OLD_CACHE) and not os.path.isdir(CACHE):
        shutil.move(OLD_CACHE, CACHE)
        print("[MOVE] _cache/ -> data/cache/")
    elif os.path.isdir(OLD_CACHE) and os.path.isdir(CACHE):
        # 兩邊都存在：把舊目錄中尚未搬過的檔案補進去，再移除舊目錄
        moved = 0
        for p in glob.glob(os.path.join(OLD_CACHE, "*.pkl")):
            dst = os.path.join(CACHE, os.path.basename(p))
            if not os.path.exists(dst):
                shutil.move(p, dst)
                moved += 1
        if not glob.glob(os.path.join(OLD_CACHE, "*")):
            os.rmdir(OLD_CACHE)
        print(f"[MERGE] 自 _cache/ 補入 {moved} 檔後移除舊目錄")
    os.makedirs(CACHE, exist_ok=True)


def load_all():
    out = []
    for p in sorted(glob.glob(os.path.join(CACHE, "*.pkl"))):
        with open(p, "rb") as f:
            out.append(pickle.load(f))
    return out


def build(records):
    prices, insts, revs, fss, cov = [], [], [], [], []
    for d in records:
        if not isinstance(d, dict) or "ticker" not in d:
            continue
        t, mkt = d["ticker"], d.get("market", "")
        px = d["price"].copy()
        px.insert(0, "ticker", t)
        px.insert(1, "market", mkt)
        prices.append(px)

        inst = d.get("inst")
        n_inst = 0
        if inst is not None and len(inst):
            inst = inst.copy()
            inst.insert(0, "ticker", t)
            insts.append(inst)
            n_inst = len(inst)

        rev = d.get("revenue") or []
        if rev:
            r = pd.DataFrame(rev)
            r["date"] = pd.to_datetime(r["date"])
            revs.append(r)

        fs = d.get("fs") or []
        if fs:
            f_ = pd.DataFrame(fs)
            f_["date"] = pd.to_datetime(f_["date"])
            fss.append(f_)

        cov.append({
            "ticker": t, "market": mkt,
            "price_rows": len(px),
            "price_start": px["date"].min().date(),
            "price_end": px["date"].max().date(),
            "inst_rows": n_inst,
            "inst_start": inst["date"].min().date() if n_inst else None,
            "inst_end": inst["date"].max().date() if n_inst else None,
            "revenue_rows": len(rev),
            "fs_rows": len(fs),
            "backtest_ready": bool(len(px) >= 800 and n_inst > 1000
                                   and len(rev) >= 60 and len(fs) >= 200),
        })
    return (
        pd.concat(prices, ignore_index=True) if prices else pd.DataFrame(),
        pd.concat(insts, ignore_index=True) if insts else pd.DataFrame(),
        pd.concat(revs, ignore_index=True) if revs else pd.DataFrame(),
        pd.concat(fss, ignore_index=True) if fss else pd.DataFrame(),
        pd.DataFrame(cov).sort_values("ticker").reset_index(drop=True),
    )


MANIFEST = """# 台股回測資料集 MANIFEST

供 `F:\\stock\\backtest\\` 的回測工具重複使用；也可直接被任何 pandas／polars／DuckDB／R
工作流讀取，不需要跑回測腳本。

| 項目 | 內容 |
|---|---|
| 歸檔日期 | {archived} |
| 資料抓取日期 | {fetched} |
| 個股數 | {n_tickers} 檔（其中 {n_ready} 檔四類資料齊全，可直接回測） |
| 涵蓋期間 | {start} ~ {end} |
| 總計 | 日線 {n_price:,} 筆｜法人 {n_inst:,} 筆｜月營收 {n_rev:,} 筆｜財報 {n_fs:,} 筆 |
| 磁碟大小 | Parquet {sz_pq}｜pickle 快取 {sz_pkl} |

## 檔案

| 檔案 | 內容 | 筆數 |
|---|---|---|
| `twstock_prices.parquet` | 日線 OHLCV ＋ 還原收盤 | {n_price:,} |
| `twstock_institutional.parquet` | 三大法人買賣超 | {n_inst:,} |
| `twstock_monthly_revenue.parquet` | 月營收 | {n_rev:,} |
| `twstock_financial_statements.parquet` | 財報逐項 | {n_fs:,} |
| `coverage.csv` | 每檔涵蓋範圍與齊全度，快速查找用 | {n_tickers} |
| `cache/*.pkl` | 每檔一個 dict，回測腳本的工作快取 | {n_tickers} |

**Parquet 是歸檔的正式格式**（開放、有型別、壓縮）。`cache/*.pkl` 只是加速用，
格式綁 Python pickle 協定，必要時可由 Parquet 重建（見末段）。

## 資料來源與口徑

| 資料 | 來源 | 口徑注意事項 |
|---|---|---|
| 日線 OHLCV | yfinance（`auto_adjust=False`） | `open/high/low/close` 為**原始價**，與 TWSE 官方盤後收盤實測 49/49 日零誤差。`adj_close` 為含息還原價，計算報酬時用它。`volume` 已除以 1000 換成**張**，與 `kline.py` 同口徑；但 yfinance 成交量僅為 TWSE 官方的約 85%（Yahoo 未計盤後定價／零股／鉅額，逐日浮動 ±7%）—— 實測對最終決策一致率 99.7%、評分平均差 0.07 分，故不影響研判結論，但**不要拿它當精確成交量引用**。 |
| 三大法人 | FinMind `TaiwanStockInstitutionalInvestorsBuySell` | 已彙總為 `fini`（外資＋外資自營）／`trust`（投信）／`dealer`（自營自行買賣＋避險）／`total`，單位**張**，與 `kline.fetch_inst_finmind` 完全同一彙總邏輯。 |
| 月營收 | FinMind `TaiwanStockMonthRevenue` | `date` 欄位已是**公告月**（例：`revenue_year=2017, revenue_month=12` 的 `date` 為 `2018-01-01`）。回測做 point-in-time 過濾時另加 10 天公告緩衝。 |
| 財報 | FinMind `TaiwanStockFinancialStatements` | `date` 為**季末日**，非公告日。回測過濾採 Q1~Q3 +45 天、Q4 年報 +90 天的公告落後期。`type` 欄含 `EPS`／`Revenue`／`GrossProfit`／`OperatingIncome` 等逐項科目（長格式）。 |

FinMind 免費額度會突發回 HTTP 402 限速；`fetch_history.py` 內建重試與「可重複執行補齊缺漏」，
這也是本資料集要歸檔保存的主要原因 —— **重抓一次要分批等額度恢復。**

## 版控

`data/` 內的 Parquet 與 `cache/` 已由 `backtest/.gitignore` 排除，避免把數十 MB 二進位檔
永久寫進 git 歷史；`MANIFEST.md` 與 `coverage.csv` 有納入版控，因此即使資料未隨 repo 散佈，
也查得到「本來有哪些資料、涵蓋到哪」。

## 載入方式

```python
import pandas as pd

D = r"F:\\stock\\backtest\\data"
px = pd.read_parquet(D + r"\\twstock_prices.parquet")
one = px[px.ticker == "2330"].sort_values("date")          # 單檔日線

inst = pd.read_parquet(D + r"\\twstock_institutional.parquet")
rev = pd.read_parquet(D + r"\\twstock_monthly_revenue.parquet")
fs = pd.read_parquet(D + r"\\twstock_financial_statements.parquet")
eps = fs[(fs.stock_id == "2330") & (fs.type == "EPS")].sort_values("date")   # 逐季 EPS

cov = pd.read_csv(D + r"\\coverage.csv")                   # 先查涵蓋範圍再決定用哪幾檔
ready = cov[cov.backtest_ready].ticker.tolist()
```

回測腳本預設就會讀 `data/cache/`，不需設定；要換資料目錄可用環境變數 `BT_CACHE`。

## 擴充（加新個股）

```powershell
cd F:\\stock\\backtest
python fetch_history.py 2603 1101        # 只抓指定代號，已存在者自動跳過
python archive_data.py                   # 重建 Parquet 與 MANIFEST
```

## 由 Parquet 重建 pickle 快取

若 `cache/` 遺失或 Python 版本更換導致 pickle 無法讀取：

```powershell
python archive_data.py --rebuild-cache
```
"""


def rebuild_cache():
    """從 Parquet 反向重建 cache/*.pkl（pickle 遺失或跨 Python 版本時使用）"""
    px = pd.read_parquet(os.path.join(DATA, "twstock_prices.parquet"))
    inst = pd.read_parquet(os.path.join(DATA, "twstock_institutional.parquet"))
    rev = pd.read_parquet(os.path.join(DATA, "twstock_monthly_revenue.parquet"))
    fs = pd.read_parquet(os.path.join(DATA, "twstock_financial_statements.parquet"))
    os.makedirs(CACHE, exist_ok=True)
    n = 0
    for t, g in px.groupby("ticker"):
        mkt = g["market"].iloc[0]
        d = {
            "ticker": t,
            "market": mkt,
            "price": g.drop(columns=["ticker", "market"]).reset_index(drop=True),
            "inst": inst[inst.ticker == t].drop(columns=["ticker"]).reset_index(drop=True),
            "revenue": rev[rev.stock_id == t].assign(
                date=lambda x: x["date"].dt.strftime("%Y-%m-%d")).to_dict("records"),
            "fs": fs[fs.stock_id == t].assign(
                date=lambda x: x["date"].dt.strftime("%Y-%m-%d")).to_dict("records"),
        }
        with open(os.path.join(CACHE, f"{t}.pkl"), "wb") as f:
            pickle.dump(d, f)
        n += 1
    print(f"[OK] 已由 Parquet 重建 {n} 檔 pickle 快取 -> {CACHE}")


def dirsize(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    return total


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def main():
    if "--rebuild-cache" in sys.argv:
        rebuild_cache()
        return

    migrate_cache()
    records = load_all()
    if not records:
        print("[ERR] data/cache/ 內無任何 .pkl，請先執行 fetch_history.py")
        return

    px, inst, rev, fs, cov = build(records)
    for name, df in [("twstock_prices", px), ("twstock_institutional", inst),
                     ("twstock_monthly_revenue", rev),
                     ("twstock_financial_statements", fs)]:
        if df.empty:
            continue
        out = os.path.join(DATA, name + ".parquet")
        df.to_parquet(out, index=False, compression="snappy")
        print(f"[OK] {name}.parquet  {len(df):>8,} 筆  {human(os.path.getsize(out))}")
    cov.to_csv(os.path.join(DATA, "coverage.csv"), index=False, encoding="utf-8-sig")
    print(f"[OK] coverage.csv        {len(cov):>8,} 檔")

    sz_pq = sum(os.path.getsize(os.path.join(DATA, f))
                for f in os.listdir(DATA) if f.endswith(".parquet"))
    fetched = datetime.fromtimestamp(
        min(os.path.getmtime(p) for p in glob.glob(os.path.join(CACHE, "*.pkl")))
    ).strftime("%Y-%m-%d")
    text = MANIFEST.format(
        archived=datetime.now().strftime("%Y-%m-%d %H:%M"),
        fetched=fetched,
        n_tickers=len(cov), n_ready=int(cov["backtest_ready"].sum()),
        start=px["date"].min().date(), end=px["date"].max().date(),
        n_price=len(px), n_inst=len(inst), n_rev=len(rev), n_fs=len(fs),
        sz_pq=human(sz_pq), sz_pkl=human(dirsize(CACHE)),
    )
    with open(os.path.join(DATA, "MANIFEST.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[OK] MANIFEST.md")
    print(f"\n歸檔完成 -> {DATA}")
    print(f"  {len(cov)} 檔個股，其中 {int(cov['backtest_ready'].sum())} 檔四類資料齊全")
    print(f"  Parquet {human(sz_pq)}｜pickle 快取 {human(dirsize(CACHE))}")


if __name__ == "__main__":
    main()
