"""FastAPI router for the meeting recorder.

Endpoints: start, stop, status, devices, list, view, delete, reset.
Transcription runs in thread pool to avoid blocking the event loop.
"""

import asyncio
import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from api.errors import problem

from api.recorder.models import (
    StartRequest, StartResponse, StatusResponse, DevicesResponse, DeviceInfo,
    StopResponse, RecordingSummary, RecordingDetail, SegmentOut,
    RecordingsListResponse, DeleteResponse, ResetResponse,
    RecorderStatus,
)
from api.recorder.state import RecorderState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recorder", tags=["recorder"])

# Paths
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "local"
RECORDINGS_DIR = DATA_DIR / "recordings"
BRAIN_DIR = DATA_DIR / "brain" / "Meetings"

# Singleton state
_state = RecorderState()

# Active capture engine (set during recording), protected by _capture_lock
_capture = None
_capture_lock = threading.Lock()

# Path traversal guard: recording IDs must match YYYYMMDD-HHMMSS
RECORDING_ID_RE = re.compile(r'^\d{8}-\d{6}$')


def _recording_id() -> str:
    """Generate a recording ID from current timestamp."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _validate_recording_id(recording_id: str, request: Request):
    """Validate recording ID format to prevent path traversal."""
    if not RECORDING_ID_RE.match(recording_id):
        return problem(400, "Invalid recording ID format", instance=request.url.path)
    return None


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.get("/status", response_model=StatusResponse)
async def recorder_status():
    """Current recorder state + elapsed time."""
    return StatusResponse(**_state.snapshot())


@router.get("/devices", response_model=DevicesResponse)
async def recorder_devices(request: Request):
    """List available mic and WASAPI loopback devices."""
    try:
        from api.recorder.capture import list_audio_devices
        raw = list_audio_devices()
        return DevicesResponse(
            mic_devices=[DeviceInfo(**d) for d in raw["mic_devices"]],
            system_devices=[DeviceInfo(**d) for d in raw["system_devices"]],
        )
    except Exception as e:
        logger.error("Failed to enumerate audio devices: %s", e)
        return problem(503, f"Failed to enumerate audio devices: {e}", instance=request.url.path)


@router.post("/start", response_model=StartResponse)
async def recorder_start(body: StartRequest, request: Request):
    """Start recording mic + system audio."""
    global _capture

    if _state.status != RecorderStatus.idle:
        return problem(
            409,
            f"Recorder is {_state.status.value}, not idle",
            instance=request.url.path,
        )

    try:
        from api.recorder.capture import DualStreamCapture

        rec_id = _recording_id()
        capture = DualStreamCapture(
            mic_device_index=body.mic_device_index,
            sys_device_index=body.sys_device_index,
        )
        capture.start()

        _state.start_recording(
            recording_id=rec_id,
            label=body.label,
            mic_device=capture.mic_device_name,
            sys_device=capture.sys_device_name,
            participant_name=body.participant_name,
        )
        with _capture_lock:
            _capture = capture

        logger.info("Recording started: %s (label=%s)", rec_id, body.label)

        return StartResponse(
            recording_id=rec_id,
            label=body.label,
            mic_device=capture.mic_device_name,
            sys_device=capture.sys_device_name,
            model_size=body.model_size.value,
        )
    except Exception as e:
        _state.set_error(str(e))
        logger.error("Failed to start recording: %s", e)
        return problem(503, f"Failed to start recording: {e}", instance=request.url.path)


@router.post("/stop", response_model=StopResponse)
async def recorder_stop(request: Request):
    """Stop recording, transcribe, and return results.

    Blocks until transcription is complete (may take 30-120s on CPU).
    """
    global _capture

    if _state.status != RecorderStatus.recording:
        return problem(
            409,
            f"Recorder is {_state.status.value}, not recording",
            instance=request.url.path,
        )

    rec_id = _state.recording_id
    label = _state.label
    started_at = _state.started_at
    mic_device = _state.mic_device
    sys_device = _state.sys_device

    # ── Block 1: Stop capture + save WAV files (fatal if fails) ──
    try:
        with _capture_lock:
            _capture.stop()
            local_capture = _capture
            _capture = None
        _state.stop_recording()

        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        mic_path = RECORDINGS_DIR / f"recording-{rec_id}-mic.wav"
        sys_path = RECORDINGS_DIR / f"recording-{rec_id}-sys.wav"
        local_capture.save(mic_path, sys_path)
        capture_errors = local_capture.errors
    except Exception as e:
        _state.set_error(str(e))
        with _capture_lock:
            _capture = None
        logger.error("Audio save failed for %s: %s", rec_id, e)
        return problem(500, f"Audio save failed: {e}", instance=request.url.path)

    # ── Block 2: Transcription (non-fatal — save recording regardless) ──
    segments = []
    transcript = ""
    sidecar_status = "complete"
    transcription_error = None

    try:
        from api.recorder.transcribe import transcribe_dual

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: transcribe_dual(mic_path, sys_path, model_size="small"),
        )
        segments = result["segments"]
        transcript = result["transcript"]

        if not segments:
            sidecar_status = "no_transcript"
    except Exception as e:
        logger.error("Transcription failed for %s: %s", rec_id, e)
        sidecar_status = "transcription_failed"
        transcription_error = str(e)

    # ── Block 3: Sidecar write (always runs after audio save) ──
    ended_at = datetime.now(timezone.utc)
    duration = (ended_at - started_at).total_seconds() if started_at else 0

    sidecar = {
        "recording_id": rec_id,
        "label": label,
        "started_at": started_at.isoformat() if started_at else None,
        "ended_at": ended_at.isoformat(),
        "duration_seconds": round(duration, 1),
        "config": {
            "model_size": "small",
            "sample_rate": 16000,
            "mic_device": mic_device,
            "sys_device": sys_device,
        },
        "speakers": {"mic": "the operator", "system": _state.participant_name or "Other"},
        "segments": segments,
        "transcript": transcript,
        "wav_mic": mic_path.name,
        "wav_sys": sys_path.name,
        "status": sidecar_status,
    }
    if capture_errors:
        sidecar["capture_warnings"] = capture_errors
    if transcription_error:
        sidecar["transcription_error"] = transcription_error

    sidecar_path = RECORDINGS_DIR / f"recording-{rec_id}.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    # ── Block 3b: Transcript markdown (non-fatal, only if segments exist) ──
    if segments:
        try:
            md_path = RECORDINGS_DIR / f"recording-{rec_id}-transcript.md"
            _write_transcript_md(
                rec_id=rec_id,
                label=label,
                started_at=started_at,
                duration=duration,
                speakers=sidecar["speakers"],
                segments=segments,
                output_path=md_path,
            )
        except Exception as md_err:
            logger.error("Failed to write transcript markdown for %s: %s", rec_id, md_err)

    # ── Block 4: Brain entry (non-fatal, existing pattern) ──
    try:
        _create_brain_entry(rec_id, label, started_at, duration, transcript)
    except Exception as brain_err:
        logger.error("Failed to create brain entry for %s: %s", rec_id, brain_err)

    # ── Always transition state out of "transcribing" ──
    _state.finish_transcription()

    logger.info("Recording complete: %s (%.1fs, %d segments, status=%s)",
                rec_id, duration, len(segments), sidecar_status)

    preview = transcript[:500]
    if len(transcript) > 500:
        preview += "..."

    return StopResponse(
        recording_id=rec_id,
        duration_seconds=round(duration, 1),
        segments_count=len(segments),
        transcript_preview=preview,
        status=sidecar_status,
    )


@router.get("/recordings", response_model=RecordingsListResponse)
async def list_recordings():
    """List all past recordings (scans sidecar JSONs)."""
    if not RECORDINGS_DIR.exists():
        return RecordingsListResponse(recordings=[])

    recordings = []
    for f in sorted(RECORDINGS_DIR.glob("recording-*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            recordings.append(RecordingSummary(
                recording_id=data["recording_id"],
                label=data.get("label"),
                started_at=data["started_at"],
                duration_seconds=data.get("duration_seconds"),
                status=data.get("status", "unknown"),
            ))
        except Exception:
            continue

    return RecordingsListResponse(recordings=recordings)


@router.get("/recordings/{recording_id}", response_model=RecordingDetail)
async def get_recording(recording_id: str, request: Request):
    """Full recording detail + transcript."""
    err = _validate_recording_id(recording_id, request)
    if err:
        return err

    sidecar = RECORDINGS_DIR / f"recording-{recording_id}.json"
    if not sidecar.exists():
        return problem(404, f"Recording '{recording_id}' not found", instance=request.url.path)

    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return RecordingDetail(
            recording_id=data["recording_id"],
            label=data.get("label"),
            started_at=data["started_at"],
            ended_at=data.get("ended_at"),
            duration_seconds=data.get("duration_seconds"),
            config=data.get("config", {}),
            speakers=data.get("speakers", {}),
            segments=[SegmentOut(**s) for s in data.get("segments", [])],
            transcript=data.get("transcript", ""),
            wav_mic=data.get("wav_mic"),
            wav_sys=data.get("wav_sys"),
            status=data.get("status", "complete"),
        )
    except Exception as e:
        logger.error("Failed to read recording %s: %s", recording_id, e)
        return problem(500, f"Failed to read recording: {e}", instance=request.url.path)


@router.delete("/recordings/{recording_id}", response_model=DeleteResponse)
async def delete_recording(recording_id: str, request: Request):
    """Delete recording files + brain entry."""
    err = _validate_recording_id(recording_id, request)
    if err:
        return err

    sidecar = RECORDINGS_DIR / f"recording-{recording_id}.json"
    if not sidecar.exists():
        return problem(404, f"Recording '{recording_id}' not found", instance=request.url.path)

    deleted = []

    # Delete WAV files + transcript markdown
    for suffix in ["-mic.wav", "-sys.wav", "-transcript.md"]:
        f = RECORDINGS_DIR / f"recording-{recording_id}{suffix}"
        if f.exists():
            f.unlink()
            deleted.append(f.name)

    # Delete sidecar
    sidecar.unlink()
    deleted.append(sidecar.name)

    # Delete brain entry
    brain_file = BRAIN_DIR / f"meeting-{recording_id}.jsonld"
    if brain_file.exists():
        brain_file.unlink()
        deleted.append(f"brain/{brain_file.name}")

    logger.info("Deleted recording %s: %s", recording_id, deleted)

    return DeleteResponse(deleted=deleted)


@router.post("/reset", response_model=ResetResponse)
async def recorder_reset(request: Request):
    """Clear error state → idle."""
    global _capture

    with _capture_lock:
        if _state.status == RecorderStatus.recording and _capture:
            # Force stop any active capture
            try:
                _capture.stop()
            except Exception:
                pass
            _capture = None

    _state.reset()
    logger.info("Recorder reset to idle")
    return ResetResponse()


# ═══════════════════════════════════════════════════════════════════════
# TRANSCRIPT MARKDOWN
# ═══════════════════════════════════════════════════════════════════════

def _format_timestamp(seconds: float) -> str:
    """Format seconds as M:SS (e.g., 65.3 → '1:05')."""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _format_duration(seconds: float) -> str:
    """Format duration as human-readable (e.g., '2m 15s')."""
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def _write_transcript_md(
    rec_id: str,
    label: Optional[str],
    started_at: Optional[datetime],
    duration: float,
    speakers: dict,
    segments: list,
    output_path: Path,
) -> None:
    """Write a standalone markdown transcript file."""
    title = label or f"Meeting {rec_id}"
    date_str = started_at.strftime("%Y-%m-%d %H:%M UTC") if started_at else "Unknown"
    duration_str = _format_duration(duration)

    # Collect unique participant names from speakers dict
    participants = sorted(set(speakers.values()))

    lines = [
        f"# {title}",
        "",
        f"**Date:** {date_str}",
        f"**Duration:** {duration_str}",
        f"**Participants:** {', '.join(participants)}",
        "",
        "---",
        "",
    ]

    for seg in segments:
        speaker = seg.get("speaker", "Unknown") if isinstance(seg, dict) else getattr(seg, "speaker", "Unknown")
        start = seg.get("start", 0) if isinstance(seg, dict) else getattr(seg, "start", 0)
        text = seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", "")
        lines.append(f"**{speaker}** [{_format_timestamp(start)}]")
        lines.append(text.strip())
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════
# BRAIN ENTRY CREATION
# ═══════════════════════════════════════════════════════════════════════

def _create_brain_entry(
    recording_id: str,
    label: Optional[str],
    started_at: Optional[datetime],
    duration: float,
    transcript: str,
) -> None:
    """Create a JSON-LD brain entry for the recording."""
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)

    name = label or f"Meeting {recording_id}"
    now = datetime.now(timezone.utc).isoformat()
    duration_min = round(duration / 60, 1)

    # Truncate transcript for brain entry text (keep it searchable but bounded)
    text = transcript[:5000] if len(transcript) > 5000 else transcript

    # Integrity hash of full transcript
    sha256 = hashlib.sha256(transcript.encode("utf-8")).hexdigest()

    entry = {
        "@context": {
            "@vocab": "https://schema.org/",
            "dc": "http://purl.org/dc/terms/",
            "as": "https://www.w3.org/ns/activitystreams#",
            "ihim": "https://ihim.local/schema#",
        },
        "@type": "CreativeWork",
        "@id": f"ihim:brain/meeting-{recording_id}",
        "identifier": f"meeting-{recording_id}",
        "name": name,
        "text": text,
        "abstract": f"Meeting recording ({duration_min} min). Transcript with speaker attribution.",
        "dateCreated": now,
        "dateModified": now,
        "ihim:category": "Meetings",
        "ihim:confidence": 1.0,
        "ihim:classifier": "meeting-recorder",
        "ihim:sha256": sha256,
        "dc:source": f"recording-{recording_id}",
    }

    path = BRAIN_DIR / f"meeting-{recording_id}.jsonld"
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
