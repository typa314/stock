@echo off
title BPA Local Server
cd /d "F:\stock"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "F:\stock\start_local_tunnel.ps1"
pause
