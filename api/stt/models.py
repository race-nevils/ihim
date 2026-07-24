"""Pydantic request/response schemas for the STT dictation API."""

from pydantic import BaseModel, Field
from typing import Optional


# ── Responses ─────────────────────────────────────────────────────────

class CorrectionDetail(BaseModel):
    text: str = Field(..., description="Corrected text")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp of correction")
    sha256: str = Field(..., description="SHA-256 hash of corrected text")


class DictationRecord(BaseModel):
    id: str = Field(..., description="Unique dictation ID")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")
    raw_transcript: str = Field(..., description="Raw Whisper output")
    cleaned_text: str = Field(..., description="LLM-cleaned text")
    whisper_model: str = Field("small", description="Whisper model used")
    cleanup_model: str = Field("llama3.2:3b", description="LLM cleanup model used")
    latency_ms: int = Field(..., description="Total pipeline latency in ms")
    correction: Optional[CorrectionDetail] = Field(None, description="User correction if applied")
    flagged: bool = Field(False, description="Whether this dictation is flagged for review")


class HistoryResponse(BaseModel):
    dictations: list[DictationRecord] = Field(default_factory=list)
    total: int = Field(0, description="Total number of dictations in history")
    total_words: int = Field(0, description="Total words dictated")


class StatsResponse(BaseModel):
    total: int = Field(0, description="Total dictation count")
    corrections: int = Field(0, description="Number of corrected dictations")
    flagged: int = Field(0, description="Number of flagged dictations")
    avg_latency_ms: int = Field(0, description="Average pipeline latency in ms")
    total_words: int = Field(0, description="Total words dictated")


class StatusResponse(BaseModel):
    active: bool = Field(False, description="Whether the hotkey listener is active")
    status: str = Field("idle", description="Engine status: idle | listening | recording | processing")
    model_loaded: bool = Field(False, description="Whether the Whisper model is cached")
    last_result_id: Optional[str] = Field(None, description="ID of the most recent dictation result")
    mute_on_dictate: bool = Field(True, description="Whether system audio is muted while dictating")


# ── Requests ──────────────────────────────────────────────────────────

class CorrectionRequest(BaseModel):
    corrected_text: str = Field(..., min_length=1, description="The corrected dictation text")


class SuccessResponse(BaseModel):
    success: bool = True
    message: str = ""


class VocabResponse(BaseModel):
    terms: list[str] = Field(default_factory=list, description="Vocabulary terms for Whisper priming")


class MuteUpdateRequest(BaseModel):
    enabled: bool = Field(..., description="Mute system audio while dictating")


class VocabUpdateRequest(BaseModel):
    add: list[str] = Field(default_factory=list, description="Terms to add")
    remove: list[str] = Field(default_factory=list, description="Terms to remove")
