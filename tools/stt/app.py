"""Floating dictation bar — standalone entry point.

Launch:
    cd IHIM && pythonw -m tools.stt.app      # no console
    cd IHIM && python  -m tools.stt.app      # debug console

Wires together:
    DictationBar  — tkinter pill overlay
    TrayIcon      — system tray (show/hide, exit)
    STTEngine   — hotkey → record → transcribe → inject
"""

import atexit
import logging
import math
import signal
import sys
from pathlib import Path

# ------------------------------------------------------------------
# Bootstrap: ensure IHIM root is on sys.path so "from tools.stt…"
# and "from api.recorder…" both resolve.
# ------------------------------------------------------------------
_IHIM_ROOT = str(Path(__file__).resolve().parents[2])
if _IHIM_ROOT not in sys.path:
    sys.path.insert(0, _IHIM_ROOT)

# ------------------------------------------------------------------
# Logging — console only (pythonw hides it; python shows it)
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("stt.app")

# ------------------------------------------------------------------
# Imports (after path setup)
# ------------------------------------------------------------------
from tools.stt.bar import DictationBar          # noqa: E402
from tools.stt.config import load_config         # noqa: E402
from tools.stt.engine import STTEngine         # noqa: E402
from tools.stt.inject import start_recall_listener, stop_recall_listener  # noqa: E402
from tools.stt.tray import TrayIcon              # noqa: E402


def _rms_from_buffers(capture) -> float:
    """Compute RMS (0.0–1.0) from the latest mic buffer chunk.

    Reads ``capture._mic_buffers[-1]`` which is a numpy float32 array.
    Returns 0.0 if nothing is available.
    """
    try:
        bufs = capture._mic_buffers
        if not bufs:
            return 0.0
        chunk = bufs[-1]
        rms_raw = float(math.sqrt(max(0.0, float((chunk * chunk).mean()))))
        # Normalise: typical speech peaks around 0.05–0.15 raw RMS;
        # scale so that normal speech ≈ 0.5–0.8 on the meter.
        return min(1.0, rms_raw * 10.0)
    except Exception:
        return 0.0


def main() -> None:
    cfg = load_config()

    # 1. Create the bar (also creates root Tk)
    bar = DictationBar()

    # 2. Create the engine with the configured hotkey
    hotkey = tuple(cfg["hotkey"]) if isinstance(cfg["hotkey"], list) else cfg["hotkey"]
    engine = STTEngine(hotkey=hotkey, config=cfg)

    # 3. Wire engine state → bar state
    def on_state_change(status: str):
        bar.set_state(status)
    engine.set_state_callback(on_state_change)

    # 4. Wire RMS volume meter (polls during recording)
    _rms_poll_id = [None]  # mutable container for after-id
    _rms_polling = [False]  # guard against double-start

    def poll_rms():
        if not _rms_polling[0]:
            _rms_poll_id[0] = None
            return
        capture = engine._mic._capture
        if capture is not None:
            bar.set_rms(_rms_from_buffers(capture))
        else:
            bar.set_rms(0.0)
        _rms_poll_id[0] = bar.root.after(50, poll_rms)

    # Start/stop polling — always runs on main thread via root.after
    _orig_cb = on_state_change

    def _start_rms_poll():
        """Start RMS polling (must be called on main thread)."""
        if _rms_polling[0]:
            return  # already running
        _rms_polling[0] = True
        poll_rms()

    def _stop_rms_poll():
        """Stop RMS polling (must be called on main thread)."""
        _rms_polling[0] = False
        if _rms_poll_id[0] is not None:
            bar.root.after_cancel(_rms_poll_id[0])
            _rms_poll_id[0] = None
        bar.set_rms(0.0)

    def on_state_with_rms(status: str):
        _orig_cb(status)
        # Defer poll start/stop to main thread (callback fires from engine thread)
        if status in ("recording", "warning", "locked"):
            bar.root.after(0, _start_rms_poll)
        else:
            bar.root.after(0, _stop_rms_poll)

    engine.set_state_callback(on_state_with_rms)

    # 5. System tray
    tray = TrayIcon(bar)
    tray.start()

    # 6. Alt+Shift+Z recall hotkey
    start_recall_listener()

    # 7. Cleanup
    def cleanup():
        engine.stop_listening()
        stop_recall_listener()
        tray.stop()

    atexit.register(cleanup)

    def sig_handler(signum, frame):
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    # 8. Start engine (activates hotkey listener)
    engine.start_listening()

    logger.info("STT dictation bar running  (hotkey: %s)", hotkey)
    logger.info("Hold hotkey to record, release to transcribe+inject")

    # 9. Mainloop (blocks until bar.quit())
    try:
        bar.run()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
