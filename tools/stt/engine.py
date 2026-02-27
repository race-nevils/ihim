"""Dictation pipeline orchestrator — record → transcribe → cleanup → inject → log.

Ties together audio capture, Whisper transcription, LLM cleanup, text injection,
and JSONL logging. Manages the hotkey listener lifecycle.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from tools.stt.audio import MicCapture
from tools.stt.hotkey import DEFAULT_HOTKEY, HotkeyListener

logger = logging.getLogger(__name__)


class STTEngine:
    """Dictation pipeline orchestrator.

    Manages the hotkey listener and runs the full dictation pipeline
    on each hold-and-release cycle.
    """

    def __init__(self, hotkey=DEFAULT_HOTKEY):
        self._hotkey = hotkey
        self._mic = MicCapture()
        self._listener: Optional[HotkeyListener] = None
        self._lock = threading.Lock()
        self._last_result: Optional[dict] = None
        self._status = "idle"  # idle | listening | recording | processing

    def start_listening(self) -> None:
        """Activate the hotkey listener."""
        with self._lock:
            if self._listener and self._listener.is_running:
                return
            self._listener = HotkeyListener(
                on_start=self._on_record_start,
                on_stop=self._on_record_stop,
                hotkey=self._hotkey,
            )
            self._listener.start()
            self._status = "listening"

    def stop_listening(self) -> None:
        """Deactivate the hotkey listener."""
        with self._lock:
            if self._listener:
                self._listener.stop()
                self._listener = None
            self._status = "idle"

    @property
    def status(self) -> str:
        if self._listener and self._listener.is_recording:
            return "recording"
        return self._status

    @property
    def last_result(self) -> Optional[dict]:
        return self._last_result

    def _on_record_start(self) -> None:
        """Called by hotkey listener on key press."""
        try:
            self._status = "recording"
            self._mic.start()
        except Exception as e:
            logger.error("Failed to start mic capture: %s", e)
            self._status = "listening"

    def _on_record_stop(self) -> None:
        """Called by hotkey listener on key release. Runs pipeline in background thread."""
        threading.Thread(
            target=self._run_pipeline,
            daemon=True,
            name="stt-pipeline",
        ).start()

    def _run_pipeline(self) -> None:
        """Full dictation pipeline: transcribe → cleanup → inject → log."""
        self._status = "processing"
        start_time = time.time()

        try:
            # 1. Stop mic and get WAV path
            wav_path = self._mic.stop()

            # 2. Transcribe
            from tools.stt.transcribe import transcribe
            raw_text = transcribe(wav_path)

            if not raw_text.strip():
                logger.info("Empty transcript, skipping")
                self._status = "listening"
                return

            # 3. LLM cleanup
            from tools.stt.cleanup import cleanup_transcript
            cleaned_text = cleanup_transcript(raw_text)

            # 4. Inject text into active window
            from tools.stt.inject import inject_text
            inject_text(cleaned_text)

            # 5. Log to JSONL
            latency_ms = int((time.time() - start_time) * 1000)
            from tools.stt.logger import log_dictation
            record = log_dictation(
                raw_transcript=raw_text,
                cleaned_text=cleaned_text,
                latency_ms=latency_ms,
            )

            self._last_result = record
            logger.info(
                "Dictation complete: %s (%dms) — '%s'",
                record["id"], latency_ms, cleaned_text[:80],
            )

        except Exception as e:
            logger.error("Dictation pipeline failed: %s", e)

        finally:
            # Clean up temp WAV
            try:
                if 'wav_path' in dir() and wav_path.exists():
                    wav_path.unlink()
            except Exception:
                pass
            self._status = "listening"

    def on_dictation_complete(self, wav_path: Path) -> Optional[dict]:
        """Manual pipeline trigger (for API use without hotkey).

        Returns the dictation record or None on failure.
        """
        self._status = "processing"
        start_time = time.time()

        try:
            from tools.stt.transcribe import transcribe
            raw_text = transcribe(wav_path)

            if not raw_text.strip():
                return None

            from tools.stt.cleanup import cleanup_transcript
            cleaned_text = cleanup_transcript(raw_text)

            from tools.stt.inject import inject_text
            inject_text(cleaned_text)

            latency_ms = int((time.time() - start_time) * 1000)
            from tools.stt.logger import log_dictation
            record = log_dictation(
                raw_transcript=raw_text,
                cleaned_text=cleaned_text,
                latency_ms=latency_ms,
            )

            self._last_result = record
            return record

        except Exception as e:
            logger.error("Manual dictation pipeline failed: %s", e)
            return None
        finally:
            self._status = "listening" if self._listener else "idle"


# Module-level singleton
_engine: Optional[STTEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> STTEngine:
    """Get or create the global STTEngine singleton."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = STTEngine()
    return _engine
