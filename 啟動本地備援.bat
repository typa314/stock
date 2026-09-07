@echo off
chcp 65001 > nul
title 台股 BPA LINE Bot 本地高算力備援伺服器
cd /d "F:\stock"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "F:\stock\start_local_tunnel.ps1"
pause
