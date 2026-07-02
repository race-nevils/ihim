"""Unit tests for the chunked streaming transcriber.

No GPU, no mic — transcription is monkeypatched; audio blocks are
synthetic numpy arrays. Covers the cut-point rules that keep commits
out of live speech and the finalize assembly (committed + final window).
"""

import time

import numpy as np
import pytest

import tools.stt.streaming as streaming
from tools.stt.streaming import ChunkedTranscriber, _pick_cut

RATE = 16000
BLOCK_S = 0.5
BLOCK = int(RATE * BLOCK_S)


def _blocks(seconds: float) -> list:
    return [np.zeros(BLOCK, dtype=np.float32) for _ in range(int(seconds / BLOCK_S))]


def _seg(start, end, text="words"):
    return {"start": start, "end": end, "text": text}


class FakeMic:
    def __init__(self, blocks):
        self._blocks = blocks

    def snapshot(self):
        return list(self._blocks), RATE


# ---------------------------------------------------------------------------
# _pick_cut — the commit-safety rules
# ---------------------------------------------------------------------------

class TestPickCut:
    def test_cuts_in_clear_silence_gap(self):
        segs = [_seg(0.0, 4.0), _seg(6.0, 9.0)]
        cut = _pick_cut(segs, window_s=12.0, block_s=BLOCK_S)
        assert cut is not None
        index, advance = cut
        assert index == 0
        # Cut lands after the segment end and before the next speech start
        # minus the VAD pad.
        assert 4.0 <= advance * BLOCK_S <= 6.0 - 0.2

    def test_never_commits_the_last_segment(self):
        # Speech may continue past the snapshot — the final segment is
        # never committable even with silence behind it.
        segs = [_seg(0.0, 4.0)]
        assert _pick_cut(segs, window_s=12.0, block_s=BLOCK_S) is None

    def test_no_cut_when_gap_too_small(self):
        segs = [_seg(0.0, 4.0), _seg(4.5, 9.0)]
        assert _pick_cut(segs, window_s=12.0, block_s=BLOCK_S) is None

    def test_no_cut_near_live_edge(self):
        # Gap is fine but the candidate ends within the edge guard.
        segs = [_seg(0.0, 10.5), _seg(11.8, 12.0)]
        assert _pick_cut(segs, window_s=12.0, block_s=BLOCK_S) is None

    def test_picks_latest_valid_gap(self):
        segs = [_seg(0.0, 2.0), _seg(3.5, 6.0), _seg(8.0, 9.0), _seg(9.2, 15.0)]
        cut = _pick_cut(segs, window_s=17.0, block_s=BLOCK_S)
        assert cut is not None
        assert cut[0] == 1  # gap after seg 2 (6.0→8.0) is the last safe one

    def test_empty_segments(self):
        assert _pick_cut([], window_s=12.0, block_s=BLOCK_S) is None


# ---------------------------------------------------------------------------
# Commit flow + finalize assembly
# ---------------------------------------------------------------------------

@pytest.fixture
def no_wav(monkeypatch, tmp_path):
    """Make write_wav cheap — no real WAV encoding needed."""
    def fake_write_wav(blocks, rate, path=None):
        p = tmp_path / "fake.wav"
        p.write_bytes(b"")
        return p
    monkeypatch.setattr(streaming, "write_wav", fake_write_wav)
    return fake_write_wav


class TestCommitFlow:
    def test_below_threshold_does_nothing(self, monkeypatch, no_wav):
        mic = FakeMic(_blocks(5.0))
        ct = ChunkedTranscriber(mic, "model")
        called = []
        monkeypatch.setattr(
            "tools.stt.transcribe.transcribe_segments",
            lambda *a, **k: called.append(1) or [],
        )
        ct._maybe_commit()
        assert not called
        assert ct.committed == ("", 0)

    def test_commit_banks_text_and_advances(self, monkeypatch, no_wav):
        mic = FakeMic(_blocks(12.0))
        ct = ChunkedTranscriber(mic, "model")
        monkeypatch.setattr(
            "tools.stt.transcribe.transcribe_segments",
            lambda *a, **k: [_seg(0.0, 4.0, "first chunk"), _seg(6.0, 9.5, "still talking")],
        )
        ct._maybe_commit()
        text, blocks_off = ct.committed
        assert text == "first chunk"
        assert 8 <= blocks_off <= 11  # cut inside the 4.0–6.0s gap
        # The uncommitted remainder still holds the in-progress speech.

    def test_no_commit_without_pause(self, monkeypatch, no_wav):
        mic = FakeMic(_blocks(12.0))
        ct = ChunkedTranscriber(mic, "model")
        monkeypatch.setattr(
            "tools.stt.transcribe.transcribe_segments",
            lambda *a, **k: [_seg(0.0, 11.8, "continuous speech")],
        )
        ct._maybe_commit()
        assert ct.committed == ("", 0)

    def test_finalize_joins_committed_and_final_window(self, monkeypatch, no_wav):
        mic = FakeMic(_blocks(14.0))
        ct = ChunkedTranscriber(mic, "model")
        ct._committed_text = ["first chunk"]
        ct._committed_blocks = 10  # 5.0s committed

        seen = {}
        def fake_transcribe(path, model_size=None, prev_text=""):
            seen["prev_text"] = prev_text
            return "and the ending"
        monkeypatch.setattr("tools.stt.transcribe.transcribe", fake_transcribe)

        blocks, rate = mic.snapshot()
        out = ct.finalize(blocks, rate)
        assert out == "first chunk and the ending"
        # Committed tail rides as decoder context for the final window.
        assert seen["prev_text"] == "first chunk"

    def test_finalize_with_no_uncommitted_audio(self, no_wav):
        mic = FakeMic(_blocks(5.0))
        ct = ChunkedTranscriber(mic, "model")
        ct._committed_text = ["everything already banked"]
        ct._committed_blocks = 10
        blocks, rate = mic.snapshot()
        assert ct.finalize(blocks, rate) == "everything already banked"

    def test_finalize_without_any_commits_transcribes_everything(
        self, monkeypatch, no_wav
    ):
        mic = FakeMic(_blocks(6.0))
        ct = ChunkedTranscriber(mic, "model")
        monkeypatch.setattr(
            "tools.stt.transcribe.transcribe",
            lambda path, model_size=None, prev_text="": "short dictation",
        )
        blocks, rate = mic.snapshot()
        assert ct.finalize(blocks, rate) == "short dictation"


class TestLiveThread:
    def test_loop_commits_then_finalize_joins_cleanly(self, monkeypatch, no_wav):
        """End-to-end through the real daemon thread: grow the buffer past
        the commit threshold, watch a commit land, then finalize on the
        frozen buffer — full transcript = banked chunk + final window."""
        monkeypatch.setattr(streaming, "_POLL_S", 0.02)
        mic = FakeMic(_blocks(12.0))
        ct = ChunkedTranscriber(mic, "model")

        monkeypatch.setattr(
            "tools.stt.transcribe.transcribe_segments",
            lambda *a, **k: [_seg(0.0, 4.0, "banked chunk"), _seg(6.0, 9.5, "live")],
        )
        monkeypatch.setattr(
            "tools.stt.transcribe.transcribe",
            lambda path, model_size=None, prev_text="": "final window",
        )

        ct.start()
        deadline = time.monotonic() + 5.0
        while ct.committed[1] == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ct.committed[0] == "banked chunk"

        mic._blocks.extend(_blocks(2.0))  # audio keeps arriving pre-release
        blocks, rate = mic.snapshot()
        out = ct.finalize(blocks, rate)
        assert out == "banked chunk final window"
        assert not ct._thread.is_alive()
