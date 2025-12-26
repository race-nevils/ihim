' iHIM Background Launcher
' Runs iHIM without a visible console window

Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "C:\Users\<user>\workspace\IHIM"
objShell.Run "pythonw run_silent.py", 0, False
