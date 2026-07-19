# iHIM server lifecycle -- the ONLY sanctioned start/stop/restart tool.
#
#   .\server.ps1 start   [-Port 7777] [-Dev]
#   .\server.ps1 stop    [-Port 7777]
#   .\server.ps1 restart [-Port 7777] [-DelaySeconds 1]
#   .\server.ps1 status  [-Port 7777]
#
# Design (replaces supervisor.py + kill_server.ps1 + kill_and_restart.ps1 +
# force_kill.ps1 + the WMIC temp-script restart endpoint):
#   - The server runs WITHOUT a reloader, so the port listener is the one and
#     only process; taskkill /T on it also reaps transcription worker children.
#   - Kill only verified iHIM processes (python + run.py/run_silent/api.main
#     in the command line). A foreign port squatter is reported, never killed.
#   - start is idempotent: if a healthy iHIM instance already listens, report
#     and exit 0 -- no duplicate servers.

param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status')]
    [string]$Action = 'status',
    [int]$Port = 7777,
    [int]$DelaySeconds = 0,
    [switch]$Dev
)

$ErrorActionPreference = 'Stop'
$IhimDir = Split-Path -Parent $PSScriptRoot
$LogPath = Join-Path $IhimDir 'data\server-lifecycle.log'
$PidPath = Join-Path $IhimDir 'data\server.pid'

# Write-Host, NOT Write-Output: log lines must never pollute function
# return values (an emitted string makes `if (-not (Invoke-Start))` always
# see a truthy array and breaks exit codes).
function Write-Log([string]$msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [$Action :$Port] $msg"
    Write-Host $line
    try { Add-Content -Path $LogPath -Value $line } catch {}
}

# python.exe (console subsystem, started hidden with output redirected to
# data\server-console.log) rather than pythonw.exe: pythonw has no stderr,
# which makes startup crashes invisible and can break libraries that write
# to sys.stderr (None under pythonw).
function Get-PythonExe {
    foreach ($candidate in @(
            (Join-Path $IhimDir '.venv\Scripts\python.exe'),
            'C:\Users\<user>\workspace\IHIM\.venv\Scripts\python.exe'
        )) {
        if (Test-Path $candidate) { return $candidate }
    }
    throw "No iHIM venv python found (looked in $IhimDir\.venv and main repo .venv)"
}

function Get-ListenerPids {
    try {
        @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Where-Object { $_.OwningProcess -gt 0 } |
            Select-Object -ExpandProperty OwningProcess -Unique)
    } catch { @() }
}

function Test-IsIhimProcess([int]$ProcessId) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    if ($proc.Name -notmatch 'python') { return $false }
    return ($proc.CommandLine -match 'run\.py|run_silent\.py|api\.main|uvicorn')
}

function Get-HealthStatus {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3
        return ($resp.Content | ConvertFrom-Json)
    } catch { return $null }
}

# A restart must never kill a live dictation: the recording buffer lives in
# RAM and an external kill takes it with the process (lost ~6 min of speech
# 2026-07-18 when the port hook restarted mid-dictation). Restart defers
# while stt is recording / locked / processing; an unreachable endpoint or
# a non-busy status proceeds immediately. Explicit 'stop' obeys at once.
function Get-STTStatus {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/stt/status" -UseBasicParsing -TimeoutSec 3
        return ($resp.Content | ConvertFrom-Json).status
    } catch { return $null }
}

function Wait-DictationIdle {
    $busy = @('recording', 'locked', 'processing')
    $status = Get-STTStatus
    if ($null -eq $status -or $busy -notcontains $status) { return }
    Write-Log "Dictation in progress ($status) -- deferring restart until idle (max 30 min)."
    $deadline = (Get-Date).AddMinutes(30)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $status = Get-STTStatus
        if ($null -eq $status -or $busy -notcontains $status) {
            Write-Log 'Dictation finished -- proceeding with restart.'
            return
        }
    }
    Write-Log 'WARNING: dictation still busy after 30 min -- restarting anyway.'
}

