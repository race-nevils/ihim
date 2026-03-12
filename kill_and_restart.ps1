# Kill all iHIM processes on port 7777 (including orphaned child workers)
# Uses process tree killing to catch uvicorn parent + child workers

$port = 7777

Write-Host "Finding processes on port $port..."

# Step 1: Find all PIDs listening on the port
$procs = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
    Where-Object { $_.OwningProcess -gt 0 } |
    Select-Object -ExpandProperty OwningProcess -Unique

if (-not $procs) {
    Write-Host "No processes found on port $port"
} else {
    Write-Host "Found PIDs on port $port : $($procs -join ', ')"

    # Step 2: Kill each process tree (parent + all children)
    foreach ($pid in $procs) {
        Write-Host "Killing process tree for PID $pid..."
        # Get child processes first
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $pid" -ErrorAction SilentlyContinue
        foreach ($child in $children) {
            Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "  Killed child PID $($child.ProcessId) ($($child.Name))"
        }
        # Kill parent
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Host "  Killed PID $pid"
    }
}

# Step 3: Find orphaned Python processes with IHIM in command line
$orphans = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'IHIM' -or $_.CommandLine -match 'ihim' }

foreach ($orphan in $orphans) {
    Write-Host "Killing orphaned IHIM Python process: PID $($orphan.ProcessId) - $($orphan.CommandLine)"
    Stop-Process -Id $orphan.ProcessId -Force -ErrorAction SilentlyContinue
}

# Step 4: Wait and verify
Start-Sleep -Seconds 2

$check = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
if ($check) {
    Write-Host "WARNING: Port $port still in use — retrying..."
    $remaining = $check | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($pid in $remaining) {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    $finalCheck = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($finalCheck) {
        Write-Host "ERROR: Port $port still not clear after retry"
    } else {
        Write-Host "Port $port is clear (after retry)"
    }
} else {
    Write-Host "Port $port is clear"
}
