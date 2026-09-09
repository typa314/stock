Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
rootDir = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
WshShell.CurrentDirectory = rootDir
WshShell.Run "cmd.exe /c ""python -m uvicorn line_server:app --host 0.0.0.0 --port 8080 >> """ & rootDir & "\logs\local_server.log"" 2>&1""", 0, False
