# 🌐 Cloudflare Worker 智慧前哨多重備援路由器部署指南

本架構將 LINE Webhook 永遠對接至全球最快、永不休眠的 **Cloudflare 邊緣節點 (Workers)**，並由 Worker 智慧探測與瀑布式分流：
* **優先順位 1**：💻 **本地電腦 (高算力優先)** —— 盤中開機享受滿血 CPU 秒回（< 0.5s）。
* **優先順位 2**：☁️ **Render 雲端 (主力守護)** —— 本機休眠或關機時，1.2 秒內全自動無感切換。
* **優先順位 3+**：🚀 **未來多雲備援 (Koyeb / Fly.io / NAS)** —— 隨時在 Worker 內熱插拔擴充。

---

## 🚀 只要 3 分鐘：在 Cloudflare 免費建立 Worker（終身免費，每日 10 萬次）

### 步驟 1：建立 Worker 服務
1. 登入 [Cloudflare Dashboard](https://dash.cloudflare.com/)（若無帳號可使用 Email 免費註冊，免信用卡）。
2. 在左側主選單點擊 **「Workers & Pages」**（或「計算 (Compute) > Workers」）。
3. 點擊右上角 **「Create application」**（或 **「Create Worker」**）。
4. 服務名稱輸入：`tw-stock-bpa-router`（或任意名稱），點擊右下角 **「Deploy」**。

---

### 步驟 2：貼上智慧路由代碼
1. 建立完成後，點擊右上角的 **「Edit code」**（編輯代碼）。
2. 將左側編輯器原本的代碼全部刪除。
3. 打開專案中的 [`cloudflare_worker/worker.js`](file:///F:/stock/cloudflare_worker/worker.js)，全選複製並貼入編輯器中。
4. 點擊右上角藍色按鈕 **「Deploy」**（儲存並發布）。

---

### 步驟 3：設定後端伺服器環境變數
1. 點擊左上角返回按鈕，進入該 Worker 的管理頁面。
2. 點選 **「Settings」**（設定）分頁 ➔ 點擊左側 **「Variables」**（變數與密碼）。
3. 在 **Environment Variables** 點擊 **「Add variable」** 新增以下設定：

| 變數名稱 (Key) | 數值範例 (Value) | 說明 |
|---|---|---|
| **`RENDER_BACKEND_URL`** | `https://tw-stock-bpa-bot.onrender.com` | Render 雲端主機網址（必填主力雲端） |
| **`LOCAL_BACKEND_URL`** | `https://xxxx.trycloudflare.com` | 本地電腦穿透網址（選填，本機開機時填入） |
| **`LOCAL_TIMEOUT_MS`** | `1500` | 本機探測超時時間（預設 1500 毫秒，關機時快速切換） |

4. 點擊 **「Save and Deploy」** 儲存。

---

### 步驟 4：更新 LINE Developers Webhook URL（從此一勞永逸）
1. 在 Worker 頁面上方取得您的專屬 Worker 網址，格式為：
   ```text
   https://tw-stock-bpa-router.你的子域名.workers.dev
   ```
2. 前往 [LINE Developers Console](https://developers.line.biz/) ➔ 點入您的 Channel ➔ **Messaging API** 分頁。
3. 找到 **Webhook URL** 點擊 **Edit**，將網址改為：
   ```text
   https://tw-stock-bpa-router.你的子域名.workers.dev/callback
   ```
4. 點擊 **Update** ➔ 點擊 **Verify**（驗證顯示 **Success** ✅ 即可！）。

---

## 💻 如何啟動本地電腦作為主力加速備援？

當您在電腦前想享受本地最強算力時：
1. 在專案根目錄開啟 PowerShell。
2. 執行：
   ```powershell
   .\start_local_tunnel.ps1
   ```
3. 腳本會自動啟動本地伺服器與 Cloudflare Tunnel，並在終端機列印出臨時穿透網址（例如 `https://abc-123.trycloudflare.com`）。
4. 將該網址複製並填入 Cloudflare Worker 的 `LOCAL_BACKEND_URL` 變數中，訊息即刻由本機極速處理！
5. **電腦隨時關機也不漏訊**：一旦關機，Worker 在 1.2 秒內自動轉發給 Render 雲端！

---

## 📊 全節點即時健康儀表板

隨時用瀏覽器打開您的 Worker 網址：
```text
https://tw-stock-bpa-router.你的子域名.workers.dev/health
```
頁面將以毫秒級精度即時列出所有後端節點（本地電腦、Render 雲端、未來備援）的健康狀態與連線延遲！
