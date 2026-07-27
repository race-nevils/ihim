"""Standalone YT transcription worker — runs in its own process (own GIL,
own CUDA context), launched by api/yt/routes.py via create_subprocess_exec.

Receives a task JSON path as argv[1]. Streams progress into the job's
sidecar JSON and appends each transcribed segment to a .segments.jsonl the
server tails for its SSE stream — the widget renders segments live.

GPU arbitration (dictation always wins):
  - Before loading its model the worker waits for stt to go idle
    (status "waiting_for_gpu").
  - Between segments it polls /api/stt/status (time-gated); the moment a
    dictation starts it unloads its model weights (CTranslate2 weights-only
    unload — the segment generator survives this, verified 2026-07-27),
    waits for idle, reloads, and continues the same generator
    (status "paused_for_dictation").
  Worst case both sides still only degrade: every model load probes free
  VRAM via _pick_device and downgrades compute type rather than OOM.

Exit codes: 0 = terminal sidecar written (complete/duplicate/failed), 1 = crash.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Launched as a standalone script: sys.path[0] is api/yt/, not the IHIM
# root, and PYTHONPATH is unset (same boundary as recorder/transcribe_worker).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

STT_BUSY = {"recording", "locked", "processing", "loading"}
_WAIT_CAP_S = 30 * 60      # give up yielding after 30 min (Wait-DictationIdle cap)
_POLL_INTERVAL_S = 2.0     # stt status poll cadence, waiting or mid-run
_MAX_SPEECH_RATE = 15.0    # trailing fabricated-segment drop (w/s), per stt


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Sidecar:
    """Atomic read-modify-write over the job sidecar (the server SSE tailer
    reads it concurrently — temp+replace so it never sees a partial file)."""

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8"))

    def update(self, **updates) -> None:
        self.data.update(updates)
        self.data["heartbeat"] = _now()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


def _stt_status(api_base: str) -> str:
    """Current stt engine status; fail-open to 'idle' when unreachable
    (test instance without stt, server mid-restart)."""
    import httpx
    try:
        r = httpx.get(f"{api_base}/api/stt/status", timeout=5)
        if r.status_code == 200:
            return r.json().get("status", "idle")
    except Exception:
        pass
    return "idle"


def _wait_for_stt_idle(api_base: str, sidecar: Sidecar, waiting_status: str) -> None:
    """Block until no dictation is live (or the 30-min cap expires).

    Updates the sidecar to waiting_status while blocked so the widget shows
    why nothing is moving; every poll refreshes the heartbeat so the
    server's stall watchdog knows the worker is alive.
    """
    if _stt_status(api_base) not in STT_BUSY:
        return
    prior = sidecar.data.get("status")
    sidecar.update(status=waiting_status)
    deadline = time.monotonic() + _WAIT_CAP_S
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL_S)
        if _stt_status(api_base) not in STT_BUSY:
            break
        sidecar.update()  # heartbeat only
    sidecar.update(status=prior)


def _clean_title(title: str) -> str:
    """Filesystem-safe title, matching the legacy yt-transcriber scheme."""
    return re.sub(r"[^\w\-]", "_", (title or "video").strip())[:120]


def _fetch_metadata(url: str) -> dict:
    import yt_dlp
    with yt_dlp.YoutubeDL(
        {"quiet": True, "no_warnings": True, "noplaylist": True}
    ) as ydl:
        info = ydl.extract_info(url, download=False)
    # Playlists resolve to their first entry — one URL, one transcription.
    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]
    return {
        "video_id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration_seconds": float(info["duration"]) if info.get("duration") else None,
        "webpage_url": info.get("webpage_url") or url,
    }


def _download_audio(url: str, dest_stem: Path, sidecar: Sidecar) -> Path:
    """Download bestaudio in its native container (no ffmpeg needed —
    faster-whisper decodes m4a/webm via PyAV). Returns the downloaded path."""
    import yt_dlp

    last_beat = 0.0

    def hook(d):
        nonlocal last_beat
        if d.get("status") != "downloading":
            return
        now = time.monotonic()
        if now - last_beat < 1.0:
            return
        last_beat = now
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        done = d.get("downloaded_bytes")
        progress = round(done / total, 3) if total and done else None
        sidecar.update(progress=progress)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": str(dest_stem) + ".%(ext)s",
        "progress_hooks": [hook],
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    matches = sorted(dest_stem.parent.glob(dest_stem.name + ".*"),
                     key=lambda p: p.stat().st_size, reverse=True)
    audio = next((p for p in matches if p.suffix != ".tmp"), None)
    if audio is None:
        raise RuntimeError("yt-dlp reported success but no audio file found")
    return audio


def _transcribe_streaming(audio: Path, task: dict, sidecar: Sidecar,
                          segments_path: Path) -> list[dict]:
    """Transcribe with live per-segment output + dictation yielding.

    Settings mirror the meeting-recorder lane of stt's tuned path
    (tools/stt/transcribe.py): long-form audio, so no hotwords vocab
    (prompt-echo hallucinations swallow 30s windows), no conditioning,
    word_timestamps=True because hallucination_silence_threshold is inert
    without it.
    """
    from api.recorder.transcribe import _deloop_text, _get_model

    api_base = task["api_base"]
    duration = sidecar.data.get("duration_seconds")

    _wait_for_stt_idle(api_base, sidecar, "waiting_for_gpu")
    model = _get_model(task["model_size"])
    sidecar.update(status="transcribing", progress=0.0)

    segments_iter, info = model.transcribe(
        str(audio),
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200),
        condition_on_previous_text=False,
        compression_ratio_threshold=1.8,
        no_speech_threshold=0.3,
        log_prob_threshold=-1.0,
        temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        hallucination_silence_threshold=1.0,
        repetition_penalty=1.1,
        language="en",
        word_timestamps=True,
    )
    if duration is None and getattr(info, "duration", None):
        duration = info.duration
        sidecar.update(duration_seconds=round(duration, 1))

    segments: list[dict] = []
    last_poll = time.monotonic()
    last_flush = 0.0

    with segments_path.open("a", encoding="utf-8", newline="\n") as out:
        for seg in segments_iter:
            text = _deloop_text(seg.text.strip())
            if text:
                entry = {"start": round(seg.start, 2),
                         "end": round(seg.end, 2), "text": text}
                segments.append(entry)
                out.write(json.dumps(entry, ensure_ascii=False) + "\n")
                out.flush()

            now = time.monotonic()
            if now - last_flush >= 2.0:
                last_flush = now
                progress = (round(min(seg.end / duration, 1.0), 3)
                            if duration else None)
                sidecar.update(progress=progress,
                               segments_count=len(segments))

            # Dictation yield: drop VRAM between segments the moment a
            # dictation starts; the generator resumes after reload.
            if now - last_poll >= _POLL_INTERVAL_S:
                last_poll = now
                if _stt_status(api_base) in STT_BUSY:
                    model.model.unload_model()
                    _wait_for_stt_idle(api_base, sidecar, "paused_for_dictation")
                    model.model.load_model()

    # Final pass, mirroring stt's list-level cleanup: clamp to real audio
    # length, drop trailing segments at impossible speech rates.
    if duration:
        segments = [s for s in segments if s["start"] < duration]
        for s in segments:
            s["end"] = min(s["end"], round(duration, 2))
    while segments:
        s = segments[-1]
        span = s["end"] - s["start"]
        if span > 0 and len(s["text"].split()) / span > _MAX_SPEECH_RATE:
            segments.pop()
        else:
            break
    return segments


def main() -> None:
    task = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    sidecar = Sidecar(Path(task["sidecar_path"]))
    segments_path = Path(task["segments_path"])
    output_dir = Path(task["output_dir"])
    audio_stem = Path(task["audio_stem"])
    audio: Path | None = None

    try:
        sidecar.update(status="fetching_metadata", started_at=_now())
        meta = _fetch_metadata(task["url"])
        sidecar.update(**meta)

        # Dedup on video id — already transcribed videos are skipped unless
        # forced (legacy ProcessedRawYT behavior, keyed on the output .txt).
        existing = sorted(output_dir.glob(f"*-{meta['video_id']}.txt"))
        if existing and not task.get("force"):
            sidecar.update(status="duplicate", txt_file=existing[0].name,
                           finished_at=_now())
            return

        sidecar.update(status="downloading", progress=0.0)
        audio = _download_audio(task["url"], audio_stem, sidecar)

        segments = _transcribe_streaming(audio, task, sidecar, segments_path)

        if segments:
            output_dir.mkdir(parents=True, exist_ok=True)
            txt_path = output_dir / f"{_clean_title(meta['title'])}-{meta['video_id']}.txt"
            txt_path.write_text(
                "\n".join(s["text"] for s in segments) + "\n", encoding="utf-8")
            sidecar.update(status="complete", txt_file=txt_path.name,
                           segments_count=len(segments), progress=1.0,
                           finished_at=_now())
            print(f"[yt-worker] Complete: {txt_path.name} ({len(segments)} segments)")
        else:
            # Music-only / no-dialogue video: VAD found nothing to decode.
            # Complete, but no .txt — an empty transcript file helps nobody.
            sidecar.update(status="complete", segments_count=0, progress=1.0,
                           finished_at=_now())
            print("[yt-worker] Complete: no speech detected, no transcript written")

    except Exception as e:
        try:
            sidecar.update(status="failed", error=str(e)[:500], finished_at=_now())
        except Exception:
            pass
        print(f"[yt-worker] Failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Free VRAM for the server / next job, then drop the audio temp.
        try:
            from api.recorder.transcribe import unload_model
            unload_model(task["model_size"])
        except Exception:
            pass
        for p in ([audio] if audio else []) + list(audio_stem.parent.glob(audio_stem.name + ".*")):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    main()
