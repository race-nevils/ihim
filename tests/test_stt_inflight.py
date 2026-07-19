"""Inflight WAL — the crash net under the in-RAM recording buffer.

An external kill (port restart, crash, BSOD) mid-recording used to
take the audio with the process (~6 min of dictation lost 2026-07-18).
The WAL appends the buffer to disk every few seconds; the boot sweep
promotes orphaned WALs to recovered/ WAVs.
"""

import json
import os
import time
import wave

import numpy as np
import pytest

from tools.stt.audio import InflightWriter, sweep_inflight

RATE = 16000


def _blocks(n, samples=800):
    """n float32 blocks of a 440Hz tone (samples each)."""
    t = np.arange(n * samples) / RATE
    tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    return [tone[i * samples:(i + 1) * samples] for i in range(n)]


class TestInflightWriter:
    def test_flush_appends_incrementally(self, tmp_path):
        buf = _blocks(3)
        writer = InflightWriter(lambda: (buf, RATE), directory=tmp_path)

        writer.flush()
        size_after_first = writer._pcm_path.stat().st_size
        assert size_after_first == 3 * 800 * 2  # int16

        # Only NEW blocks are appended on the next flush.
        buf.extend(_blocks(2))
        writer.flush()
        assert writer._pcm_path.stat().st_size == 5 * 800 * 2

        meta = json.loads(writer._meta_path.read_text(encoding="utf-8"))
        assert meta["rate"] == RATE

    def test_empty_buffer_writes_nothing(self, tmp_path):
        writer = InflightWriter(lambda: ([], RATE), directory=tmp_path)
        writer.flush()
        assert not writer._pcm_path.exists()
        assert not writer._meta_path.exists()

    def test_stop_final_captures_tail(self, tmp_path):
        # Live snapshot goes empty at capture close — the frozen buffer
        # passed to stop() must supply the tail.
        writer = InflightWriter(lambda: ([], 0), directory=tmp_path)
        frozen = _blocks(4)
        writer.stop(final=(frozen, RATE))
        assert writer._pcm_path.stat().st_size == 4 * 800 * 2

    def test_discard_removes_wal(self, tmp_path):
        writer = InflightWriter(lambda: (_blocks(2), RATE), directory=tmp_path)
        writer.flush()
        assert writer._pcm_path.exists()
        writer.discard()
        assert not writer._pcm_path.exists()
        assert not writer._meta_path.exists()


class TestSweep:
    def _orphan(self, tmp_path, name="inflight-2026-07-18_191800", rate=RATE,
                seconds=2.0, age_s=3600.0):
        pcm = tmp_path / f"{name}.pcm"
        frames = int(rate * seconds)
        pcm.write_bytes(np.zeros(frames, dtype=np.int16).tobytes())
        meta = tmp_path / f"{name}.meta.json"
        meta.write_text(json.dumps({"rate": rate, "started": "x"}),
                        encoding="utf-8")
        old = time.time() - age_s
        os.utime(pcm, (old, old))
        return pcm, meta

    def test_promotes_orphan_to_wav(self, tmp_path):
        pcm, meta = self._orphan(tmp_path, seconds=2.0)
        promoted, skipped = sweep_inflight(tmp_path)
        assert (promoted, skipped) == (1, 0)
        assert not pcm.exists() and not meta.exists()

        out = tmp_path / "2026-07-18_191800_inflight-2s.wav"
        assert out.exists()
        with wave.open(str(out), "rb") as wf:
            assert wf.getframerate() == RATE
            assert wf.getnframes() == RATE * 2

    def test_skips_fresh_wal(self, tmp_path):
        # A fresh WAL belongs to a live recording — never steal it.
        self._orphan(tmp_path, age_s=0.0)
        promoted, skipped = sweep_inflight(tmp_path)
        assert (promoted, skipped) == (0, 1)
        assert len(list(tmp_path.glob("*.pcm"))) == 1

    def test_missing_meta_assumes_16k(self, tmp_path):
        pcm, meta = self._orphan(tmp_path, seconds=1.0)
        meta.unlink()
        promoted, _ = sweep_inflight(tmp_path)
        assert promoted == 1
        with wave.open(str(tmp_path / "2026-07-18_191800_inflight-1s.wav"),
                       "rb") as wf:
            assert wf.getframerate() == 16000

    def test_empty_pcm_cleaned_no_wav(self, tmp_path):
        pcm, meta = self._orphan(tmp_path, seconds=0.0)
        promoted, skipped = sweep_inflight(tmp_path)
        assert (promoted, skipped) == (0, 0)
        assert not pcm.exists() and not meta.exists()
        assert not list(tmp_path.glob("*.wav"))
