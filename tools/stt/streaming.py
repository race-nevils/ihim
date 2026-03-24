"""Streaming Whisper transcription with local agreement for real-time dictation.

Runs Whisper repeatedly on growing audio during recording. Consecutive outputs
are compared at word boundaries -- words stable across 2+ runs are confirmed
(won't change). On release, only the tail needs processing.

Core algorithm (~200 lines, no external dependencies beyond faster-whisper):
  1. Every ~2s, snapshot mic buffers and transcribe
  2. Compare current words to previous run (local agreement)
  3. Words that match across runs = confirmed, rest = partial
  4. On release, confirmed text is done; only the unconfirmed tail is transcribed
"""

import logging
import re
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PUNCT_RE = re.compile(r'[^\w\s]', re.UNICODE)


def _strip_punct(word: str) -> str:
    """Strip punctuation for word comparison."""
    return _PUNCT_RE.sub('', word).lower()


@dataclass
class StreamResult:
    """Result of streaming transcription."""
    confirmed_text: str     # stable across N runs
    partial_text: str       # latest run, may change
    tail_start_s: float     # audio timestamp where tail transcription should begin
    run_count: int
    last_run_time: float    # time.monotonic()


class StreamingTranscriber:
    """Runs Whisper on growing audio during recording for real-time text.

    Launched as a daemon thread when recording starts. Periodically snapshots
    the mic buffers, transcribes, and runs local agreement to identify
    confirmed (stable) words vs partial (may shift) words.
    """

    def __init__(self, engine_ref, cfg: dict):
        self._engine = engine_ref
        self._cfg = cfg
        self._stream_cfg = cfg.get("streaming", {})
        self._interval = self._stream_cfg.get("interval_s", 2.0)
        self._model_name = cfg.get("model", "large-v3-turbo")

        # Load vocab once
        from tools.stt.transcribe import load_vocab
        self._vocab_prompt = load_vocab()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._result: Optional[StreamResult] = None
        self._prev_words: list[str] = []
        self._run_count = 0
        self._last_block_count = 0
        self._in_progress = False

    def start(self) -> None:
        """Launch the streaming transcription daemon thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="stt-streaming",
        )
        self._thread.start()
        logger.info("Streaming transcriber started (interval=%.1fs)", self._interval)

    def stop(self) -> None:
        """Signal the loop to stop and wait for the thread to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def get_result(self) -> Optional[StreamResult]:
        """Return the latest streaming result (thread-safe)."""
        with self._lock:
            return self._result

    def get_display_text(self) -> tuple[str, str]:
        """Return (confirmed_text, partial_text) for the bar display."""
        with self._lock:
            if self._result is None:
                return ("", "")
            return (self._result.confirmed_text, self._result.partial_text)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        """Main streaming loop -- runs every interval_s seconds."""
        while not self._stop_event.is_set():
            self._stop_event.wait(self._interval)
            if self._stop_event.is_set():
                break
            if self._in_progress:
                logger.debug("Streaming: previous run still in progress, skipping")
                continue

            self._in_progress = True
            try:
                self._run_iteration()
            except Exception as e:
                logger.warning("Streaming run failed: %s", e)
            finally:
                self._in_progress = False

    def _run_iteration(self) -> None:
        """Single iteration: snapshot buffers, transcribe, run agreement."""
        # Get capture reference safely (GIL-atomic read)
        capture = self._engine._mic._capture
        if capture is None:
            return

        # Snapshot buffers (shallow list copy -- GIL protects list.append)
        buffers = list(capture._mic_buffers)
        if not buffers:
            return

        # Skip if no new blocks since last run
        if len(buffers) == self._last_block_count:
            return

        # Need at least 2 blocks (~1s of audio at 500ms/block)
        if len(buffers) < 2:
            return

        # Cap at 60 blocks (30s -- Whisper's max context window)
        if len(buffers) > 60:
            buffers = buffers[-60:]

        native_rate = int(capture._mic_info["sample_rate"])
        self._last_block_count = len(capture._mic_buffers)

        result = self._run_once(buffers, native_rate)
        if result is not None:
            with self._lock:
                self._result = result

    def _run_once(self, buffers, native_rate) -> Optional[StreamResult]:
        """Transcribe buffered audio and run local agreement."""
        wav_path = self._buffers_to_wav(buffers, native_rate)
        if wav_path is None:
            return None

        try:
            from api.recorder.transcribe import transcribe_channel

            segments = transcribe_channel(
                wav_path,
                speaker_label="dictation",
                model_size=self._model_name,
                initial_prompt=self._vocab_prompt or None,
                condition_on_previous_text=False,
                compression_ratio_threshold=1.8,
                hallucination_silence_threshold=1.0,
                language="en",
            )

            self._run_count += 1

            # Extract words from all segments
            curr_words = []
            for seg in segments:
                curr_words.extend(seg["text"].split())

            if not curr_words:
                return self._result

            # Local agreement against previous run
            if self._prev_words:
                confirmed, partial = self._local_agreement(
                    self._prev_words, curr_words
                )
            else:
                confirmed, partial = [], curr_words

            self._prev_words = curr_words

            # Compute tail start (segment-aligned)
            tail_start = self._compute_tail_start(segments, len(confirmed))

            logger.debug(
                "Streaming run #%d: %d confirmed, %d partial, tail=%.1fs",
                self._run_count, len(confirmed), len(partial), tail_start,
            )

            return StreamResult(
                confirmed_text=" ".join(confirmed),
                partial_text=" ".join(partial),
                tail_start_s=tail_start,
                run_count=self._run_count,
                last_run_time=time.monotonic(),
            )
        finally:
            try:
                wav_path.unlink()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Audio helpers
    # ------------------------------------------------------------------

    def _buffers_to_wav(self, buffers, native_rate) -> Optional[Path]:
        """Write mic buffers to a temp 16kHz mono WAV (same as DualStreamCapture)."""
        try:
            import numpy as np
            from api.recorder.capture import _resample, TARGET_RATE

            audio = np.concatenate(buffers)
            audio = _resample(audio, native_rate, TARGET_RATE)

            # Normalize to prevent clipping (matches capture._write_wav)
            peak = np.abs(audio).max()
            if peak > 0:
                audio = audio / peak * 0.95

            pcm = (audio * 32767).astype(np.int16)

            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            path = Path(tmp.name)
            tmp.close()

            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(TARGET_RATE)
                wf.writeframes(pcm.tobytes())

            return path
        except Exception as e:
            logger.warning("Failed to write streaming WAV: %s", e)
            return None

    # ------------------------------------------------------------------
    # Local agreement
    # ------------------------------------------------------------------

    def _local_agreement(
        self, prev_words: list[str], curr_words: list[str]
    ) -> tuple[list, list]:
        """Find longest common prefix at word boundaries, ignoring punctuation.

        Words that match across consecutive runs are confirmed (stable).
        Remaining words from the current run are partial (may shift).
        """
        confirmed = []
        for pw, cw in zip(prev_words, curr_words):
            if _strip_punct(pw) == _strip_punct(cw):
                confirmed.append(cw)  # use current run's punctuation
            else:
                break

        partial = curr_words[len(confirmed):]
        return confirmed, partial

    def _compute_tail_start(
        self, segments: list[dict], confirmed_word_count: int
    ) -> float:
        """Find the audio timestamp where tail transcription should begin.

        Walks segments summing word counts. Returns seg["start"] of the
        segment containing the confirmed boundary (conservative -- slightly
        re-transcribes the boundary segment, which is safe).
        """
        if confirmed_word_count == 0 or not segments:
            return 0.0

        words_seen = 0
        for seg in segments:
            seg_wc = len(seg["text"].split())
            if words_seen + seg_wc > confirmed_word_count:
                # Boundary is in this segment -- tail starts here
                return seg["start"]
            words_seen += seg_wc

        # All segments fully confirmed -- tail at end
        return segments[-1]["end"] if segments else 0.0
