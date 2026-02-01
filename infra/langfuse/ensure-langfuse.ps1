# ensure-langfuse.ps1
# Called by ihim-master.ahk at login. Waits for Docker Desktop,
# then brings up Langfuse containers. Runs hidden, no user interaction.

$composeFile = "C:\Users\<user>\workspace\IHIM\infra\langfuse\docker-compose.yml"
$maxAttempts = 60   # 60 x 5s = 5 minutes max wait
$sleepSeconds = 5

for ($i = 0; $i -lt $maxAttempts; $i++) {
    try {
        $result = docker info 2>&1
        if ($LASTEXITCODE -eq 0) {
            docker compose -f $composeFile up -d 2>&1 | Out-Null
            exit 0
        }
    } catch {}
    Start-Sleep -Seconds $sleepSeconds
}

# Docker never became ready within timeout - exit silently
exit 1
