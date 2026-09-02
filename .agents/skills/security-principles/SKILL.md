---
name: security-principles
description: >-
  嚴格強制之軟體工程與 AI 協作安全性原則（Security Principles & Guardrails）。
  規範敏感憑證零洩漏、Git 認證安全、代碼注入防護、環境隔離與主動安全審查流程，
  確保在任何開發、測試、分析與版控過程中絕不違反資訊安全與隱私防護標準。
---

# 🛡️ 安全性原則與守則規範（Security Principles & Guardrails）

本 Skill 旨在規範本專案中所有開發、維護、指令執行、版本控制與 AI 協作行為，恪守**「最高等級資訊安全原則（Security First）」**，杜絕任何形式的密鑰洩漏、命令注入、設定污染或非授權存取。

---

## 一、 核心安全紅線（Zero-Tolerance Security Rules）

1. **嚴禁敏感資訊明文暴露（Zero Secret Exposure）**：
   - 絕對禁止在原始碼、測試腳本、設定檔、文檔、日誌（Log）或對話輸出中硬編碼或明文記錄任何密鑰。
   - 涵蓋範圍包括但不限於：
     - GitHub Personal Access Tokens (`ghp_...`, `github_pat_...`)
     - API 密鑰（如 OpenAI `sk-...`、TWSE 專用 Key、AWS/GCP Keys）
     - 資料庫與帳號密碼（`password`, `secret`, `credentials`）
     - 私鑰與憑證檔（`*.pem`, `*.key`, `id_rsa`）
2. **嚴禁 Git 遠端網址污染（Clean Git Remotes）**：
   - 絕對禁止在 `git remote` URL 中直接將 Token 嵌入（例如 `https://<token>@github.com/...`）。
   - 該行為會導致 Token 以明文寫入本機 `.git/config`，產生嚴重資安漏洞。
   - 遠端必須維持乾淨標準格式：`https://github.com/<owner>/<repo>.git`。
3. **敏感檔案禁止納入版控（Strict VCS Exclusion）**：
   - 所有環境變數檔案（`.env`、`.env.local`、`secrets.json` 等）必須無條件列入 `.gitignore`，嚴禁 `git add` 或提交進 repo。

---

## 二、 認證與密鑰管理標準作業程序（Secret Management SOP）

### 1. 安全儲存方式
- **本機開發**：使用獨立的 `.env` 檔案載入環境變數（搭配 `python-dotenv`）。
- **Git 存取認證**：
  - 優先使用作業系統內建之 **Git Credential Manager**：
    ```powershell
    git config --global credential.helper manager
    ```
  - 或配置本機 **SSH Key** 進行免密認證。

### 2. 洩漏即撤銷原則（Revocation-First Response）
- 若在對話或任何提交紀錄中發現任何 Token 或 Key 曾以明文形式出現：
  1. **第一優先警示**：立即提示使用者前往 GitHub / 服務商管理後台將該金鑰**撤銷（Revoke / Delete）**。
  2. **金鑰清洗（Scrubbing）**：立即清除本地 `.git/config`、歷史紀錄或暫存檔中的明文殘留。
  3. **禁止沿用**：不得繼續在後續命令或腳本中使用已暴露的金鑰。

---

## 三、 代碼與命令執行安全（Execution & Injection Safety）

1. **命令注入防範（Command Injection Prevention）**：
   - 在呼叫 shell 或外部子進程（Subprocess）時，禁止直接以字串拼接未經驗證的外部輸入。
   - 建議使用參數串列形式執行（如 `subprocess.run(["cmd", arg1, arg2])`），避免 `shell=True` 帶來的注入風險。
2. **動態程式碼執行禁令**：
   - 嚴格禁止在生產與資料解析程式碼中使用 `eval()`、`exec()` 或非受控反序列化（如不可信的 `pickle.load()`）。

---

## 四、 數據完整性與因果安全（Data Integrity & Zero Lookahead）

1. **時序因果安全（No Lookahead Bias）**：
   - 量化金融與技術指標計算嚴格遵守因果單向性，禁止使用未來資訊。
2. **無臆測原則（Zero-Speculation）**：
   - 任何分析輸出必須有可靠數學公式與數據來源作為支撐，嚴禁虛構指標或操盤數據。

---

## 五、 Commit 與 Push 前安全審查清單（Pre-Commit Security Checklist）

在執行 `git commit` 與 `git push` 前，必須逐項檢查：

- [ ] 執行 `git diff --staged` 檢視所有預計提交之內容，確認無任何 Token、密碼或連線字串。
- [ ] 檢查 `git remote -v`，確認所有 remote URL 不含 `@` 帳密資訊。
- [ ] 檢查 `.git/config`，確認無嵌入憑證。
- [ ] 確認 `.gitignore` 包含 `.env*`、`*.pem`、`*.key` 等敏感副檔名。
