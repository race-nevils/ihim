"""File watcher logic for inbox processing.

Simple flow:
1. New file appears → process → write to Memory folder
2. Same file gets edited → update the processed version immediately
3. No timers, no graduation - just seamless updates

File tracking (deduplication, change detection) is handled by the
database via source_filename + content_hash columns. No separate
staging registry needed.
"""
import logging
import time
import re
import traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable
from dataclasses import dataclass, field

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

    def process_files(self, processor: Callable) -> list[dict]:
        """Process files through the brain handler.

        File tracking (new vs update, change detection) is handled by
        the brain handler via database lookups. The watcher just passes
        files to the processor and moves them when done.
        """
        results = []
        files_to_process = self.scan_sources()

        for file_path, source in files_to_process:
            original_name = file_path.name
            try:
                content = self.read_file_content(file_path)

                if not content:
                    logger.info(f"Skipping empty file: {original_name}")
                    self.move_to_processed(file_path)
                    results.append({
                        "file": original_name,
                        "source": str(source.path),
                        "result": {"action": "skipped", "reason": "empty content"}
                    })
                    continue

                # Process the file - brain handler does deduplication via database
                result = processor(content, str(file_path))

                action = result.get("result", {}).get("action", "unknown")

                # Move to processed unless skipped (unchanged)
                if action != "skipped":
                    self.move_to_processed(file_path)

                results.append({
                    "file": original_name,
                    "source": str(source.path),
                    "result": result,
                    "action_type": action
                })

            except Exception as e:
                error_tb = traceback.format_exc()
                logger.error(f"Failed to process {original_name}: {e}\n{error_tb}")
                results.append({
                    "file": original_name,
                    "source": str(source.path),
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
        if self.cleanup_days > 0:
            print(f"Cleanup: processed files older than {self.cleanup_days} days")
        print("Press Ctrl+C to stop\n")

        try:
            while self._running:
                deleted = self.cleanup_old_processed()
                if deleted > 0:
                    print(f"[CLEANUP] Deleted {deleted} old processed file(s)")

                results = self.process_files(processor)

                for result in results:
                    if "error" in result:
                        print(f"[ERROR] {result['file']}: {result['error']}")
                    else:
                        file_result = result.get("result", {})
                        intent = file_result.get("intent", "unknown")
                        action = result.get("action_type", "unknown")
                        category = file_result.get("category", "")

                        if action == "classified":
                            print(f"[NEW] {result['file']} -> {category}")
                        elif action in ("updated", "updated_reclassified"):
                            print(f"[UPDATE] {result['file']} -> {category}")
                        elif action == "needs_review":
                            print(f"[REVIEW] {result['file']} -> needs_review")
                        elif action == "skipped":
                            pass  # Silent skip for unchanged files
                        else:
                            print(f"[OK] {result['file']} -> {action}")

                    if on_process:
                        on_process(result)

                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            print("\nStopping watcher...")
            self._running = False

    def stop(self):
        """Stop the watcher."""
        self._running = False
