# =====================================================================
# start_local_tunnel.ps1 - 本地電腦極速備援一鍵啟動腳本
# 啟動本機 LINE Webhook (Port 8080) 與 Cloudflare Tunnel 內網穿透
# 支援 Cloudflare API 全自動無感同步 (解法 A)
# =====================================================================

Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host "  🚀 啟動台股 BPA LINE Bot 本地極速高算力備援伺服器" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$CurrentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $CurrentDir

# 輔助函式：解析 .env 檔案
function Get-EnvMap {
    param([string]$FilePath)
    $map = @{}
    if (Test-Path $FilePath) {
        Get-Content $FilePath -Encoding UTF8 | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
                $parts = $line.Split("=", 2)
                $key = $parts[0].Trim()
                $val = $parts[1].Trim().Trim('"').Trim("'")
                $map[$key] = $val
            }
        }
    }
    return $map
}

# 1. 檢查並載入環境變數
$envMap = Get-EnvMap "$CurrentDir\.env"
if ($envMap.Count -gt 0) {
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
    Write-Host "  👉 本地公網網址: $DetectedUrl" -ForegroundColor Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray

    # 5. 嘗試透過 Cloudflare API 全自動無感同步
    $CfAccountId = $envMap["CF_ACCOUNT_ID"]
    $CfApiToken = $envMap["CF_API_TOKEN"]
    $CfWorkerName = if ($envMap["CF_WORKER_NAME"]) { $envMap["CF_WORKER_NAME"] } else { "tw-stock-bpa-router" }

    $Synced = $false
    if ($CfAccountId -and $CfApiToken) {
        Write-Host "🔄 偵測到 Cloudflare API 憑證，正在自動同步 Worker 路由..." -ForegroundColor Cyan
        $Headers = @{
            "Authorization" = "Bearer $CfApiToken"
            "Content-Type"  = "application/json"
        }
        $Body = @{
            "name" = "LOCAL_BACKEND_URL"
            "text" = $DetectedUrl
            "type" = "secret_text"
        } | ConvertTo-Json

        $ApiUrl = "https://api.cloudflare.com/client/v4/accounts/$CfAccountId/workers/scripts/$CfWorkerName/secrets"
        try {
            $Resp = Invoke-RestMethod -Uri $ApiUrl -Method Put -Headers $Headers -Body $Body -TimeoutSec 10
            if ($Resp.success) {
                $Synced = $true
                Write-Host "✨ 【全自動同步成功！】已將最新網址無感推送至 Cloudflare Worker！" -ForegroundColor Green
                Write-Host "⚡ 恭喜！現在 LINE 訊息已自動切換至您本機的強大 CPU 運算！" -ForegroundColor Green
            }
        } catch {
            Write-Host "⚠️ 自動推送至 Cloudflare 失敗: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }

    if (-not $Synced) {
        Write-Host "📋 網址已「自動複製到您的剪貼簿」！可以直接前往貼上：" -ForegroundColor Yellow
        Write-Host "   Cloudflare Dashboard ➔ Worker ($CfWorkerName) ➔ Settings ➔ Variables" -ForegroundColor Gray
        Write-Host "   將 LOCAL_BACKEND_URL 更新為: $DetectedUrl" -ForegroundColor Cyan
        Write-Host "`n💡 【升級 100% 開機全自動免手動】" -ForegroundColor White
        Write-Host "   只需在 .env 填入 CF_ACCOUNT_ID 與 CF_API_TOKEN，下次開機將全自動同步！" -ForegroundColor Gray
    }

    Write-Host "`n🛑 如需結束本地備援，請按 Ctrl + C 或直接關閉本視窗即可。" -ForegroundColor Gray
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
