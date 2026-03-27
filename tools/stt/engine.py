"""Dictation pipeline orchestrator — record → transcribe → cleanup → inject → log.

Ties together audio capture, Whisper transcription, deterministic cleanup,
clipboard injection, and JSONL logging. Manages the hotkey listener lifecycle,
VRAM lazy loading/unloading, recording timeouts, and app-context detection.
"""

import logging
import shutil
import subprocess
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
        self._status = "cold"  # cold | warm | recording | processing | warning | error
        self._on_state_change: Optional[Callable[[str], None]] = None
        self._app_context: str = "prose"  # captured at record start
        self._idle_timer: Optional[threading.Timer] = None
        self._warning_timer: Optional[threading.Timer] = None
        self._timeout_timer: Optional[threading.Timer] = None
        self._warming_up = False

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
            # Check if model is already loaded
            from api.recorder.transcribe import is_model_loaded
            model_name = self._cfg.get("model", "large-v3-turbo")
            self._set_status("warm" if is_model_loaded(model_name) else "cold")

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
            self._set_status("cold")

    @property
    def status(self) -> str:
        if self._listener and self._listener.is_recording:
            return "recording"
        return self._status

    @property
    def last_result(self) -> Optional[dict]:
        return self._last_result

    def _mute_audio(self, mute: bool) -> None:
        """Mute/unmute system audio — runs on own thread to avoid blocking hotkey listener."""
        threading.Thread(target=self._set_system_mute, args=(mute,), daemon=True).start()

    def _set_system_mute(self, mute: bool) -> None:
        try:
            import comtypes
            comtypes.CoInitialize()
            from pycaw.pycaw import AudioUtilities
            vol = AudioUtilities.GetSpeakers().EndpointVolume
            vol.SetMute(mute, None)
        except Exception:
            logger.debug("Audio mute control failed", exc_info=True)

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
        self._set_status("cold")

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
        """Called by hotkey listener on key press.

        If model is cold (not loaded), this press warms it up without recording.
        If model is warm, this press starts recording normally.
        """
        try:
            from api.recorder.transcribe import is_model_loaded, _get_model
            model_name = self._cfg.get("model", "large-v3-turbo")

            # Cold press — load model only, don't record
            if not is_model_loaded(model_name):
                self._set_status("loading")
                logger.info("Cold start — loading model '%s'", model_name)
                self._warming_up = True
                threading.Thread(
                    target=self._warm_up_model,
                    args=(model_name,),
                    daemon=True,
                    name="stt-warmup",
                ).start()
                return

            # Warm press — normal recording
            # Capture app context BEFORE recording
            from tools.stt.app_context import get_active_app_context
            self._app_context = get_active_app_context()
            logger.debug("App context at record start: %s", self._app_context)

            # Cancel idle timer while recording
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None

            self._set_status("recording")
            self._mute_audio(True)
            self._mic.start()

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
            self._set_status("warm")

    def _warm_up_model(self, model_name: str) -> None:
        """Load the Whisper model in a background thread (cold → warm)."""
        try:
            from api.recorder.transcribe import _get_model
            _get_model(model_name)
            logger.info("Model '%s' loaded — warm", model_name)
            self._set_status("warm")
        except Exception as e:
            logger.error("Model warmup failed: %s", e)
            self._set_status("error")
            time.sleep(2)
            self._set_status("cold")
        finally:
            self._warming_up = False

    def _on_record_stop(self) -> None:
        """Called by hotkey listener on key release. Runs pipeline in background thread."""
        self._mute_audio(False)  # unmute on same thread where mute worked
        # If we were warming up (cold press), don't run pipeline
        if self._warming_up:
            return
        # If not recording (e.g. cold press released after warmup finished), skip
        if not self._mic.is_recording:
            return
        self._cancel_recording_timers()
        threading.Thread(
            target=self._run_pipeline,
            daemon=True,
            name="stt-pipeline",
        ).start()

    def _run_pipeline(self) -> None:
        """Full dictation pipeline: transcribe → cleanup → inject → log."""
        self._set_status("processing")
        start_time = time.time()
        wav_path = None
        dictation_id = uuid.uuid4().hex[:8]

        try:
            # 1. Stop mic + transcribe (single Whisper pass — no seam artifacts)
            model_name = self._cfg.get("model", "large-v3-turbo")
            wav_path = self._mic.stop()
            from tools.stt.transcribe import transcribe
            raw_text = transcribe(wav_path, model_size=model_name)

            if not raw_text.strip():
                logger.info("Empty transcript, skipping")
                self._set_status("warm")
                self._reset_idle_timer()
                return

            # 3. Deterministic cleanup (no LLM, no VRAM) — context-aware
            from tools.stt.cleanup import cleanup_transcript
            cleaned_text = cleanup_transcript(raw_text, context=self._app_context)

            # 4. Inject text into active window
            from tools.stt.inject import inject_text
            inj_cfg = self._cfg.get("injection", {})
            method = inj_cfg.get("method", "auto")
            inject_text(cleaned_text, method=method)

            # 5. Success sound
            try:
                from tools.stt.sounds import play_success
                play_success(self._cfg)
            except Exception:
                pass

            # 6. Retain audio for voice model training (before WAV cleanup)
            audio_path, duration_s = (None, 0.0)
            if wav_path is not None:
                audio_path, duration_s = _maybe_retain_audio(
                    wav_path, dictation_id, self._cfg
                )

            # 7. Log to JSONL + manifest
            latency_ms = int((time.time() - start_time) * 1000)
            from tools.stt.logger import log_dictation
            record = log_dictation(
                raw_transcript=raw_text,
                cleaned_text=cleaned_text,
                latency_ms=latency_ms,
                whisper_model=model_name,
                cleanup_model="deterministic",
                dictation_id=dictation_id,
                audio_path=str(audio_path) if audio_path else None,
                duration_s=duration_s,
            )

            self._last_result = record
            logger.info(
                "Dictation complete: %s (%dms) — '%s'",
                record["id"], latency_ms, cleaned_text[:80],
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
            self._set_status("warm")
            self._reset_idle_timer()

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

            from tools.stt.cleanup import cleanup_transcript
            cleaned_text = cleanup_transcript(raw_text, context=self._app_context)

            from tools.stt.inject import inject_text
            inj_cfg = self._cfg.get("injection", {})
            inject_text(cleaned_text, method=inj_cfg.get("method", "auto"))

            latency_ms = int((time.time() - start_time) * 1000)
            from tools.stt.logger import log_dictation
            record = log_dictation(
                raw_transcript=raw_text,
                cleaned_text=cleaned_text,
                latency_ms=latency_ms,
                whisper_model=model_name,
                cleanup_model="deterministic",
            )

            self._last_result = record
            return record

        except Exception as e:
            logger.error("Manual dictation pipeline failed: %s", e)
            return None
        finally:
            self._set_status("warm" if self._listener else "cold")


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
