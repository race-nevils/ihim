# Trigger capture widget via iHIM API (production on 7777).
# Only works when production server is running — test servers don't interfere.
try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:7777/api/capture/trigger' -Method POST -TimeoutSec 2 | Out-Null
} catch {
    # Silent fail — widget or server not running
}
