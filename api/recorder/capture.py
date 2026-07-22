"""Dual-stream audio capture — mic (sounddevice) + system (PyAudioWPatch WASAPI loopback).

Two threads capture simultaneously. On stop, buffers are concatenated and written as
16-bit mono WAV files at native sample rate. The consumer (faster-whisper) handles
resampling to 16 kHz with its own anti-aliasing filter.
"""

import json
import logging
import os
import threading
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy imports — only fail when actually used, not at module load
_sd = None
_pyaudiowpatch = None
_np = None


def _get_numpy():
    global _np
    if _np is None:
        import numpy as np
        _np = np
    return _np


def _get_sounddevice():
    global _sd
    if _sd is None:
        import sounddevice as sd
        _sd = sd
    return _sd


def _get_pyaudio():
    global _pyaudiowpatch
    if _pyaudiowpatch is None:
        import pyaudiowpatch as paw
        _pyaudiowpatch = paw
    return _pyaudiowpatch



def refresh_portaudio() -> None:
    """Re-initialize PortAudio so its device snapshot matches Windows now.

    The snapshot is frozen at Pa_Initialize for the life of the process: a
    server that started before the audio endpoints were ready (boot race
    after a Windows-update reboot, post-sleep self-restart before a wireless
    headset dongle re-enumerates) sees a device list Windows no longer has —
    default input resolves to -1 and every capture fails until restart
    (2026-07-22). Closes any open PortAudio streams, so call it only from a
    failure path where capture is already broken.
    """
    sd = _get_sounddevice()
    logger.warning("Refreshing PortAudio device snapshot")
    sd._terminate()
    sd._initialize()


# ═══════════════════════════════════════════════════════════════════════
# DEVICE DISCOVERY
# ═══════════════════════════════════════════════════════════════════════

def list_audio_devices() -> dict:
    """Return available mic and WASAPI loopback devices.

    Returns dict with 'mic_devices' and 'system_devices' lists.
    Each entry: {index, name, channels, sample_rate, is_loopback}
    Also returns 'errors' list with any enumeration failures (for diagnostics).
    """
    mic_devices = []
    system_devices = []
    errors = []

    # Mic devices via sounddevice (WASAPI only — avoids duplicates from MME/DirectSound/WDM-KS)
    try:
        sd = _get_sounddevice()
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        wasapi_idx = next((i for i, h in enumerate(hostapis) if "WASAPI" in h["name"]), None)
        for i, dev in enumerate(devices):
            if (dev["max_input_channels"] > 0
                    and "loopback" not in dev["name"].lower()
                    and (wasapi_idx is None or dev["hostapi"] == wasapi_idx)):
                mic_devices.append({
                    "index": i,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "sample_rate": dev["default_samplerate"],
                    "is_loopback": False,
                })
    except Exception as e:
        logger.warning("Failed to enumerate mic devices: %s", e)
        errors.append(f"mic: {e}")

    # System audio (WASAPI loopback) via PyAudioWPatch
    try:
        paw = _get_pyaudio()
        p = paw.PyAudio()
        try:
            wasapi_info = p.get_host_api_info_by_type(paw.paWASAPI)
            for i in range(wasapi_info["deviceCount"]):
                dev_idx = wasapi_info["defaultOutputDevice"] if i == 0 else i
                try:
                    dev = p.get_device_info_by_index(
                        p.get_host_api_info_by_index(wasapi_info["index"])["devices"][i]
                        if hasattr(wasapi_info, "devices") else dev_idx
                    )
                except Exception:
                    continue
                # Check if it's a loopback device
                if dev.get("isLoopbackDevice", False):
                    system_devices.append({
                        "index": dev["index"],
                        "name": dev["name"],
                        "channels": dev["maxInputChannels"],
                        "sample_rate": dev["defaultSampleRate"],
                        "is_loopback": True,
                    })
        finally:
            p.terminate()
    except Exception as e:
        logger.warning("Failed to enumerate WASAPI loopback devices: %s", e)
        errors.append(f"wasapi: {e}")

    # Fallback: scan all PyAudioWPatch devices for loopback
    if not system_devices:
        try:
            paw = _get_pyaudio()
            p = paw.PyAudio()
            try:
                for i in range(p.get_device_count()):
                    try:
                        dev = p.get_device_info_by_index(i)
                        if dev.get("isLoopbackDevice", False) and dev["maxInputChannels"] > 0:
                            system_devices.append({
                                "index": dev["index"],
                                "name": dev["name"],
                                "channels": dev["maxInputChannels"],
                                "sample_rate": dev["defaultSampleRate"],
                                "is_loopback": True,
                            })
                    except Exception:
                        continue
            finally:
                p.terminate()
        except Exception as e:
            logger.warning("Fallback WASAPI scan failed: %s", e)
            errors.append(f"fallback: {e}")

    result = {"mic_devices": mic_devices, "system_devices": system_devices}
    if errors:
        result["errors"] = errors
    return result


