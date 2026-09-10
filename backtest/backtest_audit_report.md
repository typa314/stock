# 台股歷史基準回測資料庫與核心策略驗證代碼審查報告（修訂版）

- **審查日期**：2026-09-10（依使用者對審查項目之核對完成修訂）
- **審查對象**：`F:\stock\backtest\` 系列腳本與資料庫、`core/` 核心策略模組
- **目標**：檢驗歷史基準回測資料庫（Parquet / Cache）用以驗證核心策略之代碼正確性、Point-in-Time 零未來資料隔離度與實盤交易對帳邏輯。

---

## 📋 總體核對結論（Executive Summary）

專案中以 `backtest_accuracy.py` 為核心的回測體系，**整體架構設計嚴謹、資料保真度高，具備無未來資料之 Point-in-Time 隔離保護**。

經使用者與審查代碼逐項核對後的瑕疵與建議狀態如下：

| 嚴重度 | 項目 | main 現況 | 處置狀態 |
|---|---|---|---|
| 🚨 **崩潰** | `archive_data.py` 遇 `TWII.pkl` 拋出 `KeyError: 'ticker'` | 存在（`build()` 缺 dict 判斷） | ✅ **已於本地修復**（過濾非個股 cache） |
| ⚠️ **偏差** | `simulate_strategy.py` 遇跳空跌破停損時未計滑價 | 存在（原代碼固定以 `stop` 成交） | ✅ **已於本地修復**（改以 `min(stop, adj_open)` 成交） |
| 💡 **未實作** | 次日開盤追價限制（`Anti-Chase`） | **尚未實作於 main**（非有寫沒測） | 📌 **列為待實作策略規格** |
| 💡 **建議** | `HOLD` 門檻目前仍為 ≥65 分 | main 仍是 ≥65 分 | 📌 **建議依回測實證收緊至 ≥70 分** |

---

## 🔍 一、架構與資料庫檢核

### 1. 資料源與口徑
| 資料種類 | 來源檔案 | 單位與口徑 | 評價 |
|---|---|---|---|
| 日線 OHLCV | `data/twstock_prices.parquet` & `cache/*.pkl` | 原始價格（auto_adjust=False），與 TWSE 盤後收盤一致；成交量已除以 1000 換算為「張」 | ✅ 與生產端完全一致 |
| 還原前瞻報酬 | `adj_close` 換算之還原因子 | 含息還原價格，用於計算真實複利報酬 | ✅ 準確消除除權息跳空干擾 |
| 三大法人 | `data/twstock_institutional.parquet` | 外資（含外資自營）、投信、自營（含避險）及合計張數 | ✅ 與 `kline.fetch_inst_finmind` 彙總邏輯相同 |
| 月營收 | `data/twstock_monthly_revenue.parquet` | FinMind 公告月資料，強制 +10 天公告緩衝 | ✅ 嚴格符合法定每月 10 日前申報之時效 |
| 季財報 | `data/twstock_financial_statements.parquet` | 逐季 EPS、營收、毛利、營業利益，強制 Q1~Q3 +45 天、Q4 +90 天公告落後 | ✅ 嚴格符合台灣法定季報/年報申報期限 |
| 大盤加權指數 | `data/cache/TWII.pkl` | ^TWII 日線歷史收盤與季線 MA60 | ✅ 提供 Point-in-Time 大盤濾網 |

---

## 🔬 二、Point-in-Time 零未來資訊隔離性檢核

### 1. 攔截完整度（Monkeypatching Fidelity）
回測腳本 [backtest_accuracy.py](file:///f:/stock/backtest/backtest_accuracy.py#L150-L179) 透過 `install_patches()` 覆蓋了生產端所有外部請求與快取接口：
- `kline.fetch_twse` / `fetch_from_yfinance` / `fetch_otc`：嚴格只截取 `date <= cut`。
- `kline.fetch_institutional`：嚴格只截取 `date <= cut` 之近 5 個交易日。
- `kline.fetch_fundamentals`：比照生產端計算邏輯，並以發布落後期嚴格過濾公告日。
- `kline.fetch_realtime_bar`：回傳 `None`，強制盤後定盤。
- `core.rating.yf`：替換為 `_FakeYF`，杜絕 Minervini 補抓 15 個月數據時調用線上網路與未來數據。
- `core.market_regime.get_market_regime_status`：替換為基於 `TWII.pkl` 截斷在 `cut` 的動態計算。

### 2. 歷史資料洩漏檢驗（本機重測結果）
執行指令：
```powershell
python backtest/check_lookahead.py 2330
```
- **測試結果**：
  比對 2025-11-14 與 2025-11-28（截斷點相差 10 個交易日）之重疊 253 根 K 棒，包括 20 EMA、MACD、RSI、KD、布林通道、BPA 形態旗標、Wyckoff 突破/量縮指標等共 48 個欄位，全部無任何差異（0 處變動）：
  ```text
  截斷 2025-11-14 vs 截斷 2025-11-28 ｜重疊 253 個交易日
  [PASS] 全部 48 個欄位在重疊區間完全一致 → 引擎無未來資料洩漏
  ```

---

## 🎯 三、核心策略邏輯驗證覆蓋度

| 策略模組 | 驗證欄位 / 機制 | 檢核說明 |
|---|---|---|
| **Al Brooks BPA** | `bpa` (`always_in_zh`)、`bpa_res`、`alert` | 驗證「多頭主控 / 偏多整理 / 箱型震盪 / 偏空整理 / 空方主導」5 種狀態之後續勝率；`--with-alert` 同步驗證 H2 雙重底、20 EMA 回踩、S1 支撐回測與量縮洗盤 4 種底部買點雷達。 |
| **Stan Weinstein 趨勢** | `trend_stage`、`is_stage4` | 驗證 Stage 1~4 週期，特別是 Stage 4 衰退期觸發「標的池風控硬警示」強制禁開多單（`WAIT`）之防禦效益。 |
| **Wyckoff / VPA 量價** | `vol_score`、量價配合係數 | 驗證放量突破與窒息量守穩在不同趨勢階段之後續動能。 |
| **Minervini & CANSLIM** | `minervini` (8項樣板)、`canslim` 評級 | 驗證股價是否處於 50/150/200 MA 之上，以及近四季營收 YoY 與 EPS TTM 成長動能。 |
| **大盤體系濾網** | `is_market_bear` | 驗證加權指數破季線時，BUY 門檻自 80 分拉高至 85 分、風控停損收緊之避險能力。 |
| **交易對帳模擬** | [simulate_strategy.py](file:///f:/stock/backtest/simulate_strategy.py) | 次日開盤買進（T+1 Open）、持有滿 20 日收盤出場或先觸及 -7% 硬停損（或 ATR 自適應停損），扣除來回 0.471% 交易成本，無重疊持倉。 |

---

## 🛠️ 四、瑕疵修復與實測對比

### 1. 修復 `archive_data.py` 遇 `TWII.pkl` 拋出 `KeyError: 'ticker'`
- **問題成因**：`TWII.pkl` 是大盤加權指數的 `DataFrame`，無 `ticker` 欄位，在 `build()` 中執行 `t = d["ticker"]` 時崩潰。
- **修復方式**：[archive_data.py:L68-L70](file:///f:/stock/backtest/archive_data.py#L68-L70) 加入防禦過濾：
  ```python
  for d in records:
      if not isinstance(d, dict) or "ticker" not in d:
          continue
      t, mkt = d["ticker"], d.get("market", "")
  ```
- **驗證成果**：成功處理 30 檔個股與大盤資料，日線筆數 61,544 筆無拋錯。

### 2. 修復 `simulate_strategy.py` 跳空開低跌破停損之滑價結算
- **問題成因**：原代碼 `if px["adj_low"].iloc[j] <= stop: exit_p = stop`，若遇跳空低開（`adj_open < stop`）仍以 -7% 結算，高估了極端行情的出場價。
- **修復方式**：[simulate_strategy.py:L74](file:///f:/stock/backtest/simulate_strategy.py#L74) 改為：
  ```python
  exit_p = min(stop, px["adj_open"].iloc[j])
  ```
- **量化對比（BUY 訊號持有 20 日，全樣本 28 檔）**：
  - **修復前（理想 -7% 停損）**：加權平均報酬 **+2.67%**，策略平均 CAGR **10.7%**。
  - **修復後（真實滑價停損）**：加權平均報酬 **+2.53%**，策略平均 CAGR **9.7%**。
  - **量化結論**：跳空開低滑價使整體策略 CAGR 產生約 **-1.0%** 的客觀摩擦成本，符合台股真實交易特性，使回測結果更具防守參考價值。

### 3. 次日開盤追價限制（`Anti-Chase`）之現況釐清
- **main 現況**：目前 `origin/main` 的 `core/rating.py` 尚未落地 `check_anti_chase` 函式，追價限制（若次日開盤跳空 > +1.5% 則放棄追高）仍屬策略總冊 Phase 1 之規格建議，待正式合入 main 後再納入回測矩陣。

### 4. `HOLD` 門檻收緊建議（≥65 vs ≥70）
- **main 現況**：目前 `core/rating.py` 內 `HOLD` 門檻為 ≥65 分。
- **回測量化實證**：
  依據 [accuracy_report.md](file:///f:/stock/backtest/accuracy_report.md#L67-L77) 評分分層數據：
  - 評分 60~64 分：20 日平均報酬 +1.99%
  - 評分 65~69 分：20 日平均報酬 +2.58%（相較全樣本基準 +2.25%，超額報酬僅 +0.33%，95% CI 跨越 0，無統計顯著性）
  - 評分 80~100 分（BUY）：20 日平均報酬 +4.44%（超額 +2.19%，95% CI [+1.46%, +2.98%]，顯著優於基準）
- **建議**：維持策略總冊 Phase 1 之建議，將 `HOLD` 門檻收緊至 ≥70 分，低於 70 分者併入 `WAIT` 觀望，去除模糊區間。

---

## 🧪 五、本地自動化驗證執行紀錄

本地全套測試回歸結果：
1. **單元測試全數通過**：
   - `python test_bot_logic.py`：`Ran 9 tests in 22.6s -> OK`
   - `python test_core_strategies.py`：`Ran 31 tests in 0.826s -> OK`
2. **零未來資料稽核**：
   - `python backtest/check_lookahead.py 2330`：`[PASS] 全部 48 個欄位完全一致`
3. **歸檔工具修復後驗證**：
   - `python -c "import sys; sys.path.insert(0, 'backtest'); from archive_data import load_all, build; rec = load_all(); build(rec)"`：`Success (61,544 筆)`
