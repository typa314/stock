---
name: al-brooks-price-action
description: >-
  Al Brooks 價格行為學（BPA）台股量化研判與交叉驗證標準作業準則。
  涵蓋 20 EMA 動態基準、K 線逐根分類、Always-In 市場狀態判定、
  H1/H2/L1/L2 情境濾網、20 EMA Gap Bar、台股 Tick 級距停損掛單與零臆測驗證協議。
---

# 📊 Al Brooks 價格行為學（BPA）台股量化研判與零臆測交叉驗證準則

本 Skill 旨在規範量化交易與技術分析系統中導入 **Al Brooks 價格行為學（Brooks Price Action, BPA）** 之工程實作、數學公式、情境濾網與交叉驗證標準。所有規則恪守「**無臆測原則（Zero-Speculation Principle）**」，每一條判斷均須具備明確的數學定義與因果時序完整性。

---

## 一、 核心操盤哲學與無臆測原則（Zero-Speculation Principle）

1. **純價格行為本質**：市場所有資訊與多空博弈均已即時反應於價格（Price）本身。除 **20 EMA（20日指數移動平均線）** 作為動態價值中樞外，不依賴落後震盪指標作為進出場依據。
2. **因果時序完整性（No Lookahead Bias）**：
   - 任何第 $t$ 根 K 棒的訊號計算，嚴禁引用 $t+1$ 或未來之極值、收盤或成交量。
   - 滾動區間（Rolling Window）如近 20 日高低點，計算範圍必須為 $[t-20, t-1]$，避免自我引用引發未來數據洩漏。
3. **情境先於形態（Context Over Pattern）**：
   - K 線形態不能脫離趨勢情境單獨研判。
   - 在多頭趨勢（AIL）中，僅採納多方回檔買點（H1/H2/H3、多頭反轉棒），嚴禁將一般拉回誤判為空方進場點。
   - 在空頭趨勢（AIS）中，僅採納空方反彈空點（L1/L2/L3、空頭反轉棒），嚴禁將弱勢反彈誤判為多方買點。

---

## 二、 20 EMA 核心基準線數學規範

Al Brooks 全球專著唯一指定均線為 20 週期指數移動平均線（EMA 20）：

$$\text{EMA}_t = \alpha \cdot \text{Close}_t + (1 - \alpha) \cdot \text{EMA}_{t-1}, \quad \text{其中 } \alpha = \frac{2}{20 + 1} = \frac{2}{21}$$

- **程式碼標準實作**：
  ```python
  df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
  ```
- **斜率（Slope）量化計算**：
  $$\text{Slope}_{\text{EMA20}} = \frac{\text{EMA20}_t - \text{EMA20}_{t-5}}{\text{EMA20}_{t-5}} \times 100\%$$
  - $\text{Slope} > +0.15\%$：偏多發散
  - $\text{Slope} < -0.15\%$：偏空發散
  - $|\text{Slope}| \le 0.15\%$：走平鈍化（區間震盪特徵）

---

## 三、 K 線逐根精確分類（Bar-by-Bar Classification）

令第 $t$ 根 K 線之四價為 $O_t, H_t, L_t, C_t$，定義：
- 總震幅：$R_t = \max(H_t - L_t, 10^{-5})$
- 實體大小：$B_t = |C_t - O_t|$
- 上影線：$U_t = H_t - \max(O_t, C_t)$
- 下影線：$D_t = \min(O_t, C_t) - L_t$

### 1. 趨勢棒（Trend Bars）
- **多頭趨勢棒（Bull Trend Bar）**：
  $$C_t > O_t \quad \land \quad \frac{B_t}{R_t} \ge 0.50 \quad \land \quad C_t \ge H_t - 0.25 R_t$$
- **空頭趨勢棒（Bear Trend Bar）**：
  $$C_t < O_t \quad \land \quad \frac{B_t}{R_t} \ge 0.50 \quad \land \quad C_t \le L_t + 0.25 R_t$$

### 2. 反轉訊號棒（Reversal Signal Bars）
- **多頭反轉棒（Bull Reversal Bar）**：
  $$\frac{D_t}{R_t} \ge 0.35 \quad \land \quad C_t \ge L_t + 0.60 R_t \quad \land \quad (L_t \le L_{t-1} \lor L_t \le \text{EMA20}_t)$$
- **空頭反轉棒（Bear Reversal Bar）**：
  $$\frac{U_t}{R_t} \ge 0.35 \quad \land \quad C_t \le L_t + 0.40 R_t \quad \land \quad (H_t \ge H_{t-1} \lor H_t \ge \text{EMA20}_t)$$

