"""FastAPI router for the meeting recorder.

Endpoints: start, stop, transcribe, status, devices, list, view, rename, delete, reset.
Stop saves audio instantly. Transcription is manual via POST /transcribe/{id}.
"""

import asyncio
import json
import logging
import re
import shutil
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from api.errors import problem

from api.recorder.models import (
    StartRequest, StartResponse, StatusResponse, DevicesResponse, DeviceInfo,
    StopResponse, TranscribeResponse, RecordingSummary, RecordingDetail, SegmentOut,
    RecordingsListResponse, DeleteResponse, ResetResponse, RenameRequest,
    RenameResponse, RecorderStatus,
)
from api.recorder.state import RecorderState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recorder", tags=["recorder"])

# Paths
DATA_DIR = Path(__file__).parent.parent.parent / "data" / "local"
RECORDINGS_DIR = DATA_DIR / "recordings"
BRAIN_DIR = DATA_DIR / "brain" / "Meetings"
# Streaming capture checkpoints land here during recording; a clean stop
# removes them, a crash leaves them for the boot sweep to recover.
INPROGRESS_DIR = RECORDINGS_DIR / ".inprogress"

# ── Async file I/O helpers (prevent event loop starvation) ──

async def _aread_text(path: Path) -> str:
    """Read file text without blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: path.read_text(encoding="utf-8"))


async def _awrite_text(path: Path, content: str) -> None:
    """Write file text without blocking the event loop."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: path.write_text(content, encoding="utf-8"))


async def _aread_bytes(path: Path) -> bytes:
    """Read file bytes without blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, path.read_bytes)


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
    """List available mic and WASAPI loopback devices.

    Runs in thread pool — PortAudio/WASAPI on Windows caches device state
    per-thread at COM initialization time.  A fresh thread gets fresh COM,
    so hot-plugged devices (USB headsets, etc.) are always discovered.
    """
    try:
        from api.recorder.capture import list_audio_devices

        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, list_audio_devices)
        return DevicesResponse(
            mic_devices=[DeviceInfo(**d) for d in raw["mic_devices"]],
            system_devices=[DeviceInfo(**d) for d in raw["system_devices"]],
            errors=raw.get("errors", []),
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
            checkpoint_dir=INPROGRESS_DIR / rec_id,
        )
        capture.start()

        _state.start_recording(
            recording_id=rec_id,
            label=body.label,
            mic_device=capture.mic_device_name,
            sys_device=capture.sys_device_name,
            participant_name=body.participant_name,
            model_size=body.model_size.value,
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
    """Stop recording and save audio. Returns instantly.

    Transcription is a separate manual step via POST /transcribe/{id}.
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
    participant_name = _state.participant_name
    model_size = _state.model_size

    # ── Block 1: Stop capture + save WAV files (fatal if fails) ──
    # stop() joins capture threads (up to 10s) and save() concatenates +
    # writes potentially GBs of WAV — both run in the thread pool so a
    # long recording can't stall every other endpoint on the event loop.
    with _capture_lock:
        local_capture = _capture
        _capture = None

    mic_path = RECORDINGS_DIR / f"recording-{rec_id}-mic.wav"
    sys_path = RECORDINGS_DIR / f"recording-{rec_id}-sys.wav"

    def _stop_and_save():
        local_capture.stop()
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        local_capture.save(mic_path, sys_path)

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _stop_and_save)
        _state.stop_recording()
        capture_errors = local_capture.errors
    except Exception as e:
        _state.set_error(str(e))
        logger.error("Audio save failed for %s: %s", rec_id, e)
        return problem(500, f"Audio save failed: {e}", instance=request.url.path)

    # ── Block 2: Sidecar write (no transcription — just metadata) ──
    ended_at = datetime.now(timezone.utc)
    duration = (ended_at - started_at).total_seconds() if started_at else 0

    # Read initial prompt from preferences (stored for later transcription)
    from api.preferences import _read_prefs
    loop = asyncio.get_event_loop()
    prefs = await loop.run_in_executor(None, _read_prefs)
    initial_prompt = (prefs.get("recorder", {}).get("initial_prompt") or "").strip() or None

    sidecar = {
        "recording_id": rec_id,
        "label": label,
        "started_at": started_at.isoformat() if started_at else None,
        "ended_at": ended_at.isoformat(),
        "duration_seconds": round(duration, 1),
        # Transcription runs stt's tuned dictation path (tools/stt/
        # transcribe.py = source of truth). These mirror the settings it
        # applies, recorded per-recording for traceability.
        "config": {
            "model_size": model_size,
            "sample_rate": 16000,
            "mic_device": mic_device,
            "sys_device": sys_device,
            "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            "compression_ratio_threshold": 1.8,
            "no_speech_threshold": 0.3,
            "log_prob_threshold": -1.0,
            "hallucination_silence_threshold": 1.0,
            "word_timestamps": True,
            "repetition_penalty": 1.1,
            "condition_on_previous_text": False,
            "language": "en",
            "vocab_hotwords": False,
            "initial_prompt": initial_prompt,
        },
        "speakers": {"mic": "the operator", "system": participant_name or "Other"},
        "segments": [],
        "transcript": "",
        "wav_mic": mic_path.name,
        "wav_sys": sys_path.name,
        "status": "pending_transcription",
    }
    if capture_errors:
        sidecar["capture_warnings"] = capture_errors

    sidecar_path = RECORDINGS_DIR / f"recording-{rec_id}.json"
    await _awrite_text(sidecar_path, json.dumps(sidecar, indent=2))

    logger.info("Recording saved: %s (%.1fs, status=pending_transcription)", rec_id, duration)

    return StopResponse(
        recording_id=rec_id,
        duration_seconds=round(duration, 1),
        status="pending_transcription",
    )


