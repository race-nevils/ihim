"""Mic capture for dictation — wraps DualStreamCapture in mic-only mode.

Audio lives as a list of ~0.5s float32 blocks that grows while recording.
The streaming transcriber reads a live snapshot() during recording;
stop() freezes the buffer at release (drain-aware, so the in-flight
block holding the last word's tail is included) and returns it.

InflightWriter is the crash net under that RAM buffer: while recording,
it appends the buffer to an on-disk PCM WAL every few seconds, so an
external kill (port restart, crash, BSOD) can no longer take the
audio with the process. _salvage_audio only catches in-process failures
— a restart mid-recording lost ~6 min of dictation on 2026-07-18.
sweep_inflight() promotes orphaned WALs to recovered/ WAVs at boot.
"""

import json
import logging
import tempfile
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

RECOVERED_DIR = Path(__file__).parent / "data" / "recovered"

# Append the in-RAM recording buffer to the on-disk WAL this often.
_INFLIGHT_FLUSH_S = 3.0
# sweep_inflight() skips WALs younger than this — a live recording's WAL
# refreshes its mtime every flush, so only a dead process's WAL ages past it.
_SWEEP_MIN_AGE_S = 60.0


def write_wav(blocks: list, sample_rate: int, path: Optional[Path] = None) -> Path:
    """Write float32 mono blocks as a 16-bit WAV at native sample rate.

    No normalization, no resampling — faster-whisper resamples internally
    with its own anti-aliasing filter. Creates a temp file when *path* is
    None. Returns the path written.
    """
    import numpy as np

    if path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        path = Path(tmp.name)
        tmp.close()

    if blocks:
        audio = np.concatenate(blocks)
        pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    else:
        pcm = np.zeros(0, dtype=np.int16)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return path


def _to_int16_bytes(blocks: list) -> bytes:
    """float32 blocks → 16-bit PCM bytes (same conversion as write_wav)."""
    import numpy as np

    audio = np.concatenate(blocks)
    return (audio * 32767).clip(-32768, 32767).astype(np.int16).tobytes()


