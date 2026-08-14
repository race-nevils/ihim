"""Standalone transcription worker — runs in its own process (own GIL).

Launched by the API server via asyncio.create_subprocess_exec().
Receives a task JSON file path as argv[1], writes progress + results
to the recording's sidecar JSON so the frontend can poll status.

Exit codes:
    0 = success
    1 = error (details written to sidecar)
"""

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Transcript filenames and headers show the machine's local time; the sidecar's
# stored ISO timestamps stay UTC (iHIM standard).
CENTRAL_TZ = ZoneInfo("America/Chicago")


def _to_central(dt):
    """UTC-aware (or naive-local) datetime → Central time. None passes through."""
    if dt is None:
        return None
    return dt.astimezone(CENTRAL_TZ)

# Launched as a standalone script via create_subprocess_exec, so Python sets
# sys.path[0] to this file's own directory (api/recorder/) — not the cwd. The
# server's runtime sys.path.insert doesn't carry across the process boundary
# and PYTHONPATH is unset, so `import api` fails without this. parents[2] of
# IHIM/api/recorder/transcribe_worker.py is the IHIM root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Imported AFTER the sys.path fix above, not with the stdlib imports at the top:
# this module runs as a standalone script, so `api` is not importable until that
# line executes.
from api.preferences import owner_name  # noqa: E402


def _update_sidecar(sidecar_path: Path, updates: dict) -> dict:
    """Read-modify-write the sidecar JSON atomically."""
    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    data.update(updates)
    sidecar_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


_ILLEGAL_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _clean_name(name: str) -> str:
    """Filesystem-safe participant name (illegal chars + trailing dots stripped)."""
    cleaned = _ILLEGAL_FS.sub("", name or "").strip().rstrip(". ")
    return cleaned or "Meeting"


