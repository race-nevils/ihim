"""Entry point for the inbox watcher worker.

SINGLETON: Only one watcher instance should run at a time.
Uses a lock file to prevent duplicates (e.g., if manually started
while ihim-master.ahk already started one at login).
"""
import sys
import os
import atexit
from pathlib import Path

# Add IHIM to path for imports
IHIM_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(IHIM_ROOT))

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
    """Try to acquire the singleton lock.

    Returns True if lock acquired, False if another instance is running.
    """
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            if is_process_running(pid):
                # Process exists - another watcher is running
                return False
            # Process dead - stale lock file
            LOCK_FILE.unlink(missing_ok=True)
        except (ValueError, OSError):
            # Invalid lock file - remove it
            LOCK_FILE.unlink(missing_ok=True)

    # Write our PID to lock file
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    return True


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
        print("=" * 60)
        print("ERROR: Another inbox watcher is already running!")
        print("=" * 60)
        print(f"\nLock file: {LOCK_FILE}")
        print("\nTo force restart:")
        print("  1. Kill all python processes running runner.py")
        print("  2. Delete the lock file")
        print("  3. Start again")
        sys.exit(1)

    # Register cleanup BEFORE slow imports
    atexit.register(release_lock)
    print("Lock acquired, loading orchestrator...")

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
    path=WORKSPACE_ROOT / "Obsidian Vault" / "iHIM",
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
    print("=" * 60)
    print("Second Brain Orchestrator - Inbox Watcher")
    print("=" * 60)
    print()

    # Create orchestrator
    print("Initializing orchestrator...")
    orchestrator = create_orchestrator()
    print("Orchestrator ready.\n")

    # Create watcher with both sources
    watcher = InboxWatcher(
        sources=[DESKTOP_INBOX, OBSIDIAN_INBOX],
        processed_path=PROCESSED_PATH,
        poll_interval=2.0,
        cleanup_days=14  # Auto-delete processed files older than 14 days
    )

    # Create processor
    processor = create_processor(orchestrator)

    # Start watching
    watcher.watch(processor)


if __name__ == "__main__":
    main()
