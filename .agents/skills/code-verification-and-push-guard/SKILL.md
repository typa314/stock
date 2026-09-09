---
name: code-verification-and-push-guard
description: >-
  Enforce strict zero-speculation principle, thorough verification procedures before any code changes,
  and strictly prohibit pushing code to remote repositories without explicit user permission.
  Use whenever modifying code, reviewing modifications, analyzing market data, or handling git operations.
---

# 代碼修改驗證、禁止臆測與未授權推送規範 (Verification, Zero-Speculation & Push Guard)

本規範為本專案的最高安全、分析準確度與工程品質原則，Agent 在執行任何分析判斷、代碼修改、測試與 Git 操作時必須嚴格遵守：

## 1. 嚴禁臆測原則 (Zero Speculation Principle - 最高分析原則)
* **客觀量化至上**：所有行情診斷、多空定調、K 棒形態與主力異動解讀，**必須 100% 依據客觀且可重現的量化數據**（例如：20 EMA 斜率、乖離率、真實實體/影線比、成交量與 20MA 倍數比）。
* **無訊號即觀望**：在價格處於均線糾結、指標不明顯或市場處於區間震盪時，**嚴格禁止主觀推測「即將向上突破」、「主力準備拉抬」或「拉回一定會彈」**；必須誠實標註為「箱型震盪／觀望」，不得預設立場。
* **嚴禁主觀腦補語意**：分析與報告中嚴禁使用「感覺要發動」、「似乎在震盪吃貨」等無法被數據驗證的主觀猜測文字；一切結論必須列出具體數值支持。
* **尊重破線事實**：當價格跌破關鍵支撐或觸及風控停損線時，**嚴禁臆測「這只是主力假破底洗盤」**；必須無條件尊重破線事實，嚴格提示停損。

## 2. 嚴禁未經許可推送代碼 (Strict Push Ban)
* **未獲使用者明確指示前，嚴格禁止執行任何形式的代碼推送命令**（包含 `git push`、`git push origin ...` 或任何遠端同步指令）。
* 即使單元測試通過或改動已在本地 commit，也**絕對不能**自動或順便推送至 GitHub / 遠端儲存庫。
* 當改動與驗證完成時，Agent 僅能在本地 commit 並向使用者報告測試與驗證結果，等待使用者明確發出「請推送」、「push」或核准指示。

## 3. 代碼修改必備之「完整驗證」流程 (Comprehensive Verification Process)
任何代碼修改均不得憑空推論或草率通過，必須依序完成以下 4 道驗證關卡：

### 關卡 1：語法與靜態檢查
* 使用 `python -c "import ast; ast.parse(...)"` 或 linter 確保改動後的檔案無語法錯誤、無未閉合括號或縮排問題。

### 關卡 2：全單元測試回歸
* 執行 `python test_bot_logic.py`，確認所有單元測試、整合測試全數通過（`OK`）。
* 若改動涉及既有邏輯（例如訊息格式、警報門檻、字串替換），必須同步確認未引發回歸錯誤。

### 關卡 3：歷史與實時數據回測驗證 (堅持客觀驗證)
* 針對指標、風控策略、形態判斷或警報邏輯之修改，必須撰寫或執行回測腳本（如使用 2 年日K、高頻 5分K 歷史數據）。
* 量化呈現改動前 vs 改動後的客觀指標：
  1. 訊號觸發次數與過濾雜訊比例
  2. 後續持倉平均報酬率（Hold Returns）
  3. 勝率與達到目標比（Win Rate / Target Rate）
  4. 停損率變化（Stop Loss Rate）
* 貫徹「只報告數據客觀支持的事實，嚴禁主觀臆測行情」。

### 關卡 4：向使用者彙報與請求審查
* 將回測報表、測試結果與差異分析完整呈現給使用者。
* 清楚說明改動內容與量化效益，明確詢問使用者是否核准。
* **等待使用者確認後，才能依使用者指令進行後續動作。**
