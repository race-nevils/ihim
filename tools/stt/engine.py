"""Dictation pipeline orchestrator — record → transcribe → cleanup → inject → log.

Ties together audio capture, Whisper transcription, deterministic cleanup,
clipboard injection, and JSONL logging. Manages the hotkey listener lifecycle,
VRAM lazy loading/unloading, recording timeouts, and app-context detection.
"""

import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Callable, Optional

from tools.stt.audio import MicCapture
from tools.stt.config import load_config
from tools.stt.hotkey import DEFAULT_HOTKEY, HotkeyListener

logger = logging.getLogger(__name__)

TRAINING_DIR = Path(__file__).parent / "data" / "voice-training"


def _get_wav_duration(wav_path: Path) -> float:
    """Return WAV file duration in seconds."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


def _maybe_retain_audio(
    wav_path: Path, dictation_id: str, cfg: dict
) -> tuple[Optional[Path], float]:
    """Retain audio as FLAC for voice model training if enabled.

    Returns (saved_path, duration_s) or (None, 0.0) if retention disabled.
    """
    retention = cfg.get("audio_retention", {})
    if not retention.get("enabled", False):
        return None, 0.0

    segments_dir = TRAINING_DIR / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    duration_s = _get_wav_duration(wav_path)
    fmt = retention.get("format", "flac")
    out_path = segments_dir / f"{dictation_id}.{fmt}"

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-ac", "1", "-ar", "16000",
             str(out_path)],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0:
            logger.info("Audio retained: %s (%.1fs)", out_path.name, duration_s)
            return out_path, duration_s
        logger.warning("ffmpeg failed (rc=%d), falling back to WAV copy",
                       result.returncode)
    except FileNotFoundError:
        logger.warning("ffmpeg not found, falling back to WAV copy")
    except Exception as exc:
        logger.warning("Audio retention failed: %s, falling back to WAV copy", exc)

    # Fallback: copy WAV directly
    wav_out = segments_dir / f"{dictation_id}.wav"
    try:
        shutil.copy2(str(wav_path), str(wav_out))
        logger.info("Audio retained (WAV fallback): %s (%.1fs)",
                     wav_out.name, duration_s)
        return wav_out, duration_s
    except Exception as exc:
        logger.warning("WAV fallback also failed: %s", exc)
        return None, 0.0


_PUNCT_RE = re.compile(r'[^\w\s]', re.UNICODE)


def _strip_punct(word: str) -> str:
    return _PUNCT_RE.sub('', word).lower()


def _extract_tail_wav(wav_path: Path, tail_start_s: float) -> Optional[Path]:
    """Extract audio from tail_start_s to end of WAV as a new temp file."""
    if tail_start_s <= 0:
        return None
    try:
        with wave.open(str(wav_path), "rb") as wf:
            rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            n_frames = wf.getnframes()
            start_frame = int(tail_start_s * rate)
            if start_frame >= n_frames:
                return None
            wf.setpos(start_frame)
            tail_data = wf.readframes(n_frames - start_frame)

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tail_path = Path(tmp.name)
        tmp.close()

        with wave.open(str(tail_path), "wb") as twf:
            twf.setnchannels(n_channels)
            twf.setsampwidth(sampwidth)
            twf.setframerate(rate)
            twf.writeframes(tail_data)

        return tail_path
    except Exception as e:
        logger.warning("Tail WAV extraction failed: %s", e)
        return None


def _join_without_overlap(confirmed: str, tail: str) -> str:
    """Join confirmed and tail text, removing any word overlap at the junction."""
    if not confirmed or not tail:
        return (confirmed + " " + tail).strip()

    c_words = confirmed.split()
    t_words = tail.split()

    # Find longest suffix of confirmed that matches prefix of tail
    max_check = min(len(c_words), len(t_words), 8)
    for overlap in range(max_check, 0, -1):
        if all(
            _strip_punct(c_words[len(c_words) - overlap + i]) == _strip_punct(t_words[i])
            for i in range(overlap)
        ):
            return confirmed + " " + " ".join(t_words[overlap:])

    return confirmed + " " + tail


def _transcribe_with_streaming(
    wav_path: Path,
    model_name: str,
    streaming_result,
    cfg: dict,
) -> str:
    """Transcribe using streaming shortcut if available, else full fallback."""
    from tools.stt.transcribe import transcribe

    stream_cfg = cfg.get("streaming", {})
    max_age = stream_cfg.get("result_max_age_s", 2.0)
    min_runs = stream_cfg.get("min_agreement_runs", 2)

    if (
        streaming_result is not None
        and streaming_result.run_count >= min_runs
        and streaming_result.confirmed_text.strip()
        and (time.monotonic() - streaming_result.last_run_time) < max_age
    ):
        tail_wav = _extract_tail_wav(wav_path, streaming_result.tail_start_s)
        if tail_wav is not None:
            try:
                tail_text = transcribe(tail_wav, model_size=model_name)
                combined = _join_without_overlap(
                    streaming_result.confirmed_text.strip(),
                    tail_text.strip(),
                )
                if combined.strip():
                    logger.info(
                        "Streaming shortcut: %d confirmed words + tail from %.1fs "
                        "(run_count=%d)",
                        len(streaming_result.confirmed_text.split()),
                        streaming_result.tail_start_s,
                        streaming_result.run_count,
                    )
                    return combined
            except Exception as e:
                logger.warning("Tail transcription failed, full fallback: %s", e)
            finally:
                try:
                    tail_wav.unlink()
                except Exception:
                    pass

    # Full fallback
    return transcribe(wav_path, model_size=model_name)


class STTEngine:
    """Dictation pipeline orchestrator.

    Manages the hotkey listener and runs the full dictation pipeline
    on each hold-and-release cycle.
    """

    def __init__(self, hotkey=DEFAULT_HOTKEY, config: Optional[dict] = None):
        self._hotkey = hotkey
        self._cfg = config or load_config()
        self._mic = MicCapture()
        self._listener: Optional[HotkeyListener] = None
        self._lock = threading.Lock()
        self._last_result: Optional[dict] = None
        self._status = "idle"  # idle | listening | recording | processing | loading | warning | error
        self._on_state_change: Optional[Callable[[str], None]] = None
        self._app_context: str = "prose"  # captured at record start
        self._idle_timer: Optional[threading.Timer] = None
        self._warning_timer: Optional[threading.Timer] = None
        self._timeout_timer: Optional[threading.Timer] = None
        self._streamer = None

    def set_state_callback(self, cb: Callable[[str], None]) -> None:
        """Register a callback fired on every status transition.

        The callback receives the new status string.  Setting to None
        removes the callback.  Thread-safe — the callback may be invoked
        from any thread (hotkey listener, pipeline worker, main).
        """
        self._on_state_change = cb

    def _set_status(self, status: str) -> None:
        """Set status and fire the state-change callback (if any)."""
        self._status = status
        cb = self._on_state_change
        if cb is not None:
            try:
                cb(status)
            except Exception:
                logger.debug("State-change callback error", exc_info=True)

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
            self._set_status("listening")

    def stop_listening(self) -> None:
        """Deactivate the hotkey listener."""
        with self._lock:
            if self._listener:
                self._listener.stop()
                self._listener = None
            self._cancel_recording_timers()
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            self._set_status("idle")

    @property
    def status(self) -> str:
        if self._listener and self._listener.is_recording:
            return "recording"
        return self._status

    @property
    def last_result(self) -> Optional[dict]:
        return self._last_result

    def _cancel_recording_timers(self) -> None:
        """Cancel warning and timeout timers."""
        for timer in (self._warning_timer, self._timeout_timer):
            if timer is not None:
                timer.cancel()
        self._warning_timer = None
        self._timeout_timer = None

    def _reset_idle_timer(self) -> None:
        """Reset the VRAM idle unload timer."""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        timeout = self._cfg.get("idle_timeout_s", 600)
        self._idle_timer = threading.Timer(timeout, self._on_idle_timeout)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _on_idle_timeout(self) -> None:
        """Unload the Whisper model to free VRAM after inactivity."""
        logger.info("Idle timeout reached — unloading Whisper model to free VRAM")
        try:
            from api.recorder.transcribe import unload_model
            model_name = self._cfg.get("model", "large-v3-turbo")
            unload_model(model_name)
        except Exception as e:
            logger.debug("Model unload failed (may not be loaded): %s", e)

    def _on_recording_warning(self) -> None:
        """Called when recording nears the time limit."""
        logger.info("Recording warning: approaching time limit")
        self._set_status("warning")
        try:
            from tools.stt.sounds import play_warning
            play_warning(self._cfg)
        except Exception:
            pass

    def _on_recording_timeout(self) -> None:
        """Called when recording hits the max time limit — auto-stop."""
        logger.info("Recording timeout: auto-stopping after max duration")
        self._cancel_recording_timers()
        try:
            self._mic.stop()
        except Exception:
            pass
        threading.Thread(
            target=self._run_pipeline,
            daemon=True,
            name="stt-pipeline-timeout",
        ).start()

    def _on_record_start(self) -> None:
        """Called by hotkey listener on key press."""
        try:
            # Capture app context BEFORE recording (stt pill will have focus during recording)
            from tools.stt.app_context import get_active_app_context
            self._app_context = get_active_app_context()
            logger.debug("App context at record start: %s", self._app_context)

            # Cancel idle timer while recording
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None

            # Check if model needs loading
            from api.recorder.transcribe import is_model_loaded
            model_name = self._cfg.get("model", "large-v3-turbo")
            if not is_model_loaded(model_name):
                self._set_status("loading")

            self._set_status("recording")
            self._mic.start()

            # Start streaming transcription (real-time text during recording)
            if self._cfg.get("streaming", {}).get("enabled", True):
                try:
                    from tools.stt.streaming import StreamingTranscriber
                    self._streamer = StreamingTranscriber(self, self._cfg)
                    self._streamer.start()
                except Exception as e:
                    logger.warning("Failed to start streaming transcriber: %s", e)
                    self._streamer = None


            # Start recording timers
            rec_cfg = self._cfg.get("recording", {})
            warn_s = rec_cfg.get("warning_seconds", 300)
            max_s = rec_cfg.get("max_seconds", 360)

            self._warning_timer = threading.Timer(warn_s, self._on_recording_warning)
            self._warning_timer.daemon = True
            self._warning_timer.start()

            self._timeout_timer = threading.Timer(max_s, self._on_recording_timeout)
            self._timeout_timer.daemon = True
            self._timeout_timer.start()

        except Exception as e:
            logger.error("Failed to start mic capture: %s", e)
            self._set_status("listening")

    def _on_record_stop(self) -> None:
        """Called by hotkey listener on key release. Runs pipeline in background thread."""
        self._cancel_recording_timers()
        threading.Thread(
            target=self._run_pipeline,
            daemon=True,
            name="stt-pipeline",
        ).start()

    def _run_pipeline(self) -> None:
        """Full dictation pipeline: transcribe → inject → log."""
        self._set_status("processing")
        start_time = time.time()
        wav_path = None
        dictation_id = uuid.uuid4().hex[:8]

        try:
            # 1. Stop mic and get WAV path
            wav_path = self._mic.stop()

            # 2. Stop streamer, get result
            streamer = self._streamer
            self._streamer = None
            streaming_result = None
            if streamer:
                streamer.stop()
                streaming_result = streamer.get_result()

            # 3. Transcribe — streaming shortcut or full fallback
            model_name = self._cfg.get("model", "large-v3-turbo")
            raw_text = _transcribe_with_streaming(
                wav_path, model_name, streaming_result, self._cfg
            )

            if not raw_text.strip():
                logger.info("Empty transcript, skipping")
                self._set_status("listening")
                self._reset_idle_timer()
                return

            # 3. Inject raw transcript into active window
            from tools.stt.inject import inject_text
            inj_cfg = self._cfg.get("injection", {})
            method = inj_cfg.get("method", "auto")
            inject_text(raw_text.strip(), method=method)

            # 5. Success sound
            try:
                from tools.stt.sounds import play_success
                play_success(self._cfg)
            except Exception:
                pass

            # 6. Retain audio for voice model training (before WAV cleanup)
            audio_path, duration_s = _maybe_retain_audio(
                wav_path, dictation_id, self._cfg
            )

            # 7. Log to JSONL + manifest
            latency_ms = int((time.time() - start_time) * 1000)
            from tools.stt.logger import log_dictation
            record = log_dictation(
                raw_transcript=raw_text,
                cleaned_text=raw_text.strip(),
                latency_ms=latency_ms,
                whisper_model=model_name,
                cleanup_model="none",
                dictation_id=dictation_id,
                audio_path=str(audio_path) if audio_path else None,
                duration_s=duration_s,
            )

            self._last_result = record
            logger.info(
                "Dictation complete: %s (%dms) — '%s'",
                record["id"], latency_ms, raw_text.strip()[:80],
            )

        except Exception as e:
            logger.error("Dictation pipeline failed: %s", e)
            self._set_status("error")
            try:
                from tools.stt.sounds import play_error
                play_error(self._cfg)
            except Exception:
                pass
            # Let error state show for 2s before returning to listening
            time.sleep(2)

        finally:
            # Clean up temp WAV
            try:
                if wav_path is not None and wav_path.exists():
                    wav_path.unlink()
            except Exception:
                pass
            self._set_status("listening")
            self._reset_idle_timer()

    def get_partial_text(self) -> tuple[str, str]:
        """Return (confirmed, partial) text from the streaming transcriber."""
        streamer = self._streamer
        if streamer is None:
            return ("", "")
        return streamer.get_display_text()

    def on_dictation_complete(self, wav_path: Path) -> Optional[dict]:
        """Manual pipeline trigger (for API use without hotkey).

        Returns the dictation record or None on failure.
        """
        self._set_status("processing")
        start_time = time.time()

        try:
            from tools.stt.transcribe import transcribe
            model_name = self._cfg.get("model", "large-v3-turbo")
            raw_text = transcribe(wav_path, model_size=model_name)

            if not raw_text.strip():
                return None

            from tools.stt.inject import inject_text
            inj_cfg = self._cfg.get("injection", {})
            inject_text(raw_text.strip(), method=inj_cfg.get("method", "auto"))

            latency_ms = int((time.time() - start_time) * 1000)
            from tools.stt.logger import log_dictation
            record = log_dictation(
                raw_transcript=raw_text,
                cleaned_text=raw_text.strip(),
                latency_ms=latency_ms,
                whisper_model=model_name,
                cleanup_model="none",
            )

            self._last_result = record
            return record

        except Exception as e:
            logger.error("Manual dictation pipeline failed: %s", e)
            return None
        finally:
            self._set_status("listening" if self._listener else "idle")


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
