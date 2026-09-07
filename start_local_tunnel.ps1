# =====================================================================
# start_local_tunnel.ps1 - 本地電腦極速備援一鍵啟動腳本
# 啟動本機 LINE Webhook (Port 8080) 與 Cloudflare Tunnel 內網穿透
# =====================================================================

Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host "  🚀 啟動台股 BPA LINE Bot 本地極速高算力備援伺服器" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$CurrentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $CurrentDir

# 1. 檢查並載入環境變數
if (Test-Path "$CurrentDir\.env") {
    Write-Host "✅ 已載入本地 .env 金鑰設定檔" -ForegroundColor Green
} else {
    Write-Host "⚠️ 未偵測到 .env，請確認已設定 LINE 金鑰" -ForegroundColor Yellow
}

# 2. 檢查 Cloudflared 工具路徑
$CloudflaredBin = "cloudflared"
$HasCloudflared = Get-Command "cloudflared" -ErrorAction SilentlyContinue

if (-not $HasCloudflared) {
    if (Test-Path "C:\Program Files (x86)\cloudflared\cloudflared.exe") {
        $CloudflaredBin = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
        Write-Host "✅ 找到系統安裝版 cloudflared" -ForegroundColor Green
    } else {
        Write-Host "❌ 未偵測到 cloudflared，請確認已安裝 Cloudflare Tunnel" -ForegroundColor Red
        Exit
    }
} else {
    Write-Host "✅ 系統已就緒 Cloudflare Tunnel (cloudflared)" -ForegroundColor Green
}

# 3. 啟動本機 LINE Webhook Server (Port 8080)
Write-Host "`n🔌 [1/2] 正在啟動本地 Webhook 服務 (Port 8080)..." -ForegroundColor Cyan
$ServerProcess = Start-Process python -ArgumentList "-m uvicorn line_server:app --host 127.0.0.1 --port 8080" -PassThru -WindowStyle Hidden

Start-Sleep -Seconds 2
try {
    $Health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/health" -TimeoutSec 3 -ErrorAction Stop
    Write-Host "✅ 本地伺服器已成功運行！狀態: $($Health.status)" -ForegroundColor Green
} catch {
    Write-Host "⚠️ 本地伺服器啟動中，稍後將完成加載..." -ForegroundColor Yellow
}

# 4. 啟動 Cloudflare Tunnel 並自動擷取穿透網址
Write-Host "`n🌐 [2/2] 正在建立 Cloudflare 穿透通道 (Quick Tunnel)..." -ForegroundColor Cyan

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $CloudflaredBin
$psi.Arguments = "tunnel --url http://127.0.0.1:8080"
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true

$TunnelProcess = [System.Diagnostics.Process]::Start($psi)

$DetectedUrl = ""
$MaxWaitSec = 20
$StartTime = Get-Date

while (-not $TunnelProcess.HasExited -and -not $DetectedUrl) {
    $line = $TunnelProcess.StandardError.ReadLine()
    if ($line -and $line -match "https://[a-zA-Z0-9-]+\.trycloudflare\.com") {
        $DetectedUrl = $matches[0]
        break
    }
    if ((Get-Date) - $StartTime -gt (New-TimeSpan -Seconds $MaxWaitSec)) {
        break
    }
}

if ($DetectedUrl) {
    # 自動複製到剪貼簿
    Set-Clipboard -Value $DetectedUrl

    Write-Host "`n🎉 【本地穿透通道已成功建立！】" -ForegroundColor Green
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
    Write-Host "  👉 您的本地專屬公網網址：" -ForegroundColor Yellow
    Write-Host "     $DetectedUrl" -ForegroundColor Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
    Write-Host "📋 網址已「自動複製到您的剪貼簿」！可以直接去貼上！" -ForegroundColor Green
    Write-Host "`n💡 只要最後一步：" -ForegroundColor Yellow
    Write-Host "   前往 Cloudflare Dashboard ➔ Worker (tw-stock-bpa-router)" -ForegroundColor White
    Write-Host "   ➔ Settings ➔ Variables ➔ 加入變數：" -ForegroundColor White
    Write-Host "     Key  : LOCAL_BACKEND_URL" -ForegroundColor Cyan
    Write-Host "     Value: $DetectedUrl" -ForegroundColor Cyan
    Write-Host "   ➔ 點擊 Save and deploy！" -ForegroundColor White
    Write-Host "`n⚡ 完成後，LINE 訊息將優先由您的電腦 CPU 滿血秒回！" -ForegroundColor Green
    Write-Host "🛑 如需結束本地備援，請隨時在此視窗按 Ctrl + C 或關閉本視窗即可。" -ForegroundColor Gray
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`n" -ForegroundColor Gray

    # 保持穿透執行，並監聽關閉事件
    try {
        $TunnelProcess.WaitForExit()
    } finally {
        Write-Host "`n🛑 正在關閉本地服務與穿透通道..." -ForegroundColor Red
        if ($ServerProcess -and -not $ServerProcess.HasExited) {
            Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
        }
        if ($TunnelProcess -and -not $TunnelProcess.HasExited) {
            Stop-Process -Id $TunnelProcess.Id -Force -ErrorAction SilentlyContinue
        }
        Write-Host "👋 本地備援服務已安全停止。" -ForegroundColor Gray
    }
} else {
    Write-Host "❌ 未能在 $MaxWaitSec 秒內取得 Cloudflare Tunnel 網址。" -ForegroundColor Red
    if ($ServerProcess -and -not $ServerProcess.HasExited) {
        Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($TunnelProcess -and -not $TunnelProcess.HasExited) {
        Stop-Process -Id $TunnelProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
