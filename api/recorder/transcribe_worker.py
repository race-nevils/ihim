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
import sys
from datetime import datetime, timezone
from pathlib import Path


def _update_sidecar(sidecar_path: Path, updates: dict) -> dict:
    """Read-modify-write the sidecar JSON atomically."""
    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    data.update(updates)
    sidecar_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _write_transcript_md(rec_id, label, started_at, duration, speakers, segments, output_path):
    """Write a standalone markdown transcript file."""
    title = label or f"Meeting {rec_id}"
    date_str = started_at.strftime("%Y-%m-%d %H:%M UTC") if started_at else "Unknown"
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
    mic_label = task.get("mic_label", "the operator")
    recordings_dir = Path(task["recordings_dir"])
    brain_dir = Path(task["brain_dir"])

    try:
        # Stage 1: Loading model
        _update_sidecar(sidecar_path, {
            "status": "transcribing",
            "transcription_stage": "loading_model",
        })

        from api.recorder.transcribe import transcribe_channel, merge_transcripts, format_transcript

        # Stage 2: Transcribing mic
        _update_sidecar(sidecar_path, {"transcription_stage": "transcribing_mic"})
        mic_segments = transcribe_channel(mic_path, mic_label, model_size, initial_prompt=initial_prompt)

        # Stage 3: Transcribing system audio
        _update_sidecar(sidecar_path, {"transcription_stage": "transcribing_sys"})
        sys_segments = transcribe_channel(sys_path, sys_label, model_size, initial_prompt=initial_prompt)

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
                md_path = recordings_dir / f"recording-{recording_id}-transcript.md"
                _write_transcript_md(recording_id, label, started_at, duration, speakers, merged, md_path)
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
