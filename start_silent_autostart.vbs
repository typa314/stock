Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "F:\stock"
WshShell.Run "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""F:\stock\start_local_tunnel.ps1""", 0, False
