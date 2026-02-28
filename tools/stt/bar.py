"""Floating dictation bar — pill-shaped tkinter overlay.

Three visual states:
  idle/listening  → small pill, blue dot, "stt" label
  recording       → expanded pill, red pulsing dot, 5-bar volume meter
  processing      → small pill, spinning arc, "Processing..." label

The bar never steals focus.  All drawing is on a Canvas with a
transparent-colour background for pixel-perfect rounded corners on Windows.
"""

import ctypes
import logging
import math
import threading
import tkinter as tk
from typing import Optional

import numpy as np

from tools.stt.config import load_config

logger = logging.getLogger(__name__)

# Transparent-colour trick: Windows treats this exact colour as "see-through"
# when set via -transparentcolor.  Must not appear anywhere in the pill itself.
_TRANSPARENT = "#000001"


def _set_dpi_awareness():
    """Enable per-monitor DPI awareness (Windows 8.1+)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class DictationBar:
    """Floating pill-shaped dictation status bar."""

    def __init__(self):
        _set_dpi_awareness()

        self.cfg = load_config()
        self._wcfg = self.cfg["window"]
        self._acfg = self.cfg["appearance"]

        # State
        self._state = "idle"  # idle | listening | recording | processing
        self._rms: float = 0.0  # 0.0–1.0, updated from engine thread
        self._rms_lock = threading.Lock()
        self._spinner_angle: float = 0.0
        self._pulse_phase: float = 0.0

        # Root (hidden master)
        self.root = tk.Tk()
        self.root.withdraw()

        # Pill window
        self._win = tk.Toplevel(self.root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.attributes("-transparentcolor", _TRANSPARENT)
        self._win.attributes("-alpha", self._wcfg.get("opacity", 0.92))
        self._win.configure(bg=_TRANSPARENT)

        # Canvas fills the window — everything is drawn here
        self._canvas = tk.Canvas(
            self._win,
            highlightthickness=0,
            bg=_TRANSPARENT,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # Initial geometry (idle size, bottom-center)
        self._current_w = self._wcfg["idle_width"]
        self._current_h = self._wcfg["idle_height"]
        self._position_window()

        # Start animation ticker
        self._tick()

    # ------------------------------------------------------------------
    # Public API (called from app.py / engine callback)
    # ------------------------------------------------------------------

    def set_state(self, state: str) -> None:
        """Thread-safe state update — schedules redraw on the main thread."""
        self.root.after(0, self._apply_state, state)

    def set_rms(self, rms: float) -> None:
        """Thread-safe RMS level update (0.0–1.0)."""
        with self._rms_lock:
            self._rms = max(0.0, min(1.0, rms))

    def run(self) -> None:
        """Enter the tkinter mainloop (blocks)."""
        self.root.mainloop()

    def quit(self) -> None:
        """Destroy the bar and exit mainloop."""
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------

    def _position_window(self):
        """Place the pill at bottom-center of the primary monitor."""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - self._current_w) // 2
        y = sh - self._current_h - self.cfg.get("offset_y", 80)
        self._win.geometry(f"{self._current_w}x{self._current_h}+{x}+{y}")

    def _resize_to(self, w: int, h: int):
        """Smoothly resize the pill (instant for MVP)."""
        if w == self._current_w and h == self._current_h:
            return
        self._current_w = w
        self._current_h = h
        self._position_window()

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _apply_state(self, state: str):
        """Apply a state transition on the main thread."""
        self._state = state
        if state == "recording":
            self._resize_to(self._wcfg["recording_width"], self._wcfg["recording_height"])
        else:
            self._resize_to(self._wcfg["idle_width"], self._wcfg["idle_height"])
        # Immediate redraw
        self._draw()

    # ------------------------------------------------------------------
    # Animation loop
    # ------------------------------------------------------------------

    def _tick(self):
        """~20 FPS animation tick."""
        self._pulse_phase += 0.15
        self._spinner_angle = (self._spinner_angle + 8) % 360
        self._draw()
        self.root.after(50, self._tick)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(self):
        c = self._canvas
        c.delete("all")

        w = self._current_w
        h = self._current_h
        r = h // 2  # corner radius = half height → full pill ends

        state = self._state

        bg = self._acfg["bg_recording"] if state == "recording" else self._acfg["bg_idle"]

        # Draw pill shape (two semicircles + rectangle)
        self._draw_pill(c, 0, 0, w, h, r, bg)

        if state == "recording":
            self._draw_recording(c, w, h)
        elif state == "processing":
            self._draw_processing(c, w, h)
        else:
            self._draw_idle(c, w, h)

    def _draw_pill(self, c: tk.Canvas, x: int, y: int, w: int, h: int, r: int, fill: str):
        """Draw a pill (stadium) shape on the canvas."""
        # Left semicircle
        c.create_oval(x, y, x + 2 * r, y + h, fill=fill, outline="")
        # Right semicircle
        c.create_oval(x + w - 2 * r, y, x + w, y + h, fill=fill, outline="")
        # Centre rectangle
        c.create_rectangle(x + r, y, x + w - r, y + h, fill=fill, outline="")

    # -- idle / listening --

    def _draw_idle(self, c: tk.Canvas, w: int, h: int):
        accent = self._acfg["accent"]
        text_color = self._acfg["text_color"]

        # Blue dot (left side)
        dot_r = 5
        cx = 24
        cy = h // 2
        c.create_oval(cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r, fill=accent, outline="")

        # "stt" label
        c.create_text(
            w // 2 + 6, h // 2,
            text="stt",
            fill=text_color,
            font=(self._acfg["font_family"], self._acfg["font_size"], "bold"),
            anchor="center",
        )

    # -- recording --

    def _draw_recording(self, c: tk.Canvas, w: int, h: int):
        accent_r = self._acfg["accent_recording"]
        text_color = self._acfg["text_color"]

        # Pulsing red dot (left)
        pulse = 0.6 + 0.4 * abs(math.sin(self._pulse_phase))
        dot_r = int(6 * pulse)
        cx = 28
        cy = h // 2
        c.create_oval(cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r, fill=accent_r, outline="")

        # "Recording" label
        c.create_text(
            90, h // 2,
            text="Recording",
            fill=text_color,
            font=(self._acfg["font_family"], self._acfg["font_size"] - 1),
            anchor="center",
        )

        # 5-bar volume meter (right side)
        with self._rms_lock:
            rms = self._rms

        bar_count = 5
        bar_w = 6
        bar_gap = 4
        meter_w = bar_count * bar_w + (bar_count - 1) * bar_gap
        meter_x = w - meter_w - 28
        max_bar_h = h - 18

        for i in range(bar_count):
            # Each bar has a slightly different threshold so they fill L→R
            threshold = (i + 0.5) / bar_count
            level = max(0.0, min(1.0, rms / max(threshold, 0.01)))
            bar_h = max(4, int(max_bar_h * level))
            bx = meter_x + i * (bar_w + bar_gap)
            by = cy - bar_h // 2
            c.create_rectangle(
                bx, by, bx + bar_w, by + bar_h,
                fill=accent_r,
                outline="",
            )

    # -- processing --

    def _draw_processing(self, c: tk.Canvas, w: int, h: int):
        accent = self._acfg["accent"]
        text_color = self._acfg["text_color"]

        # Spinning arc (left)
        cx = 24
        cy = h // 2
        arc_r = 7
        c.create_arc(
            cx - arc_r, cy - arc_r, cx + arc_r, cy + arc_r,
            start=self._spinner_angle,
            extent=270,
            style="arc",
            outline=accent,
            width=2,
        )

        # "Processing..." label
        c.create_text(
            w // 2 + 6, h // 2,
            text="Processing\u2026",
            fill=text_color,
            font=(self._acfg["font_family"], self._acfg["font_size"] - 1),
            anchor="center",
        )
