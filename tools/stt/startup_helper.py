"""Windows Startup folder integration — launch stt on login (no admin needed).

Creates/removes a .lnk shortcut in the user's Startup folder pointing to
``pythonw -m tools.stt.app`` inside the IHIM directory.
"""

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_SHORTCUT_NAME = "STT Dictation.lnk"
_IHIM_ROOT = Path(__file__).resolve().parents[2]


def _startup_folder() -> Path:
    """Return the user's Windows Startup folder."""
    import os
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _shortcut_path() -> Path:
    return _startup_folder() / _SHORTCUT_NAME


def is_startup_enabled() -> bool:
    """Check if the STT startup shortcut exists."""
    return _shortcut_path().exists()


def enable_startup() -> bool:
    """Create a .lnk shortcut in the Startup folder.

    Points to: pythonw -m tools.stt.app (in the IHIM directory).
    Returns True on success.
    """
    try:
        import win32com.client

        pythonw = Path(sys.prefix) / "pythonw.exe"
        if not pythonw.exists():
            pythonw = Path(sys.prefix) / "Scripts" / "pythonw.exe"
        if not pythonw.exists():
            # Fall back to python.exe (will show console)
            pythonw = Path(sys.executable)

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(_shortcut_path()))
        shortcut.TargetPath = str(pythonw)
        shortcut.Arguments = "-m tools.stt.app"
        shortcut.WorkingDirectory = str(_IHIM_ROOT)
        shortcut.Description = "STT Dictation — hold-to-talk voice typing"
        shortcut.save()

        logger.info("Startup shortcut created: %s", _shortcut_path())
        return True

    except Exception as exc:
        logger.error("Failed to create startup shortcut: %s", exc)
        return False


def disable_startup() -> bool:
    """Remove the startup shortcut. Returns True if removed or already absent."""
    path = _shortcut_path()
    if not path.exists():
        return True
    try:
        path.unlink()
        logger.info("Startup shortcut removed: %s", path)
        return True
    except Exception as exc:
        logger.error("Failed to remove startup shortcut: %s", exc)
        return False
