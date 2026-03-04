"""Pydantic request/response schemas for the meeting recorder."""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class RecorderStatus(str, Enum):
    idle = "idle"
    recording = "recording"
    transcribing = "transcribing"
    error = "error"


class ModelSize(str, Enum):
    tiny = "tiny"
    base = "base"
    small = "small"
    small_en = "small.en"
    medium = "medium"
    medium_en = "medium.en"
    large_v3 = "large-v3"


# ── Requests ──────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    label: Optional[str] = Field(None, description="Human-readable label for the recording")
    participant_name: Optional[str] = Field(None, description="Name of the other participant (default: 'Other')")
    model_size: ModelSize = Field(ModelSize.large_v3, description="Whisper model size for transcription")
    mic_device_index: Optional[int] = Field(None, description="Mic device index (None = default)")
    sys_device_index: Optional[int] = Field(None, description="WASAPI loopback device index (None = auto-detect)")


# ── Responses ─────────────────────────────────────────────────────────

class StatusResponse(BaseModel):
    status: RecorderStatus
    recording_id: Optional[str] = None
    label: Optional[str] = None
    started_at: Optional[str] = None
    elapsed_seconds: Optional[float] = None
    mic_device: Optional[str] = None
    sys_device: Optional[str] = None
    error: Optional[str] = None


class DeviceInfo(BaseModel):
    index: int
    name: str
    channels: int
    sample_rate: float
    is_loopback: bool = False


class DevicesResponse(BaseModel):
    mic_devices: list[DeviceInfo]
    system_devices: list[DeviceInfo]
    errors: list[str] = Field(default_factory=list, description="Enumeration errors (diagnostic)")


class SegmentOut(BaseModel):
    speaker: str
    start: float
    end: float
    text: str
    confidence: float


class RecordingSummary(BaseModel):
    recording_id: str
    label: Optional[str] = None
    started_at: str
    duration_seconds: Optional[float] = None
    status: str


class RecordingDetail(BaseModel):
    recording_id: str
    label: Optional[str] = None
    started_at: str
    ended_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    config: dict = {}
    speakers: dict = {}
    segments: list[SegmentOut] = []
    transcript: str = ""
    wav_mic: Optional[str] = None
    wav_sys: Optional[str] = None
    status: str = "complete"


class StopResponse(BaseModel):
    recording_id: str
    duration_seconds: float
    status: str = "pending_transcription"


class TranscribeResponse(BaseModel):
    recording_id: str
    duration_seconds: float
    segments_count: int
    transcript_preview: str
    status: str = "complete"


class StartResponse(BaseModel):
    success: bool = True
    recording_id: str
    label: Optional[str] = None
    mic_device: Optional[str] = None
    sys_device: Optional[str] = None
    model_size: str


class RecordingsListResponse(BaseModel):
    recordings: list[RecordingSummary] = []


class DeleteResponse(BaseModel):
    success: bool = True
    deleted: list[str] = []


class ResetResponse(BaseModel):
    success: bool = True
    status: str = "idle"
