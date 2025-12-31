# SYNCTHING_SYSTEM.md

Syncthing file synchronization substrate documentation. Real-time monitoring, conflict patterns, version management.

Updated: 2025-12-28

---

## Quick Reference

| Component | Location | Purpose |
|-----------|----------|---------|
| `.stfolder` | Root of sync folder | Folder marker, contains folderID |
| `.stignore` | Per-folder | Gitignore-style exclusion patterns |
| `.stversions` | Root of sync folder | Version history storage |
| Conflict files | Inline with originals | `file.sync-conflict-DATE-TIME.ext` |
| Sync status | Syncthing UI (port 8384) | Real-time device/folder state |

---

## 1. SYSTEM OVERVIEW

### Purpose

Syncthing provides decentralized, peer-to-peer file synchronization across devices:
- **No central server**: Direct device-to-device sync
- **Version history**: Automatic `.stversions` backup before overwrites
- **Conflict resolution**: Preserves both versions when simultaneous edits occur
- **Selective sync**: `.stignore` patterns exclude platform-specific files

### workspace Configuration

Current setup (as of 2025-12-24):
```
Folder ID: workspace
Location: C:\Users\<user>\workspace
Created: 2025-12-24T21:47:55-06:00
Marker: .stfolder/syncthing-folder-108c8f.txt
```

---

## 2. COMPONENTS

### .stfolder (Folder Marker)

**Location**: `C:\Users\<user>\workspace\.stfolder\`

**Purpose**:
- Identifies directory as Syncthing-managed
- Contains folder metadata
- DO NOT DELETE - breaks sync relationship

**Contents**:
```
syncthing-folder-108c8f.txt
  ├── folderID: workspace
  └── created: 2025-12-24T21:47:55-06:00
```

**Health Indicator**:
- Present = Folder recognized by Syncthing
- Missing = Sync broken, requires re-connection

---

### .stignore (Exclusion Rules)

**Location**: `C:\Users\<user>\workspace\IHIM\.stignore`

**Purpose**: Prevent platform-specific or generated files from syncing

**Current Rules**:
```
.venv          // Python virtual environments
__pycache__    // Python bytecode cache
*.pyc          // Compiled Python files
.DS_Store      // macOS metadata
```

**Syntax** (Gitignore-style):
```
pattern         // Exact match
*.ext           // Wildcard (any prefix)
**/folder       // Any depth
!exception      // Negation (include despite prior exclusion)
(?i)case        // Case-insensitive prefix
```

**Common Patterns to Add**:
```
node_modules    // JavaScript dependencies
.vscode         // Editor settings (personal prefs)
*.log           // Log files
.env            // Secrets (CRITICAL - never sync)
dist/           // Build artifacts
target/         // Compiled output
```

**Health Indicator**:
- Properly configured = No OS-specific files syncing
- Drift detected = Syncing `.pyc`, `.DS_Store`, etc. unnecessarily

---

### .stversions (Version History)

**Location**: `C:\Users\<user>\workspace\.stversions\`

**Purpose**: Automatic versioning before file overwrites

**Structure**:
```
.stversions/
├── MEMORY_ARCHIVE~20251225-141756.md
└── MEMORY~20251225-141716.md
```

**Versioning Strategy**:
- **Simple Versioning** (default): Keep N versions, delete oldest
- **Trashcan**: Keep versions until age threshold
- **Staggered**: Keep 30 days hourly, 365 days daily, etc.
- **External**: Custom versioning command

**Version Naming**:
```
original.ext → .stversions/original~YYYYMMDD-HHMMSS.ext
```

**Health Indicators**:
| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Version count per file | 1-5 | 6-20 | 21+ |
| Total .stversions size | <10% sync folder | 10-30% | >30% |
| Oldest version age | <30 days | 30-90 days | >90 days |

**Degradation Pattern**:
1. Frequent overwrites generate many versions
2. `.stversions` grows large (disk space concern)
3. Performance degradation during sync
4. Recovery: Prune old versions or adjust strategy

---

### Sync Conflicts

**Location**: Inline with original file

**Naming Pattern**:
```
file.sync-conflict-YYYYMMDD-HHMMSS.ext
```

**Example**:
```
MEMORY.md
MEMORY.sync-conflict-20251228-143022.md  // Device A's version
```

**Conflict Trigger Conditions**:
1. Two devices edit same file simultaneously
2. Both edits complete before sync detects changes
3. Syncthing cannot auto-merge (non-text or unsafe)

**Resolution Workflow**:
```
1. Detect conflict file appears
2. Compare original vs conflict (diff tool)
3. Manually merge desired changes
4. Delete conflict file once resolved
5. Verify sync propagates merged version
```

**Health Indicators**:
| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Active conflicts | 0 | 1-3 | 4+ |
| Conflict age | N/A | <24h | >24h unresolved |
| Conflict frequency | 0/week | 1-2/week | Daily |

**Common Causes**:
- Editing same file on laptop + desktop before sync
- Network interruption during edit session
- Large files with simultaneous multi-device edits

---

## 3. SYNC FLOW

### Normal Sync Cycle

```
Device A: File modified
    ↓
