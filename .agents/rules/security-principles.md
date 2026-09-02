---
trigger: always_on
description: >-
  強制遵守最高資安原則，嚴禁敏感憑證（Token/API Key/密碼）洩漏、Git Remote URL 憑證污染與不安全代碼執行。
---

# 🛡️ 專案強制安全性規則（Always-On Security Rules）

在任何開發、操作、版控或 AI 協作中，必須無條件遵循以下資安規定：

1. **零憑證洩漏（Zero Secret Leakage）**：
   - 絕不將 GitHub PAT、API Keys、密碼或私鑰寫入原始碼、設定檔或 Commit Message。
   - 若使用者在對話中無意貼出憑證，必須第一時間提示撤銷（Revoke），並嚴禁將其硬編碼到任何檔案中。

2. **Git 遠端安全（Clean Git Remote）**：
   - 嚴禁在 `git remote` URL 中嵌入帳號或 Token（即不得出現 `https://<token>@github.com/...`）。
   - Remote URL 必須維持標準形式 `https://github.com/<owner>/<repo>.git`，憑證應交由作業系統的 Credential Manager 託管。

3. **敏感檔案隔離（VCS Exclusion）**：
   - `.env`、`.env.*`、`*.pem`、`*.key`、`secrets.*` 必須納入 `.gitignore`，嚴禁納入版本控制。

4. **命令與代碼安全（Safe Execution）**：
   - 避免命令注入風險，禁止拼接不可信字串至 shell 命令。
   - 嚴禁使用 `eval()`、`exec()` 或不可信反序列化。
