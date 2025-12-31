Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like "*uvicorn*" -or $_.Path -like "*IHIM*" } | Stop-Process -Force
Start-Sleep -Seconds 1
Get-Process -Id 299048 -ErrorAction SilentlyContinue | Stop-Process -Force
