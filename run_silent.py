"""
iHIM Silent Runner - No console window
Used for background/startup execution
"""
import sys
import os
from pathlib import Path

# Change to script directory
ihim_dir = Path(os.path.dirname(os.path.abspath(__file__)))
os.chdir(str(ihim_dir))

# Add to path
sys.path.insert(0, str(ihim_dir))

try:
    import uvicorn
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"])
    import uvicorn

# Source directories only — excludes .venv (7,773 .py files that cause
# false-positive reloads from antivirus/indexer mtime changes on Windows).
# StatReload ignores reload_excludes, so explicit reload_dirs is the only fix.
_SOURCE_DIRS = [
    d for d in [
        "api", "actions", "adapters", "handlers", "tools",
        "workers", "orchestrator", "privilege", "compliance",
        "flight_path", "configs", "sanity", "infra", "team",
    ]
    if (ihim_dir / d).is_dir()
]

# Guard required for Windows multiprocessing (uvicorn reload uses spawn)
if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="127.0.0.1",
        port=7777,
        reload=True,
        reload_dirs=[str(ihim_dir / d) for d in _SOURCE_DIRS],
        log_level="error"
    )
