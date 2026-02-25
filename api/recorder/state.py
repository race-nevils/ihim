"""Thread-safe singleton tracking recorder lifecycle.

States: idle → recording → transcribing → idle  (+ error dead-end via /reset)
"""

import threading
from datetime import datetime, timezone
from typing import Optional

from api.recorder.models import RecorderStatus


class RecorderState:
    """In-memory singleton for the recorder lifecycle."""

    _instance: Optional["RecorderState"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "RecorderState":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._status = RecorderStatus.idle
                    inst._recording_id: Optional[str] = None
                    inst._label: Optional[str] = None
                    inst._participant_name: Optional[str] = None
                    inst._started_at: Optional[datetime] = None
                    inst._mic_device: Optional[str] = None
                    inst._sys_device: Optional[str] = None
                    inst._error: Optional[str] = None
                    inst._state_lock = threading.Lock()
                    cls._instance = inst
        return cls._instance

    # ── Properties ────────────────────────────────────────────────────

    @property
    def status(self) -> RecorderStatus:
        return self._status

    @property
    def recording_id(self) -> Optional[str]:
        return self._recording_id

    @property
    def label(self) -> Optional[str]:
        return self._label

    @property
    def participant_name(self) -> Optional[str]:
        return self._participant_name

    @property
    def started_at(self) -> Optional[datetime]:
        return self._started_at

    @property
    def mic_device(self) -> Optional[str]:
        return self._mic_device

    @property
    def sys_device(self) -> Optional[str]:
        return self._sys_device

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def elapsed_seconds(self) -> Optional[float]:
        if self._started_at and self._status == RecorderStatus.recording:
            return (datetime.now(timezone.utc) - self._started_at).total_seconds()
        return None

    # ── Transitions ───────────────────────────────────────────────────

    def start_recording(
        self,
        recording_id: str,
        label: Optional[str],
        mic_device: str,
        sys_device: str,
        participant_name: Optional[str] = None,
    ) -> None:
        with self._state_lock:
            if self._status not in (RecorderStatus.idle,):
                raise RuntimeError(f"Cannot start: state is {self._status.value}")
            self._status = RecorderStatus.recording
            self._recording_id = recording_id
            self._label = label
            self._participant_name = participant_name
            self._started_at = datetime.now(timezone.utc)
            self._mic_device = mic_device
            self._sys_device = sys_device
            self._error = None

    def stop_recording(self) -> None:
        with self._state_lock:
            if self._status != RecorderStatus.recording:
                raise RuntimeError(f"Cannot stop: state is {self._status.value}")
            self._status = RecorderStatus.transcribing

    def finish_transcription(self) -> None:
        with self._state_lock:
            if self._status != RecorderStatus.transcribing:
                raise RuntimeError(f"Cannot finish: state is {self._status.value}")
            self._status = RecorderStatus.idle
            self._recording_id = None
            self._label = None
            self._participant_name = None
            self._started_at = None
            self._mic_device = None
            self._sys_device = None

    def set_error(self, message: str) -> None:
        with self._state_lock:
            self._status = RecorderStatus.error
            self._error = message

    def reset(self) -> None:
        with self._state_lock:
            self._status = RecorderStatus.idle
            self._recording_id = None
            self._label = None
            self._participant_name = None
            self._started_at = None
            self._mic_device = None
            self._sys_device = None
            self._error = None

    # ── Snapshot ──────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a dict suitable for the status endpoint."""
        with self._state_lock:
            return {
                "status": self._status,
                "recording_id": self._recording_id,
                "label": self._label,
                "participant_name": self._participant_name,
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "elapsed_seconds": self.elapsed_seconds,
                "mic_device": self._mic_device,
                "sys_device": self._sys_device,
                "error": self._error,
            }
