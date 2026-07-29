' iHIM Background Launcher
' Runs iHIM without a visible console window, from wherever this file lives.

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
objShell.CurrentDirectory = objFSO.GetParentFolderName(WScript.ScriptFullName)
objShell.Run "pythonw run_silent.py", 0, False
