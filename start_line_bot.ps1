# 一鍵啟動 BPA 股票 LINE Bot 與 Cloudflare 免費通道
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  🚀 啟動台股 BPA 操盤秘書 LINE Bot 服務" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 檢查 .env
if (-not (Test-Path ".env")) {
    Write-Host "❌ 找不到 .env 設定檔！請先確認金鑰設定。" -ForegroundColor Red
    Exit
}

# 1. 啟動 Webhook 服務
Write-Host "1. 正在啟動後端 Webhook 伺服器 (Port 8080)..." -ForegroundColor Yellow
$serverJob = Start-Process python -ArgumentList "line_server.py" -PassThru -NoNewWindow

Start-Sleep -Seconds 2

# 2. 啟動 Cloudflare Tunnel
Write-Host "2. 正在啟動 Cloudflare 公網加密通道..." -ForegroundColor Yellow
if (Test-Path ".\cloudflared.exe") {
    .\cloudflared.exe tunnel --url http://127.0.0.1:8080
} else {
    Write-Host "⚠️ 找不到 cloudflared.exe，請至官方下載或使用 ngrok http 8080" -ForegroundColor Red
}