# Active transcription worker processes {recording_id: asyncio.subprocess.Process}
_active_workers: dict = {}
# Worker timeout scales with recording length: two channels at up to 2x
# realtime each, plus a floor covering model cold-load. Real meetings run
# 1.5-3 hours — a flat cap killed them.
_TRANSCRIPTION_TIMEOUT_FLOOR = 600  # 10 minutes


def _transcription_timeout(duration_seconds: float) -> float:
    return max(_TRANSCRIPTION_TIMEOUT_FLOOR, duration_seconds * 4)


@router.post("/transcribe/{recording_id}")
async def transcribe_recording(recording_id: str, request: Request):
    """Trigger transcription for a saved recording.

    Launches a worker subprocess (own GIL, own process) so transcription
    cannot block the event loop. Returns 202 immediately; frontend polls
    GET /recordings/{id} for progress via transcription_stage field.
    """
    err = _validate_recording_id(recording_id, request)
    if err:
        return err

    sidecar_path = RECORDINGS_DIR / f"recording-{recording_id}.json"
    if not sidecar_path.exists():
        return problem(404, f"Recording '{recording_id}' not found", instance=request.url.path)

    try:
        sidecar = json.loads(await _aread_text(sidecar_path))
    except Exception as e:
        return problem(500, f"Failed to read sidecar: {e}", instance=request.url.path)

    if sidecar.get("status") == "complete":
        preview = sidecar.get("transcript", "")[:500]
        if len(sidecar.get("transcript", "")) > 500:
            preview += "..."
        return TranscribeResponse(
            recording_id=recording_id,
            duration_seconds=sidecar.get("duration_seconds", 0),
            segments_count=len(sidecar.get("segments", [])),
            transcript_preview=preview,
            status="complete",
        )

    if sidecar.get("status") == "transcribing":
        return problem(409, "Transcription already in progress", instance=request.url.path)

    # Resolve WAV paths
    mic_path = RECORDINGS_DIR / sidecar.get("wav_mic", f"recording-{recording_id}-mic.wav")
    sys_path = RECORDINGS_DIR / sidecar.get("wav_sys", f"recording-{recording_id}-sys.wav")

    if not mic_path.exists() or not sys_path.exists():
        return problem(404, "WAV files not found for this recording", instance=request.url.path)

    # Extract config from sidecar
    config = sidecar.get("config", {})
    model_size = config.get("model_size", "small")
    initial_prompt = config.get("initial_prompt")
    speakers = sidecar.get("speakers", {})
    sys_label = speakers.get("system", "Other")
    mic_label = speakers.get("mic", "the operator")

    # Write task JSON for the worker
    task = {
        "recording_id": recording_id,
        "sidecar_path": str(sidecar_path),
        "mic_path": str(mic_path),
        "sys_path": str(sys_path),
        "model_size": model_size,
        "initial_prompt": initial_prompt,
        "sys_label": sys_label,
        "mic_label": mic_label,
        "recordings_dir": str(RECORDINGS_DIR),
        "brain_dir": str(BRAIN_DIR),
    }
    task_path = RECORDINGS_DIR / f".transcribe-task-{recording_id}.json"
    await _awrite_text(task_path, json.dumps(task, indent=2))

    # Mark as transcribing
    sidecar["status"] = "transcribing"
    sidecar["transcription_stage"] = "queued"
    await _awrite_text(sidecar_path, json.dumps(sidecar, indent=2))

    # Launch worker subprocess — fire and forget with timeout
    timeout = _transcription_timeout(sidecar.get("duration_seconds") or 0)
    asyncio.create_task(_run_transcription_worker(recording_id, task_path, sidecar_path, timeout))

    logger.info("Transcription worker launched for %s", recording_id)

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=202,
        content={
            "recording_id": recording_id,
            "status": "transcribing",
            "message": "Transcription started. Poll GET /recordings/{id} for progress.",
        },
    )


