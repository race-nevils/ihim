"""Text injection into the active window via clipboard paste or pynput typing.

Primary method: write text to the Windows clipboard, simulate Ctrl+V, then
restore the previous clipboard contents in a daemon thread after the paste.

Fallback method: pynput keyboard controller's type() — slower but always works.
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Delay before injection to allow focus to return to the target window.
FOCUS_DELAY_S: float = 0.25

# Delay before restoring the clipboard (gives Ctrl+V time to complete).
CLIPBOARD_RESTORE_DELAY_S: float = 0.15


# ---------------------------------------------------------------------------
# Clipboard helpers
# ---------------------------------------------------------------------------

def _clipboard_get() -> Optional[str]:
    """Return current clipboard text, or None if unavailable or non-text."""
    try:
        import win32clipboard
        import win32con
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception as exc:
        logger.debug("Clipboard read failed: %s", exc)
    return None


def _clipboard_set(text: str) -> bool:
    """Write *text* to the clipboard. Returns True on success."""
    try:
        import win32clipboard
        import win32con
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception as exc:
        logger.debug("Clipboard write failed: %s", exc)
        return False


def _clipboard_restore_after(text: Optional[str], delay_s: float) -> None:
    """Restore *text* to the clipboard after *delay_s* seconds (daemon thread)."""
    def _restore():
        time.sleep(delay_s)
        if text is None:
            # Clear clipboard rather than leave injection text sitting there.
            try:
                import win32clipboard
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                finally:
                    win32clipboard.CloseClipboard()
            except Exception as exc:
                logger.debug("Clipboard clear failed: %s", exc)
        else:
            _clipboard_set(text)

    t = threading.Thread(target=_restore, daemon=True, name="stt-clipboard-restore")
    t.start()


# ---------------------------------------------------------------------------
# Injection methods
# ---------------------------------------------------------------------------

def _inject_via_clipboard(text: str) -> bool:
    """Inject *text* via clipboard + Ctrl+V simulation.

    Returns True on success, False if clipboard or paste simulation failed.
    """
    # Save current clipboard before we clobber it.
    previous = _clipboard_get()

    if not _clipboard_set(text):
        return False

    try:
        import ctypes
        from ctypes import wintypes

        _SendInput = ctypes.windll.user32.SendInput
        _SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
        _SendInput.restype = wintypes.UINT

        VK_CONTROL = 0x11
        VK_V = 0x56
        KEYEVENTF_KEYUP = 0x0002
        INPUT_KEYBOARD = 1

        # Full union with MOUSEINPUT for correct struct sizing on 64-bit.
        # Without MOUSEINPUT the union is too small and SendInput silently
        # injects 0 events.
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class INPUT(ctypes.Structure):
            class _INPUT(ctypes.Union):
                _fields_ = [
                    ("ki", KEYBDINPUT),
                    ("mi", MOUSEINPUT),
                    ("hi", HARDWAREINPUT),
                ]
            _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT)]

        def _key_event(vk, flags=0):
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp._input.ki.wVk = vk
            inp._input.ki.dwFlags = flags
            return inp

        events = (INPUT * 4)(
            _key_event(VK_CONTROL),
            _key_event(VK_V),
            _key_event(VK_V, KEYEVENTF_KEYUP),
            _key_event(VK_CONTROL, KEYEVENTF_KEYUP),
        )
        sent = _SendInput(4, ctypes.pointer(events), ctypes.sizeof(INPUT))
        if sent != 4:
            logger.warning("SendInput returned %d (expected 4), paste may have failed", sent)
            _clipboard_restore_after(previous, 0)
            return False
    except Exception as exc:
        logger.debug("Ctrl+V simulation failed: %s", exc)
        _clipboard_restore_after(previous, 0)
        return False

    # Restore clipboard in background after paste has time to land.
    _clipboard_restore_after(previous, CLIPBOARD_RESTORE_DELAY_S)
    return True


def _inject_via_pynput(text: str) -> None:
    """Inject *text* by typing it character-by-character via pynput."""
    from pynput.keyboard import Controller
    kb = Controller()
    kb.type(text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def inject_text(text: str, method: str = "auto") -> bool:
    """Inject *text* into the currently focused window.

    Args:
        text:   The text to inject.
        method: Injection strategy.
                "auto"      — clipboard first, pynput fallback (default).
                "clipboard" — clipboard + Ctrl+V only (raises on failure).
                "pynput"    — pynput type() only.

    Returns:
        True if injection succeeded, False otherwise.
    """
    if not text:
        return False

    time.sleep(FOCUS_DELAY_S)

    success = False

    if method == "pynput":
        try:
            _inject_via_pynput(text)
            success = True
        except Exception as exc:
            logger.error("pynput injection failed: %s", exc)

    elif method == "clipboard":
        success = _inject_via_clipboard(text)
        if not success:
            logger.error("Clipboard injection failed and no fallback requested")

    else:  # "auto"
        success = _inject_via_clipboard(text)
        if not success:
            logger.warning(
                "Clipboard injection failed, falling back to pynput type()"
            )
            try:
                _inject_via_pynput(text)
                success = True
            except Exception as exc:
                logger.error("pynput fallback injection also failed: %s", exc)

    if success:
        logger.info(
            "Injected %d characters via %s",
            len(text),
            "clipboard" if method != "pynput" else "pynput",
        )

    return success