### 3. 波動收斂與擴張棒
- **孕線（Inside Bar `i`）**：$H_t \le H_{t-1} \land L_t \ge L_{t-1}$
- **雙重孕線（Double Inside `ii`）**：連續兩根孕線，宣告進入高壓縮突破模式（Breakout Mode）。
- **外部棒（Outside Bar `o`）**：$H_t > H_{t-1} \land L_t < L_{t-1}$
- **十字猶豫棒（Doji）**：$\frac{B_t}{R_t} \le 0.25$

---

## 四、 Always-In 市場狀態判定準則

Al Brooks 操盤核心在於任何當下必須明確回答：若現在被迫在市場建立部位，應持有何種方向？

1. **Always In Long (AIL, 恆久做多)**：
   - 價格位於 20 EMA 之上，且 $\text{Slope}_{\text{EMA20}} > +0.15\%$；或
   - 連續出現強勢多頭趨勢棒突破關鍵壓力。
2. **Always In Short (AIS, 恆久做空)**：
   - 價格位於 20 EMA 之下，且 $\text{Slope}_{\text{EMA20}} < -0.15\%$；或
   - 連續出現強勢空頭趨勢棒跌破關鍵支撐。
3. **Trading Range (TR, 箱型交易區間 / 盤整)**：
   - 近 10 根 K 線穿越 20 EMA 次數 $\ge 3$ 且均線斜率走平；或
   - 觸發鐵絲網形態（TTR / Barbwire）：連續 3 根以上 K 線高低點高度交疊（重疊率 $> 45\%$ 且平均實體率 $< 40\%$）。

---

## 五、 經典高勝率交易設定（BPA Setups）與情境濾網

### 1. High 1 / High 2 (H1 / H2 多頭回踩買點)
- **情境濾網**：僅在 **AIL** 或 **TR 下半部（接近支撐）** 採納。
- **H1**：多頭回檔中（出現 lower high 後），首次突破前一根棒高點（$H_t > H_{t-1}$）。
- **H2**：若 H1 後再度回踩（雙重推動 ABC 修正），第二次突破前棒高點。此為 Al Brooks 公認勝率最高之順勢買點！
- **H3**：三次推動回踩，構成楔形多頭旗形（Wedge Bull Flag）。

### 2. Low 1 / Low 2 (L1 / L2 空頭反彈空點)
- **情境濾網**：僅在 **AIS** 或 **TR 上半部（接近壓力）** 採納。
- **L1**：空頭反彈中（出現 higher low 後），首次跌破前一根棒低點（$L_t < L_{t-1}$）。
- **L2**：二次反彈推動耗竭後，跌破前棒低點。此為空方高勝率進場點！
- **L3**：三次反彈推動，構成楔形空頭旗形（Wedge Bear Flag）。

### 3. 20 EMA Pullback (EMA 20 初次回測)
- 趨勢脫離 20 EMA 連續 8 根以上後，首次回測 20 EMA 且收盤守穩，為高勝率順勢加碼點。

### 4. 20 EMA Gap Bar（乖離缺口棒）
- **多頭缺口棒**：在多頭趨勢中，整根 K 棒最高價低於 20 EMA（$H_t < \text{EMA20}_t$）。
  - **解讀準則**：空方首次展現壓制力道，通常會引發多頭回補帶動最後一波測頂走勢；但此現象亦為趨勢老化的重大警訊，防範後續演化為 TR 盤整或 Major Trend Reversal（MTR 主要趨勢反轉）。
- **空頭缺口棒**：在空頭趨勢中，整根 K 棒最低價高於 20 EMA（$L_t > \text{EMA20}_t$），預示空方最後一擊測底。

### 5. 鐵絲網警訊（TTR / Barbwire）
- 處於密集交疊區時，嚴格執行「**80% 區間突破失敗法則**」。
- 禁止使用突破停損單追價，空手觀望或僅在邊界逆勢短沖（BLSHS: Buy Low, Sell High, Scalp）。

---

## 六、 台股升降單位（Tick Size）與訂單風控指引

依據台灣證券交易所營業細則第 63 條，精確計算最小升降檔位：

$$\text{Tick}(P) = \begin{cases} 
0.01 & P < 10 \\ 
0.05 & 10 \le P < 50 \\ 
0.10 & 50 \le P < 100 \\ 
0.50 & 100 \le P < 500 \\ 
1.00 & 500 \le P < 1000 \\ 
5.00 & P \ge 1000 
\end{cases}$$

