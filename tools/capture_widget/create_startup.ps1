$WshShell = New-Object -ComObject WScript.Shell
$StartupPath = [Environment]::GetFolderPath('Startup')
$Shortcut = $WshShell.CreateShortcut("$StartupPath\BlockAltSpace.lnk")
$Shortcut.TargetPath = "C:\Users\<user>\workspace\IHIM\tools\capture_widget\block_alt_space.ahk"
$Shortcut.Save()
Write-Host "Startup shortcut created at: $StartupPath\BlockAltSpace.lnk"
