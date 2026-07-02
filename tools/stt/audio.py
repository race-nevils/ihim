"""Mic capture for dictation — wraps DualStreamCapture in mic-only mode.

Audio lives as a list of ~0.5s float32 blocks that grows while recording.
The streaming transcriber reads a live snapshot() during recording;
stop() freezes the buffer at release (drain-aware, so the in-flight
block holding the last word's tail is included) and returns it.
"""

import logging
import tempfile
import threading
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def write_wav(blocks: list, sample_rate: int, path: Optional[Path] = None) -> Path:
    """Write float32 mono blocks as a 16-bit WAV at native sample rate.

    No normalization, no resampling — faster-whisper resamples internally
    with its own anti-aliasing filter. Creates a temp file when *path* is
    None. Returns the path written.
    """
    import numpy as np

    if path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        path = Path(tmp.name)
        tmp.close()

    if blocks:
        audio = np.concatenate(blocks)
        pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    else:
        pcm = np.zeros(0, dtype=np.int16)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return path


class MicCapture:
    """Record microphone audio into float32 blocks.

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

    def snapshot(self) -> tuple[list, int]:
        """Live (blocks so far, native sample rate). Safe during capture."""
        capture = self._capture
        if capture is None:
            return [], 16000
        return capture.mic_blocks(), capture.mic_sample_rate

    def stop(self) -> tuple[list, int]:
        """Stop capture and return the frozen (blocks, sample_rate).

        Waits for the capture thread's in-flight block read to land before
        snapshotting, so the audio ends at the release point — including
        the tail of the last spoken word — with no post-release dead air.
        """
        with self._lock:
            if self._capture is None:
                raise RuntimeError("MicCapture.stop() called but not recording")
            capture = self._capture
            self._capture = None

        if not capture.stop_mic_and_drain(timeout=1.5):
            logger.warning("Mic drain timed out — snapshotting current buffers")
        blocks = capture.mic_blocks()
        rate = capture.mic_sample_rate
        logger.info("Mic capture stopped (%d blocks)", len(blocks))
        return blocks, rate

    @property
    def is_recording(self) -> bool:
        return self._capture is not None