Syncthing detects change (inotify/polling)
    ↓
Hash delta calculated (block-level diff)
    ↓
Changed blocks transmitted to Device B
    ↓
Device B: Original moved to .stversions
    ↓
Device B: New version assembled from blocks
    ↓
Device B: Filesystem updated
    ↓
Sync complete notification
```

### Conflict Sync Cycle

```
Device A: File modified (version 1)
Device B: Same file modified (version 2)
    ↓
Both devices sync at same time
    ↓
Syncthing detects simultaneous modification
    ↓
Device A: Keeps local version (winner by device ID sort)
Device B: Renames incoming to .sync-conflict-*
    ↓
Both devices now have:
  - file.ext (one version)
  - file.sync-conflict-*.ext (other version)
    ↓
Manual resolution required
```

### Versioning Trigger

```
Remote device sends updated file
    ↓
Local Syncthing checks: Does local file exist?
    ↓
YES: Move current local to .stversions/file~TIMESTAMP.ext
    ↓
Accept incoming file
    ↓
Filesystem write completes
```

---

## 4. HEALTH METRICS

### Primary Metrics

| Metric | Calculation | Target | Alert Threshold |
|--------|-------------|--------|-----------------|
| **Sync Status** | % folders "Up to Date" | 100% | <100% for >5 min |
| **Last Sync Time** | Time since last successful sync | <5 min | >15 min |
| **Conflict Count** | Active `.sync-conflict-*` files | 0 | ≥1 |
| **Version Depth** | Avg versions per file in `.stversions` | 1-3 | >10 |
| **Version Size Ratio** | `.stversions` size / total folder size | <5% | >20% |
| **Ignored File Drift** | Sync'd files matching `.stignore` patterns | 0 | ≥1 |
| **Out of Sync Items** | Files in "Syncing" state | 0 | >0 for >5 min |

### Secondary Metrics

| Metric | Source | Purpose |
|--------|--------|---------|
| Connection state | Syncthing API `/rest/system/connections` | Device reachability |
| Global/local file counts | Syncthing API `/rest/db/status` | Folder health |
| Scan progress | Syncthing UI | Active sync operations |
| Bandwidth usage | OS network stats | Performance monitoring |

### Data Sources

**Syncthing REST API** (http://localhost:8384):
```
GET /rest/system/status          → Overall system state
GET /rest/db/status?folder=workspace   → Folder sync status
GET /rest/system/connections     → Device connectivity
GET /rest/system/config          → Configuration (includes .stignore)
GET /rest/events                 → Real-time event stream
```

**Filesystem Inspection**:
```bash
# Conflict count
find /path/to/workspace -name "*.sync-conflict-*" | wc -l

# Version depth (top 10 most-versioned files)
find .stversions -type f | sed 's/~[0-9-]*\./\./' | uniq -c | sort -rn | head -10

# Total version storage
du -sh .stversions

# Last sync time (newest file modification)
find . -type f -not -path "./.stversions/*" -printf '%T@ %p\n' | sort -n | tail -1
```

---

## 5. DEGRADATION PATTERNS

### Pattern 1: Sync Lag (Devices Out of Sync)

**Symptoms**:
- "Out of Sync" status persists >5 minutes
- Files modified locally not appearing on remote devices
- Global items count > local items count

**Common Causes**:
```
1. Network connectivity issues
2. Device offline/suspended
3. Syncthing process crashed
4. Disk full on receiving device
5. File permissions preventing write
```

**Diagnostic Steps**:
```bash
# Check Syncthing process
ps aux | grep syncthing

# Check connectivity to remote device
curl http://localhost:8384/rest/system/connections | jq

# Check folder status
curl http://localhost:8384/rest/db/status?folder=workspace | jq

# Check system errors
curl http://localhost:8384/rest/system/errors | jq
```

**Recovery**: See Section 6 (Recovery Procedures)

---

### Pattern 2: Conflict Accumulation

**Symptoms**:
- Multiple `.sync-conflict-*` files appearing
- Same file conflicting repeatedly
- Conflicts not being manually resolved

**Common Causes**:
```
1. Editing same file on multiple devices without waiting for sync
2. Unreliable network causing frequent disconnections
3. Clock skew between devices (timestamp issues)
4. Automated processes modifying files on multiple devices
```

**Diagnostic Steps**:
```bash
# List all conflicts
find . -name "*.sync-conflict-*" -ls