async def _run_transcription_worker(recording_id: str, task_path: Path, sidecar_path: Path, timeout: float):
    """Manage the transcription worker subprocess with timeout."""
    worker_script = Path(__file__).parent / "transcribe_worker.py"
    ihim_dir = Path(__file__).parent.parent.parent  # IHIM root

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(worker_script), str(task_path),
            cwd=str(ihim_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _active_workers[recording_id] = proc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            if proc.returncode != 0:
                logger.error(
                    "Transcription worker failed for %s (exit=%d): %s",
                    recording_id, proc.returncode,
                    stderr.decode("utf-8", errors="replace")[-500:] if stderr else "no stderr",
                )
            else:
                if stdout:
                    logger.info(stdout.decode("utf-8", errors="replace").strip())
        except asyncio.TimeoutError:
            logger.error("Transcription worker timed out for %s after %ds — killing", recording_id, timeout)
            proc.kill()
            await proc.wait()
            try:
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
                sidecar["status"] = "transcription_failed"
                sidecar["transcription_error"] = f"Timed out after {round(timeout)}s"
                sidecar["transcription_stage"] = None
                sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
            except Exception:
                pass
    except Exception as e:
        logger.error("Failed to launch transcription worker for %s: %s", recording_id, e)
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            sidecar["status"] = "transcription_failed"
            sidecar["transcription_error"] = f"Worker launch failed: {e}"
            sidecar["transcription_stage"] = None
            sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        except Exception:
            pass
    finally:
        _active_workers.pop(recording_id, None)


# Sidecars grow to hundreds of KB (they embed the full transcript); the
# list endpoint only needs five summary fields, so cache them by mtime.
_summary_cache: dict = {}  # path str → (mtime, RecordingSummary)


def _scan_recording_summaries() -> list:
    """Parse sidecar JSONs into summaries, reusing cached entries by mtime."""
    summaries = []
    for f in sorted(RECORDINGS_DIR.glob("recording-*.json"), reverse=True):
        try:
            mtime = f.stat().st_mtime
            cached = _summary_cache.get(str(f))
            if cached and cached[0] == mtime:
                summaries.append(cached[1])
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            summary = RecordingSummary(
                recording_id=data["recording_id"],
                label=data.get("label"),
                started_at=data["started_at"],
                duration_seconds=data.get("duration_seconds"),
                status=data.get("status", "unknown"),
            )
            _summary_cache[str(f)] = (mtime, summary)
            summaries.append(summary)
        except Exception:
            continue
    return summaries


@router.get("/recordings", response_model=RecordingsListResponse)
async def list_recordings():
    """List all past recordings (scans sidecar JSONs)."""
    if not RECORDINGS_DIR.exists():
        return RecordingsListResponse(recordings=[])

    loop = asyncio.get_event_loop()
    recordings = await loop.run_in_executor(None, _scan_recording_summaries)
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
        data = json.loads(await _aread_text(sidecar))
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
            transcription_stage=data.get("transcription_stage"),
        )
    except Exception as e:
        logger.error("Failed to read recording %s: %s", recording_id, e)
        return problem(500, f"Failed to read recording: {e}", instance=request.url.path)


