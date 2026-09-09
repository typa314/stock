@echo off
cd /d "%~dp0.."
python line_server.py >> "%~dp0..\logs\local_server.log" 2>&1
