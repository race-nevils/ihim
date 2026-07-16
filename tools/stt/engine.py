"""Dictation pipeline orchestrator — record → transcribe → cleanup → inject → log.

Ties together audio capture, chunked Whisper transcription, deterministic
cleanup, clipboard injection, and JSONL logging. Manages the hotkey
listener lifecycle, VRAM lazy loading/unloading, and app-context detection.

No artificial recording time limits — this is local processing with zero
marginal cost. Hold-to-talk stops when you release; locked mode stops when
you press the stop key. The chunked transcriber banks finished speech
during recording, so release latency stays flat at any dictation length.
"""

import ctypes
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from tools.stt.audio import MicCapture, write_wav
from tools.stt.config import load_config
from tools.stt.hotkey import DEFAULT_HOTKEY, HotkeyListener

logger = logging.getLogger(__name__)

TRAINING_DIR = Path(__file__).parent / "data" / "voice-training"
RECOVERED_DIR = Path(__file__).parent / "data" / "recovered"


# ---------------------------------------------------------------------------
# Sleep detection (independent baseline from transcribe.py — that one guards
# CUDA models, this one guards pynput hooks and engine state)
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    def _unbiased_100ns() -> int:
        t = ctypes.c_uint64()
        ctypes.windll.kernel32.QueryUnbiasedInterruptTime(ctypes.byref(t))
        return t.value
else:
    _unbiased_100ns = None  # type: ignore[assignment]

_sleep_mono: float = time.monotonic()
_sleep_unbiased: int = _unbiased_100ns() if _unbiased_100ns is not None else 0


def _system_slept(threshold_s: float = 30.0) -> bool:
    """True if system slept since last check. Updates baseline on every call."""
    global _sleep_mono, _sleep_unbiased
    if _unbiased_100ns is None:
        return False
    mono_now = time.monotonic()
    unbiased_now = _unbiased_100ns()
    mono_gap = mono_now - _sleep_mono
    unbiased_gap = (unbiased_now - _sleep_unbiased) / 10_000_000
    _sleep_mono = mono_now
    _sleep_unbiased = unbiased_now
    return (mono_gap - unbiased_gap) > threshold_s


def _salvage_audio(blocks: list, rate: int, dictation_id: str) -> Optional[Path]:
    """Write a frozen recording to recovered/ — dictated audio is never lost.

    Called when the pipeline fails or blows its deadline: the transcript is
    gone but the audio survives on disk for offline transcription. (Before
    this existed, a wedged transcription orphaned the audio in %TEMP% —
    recoverable only by luck; 2026-07-16, 2026-07-11.)
    """
    try:
        if not blocks or not rate:
            return None
        RECOVERED_DIR.mkdir(parents=True, exist_ok=True)
        duration_s = sum(len(b) for b in blocks) / rate
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        out = RECOVERED_DIR / f"{stamp}_{dictation_id}_{int(round(duration_s))}s.wav"
        write_wav(blocks, rate, path=out)
        logger.error("Audio salvaged: %s (%.1fs)", out, duration_s)
        return out
    except Exception:
        logger.error("Audio salvage FAILED for %s", dictation_id, exc_info=True)
        return None


