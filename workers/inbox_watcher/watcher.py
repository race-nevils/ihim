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
import sqlite3
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
from data.database import get_entry_by_id

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
        self._files_processed = 0
        self._files_errored = 0
        self._total_processing_ms = 0

        self.failed_path = self.processed_path.parent / "failed"
        self._warm_up_event = threading.Event()

        # Ensure directories exist
        for source in self.sources:
            source.path.mkdir(parents=True, exist_ok=True)
        self.processed_path.mkdir(parents=True, exist_ok=True)
        self.failed_path.mkdir(parents=True, exist_ok=True)

    def read_file_content(self, file_path: Path) -> str:
        """Read file content, stripping any frontmatter."""
        content = file_path.read_text(encoding="utf-8")
        frontmatter_pattern = r'^---\s*\n.*?\n---\s*\n'
        content = re.sub(frontmatter_pattern, '', content, flags=re.DOTALL)
        return content.strip()

    def _get_content_hash(self, file_path: Path) -> str:
        """Get SHA-256 hash of file content (first 16 chars).

        Uses read_file_content() to strip frontmatter before hashing,
        so the hash matches what the DB stores.
        """
        content = self.read_file_content(file_path)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def move_to_processed(self, file_path: Path) -> Path:
        """Move a file to the processed directory."""
        import shutil
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        new_name = f"{timestamp}_{file_path.name}"
        dest_path = self.processed_path / new_name
        try:
            file_path.rename(dest_path)
        except OSError:
            shutil.move(str(file_path), str(dest_path))
        return dest_path

    def _is_excluded(self, file_path: Path, source: InboxSource) -> bool:
        """Check if a file is in an excluded folder (case-insensitive on Windows)."""
        exclude_lower = {f.lower() for f in source.exclude_folders}
        for parent in file_path.parents:
            if parent.name.lower() in exclude_lower:
                return True
            if parent == source.path:
                break
        return False

    def _recover_failed_files(self):
        """Move files from failed/ back to inbox for fresh retry attempts.

        On restart, any previously failed files get another chance.
        Zero tolerance for data loss — ideas always eventually get processed.
        """
        if not self.failed_path.exists():
            return
        recovered = 0
        for f in self.failed_path.glob(self.file_pattern):
            if not f.is_file() or f.name.endswith("_error.txt"):
                continue
            # Strip timestamp prefix (YYYYMMDD-HHMMSS_) to get original name
            original_name = f.name
            ts_match = re.match(r'^\d{8}-\d{6}_(.*)$', original_name)
            if ts_match:
                original_name = ts_match.group(1)
            dest = self.sources[0].path / original_name
            if dest.exists():
                # Original still in inbox — skip (don't overwrite)
                continue
            try:
                f.rename(dest)
                recovered += 1
                logger.info(f"Recovered failed file for retry: {original_name}")
            except Exception as e:
                logger.error(f"Failed to recover {f.name}: {e}")
        # Clean up orphaned error sidecars
        if recovered > 0:
            for sidecar in self.failed_path.glob("*_error.txt"):
                try:
                    sidecar.unlink()
                except Exception:
                    pass
            logger.info(f"Recovered {recovered} file(s) from failed/ for retry")

    def _move_to_failed(self, file_path: Path, error_msg: str):
        """Move file to failed/ directory with error sidecar."""
        import shutil
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        new_name = f"{timestamp}_{file_path.name}"
        dest = self.failed_path / new_name
        try:
            file_path.rename(dest)
        except OSError:
            shutil.move(str(file_path), str(dest))

        sidecar = self.failed_path / f"{timestamp}_{file_path.stem}_error.txt"
        sidecar.write_text(
            f"File: {file_path.name}\n"
            f"Failed at: {datetime.now(timezone.utc).isoformat()}\n"
            f"Retries: {FileTracker.MAX_RETRIES}\n"
            f"Error: {error_msg}\n",
            encoding="utf-8"
        )
        self.tracker.remove(file_path)
        logger.warning(f"Moved to failed/ after {FileTracker.MAX_RETRIES} retries: {file_path.name}")

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
            if not file_path.exists():
                # File already deleted/moved externally — remove from tracker to prevent leak
                self.tracker.remove(file_path)
                archived += 1
                logger.info(f"Removed missing stale file from tracker: {file_path.name}")
                continue
            try:
                self.move_to_processed(file_path)
                self.tracker.remove(file_path)
                archived += 1
                logger.info(f"Archived stale file: {file_path.name}")
            except (FileNotFoundError, OSError) as e:
                # File disappeared between exists() check and move — clean up tracker
                self.tracker.remove(file_path)
                archived += 1
                logger.info(f"File gone during archive, removed from tracker: {file_path.name} ({e})")
            except Exception as e:
                logger.error(f"Failed to archive {file_path.name}: {e}")

        return archived

    def purge_dead_tracker_entries(self) -> int:
        """Remove tracker entries for files that no longer exist on disk.

        Called periodically during poll to prevent unbounded memory growth.
        """
        dead = [p for p in list(self.tracker.files.keys()) if not p.exists()]
        for p in dead:
            self.tracker.remove(p)
            logger.debug(f"Purged dead tracker entry: {p.name}")
        return len(dead)

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

            _proc_elapsed_ms = 0
            try:
                content = self.read_file_content(file_path)

                if not content:
                    logger.info(f"Empty file, archiving immediately: {original_name}")
                    self.move_to_processed(file_path)
                    self.tracker.remove(file_path)
                    results.append({"file": original_name, "action_type": "skipped", "result": {"action": "skipped"}, "processing_ms": 0})
                    continue

                # Process the file - brain handler does deduplication via database
                # This is a slow LLM call, but we're safe because we marked PROCESSING
                _proc_t0 = time.time()
                result = processor(content, str(file_path))
                _proc_elapsed_ms = round((time.time() - _proc_t0) * 1000)
                action = result.get("result", {}).get("action", "unknown")

                # Check if the HANDLER returned an error action
                # (brain handler catches exceptions internally, returns {"action": "error"})
                # Note: state-level "error" field may contain non-fatal warnings
                if action == "error":
                    error_msg = result.get("error", result.get("result", {}).get("error", "unknown"))
                    logger.warning(f"Processor returned error for {original_name}: {error_msg}")
                    self._files_errored += 1
                    self._total_processing_ms += _proc_elapsed_ms
                    retry_count = self.tracker.increment_retry(file_path)
                    if retry_count >= FileTracker.MAX_RETRIES:
                        self._move_to_failed(file_path, f"processor_error: {error_msg}")
                    elif file_path in self.tracker.files:
                        self.tracker.files[file_path].state = FileState.READY
                        logger.info(f"Will retry {original_name} in {FileTracker.RETRY_DELAYS[min(retry_count-1, len(FileTracker.RETRY_DELAYS)-1)]}s (attempt {retry_count}/{FileTracker.MAX_RETRIES})")
                    results.append({"file": original_name, "error": f"processor_error: {error_msg}", "processing_ms": _proc_elapsed_ms})
                    continue

                # Verify brain write actually landed in database
                processed_id = result.get("result", {}).get("processed_id")
                if processed_id:
                    try:
                        entry = get_entry_by_id(processed_id)
                        if entry is None:
                            logger.warning(f"DB verification failed for {original_name}: entry {processed_id} not found")
                            retry_count = self.tracker.increment_retry(file_path)
                            if retry_count >= FileTracker.MAX_RETRIES:
                                self._move_to_failed(file_path, f"DB verification failed: {processed_id} not in database")
                            elif file_path in self.tracker.files:
                                self.tracker.files[file_path].state = FileState.READY
                            results.append({"file": original_name, "error": f"db_verify_failed: {processed_id}"})
                            continue
                    except sqlite3.OperationalError as db_err:
                        # DB locked or similar — don't penalize the file, but make it visible
                        logger.warning(f"DB verification skipped for {original_name} (OperationalError): {db_err}")
                    except Exception as db_err:
                        # Other DB errors — still skip verification but log
                        logger.warning(f"DB verification skipped for {original_name}: {db_err}")

                # Mark as processed (stays in inbox for potential re-editing)
                content_hash = self._get_content_hash(file_path)
                self.tracker.mark_processed(file_path, content_hash)

                self._files_processed += 1
                self._total_processing_ms += _proc_elapsed_ms

                results.append({
                    "file": original_name,
                    "result": result,
                    "action_type": action,
                    "processing_ms": _proc_elapsed_ms
                })

            except Exception as e:
                error_tb = traceback.format_exc()
                logger.error(f"Failed to process {original_name}: {e}\n{error_tb}")
                self._files_errored += 1
                self._total_processing_ms += _proc_elapsed_ms
                retry_count = self.tracker.increment_retry(file_path)
                if retry_count >= FileTracker.MAX_RETRIES:
                    self._move_to_failed(file_path, str(e))
                elif file_path in self.tracker.files:
                    self.tracker.files[file_path].state = FileState.READY
                    logger.info(f"Will retry {original_name} in {FileTracker.RETRY_DELAYS[min(retry_count-1, len(FileTracker.RETRY_DELAYS)-1)]}s (attempt {retry_count}/{FileTracker.MAX_RETRIES})")
                results.append({"file": original_name, "error": str(e), "traceback": error_tb, "processing_ms": _proc_elapsed_ms})

        return results

    def watch(self, processor: Callable, on_process: Optional[Callable] = None):
        """Start watching the inbox continuously."""
        self._recover_failed_files()
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

                # Purge tracker entries for files that no longer exist on disk
                purged = self.purge_dead_tracker_entries()
                if purged > 0:
                    logger.info(f"Purged {purged} dead tracker entries")

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
                from adapters.ollama import OllamaAdapter
                from adapters.embeddings import EMBED_MODEL
                base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
                with httpx.Client(timeout=60.0) as client:
                    # 1. Warm classification model
                    client.post(
                        f"{base_url}/api/generate",
                        json={
                            "model": OllamaAdapter.FAST_MODEL,
                            "prompt": "hi",
                            "stream": False,
                            "options": {"num_predict": 1}
                        }
                    )
                    logger.info("Ollama warm-up: classification model ready")

                    # 2. Warm embedding model (sequential to avoid VRAM thrash)
                    client.post(
                        f"{base_url}/api/embeddings",
                        json={
                            "model": EMBED_MODEL,
                            "prompt": "warmup"
                        }
                    )
                    logger.info("Ollama warm-up: embedding model ready")
                    self._warm_up_event.set()
            except Exception as e:
                logger.debug(f"Ollama warm-up failed (non-fatal): {e}")
                self._warm_up_event.set()  # Unblock waiters even on failure

        thread = threading.Thread(target=_ping, daemon=True)
        thread.start()
        logger.info("Ollama warm-up started (background)")

    def wait_for_warmup(self, timeout: float = 30.0) -> bool:
        """Block until Ollama warm-up completes or timeout."""
        return self._warm_up_event.wait(timeout=timeout)

    def _write_heartbeat(self, last_results: list[dict]):
        """Write heartbeat JSON for the dashboard API to read."""
        try:
            # Record activity from this cycle
            for r in last_results:
                action = r.get("action_type", "error" if "error" in r else "unknown")
                self._recent_activity.append({
                    "file": r.get("file", "?"),
                    "action": action,
                    "processing_ms": r.get("processing_ms", 0),
                    "time": datetime.now(timezone.utc).isoformat()
                })

            # Build tracked files snapshot
            tracked = []
            for fpath, info in self.tracker.files.items():
                tracked.append({
                    "name": fpath.name,
                    "state": info.state.name,
                    "retry_count": info.retry_count,
                })

            settling = sum(1 for t in tracked if t["state"] == "SETTLING")

            total_files = self._files_processed + self._files_errored
            avg_ms = round(self._total_processing_ms / total_files) if total_files > 0 else 0

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
                "processing_stats": {
                    "files_processed": self._files_processed,
                    "files_errored": self._files_errored,
                    "avg_processing_ms": avg_ms,
                    "total_processing_ms": self._total_processing_ms,
                },
            }

            # Atomic write: write to .tmp then replace
            tmp_path = self._heartbeat_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(heartbeat, indent=2), encoding="utf-8")
            tmp_path.replace(self._heartbeat_path)
        except Exception as e:
            logger.debug(f"Heartbeat write failed: {e}")