def _get_default_mic() -> dict:
    """Return the default mic device info, preferring the WASAPI variant.

    sd.default.device[0] may return an MME device.  Since _capture_mic()
    passes WasapiSettings, we need the WASAPI version of the same hardware.
    """
    sd = _get_sounddevice()
    os_idx = sd.default.device[0]  # (input, output)
    os_dev = sd.query_devices(os_idx)

    # Find the WASAPI host-api index
    hostapis = sd.query_hostapis()
    wasapi_idx = next(
        (i for i, h in enumerate(hostapis) if "WASAPI" in h["name"]), None
    )

    # If the OS default is already WASAPI, use it directly
    if wasapi_idx is not None and os_dev["hostapi"] == wasapi_idx:
        return {
            "index": os_idx,
            "name": os_dev["name"],
            "sample_rate": os_dev["default_samplerate"],
            "is_wasapi": True,
        }

    # Otherwise find the WASAPI device whose name matches the OS default
    if wasapi_idx is not None:
        os_name = os_dev["name"].lower()
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if (dev["hostapi"] == wasapi_idx
                    and dev["max_input_channels"] > 0
                    and "loopback" not in dev["name"].lower()
                    and os_name in dev["name"].lower()):
                logger.info(
                    "Default mic remapped: MME #%d → WASAPI #%d (%s)",
                    os_idx, i, dev["name"],
                )
                return {
                    "index": i,
                    "name": dev["name"],
                    "sample_rate": dev["default_samplerate"],
                    "is_wasapi": True,
                }

    # Fallback: use the OS default as-is (non-WASAPI)
    logger.warning(
        "No WASAPI variant found for default mic '%s' — using as-is", os_dev["name"]
    )
    return {
        "index": os_idx,
        "name": os_dev["name"],
        "sample_rate": os_dev["default_samplerate"],
        "is_wasapi": False,
    }


def _get_default_loopback() -> Optional[dict]:
    """Return the first available WASAPI loopback device info."""
    devices = list_audio_devices()
    if devices["system_devices"]:
        d = devices["system_devices"][0]
        return {"index": d["index"], "name": d["name"], "sample_rate": d["sample_rate"]}
    return None


def _to_mono(data, channels: int):
    """Downmix to mono if needed."""
    if channels <= 1:
        return data
    np = _get_numpy()
    # Reshape and average across channels
    if len(data) % channels != 0:
        data = data[:len(data) - (len(data) % channels)]
    return data.reshape(-1, channels).mean(axis=1).astype(np.float32)


# ═══════════════════════════════════════════════════════════════════════
# CAPTURE ENGINE
# ═══════════════════════════════════════════════════════════════════════