### 訂單執行與等距測量目標（Measured Move, MM）
- **多方突破掛單（Buy Stop）**：$\text{Signal Bar High} + \text{Tick}$
- **多方防守停損（Protective Stop）**：$\text{Signal Bar Low} - \text{Tick}$
- **承擔風險（Risk 1R）**：$\text{Buy Stop} - \text{Protective Stop}$
- **目標一（Target +1R）**：$\text{Buy Stop} + 1\text{R}$
- **目標二（Target +2R）**：$\text{Buy Stop} + 2\text{R}$

---

## 七、 交叉驗證協議（Cross-Validation Protocol）

在任何程式碼修改或策略調整後，必須執行以下四道驗證檢驗，確保無臆測與零錯誤：

1. **數學公式檢驗**：
   - 驗證 EMA 遞迴公式是否符合 $\alpha = 2/(N+1)$。
   - 驗證 Wilder's Smoothing RSI 是否符合 $\alpha = 1/14$（`com=13`）。
2. **邊界極值檢驗**：
   - 驗證台股升降級距在 $9.99, 10.00, 49.95, 50.00, 99.9, 100.0, 499.5, 500.0, 999.0, 1000.0$ 之切換正確。
3. **情境一致性檢驗（Context Sanity Check）**：
   - 在 AIS 環境下，輸出報告中絕不允許出現無效之 H1/H2 買點推薦。
   - 在 AIL 環境下，輸出報告中絕不允許出現無效之 L1/L2 空點推薦。
4. **全市場跨標的執行測試**：
   - 上市權值股測試（如 2330 台積電）
   - 上市中型股測試（如 3042 晶技）
   - 上櫃/高價股測試（如 6446 藥華藥、6472 保瑞）

---

## 八、 軟體工程品質檢查與零未定義變數規範（Quality Assurance & Zero-Error Protocol）

為確保 Web 看盤應用（Streamlit）與 CLI 工具在生產環境（包含 Streamlit Community Cloud、Docker 與原生環境）高可靠運行，任何代碼推送前必須嚴格遵守以下品質防護檢查流程：

1. **靜態程式碼品質檢驗（Zero Undefined Variables Check）**：
   - 嚴禁僅以 `py_compile` 作為驗證標準（`py_compile` 僅檢查語法層級，無法攔截執行期 `NameError`）。
   - 必須透過 `pyflakes` 靜態掃描所有核心檔案（`app.py`、`kline.py`、`test_kline_logic.py`），確保**零未定義變數（No Undefined Names）**。
   - 所有在條件分支或 UI 元件區塊中引用的變數（如 `cost_opt`、`months_opt`），必須在作用域前定義完整，杜絕變數遺失。
2. **Streamlit 全域執行流檢查（Streamlit App Sanity Run）**：
   - 每次變更 Web App（`app.py`），必須執行整合測試驗證所有自訂參數（成本、月數、股票切換）與快取邏輯在全域執行時無異常拋出。
   - 確保所有 UI 元件（如輸入框、按鈕）之 `key` 與 `session_state` 雙向綁定正確無衝突。
3. **多環境與雲端機房防禦（Cloud Sandbox Safety）**：
   - 外部數據串接必須具備**雙軌備援機制**（如 FinMind + TWSE），防止海外雲端機房（如 AWS / Streamlit Cloud）受官方 IP 阻擋。
   - 任何外部資料請求失敗時，必須進行優雅降級或替代軌道重試，嚴禁在模組內部呼叫 `sys.exit()` 導致伺服器崩潰。
4. **自動化驗證執行守則**：
   - 任何提交前必須執行：
     ```powershell
     python -X utf8 test_kline_logic.py
     ```
   - 必須確認第 6 項測試 `Static Code Quality & Zero-Undefined-Variable Validation` 為 `[PASS]` 始可提交。
5. **雙軌環境隔離與上線審核流程（Dev-to-Prod Workflow）**：
   - **`devapp.py`（開發與驗證環境）**：所有新 UI 功能、圖卡調整、實驗性指標研發與版面改動，一律優先在 `devapp.py` 進行開發與測試。
   - **確認無誤始得推產**：與使用者共同確認 `devapp.py` 運行正常且零錯誤、無 UI 崩潰後，方可將穩定代碼同步晉級覆蓋至正式版 `app.py`。
   - **杜絕影響線上正式使用者**：Streamlit Cloud 生產環境僅追蹤穩定的 `app.py`，未經驗證的半成品或實驗中代碼嚴禁直接寫入 `app.py`。
