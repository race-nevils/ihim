"""Text injection into the active window via clipboard paste or pynput typing.

Primary method: write text to the Windows clipboard, simulate Ctrl+V, then
restore the previous clipboard contents in a daemon thread (50ms after paste).

Fallback method: pynput keyboard controller's type() — slower but always works.

Alt+Shift+Z recall: re-injects the last successfully injected transcript.
Same hotkey as STT Flow.
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Delay before injection to allow focus to return to the target window.
FOCUS_DELAY_S: float = 0.15

# Delay before restoring the clipboard (gives Ctrl+V time to complete).
CLIPBOARD_RESTORE_DELAY_S: float = 0.25

# Module-level store for the last successfully injected text.
_last_injected: Optional[str] = None
_last_injected_time: float = 0.0
_DEDUP_WINDOW_S: float = 2.0  # ignore duplicate injection within this window

# Recall listener state.
_recall_listener: Optional[object] = None
_recall_lock = threading.Lock()


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
        from pynput.keyboard import Controller, Key
        kb = Controller()
        kb.press(Key.ctrl_l)
        time.sleep(0.02)
        kb.press('v')
        time.sleep(0.02)
        kb.release('v')
        time.sleep(0.02)
        kb.release(Key.ctrl_l)
    except Exception as exc:
        logger.debug("Ctrl+V simulation failed: %s", exc)
        # Try to restore clipboard even on failure.
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
    global _last_injected, _last_injected_time

    if not text:
        return False

    # Dedup guard — skip if identical text was just injected
    now = time.time()
    if text == _last_injected and (now - _last_injected_time) < _DEDUP_WINDOW_S:
        logger.info("Dedup: skipping duplicate injection within %.1fs window", _DEDUP_WINDOW_S)
        return True

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
        _last_injected = text
        _last_injected_time = time.time()
        logger.info(
            "Injected %d characters via %s",
            len(text),
            "clipboard" if method != "pynput" else "pynput",
        )

    return success


# ---------------------------------------------------------------------------
# Alt+Shift+Z recall hotkey
# ---------------------------------------------------------------------------

def _recall_handler() -> None:
    """Re-inject the last transcript when the recall hotkey fires."""
    text = _last_injected
    if not text:
        logger.debug("Recall hotkey fired but no previous transcript to inject")
        return
    logger.info("Recall hotkey: re-injecting last transcript (%d chars)", len(text))
    inject_text(text, method="auto")


def start_recall_listener() -> None:
    """Start the Alt+Shift+Z global hotkey listener in a daemon thread.

    Idempotent — calling when already running is a no-op.
    """
    global _recall_listener

    with _recall_lock:
        if _recall_listener is not None:
            logger.debug("Recall listener already running")
            return

        try:
            from pynput import keyboard as pynput_keyboard

            # pynput GlobalHotKeys uses a string mapping.
            hotkeys = {
                "<alt>+<shift>+z": _recall_handler,
            }
            listener = pynput_keyboard.GlobalHotKeys(hotkeys)
            listener.daemon = True
            listener.start()
            _recall_listener = listener
            logger.info("Recall hotkey listener started: Alt+Shift+Z")
        except Exception as exc:
            logger.error("Failed to start recall listener: %s", exc)


def stop_recall_listener() -> None:
    """Stop the Alt+Shift+Z hotkey listener."""
    global _recall_listener

    with _recall_lock:
        if _recall_listener is None:
            return
        try:
            _recall_listener.stop()
        except Exception as exc:
            logger.debug("Error stopping recall listener: %s", exc)
        finally:
            _recall_listener = None
            logger.info("Recall hotkey listener stopped")