class DualStreamCapture:
    """Captures mic and system audio simultaneously in separate threads."""

    def __init__(
        self,
        mic_device_index: Optional[int] = None,
        sys_device_index: Optional[int] = None,
        checkpoint_dir: Optional[Path] = None,
        checkpoint_interval: int = 60,
    ):
        self._stop_event = threading.Event()
        self._mic_drained = threading.Event()
        self._mic_ready = threading.Event()
        self._mic_buffers: list = []
        self._sys_buffers: list = []
        self._mic_thread: Optional[threading.Thread] = None
        self._sys_thread: Optional[threading.Thread] = None
        self._mic_error: Optional[str] = None
        self._sys_error: Optional[str] = None

        # Streaming disk checkpoints — flush audio to disk every N blocks
        self._checkpoint_dir: Optional[Path] = checkpoint_dir
        self._checkpoint_interval: int = checkpoint_interval
        self._mic_chunk_count: int = 0
        self._sys_chunk_count: int = 0
        self._started_at_iso: Optional[str] = None

        # Resolve devices
        if mic_device_index is not None:
            sd = _get_sounddevice()
            dev = sd.query_devices(mic_device_index)
            hostapis = sd.query_hostapis()
            wasapi_idx = next(
                (i for i, h in enumerate(hostapis) if "WASAPI" in h["name"]), None
            )
            self._mic_info = {
                "index": mic_device_index,
                "name": dev["name"],
                "sample_rate": dev["default_samplerate"],
                "is_wasapi": wasapi_idx is not None and dev["hostapi"] == wasapi_idx,
            }
        else:
            self._mic_info = _get_default_mic()

        if sys_device_index is not None:
            paw = _get_pyaudio()
            p = paw.PyAudio()
            try:
                dev = p.get_device_info_by_index(sys_device_index)
                self._sys_info = {
                    "index": sys_device_index,
                    "name": dev["name"],
                    "sample_rate": dev["defaultSampleRate"],
                }
            finally:
                p.terminate()
        else:
            self._sys_info = _get_default_loopback()

    @property
    def mic_device_name(self) -> str:
        return self._mic_info["name"]

    @property
    def sys_device_name(self) -> str:
        return self._sys_info["name"] if self._sys_info else "none"

    def start(self) -> None:
        """Start capturing both streams."""
        self._stop_event.clear()
        self._mic_drained.clear()
        self._mic_ready.clear()
        self._mic_buffers.clear()
        self._sys_buffers.clear()
        self._mic_error = None
        self._sys_error = None
        self._mic_chunk_count = 0
        self._sys_chunk_count = 0

        # Create checkpoint directory and initial manifest
        if self._checkpoint_dir:
            self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
            self._started_at_iso = datetime.now(timezone.utc).isoformat()
            self._update_manifest()

        self._mic_thread = threading.Thread(
            target=self._capture_mic, daemon=True, name="recorder-mic"
        )
        self._mic_thread.start()

        if self._sys_info:
            self._sys_thread = threading.Thread(
                target=self._capture_system, daemon=True, name="recorder-sys"
            )
            self._sys_thread.start()

    def stop(self) -> None:
        """Signal both threads to stop and wait for them."""
        self._stop_event.set()
        if self._mic_thread:
            self._mic_thread.join(timeout=5)
        if self._sys_thread:
            self._sys_thread.join(timeout=5)

    def stop_mic_and_drain(self, timeout: float = 1.5) -> bool:
        """Signal stop and wait for the mic loop's in-flight block to land.

        The mic thread's blocking stream.read() completes its current
        ~0.5s block after the stop signal, appends it, and only then sets
        the drained event — so a snapshot after this call includes the
        tail of the last spoken word. Never joins the thread: sounddevice's
        stream.stop() hangs on Windows, so the daemon thread is left to
        die on its own.
        """
        self._stop_event.set()
        return self._mic_drained.wait(timeout)

    def wait_mic_ready(self, timeout: float = 1.5) -> bool:
        """True once the mic stream is live and reading; False on open
        failure or timeout.

        A stale device index can resolve fine but fail at stream open —
        without this check the capture looks live while recording dead air.
        """
        if not self._mic_ready.wait(timeout):
            return False
        return self._mic_error is None

    def mic_blocks(self) -> list:
        """Snapshot of mic blocks captured so far (safe during capture)."""
        return list(self._mic_buffers)

    @property
    def mic_sample_rate(self) -> int:
        return int(self._mic_info["sample_rate"])

    def save(self, mic_path: Path, sys_path: Path) -> tuple[str, str]:
        """Write captured audio to WAV files. Returns (mic_name, sys_name)."""
        has_chunks = self._checkpoint_dir and (
            self._mic_chunk_count > 0 or self._sys_chunk_count > 0
        )

        if has_chunks:
            # Combine disk chunks + remaining in-memory buffers
            self._save_with_chunks(
                mic_path, self._mic_buffers,
                int(self._mic_info["sample_rate"]), "mic",
            )
            if self._sys_buffers or self._sys_chunk_count > 0:
                sys_rate = int(self._sys_info["sample_rate"]) if self._sys_info else 16000
                self._save_with_chunks(sys_path, self._sys_buffers, sys_rate, "sys")
            else:
                self._write_wav(sys_path, [], 16000)
        else:
            self._write_wav(mic_path, self._mic_buffers, int(self._mic_info["sample_rate"]))
            if self._sys_buffers:
                sys_rate = int(self._sys_info["sample_rate"]) if self._sys_info else 16000
                self._write_wav(sys_path, self._sys_buffers, sys_rate)
            else:
                self._write_wav(sys_path, [], 16000)

        # Clean up in-progress checkpoint directory
        if self._checkpoint_dir and self._checkpoint_dir.exists():
            import shutil
            shutil.rmtree(self._checkpoint_dir, ignore_errors=True)
            parent = self._checkpoint_dir.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()

        return mic_path.name, sys_path.name

    @property
    def errors(self) -> list[str]:
        errs = []
        if self._mic_error:
            errs.append(f"mic: {self._mic_error}")
        if self._sys_error:
            errs.append(f"sys: {self._sys_error}")
        return errs

    # ── Internal ──────────────────────────────────────────────────────

    def _capture_mic(self) -> None:
        """Capture mic audio via sounddevice (blocking read mode).

        USB headsets (e.g. Corsair VIRTUOSO) hit PaError -9999 in callback
        mode because PortAudio's callback path queries WDM-KS terminal
        categories, which fails on certain USB audio descriptors.  Blocking
        (read) mode bypasses that code path entirely.

        Opens in stereo (native channel count) and extracts channel 0.
        PortAudio's mono downmix (channels=1) corrupts audio on some USB
        devices — capturing stereo and picking a channel avoids this.
        """
        try:
            sd = _get_sounddevice()
            native_rate = int(self._mic_info["sample_rate"])
            block_size = int(native_rate * 0.5)  # 500ms blocks

            # Query native channel count — capture at native, extract ch0
            dev_info = sd.query_devices(self._mic_info["index"])
            native_channels = max(int(dev_info["max_input_channels"]), 1)

            stream = sd.InputStream(
                device=self._mic_info["index"],
                samplerate=native_rate,
                channels=native_channels,
                dtype="float32",
                blocksize=block_size,
            )
            stream.start()
            self._mic_ready.set()
            try:
                while not self._stop_event.is_set():
                    data, overflowed = stream.read(block_size)
                    if overflowed:
                        logger.debug("mic read overflow")
                    self._mic_buffers.append(data[:, 0].copy())
                    # Periodic disk checkpoint
                    if (self._checkpoint_dir
                            and len(self._mic_buffers) >= self._checkpoint_interval):
                        try:
                            self._flush_checkpoint(
                                "mic", list(self._mic_buffers), native_rate,
                            )
                            self._mic_buffers.clear()
                        except Exception as e:
                            logger.warning("mic checkpoint failed: %s", e)
            finally:
                # Drained BEFORE stream.stop() — stop() can hang on Windows,
                # and by this point every block is already appended.
                self._mic_drained.set()
                stream.stop()
                stream.close()
        except Exception as e:
            self._mic_error = str(e)
            logger.error("mic capture error: %s", e)
            self._mic_ready.set()
            self._mic_drained.set()

    def _capture_system(self) -> None:
        """Capture system audio via PyAudioWPatch WASAPI loopback."""
        if not self._sys_info:
            self._sys_error = "No WASAPI loopback device available"
            return

        paw = None
        p = None
        stream = None
        try:
            paw = _get_pyaudio()
            p = paw.PyAudio()
            dev = p.get_device_info_by_index(self._sys_info["index"])
            native_rate = int(dev["defaultSampleRate"])
            channels = max(dev["maxInputChannels"], 1)
            block_size = int(native_rate * 0.5)

            stream = p.open(
                format=paw.paFloat32,
                channels=channels,
                rate=native_rate,
                input=True,
                input_device_index=self._sys_info["index"],
                frames_per_buffer=block_size,
            )

            while not self._stop_event.is_set():
                try:
                    data = stream.read(block_size, exception_on_overflow=False)
                    numpy = _get_numpy()
                    arr = numpy.frombuffer(data, dtype=numpy.float32)
                    arr = _to_mono(arr, channels)
                    self._sys_buffers.append(arr)
                    # Periodic disk checkpoint
                    if (self._checkpoint_dir
                            and len(self._sys_buffers) >= self._checkpoint_interval):
                        try:
                            self._flush_checkpoint(
                                "sys", list(self._sys_buffers), native_rate,
                            )
                            self._sys_buffers.clear()
                        except Exception as e:
                            logger.warning("sys checkpoint failed: %s", e)
                except Exception as e:
                    if not self._stop_event.is_set():
                        logger.warning("sys read error: %s", e)
                    break
        except Exception as e:
            self._sys_error = str(e)
            logger.error("sys capture error: %s", e)
        finally:
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception as e:
                    logger.debug("PyAudio stream cleanup: %s", e)
            if p:
                try:
                    p.terminate()
                except Exception as e:
                    logger.debug("PyAudio terminate: %s", e)

    # ── Checkpointing ──────────────────────────────────────────────

    def _flush_checkpoint(self, stream: str, buffers: list, native_rate: int) -> None:
        """Flush accumulated audio buffers to a raw PCM chunk file on disk."""
        if not self._checkpoint_dir or not buffers:
            return

        np = _get_numpy()
        audio = np.concatenate(buffers)
        pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)

        if stream == "mic":
            chunk_num = self._mic_chunk_count
            self._mic_chunk_count += 1
        else:
            chunk_num = self._sys_chunk_count
            self._sys_chunk_count += 1

        chunk_path = self._checkpoint_dir / f"{stream}-chunk-{chunk_num:04d}.raw"
        chunk_path.write_bytes(pcm.tobytes())

        self._update_manifest()
        logger.debug("Flushed %s chunk %04d (%d samples)", stream, chunk_num, len(pcm))

    def _update_manifest(self) -> None:
        """Update manifest.json with current chunk counts (atomic write)."""
        if not self._checkpoint_dir:
            return
        manifest = {
            "rec_id": self._checkpoint_dir.name,
            "started_at": self._started_at_iso,
            "mic_sample_rate": int(self._mic_info["sample_rate"]),
            "sys_sample_rate": int(self._sys_info["sample_rate"]) if self._sys_info else 16000,
            "mic_chunks": self._mic_chunk_count,
            "sys_chunks": self._sys_chunk_count,
            "mic_device": self._mic_info["name"],
            "sys_device": self._sys_info["name"] if self._sys_info else "none",
        }
        manifest_path = self._checkpoint_dir / "manifest.json"
        tmp = manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(manifest_path))

    def _save_with_chunks(self, path: Path, remaining_buffers: list,
                          native_rate: int, stream: str) -> None:
        """Combine disk chunks + remaining in-memory buffers into final WAV."""
        np = _get_numpy()
        path.parent.mkdir(parents=True, exist_ok=True)

        all_pcm = []

        # Read existing chunks from disk (native rate int16 PCM)
        chunk_count = self._mic_chunk_count if stream == "mic" else self._sys_chunk_count
        for i in range(chunk_count):
            chunk_path = self._checkpoint_dir / f"{stream}-chunk-{i:04d}.raw"
            if chunk_path.exists():
                raw = chunk_path.read_bytes()
                all_pcm.append(np.frombuffer(raw, dtype=np.int16))

        # Process remaining in-memory buffers (float32 at native rate)
        if remaining_buffers:
            audio = np.concatenate(remaining_buffers)
            pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
            all_pcm.append(pcm)

        if not all_pcm:
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(native_rate)
                wf.writeframes(b"")
            return

        final_pcm = np.concatenate(all_pcm)

        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(native_rate)
            wf.writeframes(final_pcm.tobytes())

    # ── WAV Output ───────────────────────────────────────────────

    def _write_wav(self, path: Path, buffers: list, native_rate: int) -> None:
        """Concatenate buffers and write WAV at native sample rate.

        No resampling — let the consumer (faster-whisper) handle resampling
        with its proper anti-aliasing filter (FFmpeg AudioResampler).
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        if not buffers:
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(native_rate)
                wf.writeframes(b"")
            return

        np = _get_numpy()
        audio = np.concatenate(buffers)

        # Convert to 16-bit PCM (no normalization, no resampling)
        pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)

        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(native_rate)
            wf.writeframes(pcm.tobytes())


# ═══════════════════════════════════════════════════════════════════════
# CRASH RECOVERY
# ═══════════════════════════════════════════════════════════════════════

def _write_chunks_as_wav(chunk_dir: Path, stream: str, count: int,
                         sample_rate: int, out_path: Path) -> float:
    """Assemble raw int16 PCM chunk files into a WAV. Returns duration in seconds."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = 0
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(count):
            chunk_path = chunk_dir / f"{stream}-chunk-{i:04d}.raw"
            if not chunk_path.exists():
                continue
            raw = chunk_path.read_bytes()
            wf.writeframes(raw)
            total_frames += len(raw) // 2
    return total_frames / sample_rate if sample_rate else 0.0


def recover_checkpoint(chunk_dir: Path, mic_path: Path, sys_path: Path) -> Optional[dict]:
    """Assemble an interrupted recording's checkpoint chunks into final WAVs.

    Reads manifest.json in chunk_dir, writes both channel WAVs, and returns
    the manifest augmented with 'duration_seconds'. Returns None if the
    directory holds no recoverable audio. Does NOT delete chunk_dir — the
    caller removes it only after the sidecar is safely written.
    """
    manifest_path = chunk_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    mic_chunks = int(manifest.get("mic_chunks", 0))
    sys_chunks = int(manifest.get("sys_chunks", 0))
    if mic_chunks == 0 and sys_chunks == 0:
        return None

    mic_rate = int(manifest.get("mic_sample_rate") or manifest.get("sample_rate") or 16000)
    sys_rate = int(manifest.get("sys_sample_rate") or 16000)

    mic_dur = _write_chunks_as_wav(chunk_dir, "mic", mic_chunks, mic_rate, mic_path)
    sys_dur = _write_chunks_as_wav(chunk_dir, "sys", sys_chunks, sys_rate, sys_path)

    manifest["duration_seconds"] = round(max(mic_dur, sys_dur), 1)
    return manifest