@router.patch("/recordings/{recording_id}", response_model=RenameResponse)
async def rename_recording(recording_id: str, body: RenameRequest, request: Request):
    """Rename a recording's label. Also updates the brain entry name and
    the transcript markdown's title heading when they exist."""
    err = _validate_recording_id(recording_id, request)
    if err:
        return err

    sidecar_path = RECORDINGS_DIR / f"recording-{recording_id}.json"
    if not sidecar_path.exists():
        return problem(404, f"Recording '{recording_id}' not found", instance=request.url.path)

    label = (body.label or "").strip() or None

    try:
        sidecar = json.loads(await _aread_text(sidecar_path))
        sidecar["label"] = label
        await _awrite_text(sidecar_path, json.dumps(sidecar, indent=2))
    except Exception as e:
        return problem(500, f"Failed to update sidecar: {e}", instance=request.url.path)

    # Brain entry name (best-effort — may not exist pre-transcription)
    brain_file = BRAIN_DIR / f"meeting-{recording_id}.jsonld"
    if brain_file.exists():
        try:
            entry = json.loads(await _aread_text(brain_file))
            entry["name"] = label or f"Meeting {recording_id}"
            entry["dateModified"] = datetime.now(timezone.utc).isoformat()
            await _awrite_text(brain_file, json.dumps(entry, indent=2))
        except Exception as e:
            logger.warning("Rename: brain entry update failed for %s: %s", recording_id, e)

    # Transcript markdown title heading (best-effort)
    transcript_name = sidecar.get("transcript_md")
    if transcript_name:
        md_path = RECORDINGS_DIR / Path(transcript_name).name
        if md_path.exists():
            try:
                lines = (await _aread_text(md_path)).splitlines()
                if lines and lines[0].startswith("# "):
                    lines[0] = f"# {label or md_path.stem}"
                    await _awrite_text(md_path, "\n".join(lines))
            except Exception as e:
                logger.warning("Rename: transcript md update failed for %s: %s", recording_id, e)

    logger.info("Renamed recording %s → %r", recording_id, label)
    return RenameResponse(recording_id=recording_id, label=label)


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

    # Read the sidecar for the readable transcript filename before deleting it.
    try:
        sc_data = json.loads(await _aread_text(sidecar))
    except Exception:
        sc_data = {}

    # Delete WAV files (keyed by recording id — created before any transcript).
    for suffix in ["-mic.wav", "-sys.wav"]:
        f = RECORDINGS_DIR / f"recording-{recording_id}{suffix}"
        if f.exists():
            f.unlink()
            deleted.append(f.name)

    # Delete the transcript markdown — readable name from the sidecar, with the
    # legacy id-based name as a fallback for recordings made before the rename.
    transcript_name = sc_data.get("transcript_md") or f"recording-{recording_id}-transcript.md"
    tf = RECORDINGS_DIR / Path(transcript_name).name
    if tf.exists():
        tf.unlink()
        deleted.append(tf.name)

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
# BOOT SWEEP — crash recovery, runs once at import
# ═══════════════════════════════════════════════════════════════════════

