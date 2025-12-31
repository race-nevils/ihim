"""
iHIM Supervisor - Keeps the server running forever

This script monitors the iHIM server and automatically restarts it if it crashes.
It's like a guardian angel for your local infrastructure.

Usage:
    python supervisor.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime


def log(message):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")


def is_server_running():
    """Check if server is responding on port 7777."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 7777), timeout=1):
            return True
    except (socket.timeout, socket.error):
        return False


def run_ihim():
    """
    Run iHIM server with auto-restart on crash.

    This is the stability layer - if the server dies for any reason,
    it automatically comes back to life.
    """
    ihim_dir = Path(__file__).parent
    run_script = ihim_dir / "run.py"

    if not run_script.exists():
        log(f"ERROR: run.py not found at {run_script}")
        sys.exit(1)

    log("=" * 60)
    log("iHIM Supervisor Started")
    log("=" * 60)
    log("Watching for crashes and auto-restarting...")
    log("Press Ctrl+C to stop")
    log("")

    restart_count = 0
    last_restart_time = None
    server_process = None

    while True:
        try:
            # Check if server is already running
            if server_process and server_process.poll() is None:
                # Process is still running, check if server is responsive
                if not is_server_running():
                    log("Server process alive but not responding - killing it...")
                    server_process.terminate()
                    time.sleep(2)
                    if server_process.poll() is None:
                        server_process.kill()
                    server_process = None
                else:
                    # Server is healthy, wait and check again
                    time.sleep(2)
                    continue

            # Server is not running, start it
            if last_restart_time:
                time_since_restart = time.time() - last_restart_time
                if time_since_restart < 5:
                    log("WARNING: Server crashed within 5 seconds - waiting before restart...")
                    time.sleep(5)

            log(f"Starting iHIM server (restart #{restart_count})...")
            last_restart_time = time.time()

            # Start server as background process (no browser tabs)
            env = os.environ.copy()
            env['IHIM_SUPERVISED'] = '1'  # Skip browser opening

            server_process = subprocess.Popen(
                [sys.executable, str(run_script)],
                cwd=str(ihim_dir),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # Wait for server to start
            log("Waiting for server to start...")
            server_responded = False
            for i in range(10):
                time.sleep(1)
                if is_server_running():
                    log(f"Server started successfully! (PID: {server_process.pid})")
                    server_responded = True
                    break

            if not server_responded:
                log("WARNING: Server didn't respond within 10 seconds")
                # Kill non-responsive server
                if server_process and server_process.poll() is None:
                    log("Killing non-responsive server...")
                    server_process.terminate()
                    time.sleep(1)
                    if server_process.poll() is None:
                        server_process.kill()
                server_process = None

            restart_count += 1

        except KeyboardInterrupt:
            log("\nSupervisor stopped by user (Ctrl+C)")
            if server_process:
                log("Stopping server...")
                server_process.terminate()
                time.sleep(2)
                if server_process.poll() is None:
                    server_process.kill()
            break
        except Exception as e:
            log(f"Supervisor error: {e}")
            log("Restarting in 5 seconds...")
            time.sleep(5)

    log("iHIM Supervisor stopped")


if __name__ == "__main__":
    run_ihim()
