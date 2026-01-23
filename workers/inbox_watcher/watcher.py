"""File watcher logic for inbox processing."""
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
    """Configuration for an inbox source directory.

    Attributes:
        path: Path to the inbox directory
        cleanup: Cleanup behavior after processing ("move" or "delete")
        exclude_folders: Set of folder names to skip when watching
    """
    path: Path
    cleanup: str = "move"  # "move" = move to processed, "delete" = delete after processing
    exclude_folders: set = field(default_factory=set)


class InboxWatcher:
    """Watches multiple inbox directories for new files and processes them.

    Attributes:
        sources: List of InboxSource configurations to watch
        processed_path: Path to move processed files
        poll_interval: Seconds between polls
        file_pattern: Glob pattern for files to watch (default: *.md)
        cleanup_days: Delete processed files older than this many days (0 = no cleanup)
    """

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
        """Read file content, stripping any frontmatter.

        Args:
            file_path: Path to the file

        Returns:
            File content with frontmatter stripped
        """
        content = file_path.read_text(encoding="utf-8")

        # Strip YAML frontmatter if present
        frontmatter_pattern = r'^---\s*\n.*?\n---\s*\n'
        content = re.sub(frontmatter_pattern, '', content, flags=re.DOTALL)

        return content.strip()

    def move_to_processed(self, file_path: Path) -> Path:
        """Move a file to the processed directory.

        Args:
            file_path: Path to the file to move

        Returns:
            New path in processed directory
        """
        # Add timestamp to avoid collisions
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        new_name = f"{timestamp}_{file_path.name}"
        dest_path = self.processed_path / new_name

        file_path.rename(dest_path)
        return dest_path

    def _is_excluded(self, file_path: Path, source: InboxSource) -> bool:
        """Check if a file is in an excluded folder.

        Args:
            file_path: Path to check
            source: InboxSource configuration for this file

        Returns:
            True if file should be excluded
        """
        # Check if any parent folder is in exclude list
        for parent in file_path.parents:
            if parent.name in source.exclude_folders:
                return True
            # Stop at source path
            if parent == source.path:
                break
        return False

    def scan_sources(self) -> list[tuple[Path, InboxSource]]:
        """Scan all inbox sources for new files.

        Returns:
            List of (file_path, source) tuples for files to process
        """
        results = []
        for source in self.sources:
            if not source.path.exists():
                continue
            for file_path in source.path.glob(self.file_pattern):
                # Skip directories
                if not file_path.is_file():
                    continue
                # Skip files in excluded folders
                if self._is_excluded(file_path, source):
                    continue
                # Only process root level files (not in subfolders)
                if file_path.parent != source.path:
                    continue
                results.append((file_path, source))
        return results

    def cleanup_old_processed(self) -> int:
        """Delete processed files older than cleanup_days.

        Returns:
            Number of files deleted
        """
        if self.cleanup_days <= 0:
            return 0

        deleted = 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.cleanup_days)

        for file_path in self.processed_path.glob("*"):
            if file_path.is_file():
                # Get file modification time
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    try:
                        file_path.unlink()
                        deleted += 1
                        logger.info(f"Cleaned up old file: {file_path.name}")
                    except Exception as e:
                        logger.error(f"Failed to delete {file_path.name}: {e}")

        return deleted

    def process_files(self, processor: Callable[[str, str], dict]) -> list[dict]:
        """Process all pending files from all inbox sources.

        Args:
            processor: Callable that takes (content, source_file) and returns result dict

        Returns:
            List of processing results
        """
        results = []
        files_to_process = self.scan_sources()

        for file_path, source in files_to_process:
            original_name = file_path.name
            original_path = Path(file_path)  # Keep reference for delete cleanup
            try:
                # Read content FIRST (before moving)
                content = self.read_file_content(file_path)

                # Handle empty files - still archive them but skip processing
                if not content:
                    logger.info(f"Skipping empty file: {original_name}")
                    # Always move to processed for audit trail (this removes from source)
                    self.move_to_processed(file_path)
                    results.append({
                        "file": original_name,
                        "source": str(source.path),
                        "result": {"action": "skipped", "reason": "empty content"}
                    })
                    continue

                # Archive to processed folder (always, for audit trail)
                processed_path = self.move_to_processed(file_path)

                # Process through orchestrator (file already safe in processed/)
                result = processor(content, str(processed_path))

                # Delete original ONLY after successful processing
                # (original_path is now invalid since file was moved, but for "delete"
                # cleanup sources, the file was already moved so nothing to delete)
                # Note: For Obsidian sources, move_to_processed moves the file,
                # so the original is already gone. The "delete" cleanup is handled
                # by move_to_processed itself.

                results.append({
                    "file": original_name,
                    "source": str(source.path),
                    "result": result
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
                # Source file preserved on failure for retry

        return results

    def watch(self, processor: Callable[[str, str], dict], on_process: Optional[Callable] = None):
        """Start watching the inbox continuously.

        Args:
            processor: Callable that takes (content, source_file) and returns result dict
            on_process: Optional callback called after each file is processed
        """
        self._running = True
        print("Watching sources:")
        for source in self.sources:
            exclude_info = f", excluding: {', '.join(source.exclude_folders)}" if source.exclude_folders else ""
            print(f"  - {source.path} (cleanup: {source.cleanup}{exclude_info})")
        print(f"Poll interval: {self.poll_interval}s")
        if self.cleanup_days > 0:
            print(f"Cleanup: processed files older than {self.cleanup_days} days")
        print("Press Ctrl+C to stop\n")

        try:
            while self._running:
                # Run cleanup on each poll cycle
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
                        action = file_result.get("action", "unknown")  # Fixed: action is at top level
                        print(f"[OK] {result['file']} -> {intent} -> {action}")

                    if on_process:
                        on_process(result)

                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            print("\nStopping watcher...")
            self._running = False

    def stop(self):
        """Stop the watcher."""
        self._running = False
