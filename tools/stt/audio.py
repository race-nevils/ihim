"""Mic capture for dictation — wraps DualStreamCapture in mic-only mode."""

import logging
import tempfile
import threading
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
        """Stop capture, save 16kHz mono WAV to temp file, return path."""
        with self._lock:
            if self._capture is None:
                raise RuntimeError("MicCapture.stop() called but not recording")
            self._capture.stop()
            capture = self._capture
            self._capture = None

        # Save mic channel to a temp WAV
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        mic_path = Path(tmp.name)
        tmp.close()

        # DualStreamCapture.save() writes both channels; we only need mic
        # Pass a dummy path for sys since sys_device_index=None produces empty buffer
        dummy_sys = Path(tempfile.mktemp(suffix=".wav"))
        capture.save(mic_path, dummy_sys)

        # Clean up dummy sys file
        if dummy_sys.exists():
            dummy_sys.unlink()

        logger.info("Mic capture saved: %s", mic_path)
        return mic_path

    @property
    def is_recording(self) -> bool:
        return self._capture is not None
