# 重構說明（本次變更摘要）

## 1. 合併 app.py / devapp.py
- 刪除 `devapp.py`（原本與 app.py 99% 重複）。
- `app.py` 新增 `APP_ENV=dev` 環境變數開關，設定時顯示原本 devapp.py 專屬的 DEV 提示 banner。
- 更新 `test_kline_logic.py` 的檔案品質檢查清單，移除已刪除的 devapp.py。

## 2. 移除不存在的 Hugging Face / Koyeb 部署路徑
- 刪除 `HUGGINGFACE_SETUP.md`、`KOYEB_SETUP.md`。
- `Dockerfile` 改為通用容器映像（不再綁定 HF Spaces 的 UID 1000 / port 7860 慣例，改用 port 8080）。
- `cloudflare_worker/worker.js` 移除 `koyebUrl` / `hfUrl` / `backup3Url` 相關備援節點邏輯，
  只保留真實存在的 Render 雲端 + 本機 PC 雙節點路由。
- `CLOUDFLARE_WORKER_SETUP.md` 移除對應的過時說明文字。

## 3. 拆分 kline.py（2231 行）為 core/ 套件
依職責拆成以下子模組，`kline.py` 本身改為約 40 行的相容性 facade（重新匯出所有原有
公開名稱），因此 `app.py`／`bot_flex.py`／`line_server.py`／`monitor_worker.py`／
`backtest/*.py` 完全不需要改動匯入方式。

| 模組 | 內容 |
|---|---|
| `core/constants.py` | TW_TZ、HEADERS、均線設定、停損參數等共用常數 |
| `core/data_fetch.py` | TWSE / yfinance / FinMind 資料擷取 |
| `core/indicators.py` | tick 級距、ATR、風控停損價（`compute_risk_stop`） |
| `core/strategy_brooks.py` | Al Brooks 價格行為學（BPA）判讀 |
| `core/strategy_volume.py` | Wyckoff / VPA 量價結構評估 |
| `core/strategy_trend.py` | Stan Weinstein 趨勢階段研判 |
| `core/rating.py` | 綜合評級（Minervini / CANSLIM / BPA / 籌碼） |
| `core/charting.py` | Plotly 圖表繪製（純繪圖，不做計算） |
| `core/analyzer.py` | 整合入口 `analyze_stock` / `analyze_stock_5m` + CLI |

**驗證方式**：逐一比對每個函式在新舊檔案中的原始碼是否逐字相同 —— 19 個函式中
17 個完全逐字相同（僅搬移位置），只有 2 處刻意變更並在下方說明。

### 已知且刻意的行為變更
1. **`compute_risk_stop` 改為延遲匯入 `analyze_stock`**：因為
   `core.indicators.compute_risk_stop` 會呼叫 `core.analyzer.analyze_stock` 作為
   後備方案，而 `core.analyzer` 在模組層級又會 import `core.indicators.get_tw_tick`，
   若兩邊都在檔案開頭 import 對方會造成循環匯入。改為在函式內部才 import，
   已用實際執行測試確認不會拋出 `ImportError`。
2. **`core/indicators.py` 內原本重複出現一次的停損常數**（`STOP_ATR_MULT` 等）已移除，
   統一從 `core/constants.py` 匯入，避免兩份定義互相蓋寫造成混淆（純屬拆檔案時的
   複製邊界問題，數值本身沒有變動）。

### 修正的拆分瑕疵（原本會是新 bug，已修正）
- `core/strategy_brooks.py` 呼叫 `get_tw_tick()` 但拆檔案時漏了 import，已補上
  `from core.indicators import get_tw_tick`（用 pyflakes 抓到並已驗證修正後可正確解析）。
- `test_bot_logic.py` 的 `test_07_mtf_and_institutional_gate` 原本
  `patch("kline.analyze_stock", ...)`，但 `analyze_stock_5m` 現在定義在
  `core/analyzer.py`、呼叫的是同模組內的 `analyze_stock`，patch `kline.` 這個
  facade 上的名稱不會攔截到內部呼叫。已改為 `patch("core.analyzer.analyze_stock", ...)`
  並用獨立腳本證實修正前會漏攔截、修正後正確攔截。

## 驗證結果
- 全部檔案 `py_compile` 通過。
- `pyflakes` 掃描：核心模組沒有新增的未定義名稱或多餘 import；僅存的警告
  （如 `macd_arr`/`lower_sh`/`vol_ma_v` 未使用、部分 f-string 缺少替換欄位）
  逐一比對確認是原始 `kline.py` 就存在的既有問題，不在本次重構範圍內。
- `pytest test_kline_logic.py test_bot_logic.py`：14 passed，2 failed。
  兩個失敗（`test_04_command_parser_integration`、`test_07_mtf_and_institutional_gate`）
  在**重構前的原始程式碼**、於本沙盒環境下重跑，會出現一模一樣的失敗——因為沙盒
  無法連線 TWSE / Yahoo Finance 真實行情，與本次重構無關。建議在你本機（有網路）
  的環境下重跑一次確認。

## 建議你在自己的機器上再做一次的事
1. `pip install -r requirements.txt` 後執行 `pytest` 全套，確認在有網路環境下
   `test_04` / `test_07` 也能通過（本沙盒受限於出網白名單無法驗證這兩個）。
2. 快速讀一遍 `core/analyzer.py`（原本最大的函式，897 行），評估要不要進一步
   拆成更小的子函式（例如把 5m 分析與日線分析拆成兩個檔案）。
3.（第 2 點以外，先前架構建議中還沒動的部分）`line_server.py` 的 SQLite 雙節點
   快照同步、`handle_user_command` 巨型函式、本機常駐部署腳本，這些仍維持原樣，
   之後可以再排時間處理。
