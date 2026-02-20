"""Test suite for inbox watcher resilience features.

Tests retry/backoff, failed-file recovery, DB verification,
empty file archive, and warm-up synchronization.
"""
import json
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from workers.inbox_watcher.file_tracker import FileTracker, FileState, TrackedFile
from workers.inbox_watcher.watcher import InboxWatcher, InboxSource


# =============================================================================
# FileTracker unit tests (pure logic, no I/O)
# =============================================================================

class TestFileTrackerRetry:
    """Retry tracking and backoff in FileTracker."""

    def test_retry_count_increments(self, tmp_path):
        tracker = FileTracker()
        p = tmp_path / "note.md"
        p.touch()
        tracker.files[p] = TrackedFile(p, FileState.READY, time.time())

        assert tracker.increment_retry(p) == 1
        assert tracker.increment_retry(p) == 2
        assert tracker.increment_retry(p) == 3

    def test_retry_backoff_delays(self, tmp_path):
        tracker = FileTracker()
        p = tmp_path / "note.md"
        p.touch()
        tracker.files[p] = TrackedFile(p, FileState.READY, time.time())

        before = time.time()
        tracker.increment_retry(p)
        assert tracker.files[p].retry_after >= before + 30 - 1  # ~30s

        tracker.increment_retry(p)
        assert tracker.files[p].retry_after >= before + 60 - 1  # ~60s

        tracker.increment_retry(p)
        assert tracker.files[p].retry_after >= before + 120 - 1  # ~120s

    def test_get_ready_respects_backoff(self, tmp_path):
        tracker = FileTracker()
        p = tmp_path / "note.md"
        p.touch()
        tracker.files[p] = TrackedFile(p, FileState.READY, time.time())
        # Set retry_after far in the future
        tracker.files[p].retry_after = time.time() + 9999

        ready = tracker.get_ready()
        assert p not in ready

    def test_get_ready_includes_after_backoff(self, tmp_path):
        tracker = FileTracker()
        p = tmp_path / "note.md"
        p.touch()
        tracker.files[p] = TrackedFile(p, FileState.READY, time.time())
        # Set retry_after in the past
        tracker.files[p].retry_after = time.time() - 1

        ready = tracker.get_ready()
        assert p in ready

    def test_mark_processed_resets_retry(self, tmp_path):
        tracker = FileTracker()
        p = tmp_path / "note.md"
        p.touch()
        tracker.files[p] = TrackedFile(p, FileState.READY, time.time())

        tracker.increment_retry(p)
        tracker.increment_retry(p)
        assert tracker.files[p].retry_count == 2
        assert tracker.files[p].retry_after > 0

        tracker.mark_processed(p, "abc123")
        assert tracker.files[p].retry_count == 0
        assert tracker.files[p].retry_after == 0.0

    def test_increment_retry_unknown_path(self, tmp_path):
        tracker = FileTracker()
        p = tmp_path / "ghost.md"
        assert tracker.increment_retry(p) == 0


# =============================================================================
# Watcher unit tests (mocked processor, temp directories)
# =============================================================================

