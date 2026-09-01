' LLM Proxy Tool - silent launcher (no console window)
' Double-click this file to start the app in the system tray.
' Requires Python with tkinter; pythonw.exe must be on PATH.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "pythonw.exe main.py", 0, False