# Check conflict age
find . -name "*.sync-conflict-*" -mtime +1  # >1 day old

# Identify repeat offenders
find . -name "*.sync-conflict-*" | sed 's/\.sync-conflict-[0-9-]*\././' | uniq -c | sort -rn
```

**Preventative Measures**:
```
1. Implement file locking for critical files
2. Use .stignore for rapidly-changing generated files
3. Coordinate edits (e.g., "I'm editing MEMORY.md now")
4. Increase sync interval to reduce race conditions
```

---

### Pattern 3: Version Bloat

**Symptoms**:
- `.stversions` folder growing rapidly
- Disk space warnings
- Slow sync performance

**Common Causes**:
```
1. Frequent file modifications (e.g., logs, databases)
2. Large binary files being versioned
3. Overly generous versioning policy (keep all versions)
4. No periodic cleanup of old versions
```

**Diagnostic Steps**:
```bash
# .stversions size
du -sh .stversions

# Largest versioned files
du -a .stversions | sort -rn | head -20

# Version count distribution
find .stversions -type f | cut -d~ -f1 | uniq -c | sort -rn | head -10

# Old versions (>90 days)
find .stversions -type f -mtime +90 -ls
```

**Tuning Versioning Policy**:
```xml
<!-- Simple versioning: keep only 5 versions -->
<versioning>
  <type>simple</type>
  <params>
    <keep>5</keep>
  </params>
</versioning>

<!-- Staggered: keep 30d hourly, 365d daily -->
<versioning>
  <type>staggered</type>
  <params>
    <maxAge>31536000</maxAge>  <!-- 365 days -->
  </params>
</versioning>
```

---

### Pattern 4: Ignored File Drift

**Symptoms**:
- Files matching `.stignore` patterns are syncing anyway
- Platform-specific files appearing on wrong platforms
- Large unnecessary files consuming bandwidth

**Common Causes**:
```
1. .stignore not created in folder root
2. .stignore syntax errors (invalid patterns)
3. Files added before .stignore rule created (grandfathered)
4. .stignore not applied to all devices
```

**Diagnostic Steps**:
```bash
# Check if .stignore exists
ls -la .stignore

# Test .stignore syntax (validate patterns)
syncthing cli debug file ~/workspace/.venv  # Should show "Ignored"

# Find files that SHOULD be ignored
find . -name "__pycache__" -o -name "*.pyc" -o -name ".DS_Store"
```

**Resolution**:
```
1. Create/fix .stignore in folder root
2. Stop Syncthing
3. Manually delete ignored files from all devices
4. Restart Syncthing
5. Verify files don't re-sync
```

---

## 6. RECOVERY PROCEDURES

### Conflict Resolution

**Manual Merge** (text files):
```bash
# 1. Identify conflicts
find . -name "*.sync-conflict-*"

# 2. Compare versions
diff MEMORY.md MEMORY.sync-conflict-20251228-143022.md

# 3. Manually merge (edit original file)
nano MEMORY.md

# 4. Delete conflict file
rm MEMORY.sync-conflict-20251228-143022.md

# 5. Verify sync
# Check Syncthing UI - should propagate merged version
```

**Binary File Conflicts**:
```bash
# 1. Determine which version to keep (inspect both)
# 2. Rename preferred version to original name
mv image.sync-conflict-20251228-143022.jpg image.jpg

# 3. Delete other version(s)
# 4. Verify sync
```

**Automated Conflict Detection** (for Flight Path):
```bash
#!/bin/bash
# detect_conflicts.sh
CONFLICTS=$(find ~/workspace -name "*.sync-conflict-*" | wc -l)
if [ $CONFLICTS -gt 0 ]; then
  echo "WARNING: $CONFLICTS sync conflicts detected"
  find ~/workspace -name "*.sync-conflict-*" -ls
  exit 1
fi
exit 0
```

---

### Version Cleanup

**Remove Old Versions**:
```bash
# Delete versions older than 30 days
find .stversions -type f -mtime +30 -delete

# Keep only 3 most recent versions per file
# (More complex - requires scripting)
for file in $(find .stversions -type f | cut -d~ -f1 | sort -u); do
  ls -t "$file"~* | tail -n +4 | xargs rm -f