def _make_watcher(tmp_path) -> InboxWatcher:
    """Create an InboxWatcher with temp directories."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    processed = tmp_path / "processed"
    processed.mkdir()
    source = InboxSource(path=inbox)
    watcher = InboxWatcher(
        sources=[source],
        processed_path=processed,
        poll_interval=0.1,
    )
    return watcher


class TestWatcherFailed:
    """Move-to-failed and recovery tests."""

    def test_move_to_failed_creates_sidecar(self, tmp_path):
        watcher = _make_watcher(tmp_path)
        inbox = watcher.sources[0].path

        note = inbox / "idea.md"
        note.write_text("my idea", encoding="utf-8")
        watcher.tracker.files[note] = TrackedFile(note, FileState.READY, time.time())

        watcher._move_to_failed(note, "test error message")

        # File moved out of inbox
        assert not note.exists()

        # File exists in failed/
        failed_files = list(watcher.failed_path.glob("*.md"))
        assert len(failed_files) == 1
        assert "idea.md" in failed_files[0].name

        # Error sidecar exists
        sidecars = list(watcher.failed_path.glob("*_error.txt"))
        assert len(sidecars) == 1
        sidecar_content = sidecars[0].read_text(encoding="utf-8")
        assert "test error message" in sidecar_content
        assert "idea.md" in sidecar_content

        # Removed from tracker
        assert note not in watcher.tracker.files

    def test_recover_failed_files_on_restart(self, tmp_path):
        watcher = _make_watcher(tmp_path)
        inbox = watcher.sources[0].path

        # Simulate a file in failed/ from a previous run
        failed_file = watcher.failed_path / "20260220-120000_idea.md"
        failed_file.write_text("my idea", encoding="utf-8")
        sidecar = watcher.failed_path / "20260220-120000_idea_error.txt"
        sidecar.write_text("Error: something broke", encoding="utf-8")

        watcher._recover_failed_files()

        # File moved back to inbox with original name
        assert (inbox / "idea.md").exists()
        assert (inbox / "idea.md").read_text(encoding="utf-8") == "my idea"

        # Failed dir cleaned up
        assert not failed_file.exists()
        assert not sidecar.exists()

    def test_recover_skips_if_inbox_has_original(self, tmp_path):
        watcher = _make_watcher(tmp_path)
        inbox = watcher.sources[0].path

        # Original file still in inbox
        original = inbox / "idea.md"
        original.write_text("updated content", encoding="utf-8")

        # Failed version from previous run
        failed_file = watcher.failed_path / "20260220-120000_idea.md"
        failed_file.write_text("old content", encoding="utf-8")

        watcher._recover_failed_files()

        # Original not overwritten
        assert original.read_text(encoding="utf-8") == "updated content"
        # Failed file stays (not recovered since original exists)
        assert failed_file.exists()

    def test_empty_file_archives_immediately(self, tmp_path):
        watcher = _make_watcher(tmp_path)
        inbox = watcher.sources[0].path

        # Create an empty file (frontmatter-only counts as empty after strip)
        note = inbox / "empty.md"
        note.write_text("", encoding="utf-8")

        # Manually set up tracker state to READY
        watcher.tracker.files[note] = TrackedFile(note, FileState.READY, time.time())

        def mock_processor(content, source):
            raise AssertionError("Should not process empty files")

        results = watcher.process_files(mock_processor)

        # File archived to processed/
        assert not note.exists()
        processed_files = list(watcher.processed_path.glob("*.md"))
        assert len(processed_files) == 1

        # Result recorded
        assert len(results) == 1
        assert results[0]["action_type"] == "skipped"

    def test_retry_cap_moves_to_failed(self, tmp_path):
        watcher = _make_watcher(tmp_path)
        inbox = watcher.sources[0].path

        note = inbox / "tough.md"
        note.write_text("content that always fails", encoding="utf-8")

        def failing_processor(content, source):
            return {"result": {"action": "error", "error": "Ollama down"}}

        # Simulate 3 consecutive failures
        for attempt in range(3):
            # Reset state to READY with past retry_after
            watcher.tracker.files[note] = TrackedFile(
                note, FileState.READY, time.time(),
                retry_count=attempt,
                retry_after=0.0,
            )
            watcher.process_files(failing_processor)

        # After 3 retries, file should be in failed/
        assert not note.exists()
        failed_files = list(watcher.failed_path.glob("*.md"))
        assert len(failed_files) == 1

    @patch("workers.inbox_watcher.watcher.get_entry_by_id")
    def test_db_verification_on_success(self, mock_get_entry, tmp_path):
        watcher = _make_watcher(tmp_path)
        inbox = watcher.sources[0].path

        note = inbox / "verified.md"
        note.write_text("important idea", encoding="utf-8")
        watcher.tracker.files[note] = TrackedFile(note, FileState.READY, time.time())

        # Processor succeeds but DB verification fails
        mock_get_entry.return_value = None

        def success_processor(content, source):
            return {
                "result": {
                    "action": "classified",
                    "processed_id": "brain-entry-123",
                    "category": "ideas",
                }
            }

        results = watcher.process_files(success_processor)

        # Should trigger retry (not mark as processed)
        mock_get_entry.assert_called_once_with("brain-entry-123")
        assert any("db_verify_failed" in r.get("error", "") for r in results)
        # File should still exist (retrying, not failed yet)
        assert note.exists()

    @patch("workers.inbox_watcher.watcher.get_entry_by_id")
    def test_db_error_skips_verification(self, mock_get_entry, tmp_path):
        watcher = _make_watcher(tmp_path)
        inbox = watcher.sources[0].path

        note = inbox / "dbhiccup.md"
        note.write_text("content", encoding="utf-8")
        watcher.tracker.files[note] = TrackedFile(note, FileState.READY, time.time())

        # DB throws an exception (locked, etc.)
        mock_get_entry.side_effect = Exception("database is locked")

        def success_processor(content, source):
            return {
                "result": {
                    "action": "classified",
                    "processed_id": "brain-entry-456",
                    "category": "ideas",
                }
            }

        results = watcher.process_files(success_processor)

        # File should be marked processed (DB error is non-fatal)
        assert note in watcher.tracker.files
        assert watcher.tracker.files[note].state == FileState.PROCESSED
        assert watcher.tracker.files[note].retry_count == 0

    def test_heartbeat_includes_retry_count(self, tmp_path):
        watcher = _make_watcher(tmp_path)

        note = tmp_path / "inbox" / "heartbeat_test.md"
        note.write_text("content", encoding="utf-8")
        watcher.tracker.files[note] = TrackedFile(
            note, FileState.READY, time.time(), retry_count=2
        )

        watcher._write_heartbeat([])
        heartbeat = json.loads(watcher._heartbeat_path.read_text(encoding="utf-8"))

        tracked = heartbeat["tracked_files"]
        assert len(tracked) == 1
        assert tracked[0]["retry_count"] == 2


# =============================================================================
# Warm-up tests
# =============================================================================

class TestWarmUp:
    """Ollama warm-up event synchronization."""

    def test_warmup_event_set_on_success(self, tmp_path):
        watcher = _make_watcher(tmp_path)

        with patch("workers.inbox_watcher.watcher.os") as mock_os:
            mock_os.getenv.return_value = "http://localhost:11434"
            mock_os.getpid.return_value = 1234

            # Mock httpx to simulate successful warm-up
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)

            with patch("httpx.Client", return_value=mock_client):
                watcher._warm_ollama()
                # Wait for the background thread to complete
                result = watcher.wait_for_warmup(timeout=5.0)

        assert result is True
        assert watcher._warm_up_event.is_set()

    def test_warmup_event_set_on_failure(self, tmp_path):
        watcher = _make_watcher(tmp_path)

        with patch("httpx.Client", side_effect=Exception("connection refused")):
            watcher._warm_ollama()
            result = watcher.wait_for_warmup(timeout=5.0)

        assert result is True
        assert watcher._warm_up_event.is_set()

    def test_wait_for_warmup_blocks_then_returns(self, tmp_path):
        watcher = _make_watcher(tmp_path)

        # Set the event after a short delay from another thread
        def set_after_delay():
            time.sleep(0.1)
            watcher._warm_up_event.set()

        t = threading.Thread(target=set_after_delay, daemon=True)
        t.start()

        start = time.time()
        result = watcher.wait_for_warmup(timeout=5.0)
        elapsed = time.time() - start

        assert result is True
        assert elapsed < 2.0  # Should return well before timeout
