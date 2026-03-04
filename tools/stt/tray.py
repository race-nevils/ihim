"""System-tray icon for the dictation bar.

Pillow-drawn microphone icon, pystray menu with status / show-hide / exit.
Runs in a daemon thread; dispatches GUI actions to the tkinter main thread
via ``bar.root.after(0, ...)``.
"""

import threading
from typing import TYPE_CHECKING

import pystray
from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from tools.stt.bar import DictationBar


def _create_mic_icon() -> Image.Image:
    """Draw a simple mic icon (circle + line, 64×64)."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Mic body (rounded rect approximated by ellipse)
    draw.rounded_rectangle(
        [22, 10, 42, 36],
        radius=10,
        fill="#89b4fa",
    )
    # Stand line
    draw.line([(32, 36), (32, 50)], fill="#cdd6f4", width=2)
    # Arc (cup)
    draw.arc([18, 24, 46, 46], start=0, end=180, fill="#cdd6f4", width=2)
    # Base
    draw.line([(24, 50), (40, 50)], fill="#cdd6f4", width=2)

    return img


class TrayIcon:
    """pystray system-tray icon for the dictation bar."""

    def __init__(self, bar: "DictationBar"):
        self._bar = bar
        self._icon: pystray.Icon | None = None

    def _is_startup_checked(self, item) -> bool:
        """Check state for the 'Start on Login' menu item."""
        try:
            from tools.stt.startup_helper import is_startup_enabled
            return is_startup_enabled()
        except Exception:
            return False

    def _on_startup_toggle(self, icon=None, item=None):
        """Toggle startup on login."""
        try:
            from tools.stt.startup_helper import is_startup_enabled, enable_startup, disable_startup
            if is_startup_enabled():
                disable_startup()
            else:
                enable_startup()
        except Exception:
            pass

    def start(self) -> None:
        """Create and run the tray icon in a daemon thread."""
        menu = pystray.Menu(
            pystray.MenuItem("STT Dictation", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show / Hide", self._on_show_hide, default=True),
            pystray.MenuItem(
                "Start on Login",
                self._on_startup_toggle,
                checked=self._is_startup_checked,
            ),
            pystray.MenuItem("Exit", self._on_exit),
        )
        self._icon = pystray.Icon(
            "stt-dictation",
            _create_mic_icon(),
            "STT Dictation",
            menu,
        )
        t = threading.Thread(target=self._icon.run, daemon=True)
        t.start()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

    # -- menu callbacks (run on pystray thread → dispatch to main) --

    def _on_show_hide(self, icon=None, item=None):
        self._bar.root.after(0, self._toggle_visibility)

    def _toggle_visibility(self):
        if self._bar._win.winfo_viewable():
            self._bar._win.withdraw()
        else:
            self._bar._win.deiconify()

    def _on_exit(self, icon=None, item=None):
        self._bar.root.after(0, self._bar.quit)
