# iHIM lifecycle task installer -- run once per machine (re-run to update).
#
#   .\install-resume-watchdog.ps1            registers/updates BOTH tasks
#   .\install-resume-watchdog.ps1 -Uninstall removes both
#
# Registers two Task Scheduler tasks:
#
# 1. "iHIM Resume Watchdog" -- runs "server.ps1 start" (idempotent: healthy
#    server = no-op, dead port = fresh start) on resume-from-sleep plus an
#    hourly heartbeat that self-heals any other death cause. (A
#    workstation-unlock trigger was tried and dropped: session state-change
#    triggers require elevation to register; these two do not.)
#    Why: the server process can die during a suspend transition (2026-07-02:
#    CTranslate2 destructor raised a raw C++ exception 0xe06d7363 mid-suspend
#    and killed PID 20088). The AHK launcher only starts the server at LOGIN,
#    so on an always-on machine a sleep-death left port 7777 dead for days.
#
# 2. "iHIM Restart" -- NO triggers; fired on demand (schtasks /run) by the
#    server itself: the post-sleep CUDA-hygiene restart, the transcription
#    deadline watchdog, and /api/server/restart. The task runs
#    "server.ps1 restart" under the Task Scheduler service -- OUTSIDE the
#    server's kill tree. A child helper cannot do this job: server.ps1's
#    taskkill /T reaps its own helper (tree-kill-self), and DETACHED_PROCESS
#    powershell exits 0 without executing anything, which left both sleep
#    defenses dead for 11 days (bug note 2026-07-27_detached-process-
#    restart-spawn-dead-on-arrival-sleep-defenses.md).
#
# SILENT VIA WSCRIPT WRAPPER (2026-07-27). Task Scheduler launching
# powershell.exe (console subsystem) into the interactive session flashes a
# conhost window before -WindowStyle Hidden can apply -- the recurring
# terminal flash the operator ordered this same watchdog DELETED for on 2026-07-07
# (bug note 2026-07-07_windowstyle-hidden-ignored-console-apps-stream-
# redirection.md addendum, which also names the correct pattern). Both tasks
# now run wscript.exe (GUI subsystem, no console ever) with a generated .vbs
# that launches powershell at window style 0 and WAITS (Run arg True) so
# IgnoreNew dedupe and the execution limits stay meaningful. Wrappers are
# machine glue, generated into %USERPROFILE%\scripts\ beside
# brain-sync-native.vbs; re-running the installer regenerates them.
#
# ASCII-only on purpose: PS 5.1 misparses UTF-8-no-BOM em-dashes.

param(
    [switch]$Uninstall,
    # The LIVE 7777 server always runs from the MAIN repo, so the watchdog
    # points there no matter which branch copy of this installer runs.
    [string]$ServerPs1 = 'C:\Users\<user>\workspace\IHIM\scripts\server.ps1'
)

$ErrorActionPreference = 'Stop'
$TaskName = 'iHIM Resume Watchdog'
$RestartTaskName = 'iHIM Restart'
$WrapperDir = Join-Path $env:USERPROFILE 'scripts'
$WatchdogVbs = Join-Path $WrapperDir 'ihim-resume-watchdog.vbs'
$RestartVbs = Join-Path $WrapperDir 'ihim-restart.vbs'

if ($Uninstall) {
    foreach ($t in @($TaskName, $RestartTaskName)) {
        Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed scheduled task '$t'."
    }
    foreach ($w in @($WatchdogVbs, $RestartVbs)) {
        Remove-Item $w -Force -ErrorAction SilentlyContinue
    }
    return
}

if (-not (Test-Path $ServerPs1)) {
    throw "server.ps1 not found at $ServerPs1 -- pass -ServerPs1 with the live server's lifecycle script."
}

# Trigger 1: resume from sleep. Either wake event this machine logs:
# Power-Troubleshooter 1 or Kernel-Power 107 (verified in the System log
# during the 2026-07-02 diagnosis). 20s delay lets the network/GPU settle.
$eventClass = Get-CimClass -ClassName MSFT_TaskEventTrigger `
    -Namespace Root/Microsoft/Windows/TaskScheduler
$resumeTrigger = New-CimInstance -CimClass $eventClass -ClientOnly
$resumeTrigger.Enabled = $true
$resumeTrigger.Delay = 'PT20S'
$resumeTrigger.Subscription = '<QueryList><Query Id="0" Path="System">' +
    '<Select Path="System">*[System[' +
    "(Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1)" +
    ' or ' +
    "(Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=107)" +
    ']]</Select></Query></QueryList>'

# Trigger 2: hourly heartbeat. Idempotent start = a free self-heal for any
# death cause the resume event does not cover (crash while awake, etc.).
# 10-year duration, not [TimeSpan]::MaxValue -- MaxValue serializes to an
# out-of-range XML duration and Register-ScheduledTask rejects it.
$heartbeatTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

# Silent launchers: window style 0, wait for exit. VBS escapes " by doubling.
if (-not (Test-Path $WrapperDir)) {
    New-Item -ItemType Directory -Path $WrapperDir -Force | Out-Null
}
foreach ($pair in @(
    @{ Vbs = $WatchdogVbs; Verb = 'start' },
    @{ Vbs = $RestartVbs;  Verb = 'restart' }
)) {
    $vbs = 'Set WshShell = CreateObject("WScript.Shell")' + "`r`n" +
        'WshShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""' +
        $ServerPs1 + '"" ' + $pair.Verb + '", 0, True' + "`r`n"
    Set-Content -Path $pair.Vbs -Value $vbs -Encoding ASCII
}

$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$WatchdogVbs`""

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
    -StartWhenAvailable

# Interactive-only principal: the server belongs to the operator's session (tray,
# hotkey, GPU); no stored credentials, no elevation.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName `
    -Trigger @($resumeTrigger, $heartbeatTrigger) `
    -Action $action -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName':"
Write-Host "  on resume-from-sleep (+20s) and hourly heartbeat"
Write-Host "  -> server.ps1 start (idempotent) using $ServerPs1"

# --- "iHIM Restart": demand-only, fired by the server via schtasks /run ---
$restartAction = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$RestartVbs`""

# 40-minute limit: restart defers behind a live dictation
# (Wait-DictationIdle, max 30 min) before it may act.
# MultipleInstances IgnoreNew makes stacked triggers (two blown deadlines,
# resume events 18 then 7) collapse into one restart at the OS.
$restartSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 40) `
    -StartWhenAvailable

Register-ScheduledTask -TaskName $RestartTaskName `
    -Action $restartAction -Settings $restartSettings -Principal $principal -Force | Out-Null

Write-Host "Registered scheduled task '$RestartTaskName':"
Write-Host "  demand-only (schtasks /run) -> server.ps1 restart using $ServerPs1"
Write-Host "Verify anytime: Get-ScheduledTask -TaskName 'iHIM *'"
