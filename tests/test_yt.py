"""Route-level tests for the YT transcriber (/api/yt).

The worker subprocess is never launched here — _launch_job is monkeypatched
to a recorder stub, and DATA_DIR/OUTPUT_DIR are redirected to tmp_path so
tests touch neither the real job history nor yt-transcriptions/.
"""

import json

import pytest

from api.yt import routes as yt_routes


@pytest.fixture
def yt_dirs(tmp_path, monkeypatch):
    data_dir = tmp_path / "yt"
    out_dir = tmp_path / "yt-transcriptions"
    data_dir.mkdir()
    out_dir.mkdir()
    monkeypatch.setattr(yt_routes, "DATA_DIR", data_dir)
    monkeypatch.setattr(yt_routes, "OUTPUT_DIR", out_dir)
    return data_dir, out_dir


@pytest.fixture
def no_launch(monkeypatch):
    launched = []

    async def fake_launch(job_id):
        launched.append(job_id)
        sidecar = yt_routes._read_sidecar(job_id)
        sidecar["status"] = "starting"
        yt_routes._write_sidecar(job_id, sidecar)

    monkeypatch.setattr(yt_routes, "_launch_job", fake_launch)
    return launched


def _submit(client, url="https://www.youtube.com/watch?v=test"):
    return client.post("/api/yt/jobs", json={"url": url})


def test_submit_validation(client):
    assert _submit(client, "notaurl").status_code == 422
    assert _submit(client, "ftp://x.example/y").status_code == 422
    assert client.post("/api/yt/jobs", json={}).status_code == 422


def test_submit_launches_when_idle(client, yt_dirs, no_launch):
    resp = _submit(client)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "starting"
    assert no_launch == [job["job_id"]]


def test_second_submit_queues_behind_active(client, yt_dirs, no_launch, monkeypatch):
    first = _submit(client).json()
    # Simulate the first worker still holding the GPU slot.
    monkeypatch.setitem(yt_routes._active_workers, first["job_id"], object())
    try:
        second = _submit(client, "https://youtu.be/other").json()
        assert second["status"] == "queued"
        assert no_launch == [first["job_id"]]

        listing = client.get("/api/yt/jobs").json()
        assert listing["active_job_id"] == first["job_id"]
        statuses = {j["job_id"]: j["status"] for j in listing["jobs"]}
        assert statuses[second["job_id"]] == "queued"

        # Manual kick refuses while the slot is held.
        kick = client.post(f"/api/yt/jobs/{second['job_id']}/start")
        assert kick.status_code == 409
    finally:
        yt_routes._active_workers.pop(first["job_id"], None)


def test_job_id_validation_and_missing(client, yt_dirs):
    assert client.get("/api/yt/jobs/..%2Fescape").status_code in (400, 404)
    assert client.get("/api/yt/jobs/20990101-000000").status_code == 404
    assert client.post("/api/yt/jobs/20990101-000000/cancel").status_code == 404
    assert client.delete("/api/yt/jobs/20990101-000000").status_code == 404


def test_cancel_queued_and_delete(client, yt_dirs, no_launch, monkeypatch):
    active = _submit(client).json()
    monkeypatch.setitem(yt_routes._active_workers, active["job_id"], object())
    try:
        queued = _submit(client, "https://youtu.be/queued").json()
    finally:
        yt_routes._active_workers.pop(active["job_id"], None)

    cancelled = client.post(f"/api/yt/jobs/{queued['job_id']}/cancel")
    assert cancelled.status_code == 200
    assert yt_routes._read_sidecar(queued["job_id"])["status"] == "failed"

    deleted = client.delete(f"/api/yt/jobs/{queued['job_id']}")
    assert deleted.status_code == 200
    assert yt_routes._read_sidecar(queued["job_id"]) is None


def test_text_serves_only_output_dir_basenames(client, yt_dirs):
    data_dir, out_dir = yt_dirs
    (out_dir / "Video-abc123.txt").write_text("hello transcript", encoding="utf-8")
    sidecar = {
        "job_id": "20260101-000000",
        "url": "https://youtu.be/abc123",
        "status": "complete",
        # A hostile txt_file must collapse to its basename inside OUTPUT_DIR.
        "txt_file": "..\\..\\secrets.txt",
    }
    yt_routes._write_sidecar("20260101-000000", sidecar)
    resp = client.get("/api/yt/jobs/20260101-000000/text")
    assert resp.status_code == 404

    sidecar["txt_file"] = "Video-abc123.txt"
    yt_routes._write_sidecar("20260101-000000", sidecar)
    resp = client.get("/api/yt/jobs/20260101-000000/text")
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "hello transcript"
    # The widget's Copy button hands txt_path to the clipboard — it must be
    # the absolute on-disk location of the transcript.
    import os
    assert os.path.isabs(body["txt_path"])
    assert body["txt_path"].endswith("Video-abc123.txt")


def test_delete_removes_transcript_txt(client, yt_dirs):
    """× is a real delete: the job's .txt leaves disk with the record."""
    data_dir, out_dir = yt_dirs
    txt = out_dir / "Video-del1.txt"
    txt.write_text("bye", encoding="utf-8")
    yt_routes._write_sidecar("20260103-000000", {
        "job_id": "20260103-000000", "url": "https://youtu.be/del1",
        "status": "complete", "txt_file": "Video-del1.txt",
    })
    resp = client.delete("/api/yt/jobs/20260103-000000")
    assert resp.status_code == 200
    assert "Video-del1.txt" in resp.json()["deleted"]
    assert not txt.exists()


def test_delete_txt_traversal_guard(client, yt_dirs, tmp_path):
    """A hostile txt_file collapses to its basename — files outside
    OUTPUT_DIR are never deleted."""
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me", encoding="utf-8")
    yt_routes._write_sidecar("20260104-000000", {
        "job_id": "20260104-000000", "url": "https://youtu.be/x",
        "status": "complete", "txt_file": "..\\..\\outside.txt",
    })
    resp = client.delete("/api/yt/jobs/20260104-000000")
    assert resp.status_code == 200
    assert outside.exists()


def test_boot_sweep_fails_orphaned_active_jobs(yt_dirs):
    data_dir, _ = yt_dirs
    for status, expect in [
        ("transcribing", "failed"),
        ("queued", "queued"),
        ("complete", "complete"),
    ]:
        job_id = f"2026010{len(status)}-000000"
        yt_routes._write_sidecar(job_id, {
            "job_id": job_id, "url": "https://youtu.be/x", "status": status,
        })
        yt_routes._sweep_orphaned_jobs()
        assert yt_routes._read_sidecar(job_id)["status"] == expect


def test_sse_stream_replays_and_finishes(client, yt_dirs):
    """A terminal job's stream replays its segments then closes."""
    job_id = "20260102-000000"
    yt_routes._write_sidecar(job_id, {
        "job_id": job_id, "url": "https://youtu.be/x", "status": "complete",
    })
    seg_path = yt_routes._segments_path(job_id)
    with seg_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"start": 0.0, "end": 2.0, "text": "hello"}) + "\n")
        f.write(json.dumps({"start": 2.0, "end": 4.0, "text": "world"}) + "\n")

    with client.stream("GET", f"/api/yt/jobs/{job_id}/stream") as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())
    assert "event: status" in body
    assert body.count("event: segment") == 2
    assert '"text": "hello"' in body
    # Ordering contract: the client closes the stream at the terminal status
    # event, so every segment must be emitted before it or it is lost.
    assert body.rindex("event: segment") < body.index("event: status")