def _repoint_sidecar(recordings_dir: Path, old_name: str, new_name: str) -> None:
    """Point whichever sibling sidecar named old_name at new_name."""
    for sc in recordings_dir.glob("recording-*.json"):
        try:
            data = json.loads(sc.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("transcript_md") == old_name:
            data["transcript_md"] = new_name
            sc.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return


def _assign_transcript_path(recordings_dir: Path, sidecar: dict, person: str, started_at):
    """Human-readable transcript filename: '{person} {YYYY-MM-DD}.md'.

    One meeting with a person on a day gets the bare name. A second gets a
    trailing letter and the first is renamed to ' a', so a busy day reads
    'Mark 2026-07-13 a.md', 'Mark 2026-07-13 b.md' with no gap. Re-transcription
    reuses the name already recorded in the sidecar (never mints a new letter).
    """
    existing = sidecar.get("transcript_md")
    if existing and (recordings_dir / existing).exists():
        return recordings_dir / existing

    local = _to_central(started_at)
    date = local.strftime("%Y-%m-%d") if local else "undated"
    stem = f"{_clean_name(person)} {date}"
    plain = recordings_dir / f"{stem}.md"
    lettered = sorted(recordings_dir.glob(f"{stem} [a-z].md"))

    if not plain.exists() and not lettered:
        return plain  # only meeting with this person that day

    # Collision — promote the letterless first to ' a', then take the next free.
    if plain.exists():
        first = recordings_dir / f"{stem} a.md"
        if not first.exists():
            plain.rename(first)
            _repoint_sidecar(recordings_dir, plain.name, first.name)
            lettered = sorted(recordings_dir.glob(f"{stem} [a-z].md"))

    used = {p.stem.rsplit(" ", 1)[-1] for p in lettered}
    for letter in "abcdefghijklmnopqrstuvwxyz":
        if letter not in used:
            return recordings_dir / f"{stem} {letter}.md"
    return recordings_dir / f"{stem} z.md"  # >26 with one person in a day: last wins


def _write_transcript_md(label, started_at, duration, speakers, segments, output_path):
    """Write a standalone markdown transcript file."""
    title = label or output_path.stem
    local = _to_central(started_at)
    date_str = local.strftime("%Y-%m-%d %H:%M %Z") if local else "Unknown"
    m, s = divmod(int(duration), 60)
    duration_str = f"{m}m {s}s" if m > 0 else f"{s}s"
    participants = sorted(set(speakers.values()))

    lines = [
        f"# {title}", "",
        f"**Date:** {date_str}",
        f"**Duration:** {duration_str}",
        f"**Participants:** {', '.join(participants)}",
        "", "---", "",
    ]
    for seg in segments:
        speaker = seg.get("speaker", "Unknown")
        start = seg.get("start", 0)
        text = seg.get("text", "")
        sm, ss = divmod(int(start), 60)
        lines.append(f"**{speaker}** [{sm}:{ss:02d}]")
        lines.append(text.strip())
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def _create_brain_entry(recording_id, label, started_at, duration, transcript, brain_dir):
    """Create a JSON-LD brain entry for the recording."""
    brain_dir.mkdir(parents=True, exist_ok=True)
    name = label or f"Meeting {recording_id}"
    now = datetime.now(timezone.utc).isoformat()
    duration_min = round(duration / 60, 1)
    text = transcript[:5000] if len(transcript) > 5000 else transcript
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

    path = brain_dir / f"meeting-{recording_id}.jsonld"
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")


def main():
    if len(sys.argv) < 2:
        print("Usage: transcribe_worker.py <task_json_path>", file=sys.stderr)
        sys.exit(1)

    task_path = Path(sys.argv[1])
    task = json.loads(task_path.read_text(encoding="utf-8"))

    recording_id = task["recording_id"]
    sidecar_path = Path(task["sidecar_path"])
    mic_path = Path(task["mic_path"])
    sys_path = Path(task["sys_path"])
    model_size = task.get("model_size", "small")
    initial_prompt = task.get("initial_prompt")
    sys_label = task.get("sys_label", "Other")
    mic_label = task.get("mic_label") or owner_name()
    recordings_dir = Path(task["recordings_dir"])
    brain_dir = Path(task["brain_dir"])

    try:
        # Stage 1: Loading model
        _update_sidecar(sidecar_path, {
            "status": "transcribing",
            "transcription_stage": "loading_model",
        })

        # Route each channel through stt's tuned dictation path so the
        # meeting recorder inherits the exact same settings — anti-hallucination
        # thresholds, repetition penalty, fabricated-segment drop,
        # condition_on_previous_text=False. A user initial_prompt (if any)
        # rides prev_text, the same slot dictation uses for decoder context.
        # use_vocab=False: the dictation hotwords wrapper seeds prompt-echo
        # hallucinations on long-form audio that swallow whole 30s windows
        # of real speech (see transcribe_segments docstring).
        from api.recorder.transcribe import merge_transcripts, format_transcript
        from tools.stt.transcribe import transcribe_segments

        # Stage 2: Transcribing mic
        _update_sidecar(sidecar_path, {"transcription_stage": "transcribing_mic"})
        mic_segments = transcribe_segments(
            mic_path, model_size=model_size, prev_text=initial_prompt or "",
            speaker_label=mic_label, use_vocab=False,
        )

        # Stage 3: Transcribing system audio
        _update_sidecar(sidecar_path, {"transcription_stage": "transcribing_sys"})
        sys_segments = transcribe_segments(
            sys_path, model_size=model_size, prev_text=initial_prompt or "",
            speaker_label=sys_label, use_vocab=False,
        )

        # Stage 4: Merging
        _update_sidecar(sidecar_path, {"transcription_stage": "merging"})
        merged = merge_transcripts(mic_segments, sys_segments)
        transcript = format_transcript(merged)

        sidecar_status = "complete" if merged else "no_transcript"

        # Update sidecar with results
        sidecar = _update_sidecar(sidecar_path, {
            "segments": merged,
            "transcript": transcript,
            "status": sidecar_status,
            "transcription_stage": None,
        })
        sidecar.pop("transcription_error", None)
        sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

        # Write transcript markdown
        duration = sidecar.get("duration_seconds", 0)
        label = sidecar.get("label")
        started_at_str = sidecar.get("started_at")
        started_at = datetime.fromisoformat(started_at_str) if started_at_str else None
        speakers = sidecar.get("speakers", {})

        if merged:
            try:
                # Name the transcript for a human: the person on the other end
                # (system channel) + the date. The WAVs and sidecar keep the
                # timestamp id — they exist before any transcript does.
                person = speakers.get("system") or sys_label
                md_path = _assign_transcript_path(recordings_dir, sidecar, person, started_at)
                _write_transcript_md(label, started_at, duration, speakers, merged, md_path)
                sidecar["transcript_md"] = md_path.name
                sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"[worker] Failed to write transcript markdown: {e}", file=sys.stderr)

        # Create brain entry
        try:
            _create_brain_entry(recording_id, label, started_at, duration, transcript, brain_dir)
        except Exception as e:
            print(f"[worker] Failed to create brain entry: {e}", file=sys.stderr)

        # Unload model to free VRAM
        try:
            from api.recorder.transcribe import unload_model
            unload_model(model_size)
        except Exception:
            pass

        print(f"[worker] Transcription complete: {recording_id} ({len(merged)} segments)")

    except Exception as e:
        print(f"[worker] Transcription failed: {e}", file=sys.stderr)
        try:
            _update_sidecar(sidecar_path, {
                "status": "transcription_failed",
                "transcription_error": str(e),
                "transcription_stage": None,
            })
        except Exception:
            pass
        sys.exit(1)
    finally:
        # Clean up task file
        try:
            task_path.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