done
```

**Version Storage Audit**:
```bash
#!/bin/bash
# version_audit.sh
TOTAL_SIZE=$(du -sb ~/workspace | cut -f1)
VERSION_SIZE=$(du -sb ~/workspace/.stversions | cut -f1)
RATIO=$(echo "scale=2; $VERSION_SIZE * 100 / $TOTAL_SIZE" | bc)

echo "Total sync folder: $(numfmt --to=iec $TOTAL_SIZE)"
echo "Version storage: $(numfmt --to=iec $VERSION_SIZE)"
echo "Ratio: ${RATIO}%"

if (( $(echo "$RATIO > 20" | bc -l) )); then
  echo "WARNING: Version storage exceeds 20% threshold"
  exit 1
fi
```

---

### Re-scan Folder

**When to Use**:
- Syncthing shows wrong file counts
- Manual file operations outside Syncthing
- Suspected index corruption

**Procedure**:
```bash
# Via API
curl -X POST http://localhost:8384/rest/db/scan?folder=workspace

# Via UI
# Folder Actions → Rescan All
```

**Force Override** (nuclear option):
```bash
# 1. Stop Syncthing
systemctl stop syncthing@user

# 2. Delete folder index
rm ~/.config/syncthing/index-v0.14.0.db

# 3. Restart Syncthing (will rebuild index)
systemctl start syncthing@user
```

---

### Sync Conflict Prevention

**File Locking Pattern** (Python example):
```python
import portalocker
import json

def atomic_update(filepath, modifier_func):
    """
    Atomic read-modify-write with file locking.
    Prevents sync conflicts during concurrent edits.
    """
    with portalocker.Lock(filepath, 'r+', timeout=10) as f:
        data = json.load(f)
        modified_data = modifier_func(data)
        f.seek(0)
        json.dump(modified_data, f, indent=2)
        f.truncate()
    # Lock released, Syncthing can now sync
```

**Edit Coordination**:
```bash
# Acquire edit lock (create marker file)
touch ~/workspace/MEMORY.md.lock

# Edit file
vim ~/workspace/MEMORY.md

# Release lock
rm ~/workspace/MEMORY.md.lock

# Add .lock to .stignore to prevent syncing lock files
echo "*.lock" >> .stignore
```

---

## 7. FLIGHT PATH INTEGRATION

### Health Check Endpoint

**API Route**: `/api/health/syncthing`

**Response Schema**:
```json
{
  "status": "healthy" | "warning" | "critical",
  "timestamp": "2025-12-28T14:30:00Z",
  "metrics": {
    "sync_status": "Up to Date" | "Syncing" | "Out of Sync",
    "last_sync_seconds": 45,
    "conflict_count": 0,
    "version_depth_avg": 2.3,
    "version_size_ratio": 0.08,
    "ignored_drift_count": 0,
    "out_of_sync_items": 0
  },
  "alerts": [
    {
      "severity": "warning",
      "metric": "last_sync_seconds",
      "value": 320,
      "threshold": 300,
      "message": "Last sync >5 minutes ago"
    }
  ],
  "devices": {
    "LAPTOP-ABC": {
      "connected": true,
      "last_seen": "2025-12-28T14:29:30Z"
    },
    "DESKTOP-XYZ": {
      "connected": false,
      "last_seen": "2025-12-28T12:15:00Z"
    }
  }
}
```

### Health Calculation Logic

```python
def calculate_syncthing_health():
    """
    Aggregate Syncthing health status.
    Returns: ("healthy"|"warning"|"critical", alerts[])
    """
    alerts = []

    # Check sync status
    status = get_folder_status("workspace")
    if status["state"] != "idle":
        alerts.append({
            "severity": "warning",
            "metric": "sync_status",
            "message": f"Folder state: {status['state']}"
        })

    # Check last sync time
    last_sync = get_last_sync_time()
    if last_sync > 300:  # 5 minutes
        alerts.append({
            "severity": "warning",
            "metric": "last_sync_seconds",
            "value": last_sync,
            "threshold": 300
        })

    # Check conflicts
    conflicts = count_conflict_files()
    if conflicts > 0:
        severity = "critical" if conflicts > 3 else "warning"
        alerts.append({
            "severity": severity,
            "metric": "conflict_count",
            "value": conflicts,
            "threshold": 0
        })

    # Check version bloat
    ratio = get_version_size_ratio()
    if ratio > 0.20:
        alerts.append({
            "severity": "critical",
            "metric": "version_size_ratio",
            "value": ratio,
            "threshold": 0.20
        })

    # Determine overall status
    if any(a["severity"] == "critical" for a in alerts):
        return ("critical", alerts)
    elif any(a["severity"] == "warning" for a in alerts):
        return ("warning", alerts)
    else:
        return ("healthy", [])
