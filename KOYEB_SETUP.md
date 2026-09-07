# ⚡ Koyeb 免費主力雲端部署指南 (24/7 永不休眠)

Koyeb 是目前最熱門且真正 **永久免費、24 小時不休眠 (No Spin-down)** 的無伺服器容器平台。  
部署完成後，配合新加坡節點（距離台灣僅 30ms 延遲），能提供全天候秒回的看盤體驗！

---

## 🚀 只要 3 分鐘部署至 Koyeb（完全免費、直接連動 GitHub）

### 步驟 1：登入並建立服務
1. 打開 **[https://app.koyeb.com/](https://app.koyeb.com/)**。
2. 點擊 **「Sign in with GitHub」**（直接用 GitHub 帳號免費登入，免綁信用卡）。
3. 登入後，點擊右上角按鈕 **「Create Service」**。

---

### 步驟 2：選擇儲存庫與建置設定
1. **Deployment method**：選擇 **「GitHub」**。
2. **Repository**：選擇您的儲存庫 **`typa314/stock`**（Branch 保持 `main`）。
3. **Builder**：
   * 選擇 **「Dockerfile」**（Koyeb 會自動偵測專案中的 Dockerfile）。
4. **Instance size**：
   * 選擇免費的 **「Eco / Nano」**（$0/month）。
5. **Region（地區）**：
   * 選擇 **「Singapore (sin)」**（離台灣最近，連線延遲最低）。

---

### 步驟 3：設定連接埠與 LINE 金鑰
1. 往下滑找到 **「Ports」**（連接埠設定）：
   * 將 Port 改為 **`7860`**（對應 Dockerfile 的 EXPOSE 7860，Protocol 保持 HTTP，Path 保持 `/`）。
2. 找到 **「Environment variables」**，點擊 **Add Variable** 新增 2 筆：
   * **第 1 筆**：
     * **Key**：`LINE_CHANNEL_SECRET`
     * **Value**：`b68cdc607f3e19d6992d08ab1340fe11`
   * **第 2 筆**：
     * **Key**：`LINE_CHANNEL_ACCESS_TOKEN`
     * **Value**：`U+Db0G7cpMbM96YcCSq1kg+wfEtBckpCKCAht0T2NRC4i5CZTCGEiByGYtGkRflXTDJ3JylbfUnwKrPKpp+RYhmDX899kwzWjI1713H3b7SR14XNhxGksHryQC42KB14+YSd3Jl1K0nPqY6CsvDN6wdB04t89/1O/w1cDnyilFU=`
3. 點擊最右下角的 **「Deploy」** 按鈕！

---

### 步驟 4：取得網址並填入 Cloudflare Worker（熱切換上線！）
1. 等待約 1~2 分鐘建置完成，狀態顯示為綠色 **Healthy**。
2. 在頁面上方複製您的專屬 Koyeb 公開網址，例如：
   ```text
   https://stock-bot-yourname.koyeb.app
   ```
3. 前往 **[Cloudflare Dashboard](https://dash.cloudflare.com/)** ➔ 進入 Worker (`tw-stock-bpa-router`)。
4. 點選 **Settings** ➔ **Variables** ➔ **Add variable**：
   * **Variable name**：`KOYEB_BACKEND_URL`
   * **Value**：`https://stock-bot-yourname.koyeb.app`（填入剛取得的 Koyeb 網址）
5. 點擊 **Save and deploy**！

---

### 🏆 升級後達成的超狂效果：
* **24 小時永不休眠**：Koyeb 免費實例預設不睡著，隨時傳訊息隨時秒回！
* **雙重雲端自動容錯**：
  * **主力雲端**：Koyeb（24/7 不休眠常駐）
  * **備援雲端**：Render（萬一故障自動兜底）
* **LINE 後台零改動**：Cloudflare Worker 自動優先走 Koyeb，LINE 後台完全不用重新設定！
