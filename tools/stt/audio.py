"""Mic capture for dictation — wraps DualStreamCapture in mic-only mode."""

import logging
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class MicCapture:
    """Record microphone audio to a temp WAV file.

    Uses DualStreamCapture with sys_device_index=None (mic-only mode).
    """

    def __init__(self, mic_device_index: Optional[int] = None):
        self._mic_device_index = mic_device_index
        self._capture = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Begin mic capture."""
        from api.recorder.capture import DualStreamCapture

        with self._lock:
            if self._capture is not None:
                logger.warning("MicCapture.start() called while already recording")
                return
            self._capture = DualStreamCapture(
                mic_device_index=self._mic_device_index,
                sys_device_index=None,  # mic-only
            )
            self._capture.start()
            logger.info("Mic capture started")

    def stop(self) -> Path:
        """Stop capture, write WAV from buffers, return path.

        Signals stop without joining threads — capture.stop() has a 5s
        thread.join timeout that blocks every time (sounddevice stream.stop
        hangs on Windows). Instead, read buffers directly and write WAV.
        Threads are daemon and clean up on their own.
        """
        import numpy as np

        with self._lock:
            if self._capture is None:
                raise RuntimeError("MicCapture.stop() called but not recording")
            capture = self._capture
            buffers = list(capture._mic_buffers)
            native_rate = int(capture._mic_info["sample_rate"])
            capture._stop_event.set()
            self._capture = None

        # Write WAV at native rate — Whisper resamples internally
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        mic_path = Path(tmp.name)
        tmp.close()

        if buffers:
            audio = np.concatenate(buffers)
            pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
        else:
            pcm = np.zeros(0, dtype=np.int16)

        with wave.open(str(mic_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(native_rate)
            wf.writeframes(pcm.tobytes())

        logger.info("Mic capture saved: %s (%d buffers)", mic_path, len(buffers))
        return mic_path

    def stop_fast(self) -> None:
        """Stop capture without saving to disk. Use when transcription is already done."""
        with self._lock:
            if self._capture is None:
                raise RuntimeError("MicCapture.stop_fast() called but not recording")
            self._capture._stop_event.set()
            self._capture = None
        logger.info("Mic capture stopped (no save)")

    @property
    def is_recording(self) -> bool:
        return self._capture is not None
