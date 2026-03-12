"""Dual-stream audio capture — mic (sounddevice) + system (PyAudioWPatch WASAPI loopback).

Two threads capture simultaneously. On stop, buffers are concatenated and written as
16-bit mono WAV files at 16 kHz (resampled from native rate if needed).
"""

import logging
import threading
import wave
import struct
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


TARGET_RATE = 16000  # Whisper expects 16 kHz
CHANNELS = 1         # Mono


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


# ═══════════════════════════════════════════════════════════════════════
# RESAMPLING
# ═══════════════════════════════════════════════════════════════════════

def _resample(data, orig_rate: int, target_rate: int):
    """Simple linear interpolation resample. Good enough for speech."""
    if orig_rate == target_rate:
        return data
    np = _get_numpy()
    ratio = target_rate / orig_rate
    n_samples = int(len(data) * ratio)
    indices = np.linspace(0, len(data) - 1, n_samples)
    return np.interp(indices, np.arange(len(data)), data).astype(np.float32)


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
    ):
        self._stop_event = threading.Event()
        self._mic_buffers: list = []
        self._sys_buffers: list = []
        self._mic_thread: Optional[threading.Thread] = None
        self._sys_thread: Optional[threading.Thread] = None
        self._mic_error: Optional[str] = None
        self._sys_error: Optional[str] = None

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
        self._mic_buffers.clear()
        self._sys_buffers.clear()
        self._mic_error = None
        self._sys_error = None

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

    def save(self, mic_path: Path, sys_path: Path) -> tuple[str, str]:
        """Write captured audio to WAV files. Returns (mic_name, sys_name)."""
        self._write_wav(mic_path, self._mic_buffers, int(self._mic_info["sample_rate"]))
        if self._sys_buffers:
            sys_rate = int(self._sys_info["sample_rate"]) if self._sys_info else TARGET_RATE
            self._write_wav(sys_path, self._sys_buffers, sys_rate)
        else:
            # Write empty WAV if no system audio captured
            self._write_wav(sys_path, [], TARGET_RATE)
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
        """
        try:
            sd = _get_sounddevice()
            native_rate = int(self._mic_info["sample_rate"])
            block_size = int(native_rate * 0.5)  # 500ms blocks

            stream = sd.InputStream(
                device=self._mic_info["index"],
                samplerate=native_rate,
                channels=1,
                dtype="float32",
                blocksize=block_size,
            )
            stream.start()
            try:
                while not self._stop_event.is_set():
                    data, overflowed = stream.read(block_size)
                    if overflowed:
                        logger.debug("mic read overflow")
                    self._mic_buffers.append(data[:, 0].copy())
            finally:
                stream.stop()
                stream.close()
        except Exception as e:
            self._mic_error = str(e)
            logger.error("mic capture error: %s", e)

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

    def _write_wav(self, path: Path, buffers: list, native_rate: int) -> None:
        """Concatenate buffers, resample to 16 kHz, write 16-bit mono WAV."""
        path.parent.mkdir(parents=True, exist_ok=True)

        if not buffers:
            # Write a minimal valid WAV (silence)
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(TARGET_RATE)
                wf.writeframes(b"")
            return

        np = _get_numpy()
        audio = np.concatenate(buffers)
        audio = _resample(audio, native_rate, TARGET_RATE)

        # Normalize to prevent clipping
        peak = np.abs(audio).max()
        if peak > 0:
            audio = audio / peak * 0.95

        # Convert to 16-bit PCM
        pcm = (audio * 32767).astype(np.int16)

        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(TARGET_RATE)
            wf.writeframes(pcm.tobytes())
