"""Entry point for the inbox watcher worker.

SINGLETON: Only one watcher instance should run at a time.
Uses a lock file to prevent duplicates (e.g., if manually started
while ihim-master.ahk already started one at login).
"""
import sys
import os
import logging
import atexit
from pathlib import Path

# Load environment variables before other imports
from dotenv import load_dotenv
IHIM_ROOT = Path(__file__).parent.parent.parent
load_dotenv(IHIM_ROOT.parent / ".env")

# Add IHIM to path for imports (IHIM_ROOT already defined above)
sys.path.insert(0, str(IHIM_ROOT))

# File logging - essential for pythonw.exe (no console)
LOG_PATH = IHIM_ROOT / "data" / "watcher.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ]
)
logger = logging.getLogger("watcher.runner")

# Lock file to prevent multiple instances
LOCK_FILE = IHIM_ROOT / "data" / "watcher.lock"


def is_process_running(pid: int) -> bool:
    """Check if a process with given PID is running (Windows-compatible)."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        # Fallback for non-Windows
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def acquire_lock() -> bool:
    """Try to acquire the singleton lock using atomic file creation.

    Uses O_CREAT | O_EXCL for atomic creation (no TOCTOU race).
    Checks lock file age to mitigate PID reuse on Windows.
    Returns True if lock acquired, False if another instance is running.
    """
    import time as _time

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

    # First attempt: atomic creation
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        pass  # Lock file exists — check if it's stale

    # Lock exists — read PID and validate
    try:
        pid = int(LOCK_FILE.read_text().strip())
    except (ValueError, OSError):
        # Corrupt lock file — remove and retry
        LOCK_FILE.unlink(missing_ok=True)
        return _retry_atomic_create()

    if is_process_running(pid):
        # Extra safety: check lock age to mitigate PID reuse (Windows recycles PIDs)
        try:
            lock_age = _time.time() - LOCK_FILE.stat().st_mtime
            if lock_age > 86400:  # >24h — likely stale despite PID reuse
                logger.warning(f"Lock file >24h old (PID {pid} may be reused), reclaiming")
                LOCK_FILE.unlink(missing_ok=True)
                return _retry_atomic_create()
        except OSError:
            pass
        return False  # Genuine running instance

    # Process dead — stale lock
    LOCK_FILE.unlink(missing_ok=True)
    return _retry_atomic_create()


def _retry_atomic_create() -> bool:
    """Retry atomic lock file creation after stale cleanup."""
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except (FileExistsError, OSError):
        return False


def release_lock():
    """Release the singleton lock on exit."""
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass  # Best effort cleanup


# =============================================================================
# ACQUIRE LOCK BEFORE SLOW IMPORTS
# =============================================================================
# This must happen before importing orchestrator/watcher (which load LangChain)
# Otherwise multiple processes can pass the lock check during slow import phase

if __name__ == "__main__":
    if not acquire_lock():
        logger.error("Another inbox watcher is already running! Lock file: %s", LOCK_FILE)
        sys.exit(1)

    # Register cleanup BEFORE slow imports
    atexit.register(release_lock)
    logger.info("Lock acquired, loading orchestrator...")

# Now do the slow imports (only if we have the lock or if imported as module)
from orchestrator.graph import create_orchestrator
from workers.inbox_watcher.watcher import InboxWatcher, InboxSource


# Paths
WORKSPACE_ROOT = IHIM_ROOT.parent
PROCESSED_PATH = IHIM_ROOT / "data" / "local" / "brain" / "processed"

# Inbox sources - desktop and mobile
DESKTOP_INBOX = InboxSource(
    path=IHIM_ROOT / "data" / "local" / "brain" / "inbox",
    cleanup="move"  # Archive to processed folder
)

OBSIDIAN_INBOX = InboxSource(
    path=WORKSPACE_ROOT / "iHIM Vault",
    cleanup="move",  # Also archive (move deletes original)
    exclude_folders={".obsidian", "iHIM Memory", "processed"}
)


def create_processor(orchestrator):
    """Create a processor function that uses the orchestrator."""
    def processor(content: str, source_file: str) -> dict:
        state = {
            "input_text": content,
            "source_file": source_file
        }
        result = orchestrator.invoke(state)
        return result
    return processor


def main():
    """Main entry point for the inbox watcher."""
    logger.info("Second Brain Orchestrator - Inbox Watcher starting")

    # Create orchestrator
    logger.info("Initializing orchestrator...")
    orchestrator = create_orchestrator()
    logger.info("Orchestrator ready.")

    # Create watcher with both sources
    watcher = InboxWatcher(
        sources=[DESKTOP_INBOX, OBSIDIAN_INBOX],
        processed_path=PROCESSED_PATH,
        poll_interval=2.0,
        cleanup_days=14  # Auto-delete processed files older than 14 days
    )

    # Warm Ollama before entering poll loop
    watcher._warm_ollama()
    warmed = watcher.wait_for_warmup(timeout=30.0)
    if not warmed:
        logger.warning("Ollama warm-up timed out after 30s, starting in degraded mode")
    else:
        logger.info("Ollama warm-up complete, starting watch loop")

    # Create processor
    processor = create_processor(orchestrator)

    # Start watching
    watcher.watch(processor)


if __name__ == "__main__":
    main()
