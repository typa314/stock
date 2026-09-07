# 🤗 Hugging Face Spaces 旗艦主力雲端部署指南 (2核16G ⚡ 48小時免休眠)

本指南將引導您將台股 BPA LINE Bot 部署至 **Hugging Face Spaces**。  
部署完成後，您將享有伺服器級的 **2 顆 vCPU + 16GB 記憶體**，徹底解決延遲與休眠問題，並與現有的 **Cloudflare Worker 智慧路由器** 無縫對接！

---

## 🚀 只要 4 步完成旗艦雲端部署（永久免費）

### 步驟 1：在 Hugging Face 建立新 Space
1. 前往 **[Hugging Face Spaces](https://huggingface.co/spaces)**（若無帳號可點右上角 Sign Up 免費註冊，亦可直接使用 GitHub 帳號登入）。
2. 點擊右上角頭像 ➔ 選擇 **「New Space」**。
3. 填寫設定：
   * **Space name**：`stock-bot`（或任意名稱）
   * **License**：選 `mit`（或保持預設）
   * **Select the Space SDK**：務必選擇 **「Docker」** ➔ 選擇 **「Blank」**！
   * **Space Hardware**：保持預設免費的 **「CPU basic · 2 vCPU · 16 GB · Free」**！
   * **Privacy**：選擇 **「Public」**（以便接收 LINE 官方 Webhook）。
4. 點擊最下方按鈕 **「Create Space」**。

---

### 步驟 2：設定 LINE 金鑰（Secrets，外人完全看不到）
1. 建立完成後，點擊該 Space 頁面右上方的 **「Settings」** 分頁。
2. 往下滑找到 **「Variables and secrets」** 區塊。
3. 點擊 **「New secret」** 按鈕，新增以下 2 筆密鑰：
   * **第 1 筆 Secret**：
     * **Name**：`LINE_CHANNEL_SECRET`
     * **Value**：`b68cdc607f3e19d6992d08ab1340fe11`
   * **第 2 筆 Secret**：
     * **Name**：`LINE_CHANNEL_ACCESS_TOKEN`
     * **Value**：`U+Db0G7cpMbM96YcCSq1kg+wfEtBckpCKCAht0T2NRC4i5CZTCGEiByGYtGkRflXTDJ3JylbfUnwKrPKpp+RYhmDX899kwzWjI1713H3b7SR14XNhxGksHryQC42KB14+YSd3Jl1K0nPqY6CsvDN6wdB04t89/1O/w1cDnyilFU=`

---

### 步驟 3：推送程式碼到 Hugging Face Space
在您電腦上的專案目錄打開 PowerShell，執行以下指令（將代碼推送到 Space）：

```powershell
# 1. 新增 Hugging Face Space 的 Git 遠端（請替換為您剛建立的 Space 網址）
# 例如: git remote add hf https://huggingface.co/spaces/你的HF帳號名稱/stock-bot
git remote add hf https://huggingface.co/spaces/YOUR_USERNAME/stock-bot

# 2. 推送代碼上線（推送時會要求輸入 Hugging Face 帳號與 Access Token）
git push hf main --force
```

> [!TIP]
> **如何取得 Hugging Face Access Token？**
> 點擊右上角頭像 ➔ Settings ➔ **Access Tokens** ➔ **Create new token**（Type 選擇 **Write**），複製 Token 作為密碼即可。

---

### 步驟 4：取得公開網址並填入 Cloudflare Worker（熱切換上線！）

1. 代碼推送後，Hugging Face 會在 1~2 分鐘內自動完成 Docker 建置（狀態顯示為綠色 **Running** 🎉）。
2. 取得您的專屬公網網址：
   * 格式為：`https://你的HF帳號-stock-bot.hf.space`
   * （亦可在 Space 頁面右上角點擊三個點 `...` ➔ **「Embed this Space」** 複製 Direct URL）。
3. 前往 **[Cloudflare Dashboard](https://dash.cloudflare.com/)** ➔ 進入您的 Worker (`tw-stock-bpa-router`)。
4. 點選 **Settings** ➔ **Variables** ➔ 點擊 **Add variable**：
   * **Variable name**：`HF_BACKEND_URL`
   * **Value**：`https://你的HF帳號-stock-bot.hf.space`
5. 點擊 **Save and deploy**！

---

### 🏆 升級完成！您擁有了：
* **0.8 秒以內的狂暴運算速度**（2 顆伺服器級 CPU 加持）。
* **48 小時超長免休眠**（平常看盤再也不會遇到 40 秒冷啟動等待）。
* **三重熱備援機制**：
  `本地電腦 (盤中開機滿血加速) ➔ Hugging Face (2核16G 旗艦主力) ➔ Render (留守備援)`
* **LINE 後台零改動**：Cloudflare 自動將所有流量切向 Hugging Face！
