# Kill all processes on port 7777
$procs = Get-NetTCPConnection -LocalPort 7777 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $procs) {
    if ($procId -gt 0) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}
Write-Host "Killed processes: $procs"

# Clear pycache
Remove-Item -Path "C:\Users\<user>\workspace\IHIM\api\system\__pycache__\*.pyc" -Force -ErrorAction SilentlyContinue

# Wait for port to clear
Start-Sleep -Seconds 2

# Verify port is clear
$check = Get-NetTCPConnection -LocalPort 7777 -ErrorAction SilentlyContinue
if ($check) {
    Write-Host "WARNING: Port 7777 still in use"
} else {
    Write-Host "Port 7777 is clear"
}
