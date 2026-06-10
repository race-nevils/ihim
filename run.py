"""iHIM server entry point.

    python run.py [--port 7777] [--dev]

Production mode (default) runs uvicorn in THIS process with no reloader —
one process, one PID, nothing to orphan. --dev opts into auto-reload for
active development; the reloader parent + worker child pair it creates is
exactly why reload is never the default (kill paths that miss the watcher
let it respawn the worker — the pre-refactor zombie source).

The IHIM_PORT env var is set here so the PID file and any child code can
report the real port; binding itself uses the --port argument.
"""

import argparse
import os
import sys
from pathlib import Path

IHIM_DIR = Path(__file__).resolve().parent

# Source dirs for --dev reload, EXCLUDING .venv (7,773 .py files whose
# antivirus/indexer mtime churn causes false-positive reloads on Windows).
_SOURCE_DIRS = [d for d in ("api", "adapters", "handlers", "tools", "data") if (IHIM_DIR / d).is_dir()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the iHIM server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("IHIM_PORT", 7777)))
    parser.add_argument("--dev", action="store_true", help="enable auto-reload (development only)")
    parser.add_argument("--log-level", default="info",
                        choices=["critical", "error", "warning", "info", "debug"])
    args = parser.parse_args()

    os.chdir(IHIM_DIR)
    sys.path.insert(0, str(IHIM_DIR))
    os.environ["IHIM_PORT"] = str(args.port)

    import uvicorn

    kwargs = dict(host="127.0.0.1", port=args.port, log_level=args.log_level)
    if args.dev:
        kwargs.update(reload=True, reload_dirs=[str(IHIM_DIR / d) for d in _SOURCE_DIRS])
        uvicorn.run("api.main:app", **kwargs)
    else:
        # Import the app object directly: single process, no spawn child.
        from api.main import app
        uvicorn.run(app, **kwargs)


if __name__ == "__main__":
    main()
