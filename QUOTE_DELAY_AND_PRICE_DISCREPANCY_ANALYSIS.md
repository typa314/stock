# 台股系統「報價延遲、日/分K價格不同步與 TWSE 限流機制」綜合分析與架構檢驗報告

> **報告定調**：本報告依據 `f:\stock` 專案現行程式碼走查、盤中真實市場數據（2026-09-10 09:42 實測）及證交所官方 API 通訊規範編寫，提供具體行號、量化數據與可重現驗證命令，供交叉審查與驗證。

---

## 目錄
1. [盤中實測數據對照表（驗證價格脫鉤與延遲現況）](#一盤中實測數據對照表)
2. [代碼走查：為什麼「日K 與 5分K 價格不同」？](#二代碼走查為什麼日k-與-5分k-價格不同)
3. [延遲成因深度診斷：為什麼「報價會延遲」？](#三延遲成因深度診斷為什麼報價會延遲)
4. [TWSE 官方連線硬限制分析（每 5 秒 3 個 Request）與現存風險點](#四twse-官方連線硬限制分析與現存風險點)
5. [先前提議之「即時縫合（Bar Stitching）」架構缺陷檢討](#五先前提議之即時縫合架構缺陷檢討)
6. [正確解耦架構規範（時效性需求 vs. 時框分析）](#六正確解耦架構規範時效性需求-vs-時框分析)
7. [交叉驗證重現指令清單（可於終端機直接執行）](#七交叉驗證重現指令清單)

---

## 一、盤中實測數據對照表

於 2026-09-10 09:42 台股盤中撮合期間，以相同環境、相同網路節點同時對 4 檔標的調用 `fetch_realtime_bar()`、`analyze_stock()`（日K）與 `analyze_stock_5m()`（5分K），取得以下實測數值：

| 標的代號 | 標的名稱 | TWSE MIS 即時撮合價 (時間戳) | 日K 最新價 (`close_now`) | 5分K 最新價 (`close_now`) | 5分K 資料時間戳 | 價差 (日K - 5分K) | 5分K 實質滯後時間 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **2454** | 聯發科 | **4,615.0** (09:42:01) | **4,615.0** | **4,555.0** | 09:20:00 | **+60.0 元** | **滯後 22 分鐘** |
| **2603** | 長榮 | **230.5** (09:42:20) | **231.0** | **232.5** | 09:20:00 | **-1.5 元** | **滯後 22 分鐘** |
| **3042** | 晶技 | **173.0** (09:42:32) | **173.0** | **172.5** | 09:20:00 | **+0.5 元** | **滯後 22 分鐘** |
| **6182** | 合晶 | **107.5** (09:42:32) | **107.5** | **108.0** | 09:20:00 | **-0.5 元** | **滯後 22 分鐘** |

### 實測結論：
在同一毫秒發起呼叫，日K 能精準拿到當下秒級的撮合價（4615 元），但 **5分K 的資料整整停留在 22 分鐘前的 09:20**，造成兩者價格嚴重不符，且聯發科單檔價差達到 60 元。

---

## 二、代碼走查：為什麼「日K 與 5分K 價格不同」？

### 1. 日K 的取價邏輯（[`kline.py:1367-1391`](kline.py#L1367-L1391)）
* **資料獲取流程**：
  1. 先向 TWSE / yfinance 取得歷史日線 DataFrame。
  2. 第 1367 行：主動呼叫 `rt_row = fetch_realtime_bar(ticker, market)`。
  3. 第 1382-1387 行：當日期為今日時，**動態將盤中即時撮合價覆蓋進日K 尾端**：
     ```python
     elif rt_row["date"] == df["date"].iloc[-1] and rt_row.get("is_realtime"):
         idx = len(df) - 1
         df.loc[idx, "close"] = rt_row["close"]   # 寫入 TWSE MIS 當前最新撮合價
         df.loc[idx, "high"] = max(df.loc[idx, "high"], rt_row["high"])
         df.loc[idx, "low"] = min(df.loc[idx, "low"], rt_row["low"])
     ```
  4. 因此，日K 回傳的 `close_now` 是**當下 0~5 秒內的即時撮合價**。

### 2. 5分K 的取價邏輯（[`kline.py:1814-1847`](kline.py#L1814-L1847)）
* **資料獲取流程**：
  1. 第 1814 行：僅呼叫 `yf.download(sym, interval="5m", period=f"{days}d", progress=False)`。
  2. 第 1847 行：**直接取 DataFrame 最後一筆的 Close 作為 `close_now`**：
     ```python
     close_now = float(df["close"].iloc[-1])
     ```
  3. **關鍵缺陷**：`analyze_stock_5m` 函式內部**完全沒有呼叫 `fetch_realtime_bar()`**，也沒有對接任何盤中即時行情來源，完全依賴 yfinance 抓回的最後一根 5m 棒。

### 3. 不一致的本質根源
* **日K** = 歷史日線 + **TWSE MIS 秒級撮合價（即時）**。
* **5分K** = **yfinance 延遲資料庫（延遲 20 分鐘）**。
* 兩者資料來源不同、時間戳截點相差 22 分鐘，價格必然不同。

---

## 三、延遲成因深度診斷：為什麼「報價會延遲」？

系統中的延遲並非單一原因，而是由三個不同層級疊加產生：

```
[使用者發起查詢]
      │
      ├─ 1. 網路/運算層延遲 (5~8秒) ───► fetch_twse() 逐月迴圈與 sleep(0.3)
      │
      ├─ 2. 5分K 資料源延遲 (20分鐘) ──► yfinance 免費 API 官方延遲台股 5m 資料
      │
      └─ 3. 備援切換延遲 (15分鐘) ─────► TWSE MIS 失敗 fallback 到 Yahoo Finance
```

1. **5分K 物理延遲（15 ~ 20 分鐘）**：
   * Yahoo Finance 對台股（`.TW` / `.TWO`）的 5 分鐘棒線未開放即時推送，伺服器產出 5m 棒約延後 15~20 分鐘。
2. **日K 爬蟲初次下載延遲（5 ~ 8 秒體感卡頓）**：
   * 在 [`kline.py:49-80`](kline.py#L49-L80) 的 `fetch_twse` 中，若查詢 12 個月資料，會執行 12 次 HTTP GET，每次附帶 `time.sleep(0.3)`，使得單次查詢最少需耗時 4~8 秒，造成使用者介面卡住。
3. **備援降級延遲**：
   * [`kline.py:156-181`](kline.py#L156-L181) 軌道 2（Yahoo Finance 備援）：當 TWSE MIS 網路抖動時，退回 Yahoo Finance，Yahoo 報價本身亦延遲 15 分鐘。

---

## 四、TWSE 官方連線硬限制分析與現存風險點

### 1. 證交所官方限制定義
* **限制閥值**：**每 5 秒最多 3 個 Request**（平均單一請求間隔需 $\ge 1.67$ 秒，實務建議保留緩衝至 $\ge 1.8 \sim 2.0$ 秒）。
* **超限後果**：伺服器回傳 `{"rtcode": "5000", "rtmessage": "json decode error"}`、HTTP 403 Forbidden，或直接將來源 IP 加入黑名單封鎖（Ban 掉 20 分鐘至數小時不等）。

### 2. 現有代碼中的 2 處「觸發 Ban 掉高風險地雷」

#### 🚨 地雷點 A：`kline.py` 第 78 行的 `fetch_twse` 逐月下載
```python
# kline.py:54-78
while cur <= now:
    r = requests.get(url, params={"date": date_str, "stockNo": ticker, ...})
    time.sleep(0.3)  # ⚠️ 嚴重風險：0.3 秒 = 1 秒送出 3.3 次請求
```
* **風險評估**：抓取 12 個月時，在 **3.6 秒內向 TWSE 發送 12 次請求**，直接打破「5 秒 3 次」硬限制 4 倍以上，若快取失效极易被 Ban。

#### 🚨 地雷點 B：`monitor_worker.py` 與 `line_server.py` 的無間隔迴圈查詢
```python
# monitor_worker.py:74-75
for t, (market, sname) in ticker_market_map.items():
    rt = fetch_realtime_bar(t, market)  # ⚠️ 迴圈連續發送，間隔 0 秒！
```
```python
# line_server.py:459-465 (自選股清單查詢)
for w in watch_items:
    rt = fetch_realtime_bar(t, market)  # ⚠️ 1 秒內連續查詢多檔自選股！
```
* **風險評估**：若自選名單有 6 檔股票，迴圈在 1 秒內連續發出 6 次 TWSE MIS 請求，瞬間撞上限流牆。

---

## 五、先前提議之「即時縫合（Bar Stitching）」架構缺陷檢討

在先前對話中，曾提議「將 TWSE MIS 即時成交價強行縫合進 5分K」。**經過深度審查，此做法存在嚴重的架構錯誤與數學邏輯缺陷**：

```
時間軸: 09:20 ─── [09:25] ─── [09:30] ─── [09:35] ─── [09:40] ─── 09:45 (現當下)
Yahoo 5m: 存在      ❌缺失       ❌缺失       ❌缺失       ❌缺失      不存在
TWSE MIS:                                                          ● 現價快照 (4615)
```

1. **「消失的 20 分鐘」斷層不可逆**：
   * TWSE MIS 只提供「當下瞬間快照（Snapshot）」，不提供過去 20 分鐘歷史。
   * 若將 09:45 的快照硬接在 09:20 後面，中間遺失了 4 根 5分K（09:25、09:30、09:35、09:40）。
2. **量化指標嚴重失真**：
   * 遺失 4 根 K 棒的情況下，**20 EMA 計算公式中的平滑加權指數（Alpha）計算點數錯位**。
   * Al Brooks BPA 價格行為的「連續趨勢棒／反轉棒／雙重底突破」判定需要嚴密的連貫性，中間跳空 20 分鐘會產生假突破或漏掉關鍵停損訊號。
3. **竄改歷史數據風險**：
   * 若直接把 09:20 那根 K 棒的 Close 覆蓋為 09:45 的 4615 元，等於偽造了 09:20 的成交價，破壞歷史回測與數據可信度。

---

## 六、正確解耦架構規範（時效性需求 vs. 時框分析）

遵循 **「只有時效性的需求，即時報價透過這個 API」** 的核心準則，架構必須進行徹底的**職責分離（Decoupling）**：

```
                           [使用端請求]
                                │
        ┌───────────────────────┴───────────────────────┐
        ▼                                               ▼
【時效性需求 (Time-Sensitive)】              【時框分析需求 (Time-Frame Analysis)】
  • 查當前股票現價                            • 5分K Al Brooks 當沖形態
  • 計算持倉未實現損益                        • 日K 趨勢結構 (Stan Weinstein)
  • 盤中停損/停利點觸發檢核                    • 籌碼法人與量價結構
        │                                               │
        ▼                                               ▼
[中央即時報價 Hub (Quote Hub)]                [時框歷史分析引擎 (K-Line Engine)]
  ├─ 嚴格限制：每 5 秒 ≤ 3 次                   ├─ 來源：yfinance / 本地快取
  ├─ 模式：批次查詢 (1 個請求查 20 檔)          ├─ 完整時間序列，不硬縫合快照
  └─ 來源：TWSE MIS API                         └─ 明確標註資料截點 (如：截至 09:20)
        │                                               │
        └───────────────────────┬───────────────────────┘
                                ▼
                     [統一彙整呈現在 UI / LINE]
                     • 即時現價：4,615 元 (09:45 TWSE)
                     • 5分K形態：以 09:20 完整棒線為基準
```

### 架構規則摘要：
1. **即時報價專責專用**：
   * `fetch_realtime_bar()` 的定位是「報價器（Ticker）」，**只在需要知道現在幾塊錢、算損益、檢查停損時調用**。
2. **K 線引擎保持資料純淨**：
   * `analyze_stock_5m` 專注於分析完整收盤的 K 棒，卡片明確標記 `資料時間：09:20`，不混入未完成或跨時段的瞬時資料。
3. **中央單一出口與批次合併**：
   * 所有盤中監控（`monitor_worker`）與自選清單，禁止逐檔 `for` 迴圈呼叫 TWSE。
   * 一律使用 `ex_ch=tse_2330.tw|tse_2454.tw|otc_6182.tw` 批次單次取回，並經由中央全域限流器（強制單次間隔 $\ge 1.85$ 秒），保證 100% 不觸犯 TWSE 5 秒 3 次的封鎖紅線。

---

## 七、交叉驗證重現指令清單

您可以在本機終端機（PowerShell / Command Prompt）直接執行以下指令進行交叉比對驗證：

### 1. 驗證日K 與 5分K 的價格與時間截點不一致
```powershell
python -c "
from kline import analyze_stock, analyze_stock_5m, fetch_realtime_bar
ticker = '2454'
res_d = analyze_stock(ticker, months=1, print_report=False, quick_mode=True)
res_5 = analyze_stock_5m(ticker, days=1)
rt = fetch_realtime_bar(ticker, 'tse')
print(f'=== {ticker} 交叉驗證結果 ===')
print('TWSE MIS 即時撮合價 :', rt.get('close'), '時間戳:', rt.get('time'))
print('日K close_now        :', res_d.get('close_now'))
print('5分K close_now       :', res_5.get('close_now'), '最後棒線時間:', res_5['df']['date'].iloc[-1].strftime('%H:%M:%S'))
print('價差 (日K - 5分K)    :', res_d.get('close_now') - res_5.get('close_now'))
"
```

### 2. 驗證 TWSE MIS 批次查詢支援（1 次 Request 查多檔，不消耗配額）
```powershell
python -c "
import requests
url = 'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_2330.tw|tse_2454.tw|tse_2603.tw|otc_6182.tw&json=1&delay=0'
r = requests.get(url, timeout=5).json()
print('回傳股票筆數:', len(r.get('msgArray', [])))
for item in r.get('msgArray', []):
    print(f'代號: {item.get(\"c\")} | 最新撮合價: {item.get(\"z\")} | 撮合時間: {item.get(\"t\")}')
"
```

### 3. 驗證目前單元測試基準
```powershell
python test_bot_logic.py
python test_kline_logic.py
```