function Invoke-Stop {
    $procIds = Get-ListenerPids
    if ($procIds.Count -eq 0) {
        Write-Log 'Port already clear.'
    } else {
        foreach ($procId in $procIds) {
            if (Test-IsIhimProcess $procId) {
                Write-Log "Killing iHIM process tree PID $procId"
                & taskkill /T /F /PID $procId 2>&1 | ForEach-Object { Write-Log "  $_" }
            } else {
                $name = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName
                Write-Log "REFUSING to kill PID $procId ($name) -- not an iHIM python process."
            }
        }
        # Wait for the port to clear (up to ~5s)
        for ($i = 0; $i -lt 10; $i++) {
            Start-Sleep -Milliseconds 500
            if ((Get-ListenerPids).Count -eq 0) { break }
        }
        if ((Get-ListenerPids).Count -gt 0) {
            Write-Log 'WARNING: port still held after kill.'
            return $false
        }
        Write-Log 'Port clear.'
    }
    # Remove a stale pid file if its process is gone
    if (Test-Path $PidPath) {
        try {
            $info = Get-Content $PidPath -Raw | ConvertFrom-Json
            if (-not (Get-Process -Id $info.pid -ErrorAction SilentlyContinue)) {
                Remove-Item $PidPath -Force -Confirm:$false
                Write-Log 'Removed stale pid file.'
            }
        } catch {}
    }
    return $true
}

function Invoke-Start {
    $existing = Get-ListenerPids
    if ($existing.Count -gt 0) {
        $health = Get-HealthStatus
        if ($health) {
            Write-Log "Already running and healthy (PID $($health.pid)). Nothing to do."
            return $true
        }
        Write-Log "Port $Port held but unhealthy -- stopping first."
        if (-not (Invoke-Stop)) { return $false }
    }
    $py = Get-PythonExe
    $argList = @("`"$(Join-Path $IhimDir 'run.py')`"", '--port', $Port, '--log-level', 'error')
    if ($Dev) { $argList += '--dev' }
    $consoleLog = Join-Path $IhimDir 'data\server-console.log'
    Write-Log "Starting: $py run.py --port $Port$(if ($Dev) { ' --dev' }) (console -> $consoleLog)"
    $proc = Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory $IhimDir `
        -WindowStyle Hidden -PassThru -RedirectStandardError $consoleLog `
        -RedirectStandardOutput ($consoleLog -replace '\.log$', '.out.log')
    # Health-check loop (up to ~60s -- a cold first boot imports faster-whisper etc.)
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Milliseconds 500
        if ($proc.HasExited) {
            Write-Log "ERROR: server process exited code $($proc.ExitCode) during startup. Last stderr:"
            Get-Content $consoleLog -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Write-Log "  $_" }
            return $false
        }
        $health = Get-HealthStatus
        if ($health) {
            Write-Log "Healthy. PID $($health.pid), uptime $($health.uptime_seconds)s."
            return $true
        }
    }
    Write-Log 'ERROR: server did not become healthy within 60s. Last stderr:'
    Get-Content $consoleLog -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Write-Log "  $_" }
    return $false
}

if ($DelaySeconds -gt 0) { Start-Sleep -Seconds $DelaySeconds }

switch ($Action) {
    'status' {
        $procIds = Get-ListenerPids
        if ($procIds.Count -eq 0) {
            Write-Log 'Not running (no listener).'
            exit 1
        }
        foreach ($procId in $procIds) {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $procId" -ErrorAction SilentlyContinue
            Write-Log "Listener PID ${procId}: $($proc.CommandLine)"
        }
        $health = Get-HealthStatus
        if ($health) {
            Write-Log "Health: ok, uptime $($health.uptime_seconds)s, mem $($health.memory_mb)MB"
        } else {
            Write-Log 'Health: NOT RESPONDING'
            exit 2
        }
    }
    'stop'    { if (-not (Invoke-Stop)) { exit 1 } }
    'start'   { if (-not (Invoke-Start)) { exit 1 } }
    'restart' {
        Wait-DictationIdle
        if (-not (Invoke-Stop)) { exit 1 }
        if (-not (Invoke-Start)) { exit 1 }
    }
}

