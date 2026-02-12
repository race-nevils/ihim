"""File watcher logic for inbox processing.

Flow with debounce:
1. New file appears → enters SETTLING state
2. File stable for 10s → transitions to READY → process
3. File edited again → back to SETTLING → wait for quiet
4. Idle 1 hour → STALE → archive to processed folder

The FileTracker provides the debounce to prevent mid-type interruptions.
Deduplication (new vs update) is handled by database via content_hash.
"""
import logging
import time
import json
import os
import re
import hashlib
import threading
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable
from collections import deque
from dataclasses import dataclass, field

from .file_tracker import FileTracker, FileState

logger = logging.getLogger(__name__)


@dataclass
class InboxSource:
    """Configuration for an inbox source directory."""
    path: Path
    cleanup: str = "move"
    exclude_folders: set = field(default_factory=set)


class InboxWatcher:
    """Watches inbox directories and processes files with update-in-place support."""

    def __init__(
        self,
        sources: list[InboxSource],
        processed_path: Path,
        poll_interval: float = 2.0,
        file_pattern: str = "*.md",
        cleanup_days: int = 0
    ):
        self.sources = sources
        self.processed_path = Path(processed_path)
        self.poll_interval = poll_interval
        self.file_pattern = file_pattern
        self.cleanup_days = cleanup_days
        self._running = False
        self.tracker = FileTracker()
        self._start_time = time.time()
        self._poll_count = 0
        self._recent_activity = deque(maxlen=10)
        self._heartbeat_path = Path(__file__).parent.parent.parent / "data" / "watcher_heartbeat.json"
        self._ollama_warmed_at = 0.0  # Timestamp of last Ollama warm-up

        # Ensure directories exist
        for source in self.sources:
            source.path.mkdir(parents=True, exist_ok=True)
        self.processed_path.mkdir(parents=True, exist_ok=True)

    def read_file_content(self, file_path: Path) -> str:
        """Read file content, stripping any frontmatter."""
        content = file_path.read_text(encoding="utf-8")
        frontmatter_pattern = r'^---\s*\n.*?\n---\s*\n'
        content = re.sub(frontmatter_pattern, '', content, flags=re.DOTALL)
        return content.strip()

    def _get_content_hash(self, file_path: Path) -> str:
        """Get SHA-256 hash of file content (first 16 chars)."""
        content = file_path.read_text(encoding="utf-8")
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def move_to_processed(self, file_path: Path) -> Path:
        """Move a file to the processed directory."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        new_name = f"{timestamp}_{file_path.name}"
        dest_path = self.processed_path / new_name
        file_path.rename(dest_path)
        return dest_path

    def _is_excluded(self, file_path: Path, source: InboxSource) -> bool:
        """Check if a file is in an excluded folder."""
        for parent in file_path.parents:
            if parent.name in source.exclude_folders:
                return True
            if parent == source.path:
                break
        return False

    def scan_sources(self) -> list[tuple[Path, InboxSource]]:
        """Scan all inbox sources for files."""
        results = []
        for source in self.sources:
            if not source.path.exists():
                continue
            for file_path in source.path.glob(self.file_pattern):
                if not file_path.is_file():
                    continue
                if self._is_excluded(file_path, source):
                    continue
                # Only process root level files
                if file_path.parent != source.path:
                    continue
                results.append((file_path, source))
        return results

    def cleanup_old_processed(self) -> int:
        """Delete processed files older than cleanup_days."""
        if self.cleanup_days <= 0:
            return 0

        deleted = 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.cleanup_days)

        for file_path in self.processed_path.glob("*"):
            if file_path.is_file():
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    try:
                        file_path.unlink()
                        deleted += 1
                    except Exception as e:
                        logger.error(f"Failed to delete {file_path.name}: {e}")

        return deleted

    def cleanup_stale_files(self) -> int:
        """Archive files that have been idle for 1 hour (STALE state).

        These are 'finished' notes - user stopped editing, safe to archive.
        The FileTracker manages the STALE state based on last modification time.
        """
        archived = 0

        for file_path in self.tracker.get_stale():
            try:
                self.move_to_processed(file_path)
                self.tracker.remove(file_path)
                archived += 1
                logger.info(f"Archived stale file: {file_path.name}")
            except Exception as e:
                logger.error(f"Failed to archive {file_path.name}: {e}")

        return archived

    def process_files(self, processor: Callable) -> list[dict]:
        """Process files through the brain handler.

        Uses FileTracker for debounce:
        1. Update all file states based on modification time
        2. Only process files in READY state (stable for 10s)
        3. Mark processed files so they don't re-process until edited
        """
        results = []

        # First pass: update all file states
        for file_path, source in self.scan_sources():
            try:
                mtime = file_path.stat().st_mtime
                state = self.tracker.update(file_path, mtime)

                if state == FileState.SETTLING:
                    logger.debug(f"Settling: {file_path.name}")
                    self._warm_ollama()
            except Exception as e:
                logger.error(f"Failed to stat {file_path.name}: {e}")

        # Second pass: process only READY files
        for file_path in self.tracker.get_ready():
            original_name = file_path.name

            # Mark as PROCESSING immediately to prevent race condition
            # Other poll cycles will see PROCESSING and skip this file
            self.tracker.mark_processing(file_path)

            # B2: Fresh heartbeat BEFORE the blocking LLM call.
            # Even if Ollama cold-starts (30-50s), heartbeat timestamp
            # is recent enough to keep dashboard showing "healthy".
            self._write_heartbeat([])

            # B3: Log file age for latency diagnostics
            try:
                file_age = time.time() - file_path.stat().st_mtime
                logger.info(f"Processing {original_name} (file age: {file_age:.0f}s)")
            except OSError:
                logger.info(f"Processing {original_name}")

            try:
                content = self.read_file_content(file_path)

                if not content:
                    # Empty file - skip processing but DON'T move
                    # File stays in inbox until STALE (1hr idle), then archives
                    # This prevents premature removal while user is still typing
                    logger.debug(f"Empty content, skipping: {original_name}")
                    self.tracker.mark_processed(file_path, "empty")
                    continue

                # Process the file - brain handler does deduplication via database
                # This is a slow LLM call, but we're safe because we marked PROCESSING
                result = processor(content, str(file_path))
                action = result.get("result", {}).get("action", "unknown")

                # Check if the HANDLER returned an error action
                # (brain handler catches exceptions internally, returns {"action": "error"})
                # Note: state-level "error" field may contain non-fatal warnings
                if action == "error":
                    error_msg = result.get("error", result.get("result", {}).get("error", "unknown"))
                    logger.warning(f"Processor returned error for {original_name}: {error_msg}")
                    # Revert to READY so file gets retried on next poll
                    if file_path in self.tracker.files:
                        self.tracker.files[file_path].state = FileState.READY
                    results.append({
                        "file": original_name,
                        "error": f"processor_error: {error_msg}",
                    })
                    continue

                # Mark as processed (stays in inbox for potential re-editing)
                content_hash = self._get_content_hash(file_path)
                self.tracker.mark_processed(file_path, content_hash)

                results.append({
                    "file": original_name,
                    "result": result,
                    "action_type": action
                })

            except Exception as e:
                error_tb = traceback.format_exc()
                logger.error(f"Failed to process {original_name}: {e}\n{error_tb}")
                # Revert to READY so it can be retried on next poll
                # (mark_processing set it to PROCESSING, but processing failed)
                if file_path in self.tracker.files:
                    self.tracker.files[file_path].state = FileState.READY
                results.append({
                    "file": original_name,
                    "error": str(e),
                    "traceback": error_tb
                })

        return results

    def watch(self, processor: Callable, on_process: Optional[Callable] = None):
        """Start watching the inbox continuously."""
        self._running = True
        print("Watching sources:")
        for source in self.sources:
            exclude_info = f", excluding: {', '.join(source.exclude_folders)}" if source.exclude_folders else ""
            print(f"  - {source.path}{exclude_info}")
        print(f"Poll interval: {self.poll_interval}s")
        print(f"Debounce: {FileTracker.SETTLE_SECONDS}s settle before process")
        print(f"Archive: after {FileTracker.STALE_SECONDS // 3600}hr idle")
        if self.cleanup_days > 0:
            print(f"Cleanup: processed files older than {self.cleanup_days} days")
        print("Press Ctrl+C to stop\n")

        try:
            while self._running:
                deleted = self.cleanup_old_processed()
                if deleted > 0:
                    print(f"[CLEANUP] Deleted {deleted} old processed file(s)")

                # Archive stale files (1 hour without edits)
                stale = self.cleanup_stale_files()
                if stale > 0:
                    print(f"[ARCHIVE] Moved {stale} stale file(s) to processed")

                results = self.process_files(processor)

                for result in results:
                    if "error" in result:
                        print(f"[ERROR] {result['file']}: {result['error']}")
                    else:
                        file_result = result.get("result", {})
                        action = result.get("action_type", "unknown")
                        category = file_result.get("category", "")

                        if action == "classified":
                            print(f"[NEW] {result['file']} -> {category}")
                        elif action in ("updated", "updated_reclassified"):
                            print(f"[UPDATE] {result['file']} -> {category}")
                        elif action == "misc":
                            print(f"[MISC] {result['file']} -> Misc")
                        elif action == "skipped":
                            pass  # Silent skip for unchanged files
                        else:
                            print(f"[OK] {result['file']} -> {action}")

                    if on_process:
                        on_process(result)

                self._poll_count += 1
                self._write_heartbeat(results)

                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            print("\nStopping watcher...")
            self._running = False

    def stop(self):
        """Stop the watcher."""
        self._running = False

    def _warm_ollama(self):
        """Pre-load Ollama model into VRAM during settle period.

        When Ollama idles for ~5 min, it unloads from VRAM. The first
        classification call then blocks for 30-50s (cold start), causing
        the heartbeat to go stale and dashboard to flash "Down".

        Fix: When a file enters SETTLING, fire a tiny generate request in
        a background thread. By the time the file is READY (10s later),
        the model is loaded and classification is fast.
        """
        now = time.time()
        if now - self._ollama_warmed_at < 60:
            return  # Already warmed recently
        self._ollama_warmed_at = now

        def _ping():
            try:
                import httpx
                base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
                with httpx.Client(timeout=60.0) as client:
                    client.post(
                        f"{base_url}/api/generate",
                        json={
                            "model": "qwen2.5:7b-fast",
                            "prompt": "hi",
                            "stream": False,
                            "options": {"num_predict": 1}
                        }
                    )
                logger.info("Ollama warm-up complete")
            except Exception as e:
                logger.debug(f"Ollama warm-up failed (non-fatal): {e}")

        thread = threading.Thread(target=_ping, daemon=True)
        thread.start()
        logger.info("Ollama warm-up started (background)")

    def _write_heartbeat(self, last_results: list[dict]):
        """Write heartbeat JSON for the dashboard API to read."""
        try:
            # Record activity from this cycle
            for r in last_results:
                action = r.get("action_type", "error" if "error" in r else "unknown")
                self._recent_activity.append({
                    "file": r.get("file", "?"),
                    "action": action,
                    "time": datetime.now(timezone.utc).isoformat()
                })

            # Build tracked files snapshot
            tracked = []
            for fpath, info in self.tracker.files.items():
                tracked.append({
                    "name": fpath.name,
                    "state": info.state.name,
                })

            settling = sum(1 for t in tracked if t["state"] == "SETTLING")

            heartbeat = {
                "status": "running",
                "pid": os.getpid(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "uptime_seconds": round(time.time() - self._start_time),
                "poll_count": self._poll_count,
                "tracked_files": tracked,
                "tracked_count": len(tracked),
                "settling_count": settling,
                "recent_activity": list(self._recent_activity),
            }

            # Atomic write: write to .tmp then replace
            tmp_path = self._heartbeat_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(heartbeat, indent=2), encoding="utf-8")
            tmp_path.replace(self._heartbeat_path)
        except Exception as e:
            logger.debug(f"Heartbeat write failed: {e}")
