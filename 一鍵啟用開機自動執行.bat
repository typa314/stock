@echo off
title Enable Autostart
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$scriptDir = (Get-Item '%~dp0').FullName.TrimEnd('\'); $WshShell = New-Object -ComObject WScript.Shell; $ShortcutPath = [System.IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Startup\TwStockBpaServer.lnk'); $Shortcut = $WshShell.CreateShortcut($ShortcutPath); $Shortcut.TargetPath = 'wscript.exe'; $Shortcut.Arguments = ('\"' + $scriptDir + '\start_silent_autostart.vbs\"'); $Shortcut.WorkingDirectory = $scriptDir; $Shortcut.Description = 'BPA Stock LINE Bot Local Server'; $Shortcut.Save(); Write-Host 'Autostart Enabled Successfully!' -ForegroundColor Green"
echo.
echo ========================================================
echo  [OK] Successfully enabled background autostart on boot!
echo  From now on, the local server will run silently in the
echo  background every time Windows starts up.
echo ========================================================
echo.
pause
