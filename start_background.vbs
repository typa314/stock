Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "F:\stock"
WshShell.Run "cmd.exe /c """"C:\Users\typa3\AppData\Local\Programs\Python\Python39\python.exe"" line_server.py >> ""F:\stock\logs\local_server.log"" 2>&1""", 0, False