```

### Dashboard Widgets

**Syncthing Status Card**:
```
┌─────────────────────────────────┐
│ SYNCTHING                       │
├─────────────────────────────────┤
│ Status: ● Up to Date            │
│ Last Sync: 45s ago              │
│ Conflicts: 0                    │
│ Devices: 2/2 online             │
│                                 │
│ Version Storage: 8% (2.1 GB)   │
└─────────────────────────────────┘
```

**Alert Example**:
```
⚠️ SYNCTHING WARNING
  • 2 sync conflicts detected
  • Last sync: 6 minutes ago
  • Device DESKTOP-XYZ offline

  [Resolve Conflicts] [View Details]
```

### Monitoring Integration

**Prometheus Metrics** (if implemented):
```
syncthing_sync_status{folder="workspace"} 1  # 1=up to date, 0=syncing, -1=out of sync
syncthing_last_sync_seconds{folder="workspace"} 45
syncthing_conflict_count{folder="workspace"} 0
syncthing_version_size_bytes{folder="workspace"} 2147483648
syncthing_device_connected{device="LAPTOP-ABC"} 1
```

**Event Stream** (WebSocket):
```json
{
  "type": "syncthing_event",
  "timestamp": "2025-12-28T14:30:00Z",
  "event": "ItemStarted",
  "data": {
    "folder": "workspace",
    "item": "MEMORY.md",
    "action": "update"
  }
}
```

---

## 8. TROUBLESHOOTING

### Common Issues

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| "Out of Sync" persistent | Network issue or device offline | Check device connectivity |
| Conflicts on every edit | Clock skew or no sync coordination | Sync system clocks, coordinate edits |
| .stversions huge | No version cleanup | Prune old versions, adjust policy |
| Files not syncing | .stignore misconfiguration | Review .stignore patterns |
| Slow sync performance | Large .stversions or many files | Cleanup versions, exclude generated files |
| Missing files after sync | Accidental deletion or move | Restore from .stversions |

### Diagnostic Commands

```bash
# Syncthing process status
systemctl status syncthing@user

# Check API reachability
curl http://localhost:8384/rest/system/ping

# View recent errors
curl http://localhost:8384/rest/system/errors | jq

# Folder statistics
curl http://localhost:8384/rest/db/status?folder=workspace | jq

# Device connections
curl http://localhost:8384/rest/system/connections | jq

# Live event stream (subscribe for real-time)
curl -H "X-API-Key: YOUR_API_KEY" http://localhost:8384/rest/events
```

### Log Locations

```
Linux: ~/.config/syncthing/
Windows: %LOCALAPPDATA%\Syncthing\
macOS: ~/Library/Application Support/Syncthing/

Key files:
  syncthing.log           # Main log
  config.xml              # Configuration (includes .stignore)
  index-v0.14.0.db        # File index database
```

---

## 9. SECURITY CONSIDERATIONS

### Guardrails (from GUARDRAILS.md)

**HARD STOPS** - Never modify without explicit approval:
- `.stignore` (could expose secrets or break sync)
- `.stfolder` (breaks sync relationship)
- `.stversions` (recovery mechanism)
- Syncthing `config.xml`

### Secrets Protection

**Critical .stignore patterns**:
```
.env
*.key
*.pem
credentials.json
secrets/
config/local.json
```

**Verification**:
```bash
# Ensure secrets are ignored
syncthing cli debug file ~/workspace/.env
# Should output: "Ignored: true"
```

### Access Control

- Syncthing API requires API key (found in `config.xml`)
- UI accessible only on localhost:8384 by default
- Device connections require manual approval
- Folder sharing requires explicit configuration

---

## 10. FUTURE ENHANCEMENTS

### Automated Conflict Resolution

**ML-based auto-merge**:
- Train model on past manual resolutions
- Auto-merge low-risk conflicts (e.g., append-only logs)
- Flag high-risk conflicts for human review

### Predictive Version Cleanup

**Smart retention**:
- Keep versions of frequently-edited files longer
- Aggressive cleanup for rarely-accessed files
- Preserve versions before major changes (detected via commit messages)

### Real-Time Flight Path Alerts

**WebSocket push notifications**:
```javascript
// Browser receives instant alerts
socket.on('syncthing:conflict', (data) => {
  showAlert(`Sync conflict: ${data.filename}`);
  offerResolutionUI(data);
});
```

### Integration with Git

**Sync-aware commits**:
- Detect when local changes pending sync
- Warn before committing if devices out of sync
- Auto-pull `.stversions` for recovery

---

*This file is part of the organic system. Updated by the agent Spartan instance.*
