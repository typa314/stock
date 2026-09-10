# 核心交易策略與量化模型規格書 (Core Strategy Specification)

> **版本**：v2.1  
> **生效日期**：2026-09-10  
> **核心準則**：Zero Speculation（零猜測、純量化、100% 邏輯可重現）  
> **目標程式庫**：`F:\stock\core\`

---

## 1. 概觀與設計哲學

本專案之核心策略旨在提供高訊號雜訊比（Signal-to-Noise Ratio）之台股量化技術與基本面決策分析。系統由 5 大子模組構成：
1. **數值與指標基礎模組 (`core/indicators.py`)**：台股升降單位（Tick Rules）、真實波動區間（ATR）與動態風控停損點。
2. **專業趨勢分析模組 (`core/strategy_trend.py`)**：史丹·溫斯坦（Stan Weinstein）四階段趨勢框架、均線排列與籌碼因子。
3. **量價關係分析模組 (`core/strategy_volume.py`)**：威科夫（Wyckoff）與量價分析（VPA）八大狀態機。
4. **阿爾·布魯克斯價格行為模組 (`core/strategy_brooks.py`)**：Always-In 多空主控、K 線形態（H1~H3 / L1~L3）與停損/停利點。
5. **綜合評級與操盤決策模組 (`core/rating.py`)**：Minervini 趨勢樣板、CANSLIM 成長動能、法人籌碼與 HMM 濾網評分矩陣。

任何對上述核心邏輯之更動，**必須維持 100% 邏輯回歸驗證通過**，嚴禁引進主觀臆測。

---

## 2. 數值與指標規則 (`core/indicators.py`)

### 2.1 台灣證券交易所（TWSE）升降單位規範 (`get_tw_tick`)

| 價格區間（元） | 升降單位（Tick Size） | 數學定義 |
| :--- | :--- | :--- |
| `P < 10.0` | **0.01** | `price < 10` |
| `10.0 <= P < 50.0` | **0.05** | `10 <= price < 50` |
| `50.0 <= P < 100.0` | **0.10** | `50 <= price < 100` |
| `100.0 <= P < 500.0` | **0.50** | `100 <= price < 500` |
| `500.0 <= P < 1000.0` | **1.00** | `500 <= price < 1000` |
| `P >= 1000.0` | **5.00** | `price >= 1000` |

### 2.2 動態 ATR 波動率計算 (`compute_atr_pct`)
- **週期**：$N = 20$
- **真實區間（True Range, TR）**：
  $$TR_t = \max(High_t - Low_t,\; |High_t - Close_{t-1}|,\; |Low_t - Close_{t-1}|)$$
- **ATR 百分比**：
  $$ATR_{20} = \frac{1}{20} \sum_{i=0}^{19} TR_{t-i}$$
  $$ATR\% = \frac{ATR_{20}}{Close_t} \times 100\%$$

### 2.3 動態風控停損定價 (`compute_risk_stop`)
- **使用者覆寫優先權**：若使用者設定 `user_stop_pct` 且不等於預設值 `-7.0%`，強制採用使用者設定。
- **動態 ATR 計算**：
  $$Stop\% = \operatorname{clamp}(-3.0 \times ATR\%, -15.0\%, -8.0\%)$$
- **停損價格計算**：
  $$Price_{stop} = Cost \times (1 + \frac{Stop\%}{100})$$
- **容錯備援**：若技術資料取得失敗，回退至預設 `-7.0%`。

---

## 3. 趨勢狀態機模組 (`core/strategy_trend.py`)

### 3.1 史丹·溫斯坦（Stan Weinstein）四階段趨勢判定
計算 MA20 與 MA60 之 5 日斜率：
$$Slope_{MA20} = \frac{MA20_t - MA20_{t-4}}{MA20_{t-4}},\quad Slope_{MA60} = \frac{MA60_t - MA60_{t-4}}{MA60_{t-4}}$$

1. **Stage 2 主升推進 (+2 分)**：
   - 條件：$MA20 > MA60$ 且 $Slope_{MA20} > +0.3\%$ 且 $Slope_{MA60} \ge 0\%$
   - 狀態：`Stage 2 主升推進（多頭加速段）`
2. **Stage 4 主跌修正 (-2 分)**：
   - 條件：$MA20 < MA60$ 且 $Slope_{MA20} < -0.3\%$ 且 $Slope_{MA60} \le 0\%$
   - 狀態：`Stage 4 主跌修正（空頭尋底段）`
3. **Stage 1 打底築底 (0 分)**：
   - 條件：$Slope_{MA60} < 0$ 且 $MA20 < MA60$ 且 $Slope_{MA20} \ge -0.2\%$
   - 狀態：`Stage 1 打底築底（均線收斂中）`
4. **Stage 3 高檔做頭 (-1 分)**：
   - 條件：不符合上述三者之其餘情況
   - 狀態：`Stage 3 高檔做頭（震盪整理段）`

### 3.2 短線均線乖離動態
- $Close > MA5 \land Close > MA20$：**+1 分**（短線偏多）
- $Close < MA5 \land Close < MA20$：**-1 分**（短線承壓）
- 其餘情況：**0 分**

### 3.3 擺盪指標（MACD 與 RSI）
- **MACD 多頭強勢**：$DIF > 0 \land Signal > 0 \land Hist > 0$（**+1 分**）
- **MACD 空頭低迷**：$DIF < 0 \land Signal < 0 \land Hist < 0$（**-1 分**）
- **RSI 區間**：
  - $50 \le RSI \le 68$：**+1 分**（多頭健康區間）
  - $32 \le RSI < 50$：**-1 分**（弱勢整理區間）
  - 其餘極端或中立：**0 分**

### 3.4 三大法人籌碼因子
- 外資買超 $> 0$ 且 投信買超 $> 0$：**+2 分**
- 外資賣超 $< 0$ 且 投信賣超 $< 0$：**-2 分**
- 外資單日大量買超 $> +500$ 張：**+1 分**
- 外資單日大量賣超 $< -500$ 張：**-1 分**

---

## 4. 量價狀態機模組 (`core/strategy_volume.py`)

基準量能比率定義：$Ratio_{vol} = \frac{Volume_t}{MA20_{vol}}$，漲跌幅 $Chg = \frac{Close_t - Close_{t-1}}{Close_{t-1}}$。

| 狀態代碼 | 中文名稱 | 判定條件 | 分數 | 操作含義 |
| :--- | :--- | :--- | :---: | :--- |
| `CHURN` | 爆量滯漲 | $Ratio_{vol} > 1.8 \land (\frac{UpperShadow}{Range} > 0.4 \lor \frac{Body}{Range} < 0.25)$ | **-1** | 籌碼高檔鬆動，出貨疑慮 |
| `BREAKOUT` | 帶量突破 | $df[\text{"breakout"}] = \text{True}$（過20日高且量 $> 1.5 \times MA20_{vol}$） | **+2** | 攻擊訊號確立 |
| `DRYUP` | 窒息量打底 | $Volume_t < 0.45 \times MA20_{vol}$ | **0** | 賣壓竭盡，等待放量 |
| `BULL_EXP` | 價量齊揚 | $Chg > 0 \land Ratio_{vol} \ge 1.25$ | **+2** | 多方實質買盤湧入 |
| `BULL_DIV` | 量價背離 | $Chg > 0 \land Ratio_{vol} \le 0.75$ | **0** | 追價動能不足 |
| `BEAR_EXP` | 放量重挫 | $Chg < 0 \land Ratio_{vol} \ge 1.25$ | **-2** | 恐慌拋售，法人出逃 |
| `BEAR_RET` | 價跌量縮 | $Chg < 0 \land Ratio_{vol} \le 0.75$ | **+1** (若 $Close \ge MA20$) / **-1** (若 $Close < MA20$) | 守穩均線為良性回檔 |
| `NORMAL` | 量價常態 | 不符合上述特殊情境 | **0** | 中性震盪 |

---

## 5. 阿爾·布魯克斯價格行為模組 (`core/strategy_brooks.py`)

### 5.1 Always-In 狀態判定
1. **箱型震盪 (`Trading Range`) [0 分]**：
   - 觸發：$TTR = \text{True}$（3 根棒線重疊 $>45\%$ 且平均實體 $<40\%$），或（近 10 根穿越 EMA20 次數 $\ge 3$ 且 $|Slope_{EMA20}| < 0.3\%$）。
2. **多頭主控 (`Always In Long, AIL`) [+2 分]**：
   - 條件：$Close > EMA20 \land Slope_{EMA20} > 0.15\%$。
3. **空方主導 (`Always In Short, AIS`) [-2 分]**：
   - 條件：$Close < EMA20 \land Slope_{EMA20} < -0.15\%$。
4. **多頭拉回 (`AIL Pullback`) [+1 分]**：
   - 條件：$Close \ge EMA20$（斜率不符強多頭）。
5. **空頭反彈 (`AIS Pullback`) [-1 分]**：
   - 條件：$Close < EMA20$（斜率不符強空頭）。

### 5.2 交易形態與順勢濾網
> [!NOTE]
> **量化計數規格聲明（Quantitative State Machine Specification）**：  
> 本系統之 High 1/2/3 (H1/H2/H3) 與 Low 1/2/3 (L1/L2/L3) 為量化演算法專用之「**10-Bar 滾動回撤波段計數器（Swing-Window Pullback Classifier）**」。
> - **核心演算法**：以 10 根 K 線滾動窗口為基準，價格未創新高且出現回撤（$High_t < High_{t-1}$）後首度創前高標記為 H1；同波回撤再度創高標記為 H2；第三度標記為 H3（楔形旗形）。若價格刷新 10 根新高則重置計數為 0。
> - **觀念釐清**：此為 100% 離散確定性狀態機，旨在消除人工主觀性、精確捕捉回撤測試支撐買點，**非交易室人工肉眼或 tick-by-tick 逐筆微觀計數**。

- **High 1 / High 2 / High 3 (H1/H2/H3)**：
  - 多頭回檔後創前根高點之推進棒。
  - **進場濾網**：僅在 `AIL` 狀態、或 `Trading Range` 且價格處於布林下半部（$Close \le Mid_{BB}$）時方為有效進場點。
- **Low 1 / Low 2 / Low 3 (L1/L2/L3)**：
  - 空頭反彈後創前根低點之推進棒。
  - **進場濾網**：僅在 `AIS` 狀態、或 `Trading Range` 且價格處於布林上半部（$Close \ge Mid_{BB}$）時方為有效進場點。

### 5.3 停損與測量目標（Stop Order & Measured Move）
- **多頭停損限價（Buy Stop）**：
  $$Entry = High_{signal} + Tick$$
  $$StopLoss = Low_{signal} - Tick$$
  $$Risk = Entry - StopLoss$$
  $$MM_{1R} = Entry + Risk,\quad MM_{2R} = Entry + 2 \times Risk$$
- **空頭停損限價（Sell Stop）**：
  $$Entry = Low_{signal} - Tick$$
  $$StopLoss = High_{signal} + Tick$$
  $$Risk = StopLoss - Entry$$
  $$MM_{1R} = Entry - Risk,\quad MM_{2R} = Entry - 2 \times Risk$$

---

## 6. 綜合評級與操盤決策模組 (`core/rating.py`)

### 6.1 評分權重矩陣（總分 0 ~ 100 分）
$$TotalScore = \operatorname{round}\left( \frac{M_{passed}}{7} \times 35 + \frac{\max(0, C_{score})}{5} \times 25 + Score_{BPA} + Score_{Inst} \right)$$
*(若歷史資料不足 200 交易日，$M_{passed} = \text{None}$，Minervini 得分記 0 分，狀態標註「資料不足（無法評估）」)*

1. **Minervini 7 條件趨勢樣板（滿分 35 分）**：
   - (1) $Close > MA150 \land Close > MA200$
   - (2) $MA150 > MA200$
   - (3) $MA200 \ge MA200_{22d} \times 0.995$（年線持平或走揚）
   - (4) $MA50 > MA150 \land MA50 > MA200$
   - (5) $Close > MA50$
   - (6) $\frac{Close - Low_{52w}}{Low_{52w}} \ge 25\%$（高出 52 週低點 25% 以上）
   - (7) $\frac{High_{52w} - Close}{High_{52w}} \le 25\%$（位於 52 週高點 25% 以內）
   - **資料不足嚴格防護**：若資料不足無法計算 200MA 與 52 週高低點，回退為 `None`，不給予假分數。

2. **CANSLIM 基本面動能（滿分 25 分）**：
   - 營收 YoY $\ge +20\%$ (+2 分)，$\ge 0\%$ (+1 分)，$< 0\%$ (-1 分)
   - 近四季 EPS（TTM）$> 0$ (+2 分)
   - 毛利率 $\ge 30\%$ (+1 分)
   - 累積得分 $C_{score}$，折算 $\frac{\max(0, C_{score})}{5} \times 25$。

3. **BPA 價格行為（滿分 30 分）**：
   - 若處於多頭（含 AIL）：**30 分**
   - 若處於盤整 / 震盪：**15 分**
   - 若處於空方：**5 分**
4. **法人籌碼（滿分 10 分）**：
   - 5 日三大法人累計合計買超 $> 0$：**10 分**；否則 **0 分**。

### 6.2 評級星級
- `TotalScore >= 80` 且 `m_passed >= 5`：⭐⭐⭐⭐⭐ 頂級飆股體質（Stage 2 主升）
- `TotalScore >= 65`：⭐⭐⭐⭐ 優質多頭（穩健推升中）
- `TotalScore >= 45`：⭐⭐⭐ 區間震盪（待動能表態）
- `TotalScore < 45`：⚠️ 空頭承壓（弱勢修正中）

### 6.3 操盤訊號（Action Decision Engine）
- **BUY（建議買入）**：
  - 觸發：$TotalScore \ge 80$ 且（`"多"` in BPA 描述 或 `"主升"` in Badge）。
  - **HMM 市場濾網**：若市況為不利高波震盪（`is_adverse`），門檻提升至 $TotalScore \ge 85$；未達 85 分則降為 `WAIT`（建議觀望）。
- **HOLD（建議持有）**：$TotalScore \ge 60$ 且無空頭主控訊號。
- **WAIT（建議觀望）**：$TotalScore \ge 45$。
- **SELL（建議賣出）**：$TotalScore < 45$。

---

## 7. 邏輯不變性與防護承諾 (Invariance Contract)

在任何後續代碼重構或新功能添加時，必須保證：
1. **浮點數容差一致性**：所有價格乘數比對維持原精度容忍（如 `0.995`、`1.005`）。
2. **Tick 計算不跨界**：不得將台股升降級距簡化為定值。
3. **測試先行（Test-First / Regression Guard）**：修改任何策略公式前，必須在 `test_core_strategies.py` 增設對應之合成資料測試案例。
