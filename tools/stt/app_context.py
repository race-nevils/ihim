"""Detect the currently focused application window and map it to a context hint.

Used by the cleanup pipeline to apply context-appropriate post-processing.
For example, code editors get minimal punctuation cleanup while prose editors
get full sentence formatting.

Context values:
    "code"      — IDE or text editor (VS Code, PyCharm, Vim, etc.)
    "terminal"  — shell or terminal emulator
    "chat"      — messaging app (Slack, Discord, Teams, etc.)
    "prose"     — everything else (Word, browser, email, Notepad, etc.)
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Context keyword maps
# ---------------------------------------------------------------------------

# Each entry is (context_name, [substrings to match in window title]).
# Checked in order — first match wins.
_CONTEXT_RULES: list[tuple[str, list[str]]] = [
    ("code", [
        "Visual Studio Code",
        "VS Code",
        "Code -",
        "PyCharm",
        "IntelliJ",
        "Sublime",
        "Vim",
        "Neovim",
    ]),
    ("terminal", [
        "Windows Terminal",
        "Terminal",
        "PowerShell",
        "Command Prompt",
        "cmd.exe",
        "bash",
        "Git Bash",
        "Alacritty",
        "Wezterm",
    ]),
    ("chat", [
        "Slack",
        "Discord",
        "Teams",
        "WhatsApp",
        "Telegram",
        "Signal",
        "Messenger",
    ]),
]

_FALLBACK_CONTEXT = "prose"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_active_window_title() -> str:
    """Return the raw title of the currently focused window.

    Returns an empty string if win32gui is unavailable or the call fails.
    """
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        return win32gui.GetWindowText(hwnd)
    except ImportError:
        logger.debug("win32gui not available — cannot read foreground window title")
    except Exception as exc:
        logger.debug("GetForegroundWindow failed: %s", exc)
    return ""


def get_active_app_context() -> str:
    """Return a context hint for the currently focused application window.

    Checks the window title against known keyword sets and returns one of:
    "code", "terminal", "chat", or "prose" (default fallback).

    Falls back to "prose" if win32gui is not installed or the call fails.
    """
    title = get_active_window_title()

    if not title:
        logger.debug("Empty window title — defaulting to context '%s'", _FALLBACK_CONTEXT)
        return _FALLBACK_CONTEXT

    title_lower = title.lower()

    for context, keywords in _CONTEXT_RULES:
        for keyword in keywords:
            if keyword.lower() in title_lower:
                logger.debug(
                    "Window '%s' matched keyword '%s' → context '%s'",
                    title,
                    keyword,
                    context,
                )
                return context

    logger.debug("Window '%s' matched no rules → context '%s'", title, _FALLBACK_CONTEXT)
    return _FALLBACK_CONTEXT
