# 台股回測資料集 MANIFEST

供 `F:\stock\backtest\` 的回測工具重複使用；也可直接被任何 pandas／polars／DuckDB／R
工作流讀取，不需要跑回測腳本。

| 項目 | 內容 |
|---|---|
| 歸檔日期 | 2026-09-09 16:17 |
| 資料抓取日期 | 2026-09-09 |
| 個股數 | 30 檔（其中 29 檔四類資料齊全，可直接回測） |
| 涵蓋期間 | 2018-01-02 ~ 2026-09-09 |
| 總計 | 日線 61,544 筆｜法人 61,033 筆｜月營收 3,036 筆｜財報 16,283 筆 |
| 磁碟大小 | Parquet 2.2 MB｜pickle 快取 6.6 MB |

## 檔案

| 檔案 | 內容 | 筆數 |
|---|---|---|
| `twstock_prices.parquet` | 日線 OHLCV ＋ 還原收盤 | 61,544 |
| `twstock_institutional.parquet` | 三大法人買賣超 | 61,033 |
| `twstock_monthly_revenue.parquet` | 月營收 | 3,036 |
| `twstock_financial_statements.parquet` | 財報逐項 | 16,283 |
| `coverage.csv` | 每檔涵蓋範圍與齊全度，快速查找用 | 30 |
| `cache/*.pkl` | 每檔一個 dict，回測腳本的工作快取 | 30 |

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

D = r"F:\stock\backtest\data"
px = pd.read_parquet(D + r"\twstock_prices.parquet")
one = px[px.ticker == "2330"].sort_values("date")          # 單檔日線

inst = pd.read_parquet(D + r"\twstock_institutional.parquet")
rev = pd.read_parquet(D + r"\twstock_monthly_revenue.parquet")
fs = pd.read_parquet(D + r"\twstock_financial_statements.parquet")
eps = fs[(fs.stock_id == "2330") & (fs.type == "EPS")].sort_values("date")   # 逐季 EPS

cov = pd.read_csv(D + r"\coverage.csv")                   # 先查涵蓋範圍再決定用哪幾檔
ready = cov[cov.backtest_ready].ticker.tolist()
```

回測腳本預設就會讀 `data/cache/`，不需設定；要換資料目錄可用環境變數 `BT_CACHE`。

## 擴充（加新個股）

```powershell
cd F:\stock\backtest
python fetch_history.py 2603 1101        # 只抓指定代號，已存在者自動跳過
python archive_data.py                   # 重建 Parquet 與 MANIFEST
```

## 由 Parquet 重建 pickle 快取

若 `cache/` 遺失或 Python 版本更換導致 pickle 無法讀取：

```powershell
python archive_data.py --rebuild-cache
```
