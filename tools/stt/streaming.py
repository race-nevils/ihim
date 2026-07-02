"""Chunked streaming transcription — flat release latency at any length.

While recording, audio since the last COMMIT POINT is transcribed once
it grows past ``_COMMIT_AT_S``. Segments followed by a clear silence gap
are then committed: their text is banked and the commit point advances
to a block boundary inside that gap. Everything after the commit point
is re-transcribed next round with the committed tail as decoder context,
so no cut ever lands mid-word and each pass costs one bounded window —
never the whole recording.

On release, ``finalize()`` transcribes only the final window (commit
point → release). Whisper always sees real speech context there; it is
never handed an isolated sub-second tail — the historical source of
hallucinated endings ("closed captioning by...") and vocabulary spew.
"""

import logging
import math
import threading
import time
from typing import Optional

from tools.stt.audio import MicCapture, write_wav

logger = logging.getLogger(__name__)

# Run a commit pass once this much uncommitted audio has accumulated.
_COMMIT_AT_S = 10.0
# A segment is committable only if the NEXT segment starts at least this
# long after it ends — the cut lands in real silence, never mid-word.
_MIN_GAP_S = 1.0
# Keep the cut clear of the live edge of the window snapshot.
_EDGE_GUARD_S = 2.0
# VAD pads speech starts by 200ms — the cut must stay clear of that too.
_SPEECH_PAD_S = 0.2
# How often the loop re-checks the buffer.
_POLL_S = 1.0


def _pick_cut(segments: list[dict], window_s: float, block_s: float) -> Optional[tuple[int, int]]:
    """Choose the latest safe commit cut.

    Returns (last committed segment index, blocks to advance) or None.
    The cut is a block boundary inside an inter-segment silence gap of at
    least ``_MIN_GAP_S``, clear of both the following speech (VAD pad) and
    the live edge of the window. The final segment is never committable —
    its speech may continue beyond the snapshot.
    """
    best = None
    for i in range(len(segments) - 1):
        end = segments[i]["end"]
        gap = segments[i + 1]["start"] - end
        if gap < _MIN_GAP_S or end > window_s - _EDGE_GUARD_S:
            continue
        advance = math.ceil((end + 0.05) / block_s)
        if advance * block_s <= segments[i + 1]["start"] - _SPEECH_PAD_S:
            best = (i, advance)
    return best


class ChunkedTranscriber:
    """Daemon thread that commits finished speech chunks during recording."""

    def __init__(self, mic: MicCapture, model_name: str):
        self._mic = mic
        self._model_name = model_name
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._committed_text: list[str] = []
        self._committed_blocks = 0

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="stt-streaming",
        )
        self._thread.start()
        logger.info("Chunked transcriber started (commit at %.0fs)", _COMMIT_AT_S)

    @property
    def committed(self) -> tuple[str, int]:
        """(banked text, commit point in blocks) — thread-safe snapshot."""
        with self._lock:
            return " ".join(self._committed_text), self._committed_blocks

    def finalize(self, blocks: list, sample_rate: int) -> str:
        """Stop the loop and transcribe commit point → end of frozen buffer.

        Joining the loop thread first guarantees no concurrent GPU calls
        and that any commit already in flight lands before the offset is
        read. Returns the full raw transcript (committed + final window).
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=30)

        committed_text, committed_blocks = self.committed
        window = blocks[committed_blocks:]
        if not window:
            return committed_text

        window_s = sum(len(b) for b in window) / sample_rate
        wav_path = write_wav(window, sample_rate)
        try:
            from tools.stt.transcribe import transcribe
            t0 = time.monotonic()
            tail_text = transcribe(
                wav_path, model_size=self._model_name, prev_text=committed_text,
            ).strip()
            logger.info(
                "FINAL WINDOW: %.1fs audio in %.1fs → %d chars "
                "(%d chars committed earlier)",
                window_s, time.monotonic() - t0, len(tail_text), len(committed_text),
            )
        finally:
            try:
                wav_path.unlink()
            except Exception:
                pass

        return (committed_text + " " + tail_text).strip()

    # ------------------------------------------------------------------
    # Commit loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_event.wait(_POLL_S):
            try:
                self._maybe_commit()
            except Exception:
                logger.warning("Commit pass failed", exc_info=True)

    def _maybe_commit(self) -> None:
        blocks, rate = self._mic.snapshot()
        window = blocks[self._committed_blocks :]
        if not window:
            return
        block_s = len(window[0]) / rate
        window_s = sum(len(b) for b in window) / rate
        if window_s < _COMMIT_AT_S:
            return

        wav_path = write_wav(window, rate)
        try:
            from tools.stt.transcribe import transcribe_segments
            prev_text, offset = self.committed
            t0 = time.monotonic()
            segments = transcribe_segments(
                wav_path, model_size=self._model_name, prev_text=prev_text,
            )
            elapsed = time.monotonic() - t0
        finally:
            try:
                wav_path.unlink()
            except Exception:
                pass

        cut = _pick_cut(segments, window_s, block_s)
        if cut is None:
            if window_s > 60.0:
                logger.warning(
                    "No committable pause in %.0fs of audio — window keeps growing",
                    window_s,
                )
            return

        cut_index, advance = cut
        text = " ".join(s["text"] for s in segments[: cut_index + 1]).strip()
        with self._lock:
            if text:
                self._committed_text.append(text)
            self._committed_blocks = offset + advance
        logger.info(
            "COMMIT: %.1fs window in %.1fs → banked %d segs (%d chars), "
            "commit point now block %d",
            window_s, elapsed, cut_index + 1, len(text), offset + advance,
        )