def _reset_stuck_transcriptions() -> None:
    """Return orphaned 'transcribing' sidecars to 'pending_transcription'.

    The worker is fire-and-forget; a server restart mid-job (the
    port-ensure hook restarts on any code edit) strands the sidecar at
    'transcribing', which /transcribe then 409s forever. If a worker
    somehow survived the restart, its final sidecar write simply wins.
    """
    if not RECORDINGS_DIR.exists():
        return
    for f in RECORDINGS_DIR.glob("recording-*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("status") != "transcribing":
                continue
            data["status"] = "pending_transcription"
            data["transcription_stage"] = None
            f.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.warning(
                "Boot sweep: %s was stuck at 'transcribing' — reset to pending", f.name
            )
        except Exception:
            continue


def _recover_interrupted_recordings() -> None:
    """Assemble crash-orphaned capture checkpoints into pending recordings.

    A recording that died mid-capture (crash, BSOD, forced restart) leaves
    chunk files under .inprogress/<rec_id>/. Rebuild the channel WAVs from
    them and write a pending_transcription sidecar, enriched from
    .recorder-state.json when it matches. A clean stop never gets here —
    save() removes its checkpoint directory.
    """
    if not INPROGRESS_DIR.exists():
        return

    import time
    from api.recorder.capture import recover_checkpoint

    state_file = RECORDINGS_DIR / ".recorder-state.json"
    state: dict = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    state_consumed = False

    for chunk_dir in sorted(p for p in INPROGRESS_DIR.iterdir() if p.is_dir()):
        rec_id = chunk_dir.name
        try:
            # A manifest touched in the last 2 minutes may belong to a live
            # recording in another instance (chunks flush every ~30s) — leave it.
            manifest_path = chunk_dir / "manifest.json"
            if manifest_path.exists() and (time.time() - manifest_path.stat().st_mtime) < 120:
                continue

            sidecar_path = RECORDINGS_DIR / f"recording-{rec_id}.json"
            if sidecar_path.exists():
                # A clean stop already produced this recording — leftovers only.
                shutil.rmtree(chunk_dir, ignore_errors=True)
                continue

            mic_path = RECORDINGS_DIR / f"recording-{rec_id}-mic.wav"
            sys_path = RECORDINGS_DIR / f"recording-{rec_id}-sys.wav"
            manifest = recover_checkpoint(chunk_dir, mic_path, sys_path)
            if manifest is None:
                shutil.rmtree(chunk_dir, ignore_errors=True)
                continue

            matches = state.get("recording_id") == rec_id
            if matches:
                state_consumed = True
            started_at = manifest.get("started_at")
            if not started_at:
                try:
                    started_at = datetime.strptime(rec_id, "%Y%m%d-%H%M%S").replace(
                        tzinfo=timezone.utc
                    ).isoformat()
                except ValueError:
                    started_at = None
            duration = manifest.get("duration_seconds", 0)

            sidecar = {
                "recording_id": rec_id,
                "label": state.get("label") if matches else None,
                "started_at": started_at,
                "ended_at": None,
                "duration_seconds": duration,
                "config": {
                    "model_size": (state.get("model_size") if matches else None) or "large-v3",
                    "mic_device": manifest.get("mic_device"),
                    "sys_device": manifest.get("sys_device"),
                    "initial_prompt": None,
                },
                "speakers": {
                    "mic": "the operator",
                    "system": (state.get("participant_name") if matches else None) or "Other",
                },
                "segments": [],
                "transcript": "",
                "wav_mic": mic_path.name,
                "wav_sys": sys_path.name,
                "status": "pending_transcription",
                "recovered": True,
                "capture_warnings": [
                    "recovered from crash checkpoints — tail after the last flush is lost"
                ],
            }
            sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
            shutil.rmtree(chunk_dir, ignore_errors=True)
            logger.warning(
                "Boot sweep: recovered interrupted recording %s (%.1fs) from checkpoints",
                rec_id, duration,
            )
        except Exception as e:
            logger.error("Checkpoint recovery failed for %s: %s", rec_id, e)

    if state_consumed:
        try:
            state_file.unlink(missing_ok=True)
        except Exception:
            pass
    try:
        if INPROGRESS_DIR.exists() and not any(INPROGRESS_DIR.iterdir()):
            INPROGRESS_DIR.rmdir()
    except Exception:
        pass


try:
    _reset_stuck_transcriptions()
    _recover_interrupted_recordings()
except Exception as _e:
    logger.error("Recorder boot sweep failed: %s", _e)
