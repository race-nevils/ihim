"""File lifecycle state machine for inbox processing.

Tracks files through states to provide proper debounce:
- SETTLING: File modified recently, waiting for quiet period
- READY: File stable for 10s, ready to process
- PROCESSED: Brain entry created/updated
- STALE: Idle 1hr, ready to archive

This solves the mid-type interruption problem by only processing
files that have "settled" (no edits for 10 seconds).
"""
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import time


class FileState(Enum):
    """Lifecycle states for tracked files."""
    SETTLING = "settling"    # Modified recently, waiting for quiet
    READY = "ready"          # Quiet for 10s, ready to process
    PROCESSED = "processed"  # Brain entry created/updated
    STALE = "stale"          # Idle 1hr, ready to archive


@dataclass
class TrackedFile:
    """State tracking for a single file."""
    path: Path
    state: FileState
    last_mtime: float
    content_hash: str | None = None


class FileTracker:
    """Track file lifecycle through the pipeline.

    Usage:
        tracker = FileTracker()

        # In poll loop:
        for path in files:
            state = tracker.update(path, path.stat().st_mtime)
            if state == FileState.SETTLING:
                # Skip - file still being edited
                continue

        # Process only READY files
        for path in tracker.get_ready():
            process(path)
            tracker.mark_processed(path, hash)

        # Archive STALE files
        for path in tracker.get_stale():
            archive(path)
            tracker.remove(path)
    """

    SETTLE_SECONDS = 10      # Wait 10s after last edit before processing
    STALE_SECONDS = 3600     # Archive after 1 hour of no edits

    def __init__(self):
        self.files: dict[Path, TrackedFile] = {}

    def update(self, path: Path, mtime: float) -> FileState:
        """Update file state based on modification time.

        Args:
            path: File path
            mtime: Current modification time (from stat)

        Returns:
            Current state after update
        """
        now = time.time()

        if path not in self.files:
            # New file detected - start in SETTLING
            self.files[path] = TrackedFile(path, FileState.SETTLING, mtime)
            return FileState.SETTLING

        tracked = self.files[path]

        # File was modified since last check - reset to SETTLING
        if mtime > tracked.last_mtime:
            tracked.last_mtime = mtime
            tracked.state = FileState.SETTLING
            return FileState.SETTLING

        # File hasn't changed - check for state transitions
        quiet_time = now - tracked.last_mtime

        if tracked.state == FileState.SETTLING:
            if quiet_time >= self.SETTLE_SECONDS:
                tracked.state = FileState.READY

        elif tracked.state == FileState.PROCESSED:
            if quiet_time >= self.STALE_SECONDS:
                tracked.state = FileState.STALE

        return tracked.state

    def mark_processed(self, path: Path, content_hash: str):
        """Mark file as processed with its content hash."""
        if path in self.files:
            self.files[path].state = FileState.PROCESSED
            self.files[path].content_hash = content_hash

    def remove(self, path: Path):
        """Remove file from tracking (after archive/delete)."""
        self.files.pop(path, None)

    def get_ready(self) -> list[Path]:
        """Get files ready for processing (settled 10s+)."""
        return [f.path for f in self.files.values() if f.state == FileState.READY]

    def get_stale(self) -> list[Path]:
        """Get files ready for archiving (idle 1hr+)."""
        return [f.path for f in self.files.values() if f.state == FileState.STALE]

    def get_state(self, path: Path) -> FileState | None:
        """Get current state of a specific file."""
        if path in self.files:
            return self.files[path].state
        return None

    def clear(self):
        """Clear all tracked files (for testing/reset)."""
        self.files.clear()
