@echo off
title Stop Local Server
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& { Write-Host 'Stopping local BPA Stock server and Cloudflare Tunnel...' -ForegroundColor Yellow; Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; Write-Host 'Successfully stopped all local processes!' -ForegroundColor Green }"
echo.
echo ========================================================
echo  [OK] Local server and tunnel have been stopped.
echo  Cloudflare Worker will now automatically route all
echo  traffic to Render Cloud!
echo ========================================================
echo.
pause
