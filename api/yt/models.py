"""Pydantic models for the YT transcriber."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

ModelSize = Literal[
    "tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"
]

# Job lifecycle:
#   queued -> starting -> fetching_metadata -> downloading -> waiting_for_gpu
#   -> transcribing <-> paused_for_dictation -> complete | duplicate | failed
ACTIVE_STATUSES = {
    "starting", "fetching_metadata", "downloading",
    "waiting_for_gpu", "transcribing", "paused_for_dictation",
}
TERMINAL_STATUSES = {"complete", "duplicate", "failed"}


class SubmitRequest(BaseModel):
    url: str = Field(min_length=10, max_length=2000, pattern=r"^https?://")
    model_size: ModelSize = "large-v3-turbo"
    # Re-transcribe even if a .txt for this video id already exists.
    force: bool = False


class JobOut(BaseModel):
    job_id: str
    url: str
    status: str
    title: Optional[str] = None
    video_id: Optional[str] = None
    uploader: Optional[str] = None
    duration_seconds: Optional[float] = None
    # 0.0-1.0 within the current stage (download bytes or transcribed time).
    progress: Optional[float] = None
    error: Optional[str] = None
    txt_file: Optional[str] = None
    segments_count: Optional[int] = None
    created_at: Optional[str] = None
    finished_at: Optional[str] = None


class JobsListResponse(BaseModel):
    jobs: list[JobOut]
    active_job_id: Optional[str] = None


class CancelResponse(BaseModel):
    job_id: str
    status: str


class DeleteResponse(BaseModel):
    deleted: list[str]


class TextResponse(BaseModel):
    job_id: str
    txt_file: str
    text: str
