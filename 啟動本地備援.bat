@echo off
title BPA Local Server
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_local_tunnel.ps1"
pause
