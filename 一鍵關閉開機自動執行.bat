@echo off
title Disable Autostart
cd /d "F:\stock"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ShortcutPath = [System.IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Startup\TwStockBpaServer.lnk'); if (Test-Path $ShortcutPath) { Remove-Item $ShortcutPath -Force; Write-Host 'Autostart Disabled Successfully!' -ForegroundColor Yellow } else { Write-Host 'Autostart is not enabled.' -ForegroundColor Gray }"
echo.
echo ========================================================
echo  [OK] Autostart shortcut removed from Startup folder.
echo ========================================================
echo.
pause
