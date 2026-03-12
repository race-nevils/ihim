"""
iHIM Supervisor - Keeps the server running forever

This script monitors the iHIM server and automatically restarts it if it crashes.
Uses HTTP health check (not just socket) and rotating log files for visibility.

Usage:
    python supervisor.py
"""
import os
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime
import logging


# ── Logging to rotating file + console ──────────────────────────────
_LOG_DIR = Path(__file__).parent / "data"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_PATH = _LOG_DIR / "server.log"

_file_handler = RotatingFileHandler(
    _LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))

_sv_logger = logging.getLogger("supervisor")
_sv_logger.setLevel(logging.INFO)
_sv_logger.addHandler(_file_handler)
_sv_logger.addHandler(_console_handler)


def log(message):
    _sv_logger.info(message)


# ── PID lock file (prevent duplicate supervisors) ───────────────────
_LOCK_PATH = _LOG_DIR / "supervisor.lock"


def _acquire_lock():
    """Write PID lock file. Exit if another supervisor is running."""
    if _LOCK_PATH.exists():
        try:
            old_pid = int(_LOCK_PATH.read_text().strip())
            import psutil
            if psutil.pid_exists(old_pid):
                proc = psutil.Process(old_pid)
                if "python" in proc.name().lower():
                    log(f"ERROR: Another supervisor is already running (PID {old_pid})")
                    sys.exit(1)
        except Exception:
            pass  # stale lock, overwrite
    _LOCK_PATH.write_text(str(os.getpid()))


def _release_lock():
    try:
        _LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def is_server_healthy():
    """Check if server is actually responding to HTTP requests.

    A hung event loop still accepts TCP connections (socket check passes),
    but an HTTP GET to /api/health will time out. This catches real hangs.
    """
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:7777/api/health")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _kill_process_tree(pid):
    """Kill a process and all its children using psutil."""
    try:
        import psutil
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
        psutil.wait_procs(children + [parent], timeout=5)
    except Exception as e:
        log(f"Process tree kill failed for PID {pid}: {e}")


def run_ihim():
    """
    Run iHIM server with auto-restart on crash.

    Stability layer — if the server dies, it comes back.
    Server output goes to rotating log file (data/server.log).
    """
    ihim_dir = Path(__file__).parent
    run_script = ihim_dir / "run.py"

    if not run_script.exists():
        log(f"ERROR: run.py not found at {run_script}")
        sys.exit(1)

    _acquire_lock()

    log("=" * 60)
    log("iHIM Supervisor Started")
    log(f"Log file: {_LOG_PATH}")
    log("=" * 60)
    log("Watching for crashes and auto-restarting...")
    log("Press Ctrl+C to stop")
    log("")

    restart_count = 0
    last_restart_time = None
    server_process = None

    try:
        while True:
            try:
                # Check if server is already running
                if server_process and server_process.poll() is None:
                    if not is_server_healthy():
                        log("Server process alive but not responding to HTTP health check — killing...")
                        _kill_process_tree(server_process.pid)
                        server_process = None
                    else:
                        time.sleep(2)
                        continue

                # Server is not running, start it
                if last_restart_time:
                    time_since_restart = time.time() - last_restart_time
                    if time_since_restart < 5:
                        log("WARNING: Server crashed within 5 seconds — waiting before restart...")
                        time.sleep(5)

                log(f"Starting iHIM server (restart #{restart_count})...")
                last_restart_time = time.time()

                env = os.environ.copy()
                env['IHIM_SUPERVISED'] = '1'

                # Pipe server output to log file (not DEVNULL!)
                server_process = subprocess.Popen(
                    [sys.executable, str(run_script)],
                    cwd=str(ihim_dir),
                    env=env,
                    stdout=open(_LOG_PATH, "a", encoding="utf-8"),
                    stderr=subprocess.STDOUT,
                )

                # Wait for server to respond to HTTP health check
                log("Waiting for server to pass health check...")
                server_responded = False
                for i in range(15):
                    time.sleep(1)
                    if is_server_healthy():
                        log(f"Server healthy! (PID: {server_process.pid})")
                        server_responded = True
                        break

                if not server_responded:
                    log("WARNING: Server didn't pass health check within 15 seconds")
                    if server_process and server_process.poll() is None:
                        log("Killing non-responsive server...")
                        _kill_process_tree(server_process.pid)
                    server_process = None

                restart_count += 1

            except KeyboardInterrupt:
                raise
            except Exception as e:
                log(f"Supervisor error: {e}")
                log("Restarting in 5 seconds...")
                time.sleep(5)

    except KeyboardInterrupt:
        log("\nSupervisor stopped by user (Ctrl+C)")
        if server_process and server_process.poll() is None:
            log("Stopping server...")
            _kill_process_tree(server_process.pid)
    finally:
        _release_lock()

    log("iHIM Supervisor stopped")


if __name__ == "__main__":
    run_ihim()