class InflightWriter:
    """Append-only on-disk WAL of a recording in progress.

    Every flush appends only the blocks not yet written — raw int16 PCM,
    no WAV header, so a kill at any byte leaves a fully recoverable file
    (a WAV header holds a frame count patched on close; a killed writer
    would leave it wrong). The sample rate lives in a sidecar
    ``.meta.json`` written on the first flush. ``discard()`` removes both
    — call it only once the audio is persisted elsewhere (retained FLAC,
    salvage WAV) or the dictation completed.
    """

    def __init__(self, snapshot: Callable[[], tuple[list, int]],
                 directory: Path = RECOVERED_DIR):
        self._snapshot = snapshot
        self._dir = directory
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._flushed_blocks = 0
        self._meta_written = False
        stamp = time.strftime("%Y-%m-%d_%H%M%S")
        self._pcm_path = directory / f"inflight-{stamp}.pcm"
        self._meta_path = directory / f"inflight-{stamp}.meta.json"

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="stt-inflight",
        )
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop_event.wait(_INFLIGHT_FLUSH_S):
            self.flush()

    def flush(self) -> None:
        """Append blocks recorded since the last flush. Never raises."""
        try:
            blocks, rate = self._snapshot()
            if not blocks or not rate:
                return
            new = blocks[self._flushed_blocks:]
            if not new:
                return
            if not self._meta_written:
                self._dir.mkdir(parents=True, exist_ok=True)
                self._meta_path.write_text(json.dumps({
                    "rate": rate,
                    "started": datetime.now(timezone.utc).isoformat(),
                }), encoding="utf-8")
                self._meta_written = True
            with open(self._pcm_path, "ab") as f:
                f.write(_to_int16_bytes(new))
            self._flushed_blocks += len(new)
        except Exception:
            logger.warning("Inflight WAL flush failed", exc_info=True)

    def stop(self, final: Optional[tuple[list, int]] = None) -> None:
        """Stop the flush loop, then flush once more. Keeps the WAL.

        *final* is the frozen (blocks, rate) from MicCapture.stop() —
        after the capture closes, the live snapshot reads empty, so the
        tail since the last flush must come from the frozen buffer. The
        WAL then stays complete through 'processing': a kill during
        transcription still recovers the full audio.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if final is not None:
            self._snapshot = lambda: final
        self.flush()

    def discard(self) -> None:
        """Delete the WAL — the audio is safely persisted elsewhere."""
        for path in (self._pcm_path, self._meta_path):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                logger.warning("Inflight WAL cleanup failed: %s", path)


def sweep_inflight(directory: Path = RECOVERED_DIR,
                   min_age_s: float = _SWEEP_MIN_AGE_S) -> tuple[int, int]:
    """Promote orphaned inflight WALs to recovered/ WAVs.

    Returns (promoted, skipped). A WAL younger than *min_age_s* belongs
    to a recording in progress (its mtime refreshes every flush) — skip
    it; the caller re-sweeps later. Runs at engine boot: any WAL old
    enough to sweep is from a process that died mid-recording.
    """
    promoted = skipped = 0
    now = time.time()
    for pcm_path in sorted(directory.glob("inflight-*.pcm")):
        try:
            if now - pcm_path.stat().st_mtime < min_age_s:
                skipped += 1
                continue
            meta_path = pcm_path.with_suffix(".meta.json")
            rate = 16000
            try:
                rate = int(json.loads(meta_path.read_text(encoding="utf-8"))["rate"])
            except Exception:
                logger.warning("Inflight meta unreadable for %s — assuming 16kHz",
                               pcm_path.name)
            data = pcm_path.read_bytes()
            if data:
                duration_s = (len(data) // 2) / rate
                stamp = pcm_path.stem[len("inflight-"):]
                out = directory / f"{stamp}_inflight-{int(round(duration_s))}s.wav"
                with wave.open(str(out), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(rate)
                    wf.writeframes(data)
                logger.error(
                    "Recovered in-flight dictation audio: %s (%.1fs) — "
                    "process died mid-recording", out, duration_s,
                )
                promoted += 1
            pcm_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
        except Exception:
            logger.error("Inflight sweep failed for %s", pcm_path, exc_info=True)
    return promoted, skipped


class MicCapture:
    """Record microphone audio into float32 blocks.

    Uses DualStreamCapture with sys_device_index=None (mic-only mode).
    """

    def __init__(self, mic_device_index: Optional[int] = None):
        self._mic_device_index = mic_device_index
        self._capture = None
        self._lock = threading.Lock()
        self._inflight: Optional[InflightWriter] = None

    def start(self) -> None:
        """Begin mic capture (+ the on-disk inflight WAL)."""
        from api.recorder.capture import DualStreamCapture

        with self._lock:
            if self._capture is not None:
                logger.warning("MicCapture.start() called while already recording")
                return
            self._capture = DualStreamCapture(
                mic_device_index=self._mic_device_index,
                sys_device_index=None,  # mic-only
            )
            self._capture.start()
            self._inflight = InflightWriter(self.snapshot)
            self._inflight.start()
            logger.info("Mic capture started")

    def snapshot(self) -> tuple[list, int]:
        """Live (blocks so far, native sample rate). Safe during capture."""
        capture = self._capture
        if capture is None:
            return [], 16000
        return capture.mic_blocks(), capture.mic_sample_rate

    def stop(self) -> tuple[list, int]:
        """Stop capture and return the frozen (blocks, sample_rate).

        Waits for the capture thread's in-flight block read to land before
        snapshotting, so the audio ends at the release point — including
        the tail of the last spoken word — with no post-release dead air.
        """
        with self._lock:
            if self._capture is None:
                raise RuntimeError("MicCapture.stop() called but not recording")
            capture = self._capture
            self._capture = None

        if not capture.stop_mic_and_drain(timeout=1.5):
            logger.warning("Mic drain timed out — snapshotting current buffers")
        blocks = capture.mic_blocks()
        rate = capture.mic_sample_rate
        if self._inflight is not None:
            self._inflight.stop(final=(blocks, rate))
        logger.info("Mic capture stopped (%d blocks)", len(blocks))
        return blocks, rate

    def discard_inflight(self) -> None:
        """Drop the WAL — call once the audio is persisted elsewhere."""
        inflight, self._inflight = self._inflight, None
        if inflight is not None:
            inflight.stop()
            inflight.discard()

    @property
    def is_recording(self) -> bool:
        return self._capture is not None
