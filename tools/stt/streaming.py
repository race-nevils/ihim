"""Streaming Whisper — transcribe during recording for lower release latency.

Runs Whisper back-to-back on growing mic buffers during recording.
On release, the engine uses the streaming result and only transcribes
the small tail of audio the streamer didn't cover.
"""

import logging
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class StreamResult:
    """Snapshot of what the streamer has transcribed so far."""
    text: str
    word_count: int
    run_count: int
    last_run_time: float       # time.monotonic()
    blocks_covered: int        # how many blocks were in the last transcription


class StreamingTranscriber:
    """Daemon thread that transcribes growing mic audio during recording."""

    def __init__(self, engine_ref, model_name: str):
        self._engine = engine_ref
        self._model_name = model_name
        self._interval = 2.0

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._result: Optional[StreamResult] = None
        self._run_count = 0
        self._last_block_count = 0

    def start(self) -> None:
        """Launch the streaming daemon thread."""
        self._stop_event.clear()
        self._run_count = 0
        self._last_block_count = 0
        self._result = None
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="stt-streaming",
        )
        self._thread.start()
        logger.info("Streaming transcriber started (interval=%.1fs)", self._interval)

    def stop(self) -> None:
        """Signal stop and wait for current GPU work to finish.

        Must join the thread so that any in-flight Whisper call completes
        before the caller starts a new one — two concurrent GPU calls crash.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=30)

    def get_result(self) -> Optional[StreamResult]:
        with self._lock:
            return self._result

    def transcribe_tail(self) -> str:
        """Transcribe audio the streamer missed (call after stop).

        Grabs buffers beyond what the last streaming run covered,
        writes a tiny WAV, and transcribes just that tail.
        """
        capture = self._engine._mic._capture
        if capture is None:
            return ""

        result = self.get_result()
        if result is None:
            return ""

        all_buffers = list(capture._mic_buffers)
        covered = result.blocks_covered
        if len(all_buffers) <= covered:
            return ""

        tail_buffers = all_buffers[covered:]
        native_rate = int(capture._mic_info["sample_rate"])

        # Estimate tail duration — skip if too short (Whisper hallucinates on <0.5s)
        import numpy as np
        total_samples = sum(len(b) for b in tail_buffers)
        tail_duration_s = total_samples / native_rate
        if tail_duration_s < 0.5:
            logger.info("TAIL SKIP: %.2fs too short, would hallucinate", tail_duration_s)
            return ""

        wav_path = self._write_wav(tail_buffers, native_rate)
        if wav_path is None:
            return ""

        try:
            t0 = time.monotonic()
            from tools.stt.transcribe import transcribe
            text = transcribe(wav_path, model_size=self._model_name)
            elapsed = time.monotonic() - t0
            tail_text = text.strip()
            logger.info(
                "TAIL TRANSCRIPTION: %.1fs for %d blocks (%.2fs audio) → '%s'",
                elapsed, len(tail_buffers), tail_duration_s, tail_text[:80],
            )
            return tail_text
        except Exception as e:
            logger.warning("Tail transcription failed: %s", e)
            return ""
        finally:
            try:
                wav_path.unlink()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self._interval)
            if self._stop_event.is_set():
                break
            try:
                self._run_once()
            except Exception as e:
                logger.warning("Streaming run failed: %s", e)

    def _run_once(self) -> None:
        """Single iteration: snapshot buffers → WAV → transcribe."""
        capture = self._engine._mic._capture
        if capture is None:
            return

        buffers = list(capture._mic_buffers)
        if len(buffers) < 4:  # need ~2s of audio before first streaming run
            return

        if len(buffers) == self._last_block_count:
            return
        self._last_block_count = len(buffers)

        native_rate = int(capture._mic_info["sample_rate"])
        wav_path = self._write_wav(buffers, native_rate)
        if wav_path is None:
            return

        try:
            t0 = time.monotonic()
            from tools.stt.transcribe import transcribe
            text = transcribe(wav_path, model_size=self._model_name, word_timestamps=False)
            elapsed = time.monotonic() - t0

            self._run_count += 1
            words = text.split() if text.strip() else []

            result = StreamResult(
                text=text.strip(),
                word_count=len(words),
                run_count=self._run_count,
                last_run_time=time.monotonic(),
                blocks_covered=len(buffers),
            )
            with self._lock:
                self._result = result

            logger.info(
                "STREAMING RUN #%d: %.1fs to transcribe %d blocks → %d words: '%s'",
                self._run_count, elapsed, len(buffers), len(words),
                text.strip()[:100],
            )
        finally:
            try:
                wav_path.unlink()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # WAV helper
    # ------------------------------------------------------------------

    def _write_wav(self, buffers, native_rate) -> Optional[Path]:
        """Concatenate mic buffers into a temp WAV at native sample rate.

        No normalization — matches capture.py's approach so Whisper sees
        consistent audio across streaming runs and the normal path.
        """
        try:
            import numpy as np
            audio = np.concatenate(buffers)
            pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)

            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            path = Path(tmp.name)
            tmp.close()

            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(native_rate)
                wf.writeframes(pcm.tobytes())
            return path
        except Exception as e:
            logger.warning("Failed to write streaming WAV: %s", e)
            return None