def _maybe_retain_audio(
    wav_path: Path, dictation_id: str, duration_s: float, cfg: dict
) -> Optional[Path]:
    """Retain audio as FLAC for voice model training if enabled.

    Returns the saved path, or None if retention is disabled or failed.
    """
    retention = cfg.get("audio_retention", {})
    if not retention.get("enabled", False):
        return None

    segments_dir = TRAINING_DIR / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

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
            return out_path
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
        return wav_out
    except Exception as exc:
        logger.warning("WAV fallback also failed: %s", exc)
        return None


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
        self._status = "cold"  # cold | warm | loading | recording | locked | processing | error
        self._on_state_change: Optional[Callable[[str], None]] = None
        self._app_context: str = "prose"  # captured at record start
        self._idle_timer: Optional[threading.Timer] = None
        self._streamer = None
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
            self._listener = self._new_listener()
            self._listener.start()
            from api.recorder.transcribe import is_model_loaded
            model_name = self._cfg.get("model", "large-v3-turbo")
            self._set_status("warm" if is_model_loaded(model_name) else "cold")

    def stop_listening(self) -> None:
        """Deactivate the hotkey listener."""
        with self._lock:
            if self._listener:
                self._listener.stop()
                self._listener = None
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            self._set_status("cold")

    def _new_listener(self) -> HotkeyListener:
        return HotkeyListener(
            on_start=self._on_record_start,
            on_stop=self._on_record_stop,
            hotkey=self._hotkey,
            lock_key=self._cfg.get("lock_key"),
            stop_key=self._cfg.get("stop_key"),
            on_locked=self._on_record_locked,
        )

    @property
    def status(self) -> str:
        # Recording-while-warming: an ack'd recording is genuine (the ack
        # gate guarantees it), so it outranks the warm-up in progress.
        if self._listener and self._listener.is_locked:
            return "locked"
        if self._listener and self._listener.is_recording:
            return "recording"
        if self._warming_up:
            return "loading"
        return self._status

    @property
    def last_result(self) -> Optional[dict]:
        return self._last_result

    def _mute_audio(self, mute: bool) -> None:
        """Mute/unmute system audio — own thread to avoid blocking the hotkey listener."""
        threading.Thread(target=self._set_system_mute, args=(mute,), daemon=True).start()

    def _set_system_mute(self, mute: bool) -> None:
        try:
            import comtypes
            comtypes.CoInitialize()
            try:
                from pycaw.pycaw import AudioUtilities
                vol = AudioUtilities.GetSpeakers().EndpointVolume
                vol.SetMute(mute, None)
            finally:
                comtypes.CoUninitialize()
        except Exception:
            logger.debug("Audio mute control failed", exc_info=True)

    def _reset_idle_timer(self) -> None:
        """Reset the VRAM idle unload timer."""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        timeout = self._cfg.get("idle_timeout_s", 600)
        self._idle_timer = threading.Timer(timeout, self._on_idle_timeout)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def on_system_suspend(self) -> None:
        """Proactively flush GPU models before system sleep.

        Without this, active CUDA contexts cause the NVIDIA driver to fail
        its power state transition (bugcheck 0x9F DRIVER_POWER_STATE_FAILURE).
        Called from power event handler on a worker thread — thread-safe.
        """
        logger.info("System suspending — flushing GPU models to prevent BSOD")
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        try:
            from api.recorder.transcribe import flush_all_models
            flush_all_models()
        except Exception as e:
            logger.error("Pre-sleep GPU flush failed: %s", e)
        self._set_status("cold")

    def on_system_resume(self) -> None:
        """Reset state after system wake.

        Consumes the sleep gap in both transcribe.py and engine.py baselines,
        then proactively recycles the pynput listener.  Without the proactive
        recycle, the first keypress after wake gets swallowed (detected as
        stale, triggers recycle, returns without recording).
        """
        logger.info("System resumed — resetting state and recycling listener")
        # A process that used CUDA carries undefined GPU-library state across
        # sleep (cuBLAS/CT2 bound to the reset primary context) — the next
        # encode() can hang forever, unloggable and uncatchable (2026-07-16:
        # 8 minutes of dictation stuck at PROCESSING). In-process recovery is
        # choreography against UB; process death is the only clean slate.
        try:
            from api.recorder.transcribe import cuda_was_used
            if cuda_was_used():
                logger.warning(
                    "CUDA was used in this process — restarting server for a "
                    "clean GPU context (in-process post-sleep recovery is UB)"
                )
                self._set_status("cold")
                self._restart_server_detached("post-sleep CUDA hygiene")
                return
        except Exception as e:
            logger.error("Post-wake CUDA-use check failed: %s", e)
        try:
            from api.recorder.transcribe import _check_system_sleep, evict_model_cache
            _check_system_sleep()  # updates CUDA baseline as side effect
            # Evict here, on the stable post-wake driver — the suspend-side
            # flush keeps the objects alive on purpose (destructor mid-suspend
            # crashed the server 2026-07-02, exception 0xe06d7363)
            evict_model_cache()
        except Exception as e:
            logger.error("Post-wake model-cache eviction failed: %s", e)
        # Consume engine-level sleep baseline so _on_record_start() doesn't
        # also detect sleep and swallow the first keypress
        _system_slept()
        # Proactively recycle pynput listener — hooks go stale after sleep
        self._recycle_listener()
        self._set_status("cold")

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

    def _on_record_locked(self) -> None:
        """Called by hotkey listener when lock key is pressed during recording."""
        self._set_status("locked")
        logger.info("Recording locked — hands-free, no time limit")
        try:
            from tools.stt.sounds import play_locked
            play_locked(self._cfg)
        except Exception:
            pass

    def _restart_server_detached(self, reason: str) -> None:
        """Spawn scripts/server.ps1 restart, detached — survives this process.

        Same invocation as /api/server/restart. The engine only runs in the
        live instance (test ports set IHIM_STT_AUTOSTART=0), so the port
        default matches the live server.
        """
        server_ps1 = Path(__file__).parents[2] / "scripts" / "server.ps1"
        if sys.platform != "win32" or not server_ps1.exists():
            logger.error("Cannot self-restart (%s): server.ps1 unavailable", reason)
            return
        port = os.environ.get("IHIM_PORT", "7777")
        flags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
        try:
            subprocess.Popen(
                [
                    "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(server_ps1), "restart",
                    "-Port", port, "-DelaySeconds", "2",
                ],
                creationflags=flags,
                close_fds=True,
                cwd=str(server_ps1.parents[1]),
            )
            logger.warning("Detached server restart spawned (%s)", reason)
        except Exception as e:
            logger.error("Failed to spawn detached restart (%s): %s", reason, e)

    def _recycle_listener(self) -> None:
        """Stop and restart the hotkey listener to clear stale OS hooks.

        Called automatically when sleep/wake is detected.  pynput keyboard
        hooks (SetWindowsHookEx) degrade after sleep — the hook thread's
        message pump accumulates stale messages and can deliver duplicate
        or phantom key events.
        """
        logger.info("Recycling hotkey listener (post-sleep cleanup)")
        with self._lock:
            if self._listener:
                self._listener.stop()
            self._listener = self._new_listener()
            self._listener.start()
        logger.info("Hotkey listener recycled — fresh OS hooks")

    def _on_record_start(self) -> bool:
        """Called by hotkey listener on chord press.

        Returns True only if recording actually started — the listener's
        recording/lock state machine follows this ack. A post-sleep press
        recycles the listener and is swallowed; a mic failure aborts.

        A cold press records THROUGH the model load: the mic doesn't need
        Whisper, so recording starts immediately while the model loads on
        a background thread. The streamer/finalize block on _get_model's
        single-flight load and catch up — speech from the very first
        press is kept, no press is ever swallowed waiting for warm.
        """
        # Recycle listener if system slept — pynput hooks go stale
        if _system_slept():
            logger.warning("Sleep detected — recycling hotkey listener before recording")
            self._recycle_listener()
            return False  # Swallow this press; recycled listener catches the next one

        try:
            from api.recorder.transcribe import is_model_loaded
            model_name = self._cfg.get("model", "large-v3-turbo")

            # Cold press — kick the model load, then fall through and record
            if not is_model_loaded(model_name) and not self._warming_up:
                logger.info("Cold start — loading model '%s' while recording", model_name)
                self._warming_up = True
                threading.Thread(
                    target=self._warm_up_model,
                    args=(model_name,),
                    daemon=True,
                    name="stt-warmup",
                ).start()

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

            # Start the chunked streaming transcriber
            try:
                from tools.stt.streaming import ChunkedTranscriber
                self._streamer = ChunkedTranscriber(self._mic, model_name)
                self._streamer.start()
            except Exception as e:
                logger.warning("Failed to start chunked transcriber: %s", e)
                self._streamer = None
            return True

        except Exception as e:
            logger.error("Failed to start mic capture: %s", e)
            self._mute_audio(False)
            self._set_status("warm")
            return False

    def _warm_up_model(self, model_name: str) -> None:
        """Load the Whisper model in a background thread (cold → warm)."""
        try:
            from api.recorder.transcribe import _get_model
            _get_model(model_name)
            logger.info("Model '%s' loaded — warm", model_name)
            listener = self._listener
            if listener and (listener.is_recording or listener.is_locked):
                # Recording rode through the load — don't stomp its status;
                # the pipeline broadcasts warm when it finishes.
                self._status = "warm"
            else:
                self._set_status("warm")
        except Exception as e:
            logger.error("Model warmup failed: %s", e)
            self._set_status("error")
            time.sleep(2)
            self._set_status("cold")
        finally:
            self._warming_up = False

    def _on_record_stop(self) -> None:
        """Called by hotkey listener on release. Runs pipeline in background thread."""
        self._mute_audio(False)  # unmute on same thread where mute worked
        if not self._mic.is_recording:
            return
        threading.Thread(
            target=self._run_pipeline,
            daemon=True,
            name="stt-pipeline",
        ).start()

    def _run_pipeline(self) -> None:
        """Full dictation pipeline: transcribe → cleanup → inject → log."""
        self._set_status("processing")
        start_time = time.time()
        dictation_id = uuid.uuid4().hex[:8]
        wav_path: Optional[Path] = None
        blocks: list = []
        rate = 0

        try:
            model_name = self._cfg.get("model", "large-v3-turbo")

            # 1. Freeze the audio at release — everything after is dead air.
            blocks, rate = self._mic.stop()
            duration_s = sum(len(b) for b in blocks) / rate if rate else 0.0

            # 2. Transcribe: banked chunks + one bounded final window.
            # Deadline watchdog: a wedged GPU hangs encode() forever with no
            # exception (post-sleep CUDA UB, 2026-07-16 — stuck at PROCESSING
            # with 8 minutes of speech). A hung thread can't be killed, so on
            # deadline: salvage the audio, surface the error, restart the
            # server — process death is the only reliable unwedge.
            transcribed = threading.Event()

            def _on_deadline() -> None:
                if transcribed.is_set():
                    return
                logger.error(
                    "Transcription blew its %.0fs deadline (%.1fs audio) — "
                    "salvaging audio and restarting the server",
                    deadline_s, duration_s,
                )
                _salvage_audio(blocks, rate, dictation_id)
                self._set_status("error")
                try:
                    from tools.stt.sounds import play_error
                    play_error(self._cfg)
                except Exception:
                    pass
                self._restart_server_detached("transcription deadline blown — GPU wedged")

            deadline_s = max(90.0, duration_s * 0.5)
            watchdog = threading.Timer(deadline_s, _on_deadline)
            watchdog.daemon = True
            watchdog.start()

            try:
                streamer, self._streamer = self._streamer, None
                if streamer is not None:
                    raw_text = streamer.finalize(blocks, rate)
                else:
                    # Chunked transcriber never started — single full pass.
                    from tools.stt.transcribe import transcribe
                    wav_path = write_wav(blocks, rate)
                    raw_text = transcribe(wav_path, model_size=model_name)
                    logger.info("FULL PASS: chunked transcriber unavailable")
            finally:
                transcribed.set()
                watchdog.cancel()

            if not raw_text.strip():
                logger.info("Empty transcript, skipping")
                return

            # 3. Deterministic cleanup (no LLM, no VRAM) — context-aware
            from tools.stt.cleanup import cleanup_transcript
            cleaned_text = cleanup_transcript(raw_text, context=self._app_context)

            # 4. Inject text into active window
            from tools.stt.inject import inject_text
            method = self._cfg.get("injection", {}).get("method", "auto")
            inject_text(cleaned_text, method=method)

            # 5. Success sound
            try:
                from tools.stt.sounds import play_success
                play_success(self._cfg)
            except Exception:
                pass

            # 6. Retain audio for voice model training
            audio_path = None
            if self._cfg.get("audio_retention", {}).get("enabled", False):
                if wav_path is None:
                    wav_path = write_wav(blocks, rate)
                audio_path = _maybe_retain_audio(
                    wav_path, dictation_id, duration_s, self._cfg
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
                "Dictation complete: %s (%.1fs audio, %dms to inject) — '%s'",
                record["id"], duration_s, latency_ms, cleaned_text[:80],
            )

        except Exception as e:
            logger.error("Dictation pipeline failed: %s", e, exc_info=True)
            _salvage_audio(blocks, rate, dictation_id)
            self._set_status("error")
            try:
                from tools.stt.sounds import play_error
                play_error(self._cfg)
            except Exception:
                pass
            # Let error state show for 2s before returning to listening
            time.sleep(2)

        finally:
            try:
                if wav_path is not None and wav_path.exists():
                    wav_path.unlink()
            except Exception:
                pass
            self._set_status("warm")
            self._reset_idle_timer()


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
