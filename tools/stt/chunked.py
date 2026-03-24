"""Silero VAD-based chunked transcription — transcribes during recording.

Uses faster_whisper.vad.get_speech_timestamps() (Silero VAD v6) to detect
speech boundaries. Completed utterances are transcribed in background threads
while recording continues, so only the final chunk needs processing after
hotkey release.

Standard pattern used by Google STT, AWS Transcribe, Azure Speech.
"""

import logging
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Minimum blocks before attempting VAD (each block = 500ms at native rate)
_MIN_BLOCKS_FOR_VAD = 4  # 2 seconds of audio


class ChunkedTranscriber:
    """Transcribes speech chunks during recording for lower release-to-text latency."""

    def __init__(self, model_name: str, config: dict):
        self._model_name = model_name
        self._min_silence_ms = config.get("min_silence_ms", 1500)
        self._min_speech_ms = config.get("min_speech_ms", 500)
        self._speech_pad_ms = config.get("speech_pad_ms", 200)
        self._poll_interval = config.get("poll_interval_s", 2.0)

        self._capture = None          # DualStreamCapture reference
        self._native_rate: int = 0    # device sample rate (e.g. 48000)
        self._buf_cursor: int = 0     # index into _mic_buffers consumed so far
        self._pending_audio: list = []  # audio blocks since last dispatched chunk
        self._completed_texts: list[str] = []
        self._dispatch_threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._watcher_thread: Optional[threading.Thread] = None
        self._results_lock = threading.Lock()
        self._failed = False

    def start(self, capture) -> None:
        """Begin watching the capture's mic buffers for speech boundaries."""
        self._capture = capture
        self._native_rate = int(capture._mic_info["sample_rate"])
        self._buf_cursor = 0
        self._pending_audio = []
        self._completed_texts = []
        self._dispatch_threads = []
        self._stop_event.clear()
        self._failed = False

        self._watcher_thread = threading.Thread(
            target=self._watcher_loop,
            daemon=True,
            name="stt-chunked-watcher",
        )
        self._watcher_thread.start()
        logger.info("Chunked transcriber started (poll=%.1fs, silence=%dms)",
                     self._poll_interval, self._min_silence_ms)

    def finalize(self) -> str:
        """Stop watching, transcribe remaining audio, return concatenated text.

        Called by the pipeline thread after mic.stop().
        """
        # Signal watcher to exit
        self._stop_event.set()
        if self._watcher_thread is not None:
            self._watcher_thread.join(timeout=5)

        # Grab any remaining audio not yet consumed
        remaining = self._drain_remaining()

        # Transcribe the tail chunk if there's enough audio
        if remaining is not None and len(remaining) > 0:
            tail_samples_16k = len(self._resample_to_16k(remaining))
            min_samples = int(16000 * self._min_speech_ms / 1000)
            if tail_samples_16k >= min_samples:
                self._dispatch_chunk(remaining, label="tail")

        # Wait for all dispatch threads to finish
        for t in self._dispatch_threads:
            t.join(timeout=30)

        with self._results_lock:
            result = " ".join(t for t in self._completed_texts if t.strip())

        if result.strip():
            logger.info("Chunked transcription: %d chunks, %d chars",
                        len(self._completed_texts), len(result))

        return result

    # ── Internal ──────────────────────────────────────────────────────

    def _watcher_loop(self) -> None:
        """Poll mic buffers, run VAD, dispatch completed utterances."""
        try:
            from faster_whisper.vad import get_speech_timestamps, VadOptions

            vad_options = VadOptions(
                threshold=0.5,
                min_silence_duration_ms=self._min_silence_ms,
                min_speech_duration_ms=self._min_speech_ms,
                speech_pad_ms=self._speech_pad_ms,
            )

            while not self._stop_event.wait(self._poll_interval):
                try:
                    self._poll_once(vad_options, get_speech_timestamps)
                except Exception:
                    logger.debug("Chunked watcher poll error", exc_info=True)

        except Exception as e:
            logger.warning("Chunked watcher failed to start: %s", e)
            self._failed = True

    def _poll_once(self, vad_options, get_speech_timestamps) -> None:
        """Single poll cycle: read new buffers, check for speech boundaries."""
        capture = self._capture
        if capture is None:
            return

        # Read new blocks from capture
        buffers = capture._mic_buffers
        new_blocks = buffers[self._buf_cursor:]
        if not new_blocks:
            return
        self._buf_cursor = len(buffers)
        self._pending_audio.extend(new_blocks)

        # Need enough audio for meaningful VAD
        if len(self._pending_audio) < _MIN_BLOCKS_FOR_VAD:
            return

        # Concatenate and resample for VAD
        audio = np.concatenate(self._pending_audio)
        audio_16k = self._resample_to_16k(audio)

        # Run VAD
        timestamps = get_speech_timestamps(audio_16k, vad_options, sampling_rate=16000)

        if not timestamps:
            return

        # Check if the last speech segment has ended (silence at the tail)
        last_end = timestamps[-1]["end"]
        total_samples = len(audio_16k)
        silence_at_tail = total_samples - last_end
        min_silence_samples = int(16000 * self._min_silence_ms / 1000)

        if silence_at_tail < min_silence_samples:
            # Speech is still ongoing or silence too short — keep accumulating
            return

        # We have a completed utterance: extract speech portion up to last_end
        # Convert 16kHz sample index back to native rate
        ratio = self._native_rate / 16000
        cut_at_native = int(last_end * ratio)

        if cut_at_native <= 0 or cut_at_native > len(audio):
            return

        speech_audio = audio[:cut_at_native]
        remaining_audio = audio[cut_at_native:]

        # Dispatch the completed chunk for transcription
        chunk_num = len(self._dispatch_threads) + 1
        self._dispatch_chunk(speech_audio, label=f"chunk-{chunk_num}")

        # Keep remaining audio for next cycle
        self._pending_audio = [remaining_audio] if len(remaining_audio) > 0 else []

    def _drain_remaining(self) -> Optional[np.ndarray]:
        """Collect any audio not yet dispatched."""
        capture = self._capture
        if capture is None:
            if self._pending_audio:
                return np.concatenate(self._pending_audio)
            return None

        # Grab anything added after our last cursor position
        buffers = capture._mic_buffers
        new_blocks = buffers[self._buf_cursor:]
        all_pending = self._pending_audio + list(new_blocks)

        if not all_pending:
            return None

        return np.concatenate(all_pending)

    def _resample_to_16k(self, audio: np.ndarray) -> np.ndarray:
        """Downsample to 16kHz for Silero VAD input.

        Simple decimation — acceptable for VAD (speech/silence detection).
        Transcription uses faster-whisper's proper resampler via temp WAV.
        """
        factor = self._native_rate / 16000
        if factor <= 1.0:
            return audio.copy()
        # Integer factor: simple decimation (e.g. 48000/16000 = 3)
        int_factor = int(round(factor))
        if abs(factor - int_factor) < 0.01:
            return audio[::int_factor].copy()
        # Non-integer factor: linear interpolation
        n_samples = int(len(audio) / factor)
        indices = np.linspace(0, len(audio) - 1, n_samples)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

    def _dispatch_chunk(self, audio: np.ndarray, label: str = "chunk") -> None:
        """Write audio to temp WAV, transcribe, store result."""
        # Run transcription in a thread (sequential — GPU serializes anyway)
        t = threading.Thread(
            target=self._transcribe_chunk,
            args=(audio, label),
            daemon=True,
            name=f"stt-chunked-{label}",
        )
        self._dispatch_threads.append(t)
        t.start()

    def _transcribe_chunk(self, audio: np.ndarray, label: str) -> None:
        """Write chunk WAV, transcribe, append result."""
        wav_path = None
        try:
            wav_path = self._write_chunk_wav(audio)
            from tools.stt.transcribe import transcribe
            text = transcribe(wav_path, model_size=self._model_name)
            with self._results_lock:
                self._completed_texts.append(text)
            logger.info("Chunked %s transcribed: '%s'", label, text[:80] if text else "")
        except Exception as e:
            logger.warning("Chunk %s transcription failed: %s", label, e)
            self._failed = True
        finally:
            if wav_path is not None:
                try:
                    wav_path.unlink()
                except Exception:
                    pass

    def _write_chunk_wav(self, audio: np.ndarray) -> Path:
        """Write audio to a temp WAV file at native sample rate."""
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="stt-chunk-")
        wav_path = Path(tmp.name)
        tmp.close()

        # Normalize to prevent clipping
        peak = np.abs(audio).max()
        if peak > 0:
            audio = audio / peak * 0.95

        pcm = (audio * 32767).astype(np.int16)

        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._native_rate)
            wf.writeframes(pcm.tobytes())

        return wav_path
