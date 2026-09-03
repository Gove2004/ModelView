' ModelView - silent launcher (no console window)
' Double-click to start the floating panels + tray.
' Uses the project virtualenv (PySide6); falls back to PATH pythonw.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base
venv = base & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(venv) Then
    sh.Run """" & venv & """ main.py", 0, False
Else
    sh.Run "pythonw.exe main.py", 0, False
End If
