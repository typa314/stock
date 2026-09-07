# =====================================================================
# start_local_tunnel.ps1 - 本地電腦極速備援一鍵啟動腳本
# 啟動本機 LINE Webhook (Port 8080) 與 Cloudflare Tunnel 內網穿透
# =====================================================================

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "🚀 啟動台股 BPA LINE Bot 本地高算力備援伺服器" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$CurrentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $CurrentDir

# 1. 檢查並載入環境變數
if (Test-Path "$CurrentDir\.env") {
    Write-Host "✅ 已載入本地 .env 金鑰設定檔" -ForegroundColor Green
} else {
    Write-Host "⚠️ 未偵測到 .env，請確認已設定 LINE 金鑰" -ForegroundColor Yellow
}

# 2. 檢查 Cloudflared 工具
$CloudflaredBin = "cloudflared"
$HasCloudflared = Get-Command "cloudflared" -ErrorAction SilentlyContinue

if (-not $HasCloudflared) {
    $BinDir = "$CurrentDir\bin"
    if (-not (Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir -Force | Out-Null }
    $LocalCloudflared = "$BinDir\cloudflared.exe"

    if (Test-Path $LocalCloudflared) {
        $CloudflaredBin = $LocalCloudflared
        Write-Host "✅ 使用本地免安裝版 cloudflared ($CloudflaredBin)" -ForegroundColor Green
    } else {
        Write-Host "📥 正在自動下載官方 Cloudflare Tunnel 工具 (約 15MB)..." -ForegroundColor Yellow
        $DownloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $DownloadUrl -OutFile $LocalCloudflared -UseBasicParsing
            $CloudflaredBin = $LocalCloudflared
            Write-Host "✅ Cloudflare Tunnel 下載完成！" -ForegroundColor Green
        } catch {
            Write-Host "❌ 自動下載失敗，請手動安裝: winget install Cloudflare.cloudflared" -ForegroundColor Red
        }
    }
} else {
    Write-Host "✅ 系統已安裝 Cloudflare Tunnel (cloudflared)" -ForegroundColor Green
}

# 3. 啟動本機 LINE Webhook Server (Port 8080) 在背景視窗
Write-Host "`n🔌 [1/2] 正在啟動本地 Webhook 服務 (Port 8080)..." -ForegroundColor Cyan
$ServerProcess = Start-Process python -ArgumentList "-m uvicorn line_server:app --host 127.0.0.1 --port 8080" -PassThru

Start-Sleep -Seconds 2
try {
    $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/health" -TimeoutSec 3 -ErrorAction Stop
    Write-Host "✅ 本地伺服器已成功運行！狀態: $($Health.status)" -ForegroundColor Green
} catch {
    Write-Host "⚠️ 本地伺服器啟動中，稍後將完成加載..." -ForegroundColor Yellow
}

# 4. 啟動 Cloudflare Tunnel
Write-Host "`n🌐 [2/2] 正在建立 Cloudflare 穿透通道 (Quick Tunnel)..." -ForegroundColor Cyan
Write-Host "💡 稍後畫面出現的「https://xxxx.trycloudflare.com」即為您本機的專屬穿透網址！" -ForegroundColor Yellow
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
Write-Host "👉 請將該網址複製並填入 Cloudflare Worker 的 LOCAL_BACKEND_URL 變數中！" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`n" -ForegroundColor Gray

try {
    & $CloudflaredBin tunnel --url http://127.0.0.1:8080
} finally {
    Write-Host "`n🛑 正在關閉本地服務..." -ForegroundColor Red
    if ($ServerProcess -and -not $ServerProcess.HasExited) {
        Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "👋 本地備援服務已安全停止。" -ForegroundColor Gray
}
