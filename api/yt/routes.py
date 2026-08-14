"""FastAPI router for the YT transcriber widget.

Endpoints: submit (queued FIFO, one GPU job at a time), list, detail,
SSE stream (live segments), text, start (kick a queued job), cancel, delete.

The transcription itself runs in a worker subprocess (api/yt/yt_worker.py)
— own GIL, own CUDA context, crash-isolated, launched with the same VRAM
handoff the meeting recorder uses. The server tails the worker's sidecar +
segments JSONL to feed the widget's SSE stream.
"""

import asyncio
import json
import logging
import re
import sys
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api.errors import problem
from api.yt.models import (
    ACTIVE_STATUSES, TERMINAL_STATUSES,
    CancelResponse, DeleteResponse, JobOut, JobsListResponse,
    SubmitRequest, TextResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/yt", tags=["yt"])

CENTRAL_TZ = ZoneInfo("America/Chicago")

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "local" / "yt"
# Transcripts land in the workshop's existing corpus folder (workspace root).
OUTPUT_DIR = Path(__file__).parent.parent.parent.parent / "yt-transcriptions"

# Timestamp id + optional collision suffix (two submits in the same second
# — pasting a batch of URLs into the queue is the normal case).
JOB_ID_RE = re.compile(r"^\d{8}-\d{6}(-\d{1,3})?$")

# One GPU job at a time. {job_id: asyncio.subprocess.Process}
_active_workers: dict = {}
# A worker whose sidecar heartbeat goes stale this long is stuck (CUDA hang
# after sleep, dead network) — kill it and fail the job.
_HEARTBEAT_STALL_S = 600
_SSE_POLL_S = 0.5


def _sidecar_path(job_id: str) -> Path:
    return DATA_DIR / f"job-{job_id}.json"


def _segments_path(job_id: str) -> Path:
    return DATA_DIR / f"job-{job_id}.segments.jsonl"


def _read_sidecar(job_id: str) -> Optional[dict]:
    try:
        return json.loads(_sidecar_path(job_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_sidecar(job_id: str, data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _sidecar_path(job_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _job_out(data: dict) -> JobOut:
    return JobOut(**{k: data.get(k) for k in JobOut.model_fields})


def _all_jobs() -> list[dict]:
    if not DATA_DIR.exists():
        return []
    jobs = []
    for f in sorted(DATA_DIR.glob("job-*.json"), reverse=True):
        try:
            jobs.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return jobs


def _active_job_id() -> Optional[str]:
    return next(iter(_active_workers), None)


def _api_base() -> str:
    port = os.environ.get("IHIM_PORT", "").strip() or "7777"
    return f"http://127.0.0.1:{port}"


# ═══════════════════════════════════════════════════════════════════════
# WORKER LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════

async def _launch_job(job_id: str) -> None:
    """Hand the GPU to a worker subprocess for one job.

    Caller guarantees no other worker is active. Mirrors the meeting
    recorder's VRAM handoff: unload this process's warm Whisper models
    (stt's dictation model) unless stt is mid-job — the worker waits
    for idle itself and re-probes VRAM at load time.
    """
    sidecar = _read_sidecar(job_id)
    if sidecar is None:
        return
    sidecar["status"] = "starting"
    _write_sidecar(job_id, sidecar)

    task = {
        "job_id": job_id,
        "url": sidecar["url"],
        "model_size": sidecar.get("model_size", "large-v3-turbo"),
        "force": sidecar.get("force", False),
        "sidecar_path": str(_sidecar_path(job_id)),
        "segments_path": str(_segments_path(job_id)),
        "audio_stem": str(DATA_DIR / f"job-{job_id}.audio"),
        "output_dir": str(OUTPUT_DIR),
        "api_base": _api_base(),
    }
    task_path = DATA_DIR / f".task-{job_id}.json"
    task_path.write_text(json.dumps(task, indent=2), encoding="utf-8")

    try:
        from tools.stt import engine as _stt_engine
        stt_busy = (
            _stt_engine._engine is not None
            and _stt_engine._engine.status in ("recording", "locked", "processing", "loading")
        )
        if not stt_busy:
            from api.recorder.transcribe import unload_all_models
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, unload_all_models)
    except Exception as e:
        logger.warning("YT pre-worker model unload skipped: %s", e)

    worker_script = Path(__file__).parent / "yt_worker.py"
    ihim_dir = Path(__file__).parent.parent.parent
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(worker_script), str(task_path),
            cwd=str(ihim_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        logger.error("YT worker launch failed for %s: %s", job_id, e)
        sidecar["status"] = "failed"
        sidecar["error"] = f"Worker launch failed: {e}"
        _write_sidecar(job_id, sidecar)
        task_path.unlink(missing_ok=True)
        return

    _active_workers[job_id] = proc
    asyncio.create_task(_supervise(job_id, proc, task_path))
    logger.info("YT worker launched for %s (%s)", job_id, sidecar["url"])


async def _supervise(job_id: str, proc, task_path: Path) -> None:
    """Watch a worker: heartbeat-stall kill, exit handling, queue chaining.

    Stall detection is heartbeat-based, not duration-based — the worker
    beats on every stage transition, download tick, segment, and pause
    poll, so a fixed staleness window supervises any video length and
    survives dictation pauses (the pause loop beats too).
    """
    stderr_tail = b""
    try:
        while True:
            try:
                await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=30)
                break
            except asyncio.TimeoutError:
                sidecar = _read_sidecar(job_id) or {}
                beat = sidecar.get("heartbeat")
                try:
                    beat_dt = datetime.fromisoformat(beat) if beat else None
                except ValueError:
                    beat_dt = None
                if beat_dt is None:
                    continue
                stale = (datetime.now(timezone.utc) - beat_dt).total_seconds()
                if stale > _HEARTBEAT_STALL_S:
                    logger.error(
                        "YT worker %s heartbeat stale %.0fs — killing", job_id, stale)
                    proc.kill()
                    await proc.wait()
                    sidecar["status"] = "failed"
                    sidecar["error"] = f"Worker stalled (no progress for {int(stale)}s)"
                    _write_sidecar(job_id, sidecar)
                    break

        try:
            _, stderr_tail = await asyncio.wait_for(proc.communicate(), timeout=10)
        except (asyncio.TimeoutError, Exception):
            pass

        sidecar = _read_sidecar(job_id) or {}
        if sidecar.get("status") not in TERMINAL_STATUSES:
            # Worker died without writing a terminal state (crash, kill).
            sidecar["status"] = "failed"
            sidecar["error"] = (
                stderr_tail.decode("utf-8", errors="replace")[-300:].strip()
                or f"Worker exited (code {proc.returncode}) without a result"
            )
            _write_sidecar(job_id, sidecar)
        if proc.returncode != 0:
            logger.error("YT worker %s exit=%s: %s", job_id, proc.returncode,
                         stderr_tail.decode("utf-8", errors="replace")[-300:])
        else:
            logger.info("YT worker %s finished: %s", job_id, sidecar.get("status"))
    finally:
        _active_workers.pop(job_id, None)
        task_path.unlink(missing_ok=True)
        # FIFO chain: oldest queued job launches next.
        queued = sorted(
            (j["job_id"] for j in _all_jobs() if j.get("status") == "queued"))
        if queued and _active_job_id() is None:
            await _launch_job(queued[0])


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.post("/jobs")
async def submit_job(body: SubmitRequest, request: Request):
    """Submit a URL. Launches immediately when the GPU slot is free,
    otherwise queues FIFO (auto-launched as earlier jobs finish)."""
    base = datetime.now(CENTRAL_TZ).strftime("%Y%m%d-%H%M%S")
    job_id = base
    n = 2
    while _read_sidecar(job_id) is not None:
        job_id = f"{base}-{n}"
        n += 1

    sidecar = {
        "job_id": job_id,
        "url": body.url,
        "model_size": body.model_size,
        "force": body.force,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_sidecar(job_id, sidecar)

    if _active_job_id() is None:
        await _launch_job(job_id)

    return JSONResponse(status_code=202,
                        content=_job_out(_read_sidecar(job_id)).model_dump())


@router.get("/jobs", response_model=JobsListResponse)
async def list_jobs():
    loop = asyncio.get_event_loop()
    jobs = await loop.run_in_executor(None, _all_jobs)
    return JobsListResponse(
        jobs=[_job_out(j) for j in jobs],
        active_job_id=_active_job_id(),
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: str, request: Request):
    if not JOB_ID_RE.match(job_id):
        return problem(400, "Invalid job ID", instance=request.url.path)
    sidecar = _read_sidecar(job_id)
    if sidecar is None:
        return problem(404, f"Job '{job_id}' not found", instance=request.url.path)
    return _job_out(sidecar)


@router.post("/jobs/{job_id}/start", response_model=JobOut)
async def start_job(job_id: str, request: Request):
    """Kick a queued job (used after a server restart parks the queue)."""
    if not JOB_ID_RE.match(job_id):
        return problem(400, "Invalid job ID", instance=request.url.path)
    sidecar = _read_sidecar(job_id)
    if sidecar is None:
        return problem(404, f"Job '{job_id}' not found", instance=request.url.path)
    if sidecar.get("status") != "queued":
        return problem(409, f"Job is {sidecar.get('status')}, not queued",
                       instance=request.url.path)
    if _active_job_id() is not None:
        return problem(409, "Another job is already running",
                       instance=request.url.path)
    await _launch_job(job_id)
    return _job_out(_read_sidecar(job_id))


@router.post("/jobs/{job_id}/cancel", response_model=CancelResponse)
async def cancel_job(job_id: str, request: Request):
    if not JOB_ID_RE.match(job_id):
        return problem(400, "Invalid job ID", instance=request.url.path)
    sidecar = _read_sidecar(job_id)
    if sidecar is None:
        return problem(404, f"Job '{job_id}' not found", instance=request.url.path)

    proc = _active_workers.get(job_id)
    if proc is not None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        # _supervise handles reaping + queue chaining; mark intent now.
        sidecar = _read_sidecar(job_id) or sidecar
    elif sidecar.get("status") not in ("queued", *ACTIVE_STATUSES):
        return problem(409, f"Job is already {sidecar.get('status')}",
                       instance=request.url.path)

    sidecar["status"] = "failed"
    sidecar["error"] = "Cancelled"
    _write_sidecar(job_id, sidecar)
    logger.info("YT job %s cancelled", job_id)
    return CancelResponse(job_id=job_id, status="failed")


@router.delete("/jobs/{job_id}", response_model=DeleteResponse)
async def delete_job(job_id: str, request: Request):
    """Remove a job's record, segment stream, AND its transcript .txt in
    yt-transcriptions/. The widget's × is a real delete-off-disk, confirm-gated
    in the UI, not a hide. Note a `duplicate`
    job shares its txt_file with the original job — deleting either record
    removes the one shared file."""
    if not JOB_ID_RE.match(job_id):
        return problem(400, "Invalid job ID", instance=request.url.path)
    if job_id in _active_workers:
        return problem(409, "Job is running — cancel it first",
                       instance=request.url.path)
    if _read_sidecar(job_id) is None:
        return problem(404, f"Job '{job_id}' not found", instance=request.url.path)

    sidecar = _read_sidecar(job_id) or {}
    targets = [_sidecar_path(job_id), _segments_path(job_id),
               *DATA_DIR.glob(f"job-{job_id}.audio.*")]
    txt_file = sidecar.get("txt_file")
    if txt_file:
        # Strictly by basename from the one output dir (traversal guard,
        # same rule as job_text).
        txt_path = OUTPUT_DIR / Path(txt_file).name
        if txt_path.suffix == ".txt":
            targets.append(txt_path)

    deleted = []
    for p in targets:
        try:
            if p.exists():
                p.unlink()
                deleted.append(p.name)
        except OSError:
            pass
    return DeleteResponse(deleted=deleted)


@router.get("/jobs/{job_id}/text", response_model=TextResponse)
async def job_text(job_id: str, request: Request):
    """Final transcript text (reads the .txt this job produced/points at)."""
    if not JOB_ID_RE.match(job_id):
        return problem(400, "Invalid job ID", instance=request.url.path)
    sidecar = _read_sidecar(job_id)
    if sidecar is None:
        return problem(404, f"Job '{job_id}' not found", instance=request.url.path)
    txt_file = sidecar.get("txt_file")
    if not txt_file:
        return problem(404, "No transcript for this job", instance=request.url.path)
    # Serve strictly by basename from the one output dir (traversal guard).
    path = OUTPUT_DIR / Path(txt_file).name
    if path.suffix != ".txt" or not path.exists():
        return problem(404, f"Transcript file '{txt_file}' missing",
                       instance=request.url.path)
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(
        None, lambda: path.read_text(encoding="utf-8"))
    return TextResponse(job_id=job_id, txt_file=path.name,
                        txt_path=str(path.resolve()), text=text)


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str, request: Request):
    """SSE: replay already-transcribed segments, then tail live ones.

    Events: `status` (sidecar snapshot on any change), `segment` (one per
    transcribed segment). Closes itself once the job goes terminal.
    """
    if not JOB_ID_RE.match(job_id):
        return problem(400, "Invalid job ID", instance=request.url.path)
    if _read_sidecar(job_id) is None:
        return problem(404, f"Job '{job_id}' not found", instance=request.url.path)

    async def generate():
        seg_path = _segments_path(job_id)
        offset = 0
        last_status_json = ""
        idle = 0.0
        try:
            while True:
                # Segments flush BEFORE status: the client closes the stream
                # on a terminal status event, so any segments emitted after
                # it in the same poll would be dropped — on a fast job that
                # was the entire transcript (2026-07-27).
                sidecar = _read_sidecar(job_id) or {}

                if seg_path.exists():
                    # Binary tail — byte offsets stay honest regardless of
                    # platform newline translation.
                    with seg_path.open("rb") as f:
                        f.seek(offset)
                        chunk = f.read()
                    if chunk:
                        # Only complete lines; a partial tail waits for its
                        # newline on the next poll.
                        complete, _, partial = chunk.rpartition(b"\n")
                        if complete:
                            offset += len(chunk) - len(partial)
                            for line in complete.decode("utf-8", errors="replace").splitlines():
                                if line.strip():
                                    yield f"event: segment\ndata: {line}\n\n"
                            idle = 0.0

                status_json = _job_out(sidecar).model_dump_json()
                if status_json != last_status_json:
                    last_status_json = status_json
                    yield f"event: status\ndata: {status_json}\n\n"
                    idle = 0.0

                if sidecar.get("status") in TERMINAL_STATUSES:
                    break
                await asyncio.sleep(_SSE_POLL_S)
                idle += _SSE_POLL_S
                if idle >= 15.0:
                    idle = 0.0
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════════════════
# BOOT SWEEP — a server restart mid-job leaves an active-status sidecar
# with no worker behind it (workers are killed at shutdown). Fail it
# loudly; queued jobs stay queued for a manual /start kick.
# ═══════════════════════════════════════════════════════════════════════

def _sweep_orphaned_jobs() -> None:
    if not DATA_DIR.exists():
        return
    for f in DATA_DIR.glob("job-*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") in ACTIVE_STATUSES:
            data["status"] = "failed"
            data["error"] = "Server restarted mid-transcription"
            f.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.warning("YT boot sweep: %s was orphaned mid-job — failed", f.name)
    for stray in DATA_DIR.glob(".task-*.json"):
        stray.unlink(missing_ok=True)


try:
    _sweep_orphaned_jobs()
except Exception as _e:
    logger.error("YT boot sweep failed: %s", _e)
