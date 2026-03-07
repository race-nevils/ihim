"""
Second Brain Capture Widget
===========================
System tray app with floating search bar for quick thought capture.

- Alt+Space opens floating input bar (configurable)
- Enter saves to inbox/, Esc cancels
- Runs in system tray

Usage:
    pythonw widget.pyw
    # or
    python widget.pyw
"""
import ctypes
import atexit
import json
import logging
import signal
import socket
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Third-party
import pystray
from PIL import Image, ImageDraw
from pynput import keyboard as pynput_keyboard
from pynput import mouse as pynput_mouse

# Internal TCP trigger port — iHIM API bridges external triggers here.
# NOT in the iHIM port range (7777-7780) to avoid conflicts with test servers.
TRIGGER_PORT = 47778


# Load config
CONFIG_PATH = Path(__file__).parent / "config.json"
DEFAULT_CONFIG = {
    "hotkey": "<alt>+<space>",  # pynput format
    "inbox_path": "C:/Users/<user>/workspace/IHIM/data/local/brain/inbox",
    "window": {
        "width": 600,
        "height": 50,
        "opacity": 0.95,
        "position": "center"
    },
    "appearance": {
        "bg_color": "#1e1e2e",
        "fg_color": "#cdd6f4",
        "placeholder": "Capture thought... (Enter to save, Esc to cancel)",
        "font_family": "Segoe UI",
        "font_size": 14
    }
}


def load_config() -> dict:
    """Load config from file or use defaults."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            user_config = json.load(f)
            # Merge with defaults
            config = {**DEFAULT_CONFIG, **user_config}
            # Merge nested dicts
            for key in ["window", "appearance"]:
                if key in user_config:
                    config[key] = {**DEFAULT_CONFIG[key], **user_config[key]}
            return config
    return DEFAULT_CONFIG


class CaptureWidget:
    """Floating capture widget with system tray integration."""

    def __init__(self):
        self.config = load_config()
        self.inbox_path = Path(self.config["inbox_path"])
        self.inbox_path.mkdir(parents=True, exist_ok=True)

        # Hotkey listener
        self.hotkey_listener = None
        self.current_keys = set()

        # Mouse listener for click-outside-to-close
        self.mouse_listener = None

        # Debounce state
        self._is_visible = False
        self._has_content_placeholder = True
        self._last_show_time = 0
        self._last_key_time = 0

        # Tkinter root (hidden)
        self.root = tk.Tk()
        self.root.withdraw()  # Hide main window

        # Create floating input window
        self.input_window = None
        self.entry = None
        self._create_input_window()

        # System tray
        self.tray_icon = None
        self._create_tray_icon()

        # Register cleanup handlers
        self._register_cleanup()

        # Register hotkey
        self._register_hotkey()

        # Start TCP trigger listener for AHK
        self._start_trigger_listener()

    def _start_trigger_listener(self):
        """Start TCP socket listener for external triggers (AHK hotkey)."""
        def listener_thread():
            try:
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("127.0.0.1", TRIGGER_PORT))
                server.listen(1)
                print(f"Trigger listener on port {TRIGGER_PORT}")
                while True:
                    try:
                        conn, addr = server.accept()
                        conn.close()  # Just need the connection signal
                        self.root.after(0, self.show)
                    except Exception as e:
                        logger.debug(f"Trigger listener accept error: {e}")
            except Exception as e:
                logger.error(f"Trigger listener failed to start: {e}")

        thread = threading.Thread(target=listener_thread, daemon=True)
        thread.start()

    def _register_cleanup(self):
        """Register cleanup handlers for graceful shutdown."""
        atexit.register(self._cleanup)

        # Handle Ctrl+C
        def signal_handler(signum, frame):
            print("\nShutting down...")
            self._cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def _stop_listener(self, listener_attr: str):
        """Stop a listener by attribute name and set to None."""
        listener = getattr(self, listener_attr, None)
        if listener is not None:
            try:
                listener.stop()
            except Exception as e:
                print(f"Error stopping {listener_attr}: {e}")
            setattr(self, listener_attr, None)

    def _cleanup(self):
        """Clean up all resources."""
        print("Cleaning up...")
        self._stop_listener("hotkey_listener")
        self._stop_listener("mouse_listener")
        # Stop tray icon if running
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None

    def _create_input_window(self):
        """Create the floating input window (initially hidden)."""
        cfg = self.config["window"]
        appearance = self.config["appearance"]

        # Create toplevel window
        self.input_window = tk.Toplevel(self.root)
        self.input_window.withdraw()  # Start hidden

        # Window properties
        self.input_window.overrideredirect(True)  # No title bar
        self.input_window.attributes("-topmost", True)  # Always on top
        self.input_window.attributes("-alpha", cfg.get("opacity", 0.95))

        # Background
        self.input_window.configure(bg=appearance["bg_color"])

        # Calculate position - taller window for two fields
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        win_width = cfg["width"]
        win_height = cfg["height"] + 100  # Extra height for title + multi-line content

        # Always center on screen
        x = (screen_width - win_width) // 2
        y = (screen_height - win_height) // 2

        self.input_window.geometry(f"{win_width}x{win_height}+{x}+{y}")

        # Create frame with padding
        frame = tk.Frame(
            self.input_window,
            bg=appearance["bg_color"],
            padx=10,
            pady=10
        )
        frame.pack(fill=tk.BOTH, expand=True)

        # Font for entries
        entry_font = tkfont.Font(
            family=appearance.get("font_family", "Segoe UI"),
            size=appearance.get("font_size", 14)
        )
        title_font = tkfont.Font(
            family=appearance.get("font_family", "Segoe UI"),
            size=appearance.get("font_size", 14) - 2
        )

        # Title entry (smaller, top)
        self.title_entry = tk.Entry(
            frame,
            font=title_font,
            bg=appearance["bg_color"],
            fg=appearance["fg_color"],
            insertbackground=appearance["fg_color"],
            relief=tk.FLAT,
            highlightthickness=0
        )
        self.title_entry.pack(fill=tk.X, pady=(0, 5))

        # Content text area (multi-line input)
        self.entry = tk.Text(
            frame,
            font=entry_font,
            bg=appearance["bg_color"],
            fg=appearance["fg_color"],
            insertbackground=appearance["fg_color"],  # Cursor color
            relief=tk.FLAT,
            highlightthickness=0,
            wrap=tk.WORD,
            height=4,
            undo=True,
        )
        self.entry.pack(fill=tk.BOTH, expand=True)

        # Placeholder text
        self.title_placeholder = "Title (optional)..."
        self.placeholder = appearance.get("placeholder", "Capture thought... (Shift+Enter for new line)")
        self._set_placeholder()

        # Bindings for title entry
        self.title_entry.bind("<Return>", self._on_title_enter)
        self.title_entry.bind("<Escape>", self._on_cancel)
        self.title_entry.bind("<FocusIn>", self._on_title_focus_in)
        self.title_entry.bind("<FocusOut>", self._on_title_focus_out)

        # Bindings for content text area
        self.entry.bind("<Return>", self._on_submit)
        self.entry.bind("<Shift-Return>", self._on_newline)
        self.entry.bind("<Escape>", self._on_cancel)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)

    def _set_placeholder(self):
        """Set placeholder text in both entries."""
        # Title placeholder
        self.title_entry.delete(0, tk.END)
        self.title_entry.insert(0, self.title_placeholder)
        self.title_entry.config(fg="#6c7086")  # Dimmed color for placeholder
        # Content placeholder
        self.entry.delete("1.0", tk.END)
        self.entry.insert("1.0", self.placeholder)
        self.entry.config(fg="#6c7086")  # Dimmed color for placeholder
        self._has_content_placeholder = True

    def _on_title_focus_in(self, event):
        """Clear title placeholder on focus."""
        if self.title_entry.get() == self.title_placeholder:
            self.title_entry.delete(0, tk.END)
            self.title_entry.config(fg=self.config["appearance"]["fg_color"])

    def _on_title_focus_out(self, event):
        """Restore title placeholder if empty."""
        if not self.title_entry.get():
            self.title_entry.delete(0, tk.END)
            self.title_entry.insert(0, self.title_placeholder)
            self.title_entry.config(fg="#6c7086")

    def _on_title_enter(self, event):
        """Handle Enter in title field - move to content."""
        self.entry.focus_set()
        # Clear content placeholder if present
        if self._has_content_placeholder:
            self.entry.delete("1.0", tk.END)
            self.entry.config(fg=self.config["appearance"]["fg_color"])
            self._has_content_placeholder = False
        return "break"

    def _on_focus_in(self, event):
        """Clear placeholder on focus."""
        if self._has_content_placeholder:
            self.entry.delete("1.0", tk.END)
            self.entry.config(fg=self.config["appearance"]["fg_color"])
            self._has_content_placeholder = False

    def _on_focus_out(self, event):
        """Restore placeholder if empty."""
        content = self.entry.get("1.0", "end-1c").strip()
        if not content:
            self.entry.delete("1.0", tk.END)
            self.entry.insert("1.0", self.placeholder)
            self.entry.config(fg="#6c7086")
            self._has_content_placeholder = True

    def _create_tray_icon(self):
        """Create system tray icon."""
        # Create a simple brain icon
        icon_size = 64
        image = Image.new("RGBA", (icon_size, icon_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Draw a simple brain shape (circle with squiggle)
        margin = 8
        draw.ellipse(
            [margin, margin, icon_size - margin, icon_size - margin],
            fill="#89b4fa",
            outline="#cdd6f4",
            width=2
        )
        # Add a simple line to suggest brain folds
        draw.arc(
            [margin + 10, margin + 5, icon_size - margin - 10, icon_size - margin - 5],
            start=0,
            end=180,
            fill="#1e1e2e",
            width=2
        )

        # Create menu
        menu = pystray.Menu(
            pystray.MenuItem("Capture (Alt+Space)", self._show_from_tray, default=True),
            pystray.MenuItem("---", None),
            pystray.MenuItem("Exit", self._exit_app)
        )

        self.tray_icon = pystray.Icon(
            "SecondBrain",
            image,
            "Second Brain Capture",
            menu
        )

    def _register_hotkey(self):
        """Register global hotkey using pynput."""

        def on_press(key):
            try:
                now = time.time()
                # Stale key guard: clear if no activity for 2s or set is suspiciously large.
                # Windows drops on_release events during alt-tab, screen lock, focus changes,
                # leaving phantom keys that cause false Alt+Space triggers over time.
                if (now - self._last_key_time > 2.0) or len(self.current_keys) > 4:
                    self.current_keys.clear()
                self._last_key_time = now

                self.current_keys.add(key)
                # Check for Alt + Space
                if (pynput_keyboard.Key.alt in self.current_keys or
                    pynput_keyboard.Key.alt_l in self.current_keys or
                    pynput_keyboard.Key.alt_r in self.current_keys):
                    if pynput_keyboard.Key.space in self.current_keys:
                        self.root.after(0, self.show)
                        self.current_keys.clear()
            except Exception as e:
                logger.debug(f"Hotkey on_press error: {e}")

        def on_release(key):
            try:
                self.current_keys.discard(key)
            except Exception as e:
                logger.debug(f"Hotkey on_release error: {e}")

        # Start listener (non-blocking)
        self.hotkey_listener = pynput_keyboard.Listener(
            on_press=on_press,
            on_release=on_release,
            suppress=False  # IMPORTANT: Don't suppress keys
        )
        self.hotkey_listener.start()
        print("Registered hotkey: Alt+Space")

    def _show_from_tray(self, icon=None, item=None):
        """Show from tray menu click."""
        self.root.after(0, self.show)

    def _force_foreground_win32(self) -> bool:
        """Force the input window to the foreground using Win32 API.

        Uses the ALT key trick (synthetic keybd_event) to reset Windows'
        ForegroundLockTimeout before calling SetForegroundWindow. This is
        the same technique AutoHotkey uses internally and works reliably
        on Windows 10/11 where AttachThreadInput alone often fails.
        """
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = int(self.input_window.winfo_id())
        foreground_hwnd = user32.GetForegroundWindow()

        if foreground_hwnd == hwnd:
            return True

        foreground_tid = user32.GetWindowThreadProcessId(foreground_hwnd, None)
        current_tid = kernel32.GetCurrentThreadId()

        # ALT key trick: resets ForegroundLockTimeout on Win10/11
        VK_MENU = 0x12
        KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

        attached = False
        if foreground_tid and foreground_tid != current_tid:
            user32.AttachThreadInput(foreground_tid, current_tid, True)
            attached = True

        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.SetFocus(hwnd)

        if attached:
            user32.AttachThreadInput(foreground_tid, current_tid, False)

        return user32.GetForegroundWindow() == hwnd

    def show(self):
        """Show the capture input window."""
        # Debounce: prevent rapid triggers (200ms cooldown)
        now = time.time()
        if self._is_visible or (now - self._last_show_time) < 0.2:
            return
        self._last_show_time = now
        self._is_visible = True

        self._set_placeholder()
        self.input_window.deiconify()
        self.input_window.lift()
        # Win32 focus deferred to _focus_entry (after window is painted)
        self.root.after(50, self._focus_entry)
        self._start_mouse_listener()

    def _focus_entry(self, attempt=0):
        """Set focus to title entry with Win32 foreground + retry loop.

        Called 50ms after show() to ensure the window is painted before
        attempting Win32 focus. Retries up to 3 times at 30ms intervals
        if foreground acquisition fails (~140ms worst case).
        """
        if not self._is_visible:
            return
        self.input_window.update_idletasks()  # flush paint
        success = self._force_foreground_win32()
        if not success and attempt < 3:
            self.root.after(30, lambda: self._focus_entry(attempt + 1))
            return
        self.title_entry.focus_force()
        if self.title_entry.get() == self.title_placeholder:
            self.title_entry.delete(0, tk.END)
            self.title_entry.config(fg=self.config["appearance"]["fg_color"])

    def hide(self):
        """Hide the capture input window."""
        if not self._is_visible:
            return  # Already hidden
        self._is_visible = False
        self._stop_mouse_listener()
        self.input_window.withdraw()
        # Clear both fields
        self.title_entry.delete(0, tk.END)
        self.entry.delete("1.0", tk.END)
        self._set_placeholder()

    def _start_mouse_listener(self):
        """Start listening for mouse clicks to detect click-outside."""
        # Check if listener exists and is still alive
        if self.mouse_listener is not None:
            if self.mouse_listener.is_alive():
                return  # Already running
            # Dead listener, clean it up
            self.mouse_listener = None

        def on_click(x, y, button, pressed):
            if not pressed:  # Only handle button press, not release
                return
            # Schedule check on main thread
            self.root.after(0, lambda: self._check_click_outside(x, y))

        self.mouse_listener = pynput_mouse.Listener(on_click=on_click)
        self.mouse_listener.start()

    def _stop_mouse_listener(self):
        """Stop the mouse click listener."""
        if self.mouse_listener is not None:
            self.mouse_listener.stop()
            self.mouse_listener = None

    def _check_click_outside(self, x, y):
        """Check if a click was outside the window and hide if so."""
        if not self.input_window.winfo_viewable():
            return

        # Get window bounds
        win_x = self.input_window.winfo_rootx()
        win_y = self.input_window.winfo_rooty()
        win_width = self.input_window.winfo_width()
        win_height = self.input_window.winfo_height()

        # Check if click is outside
        if not (win_x <= x <= win_x + win_width and
                win_y <= y <= win_y + win_height):
            self.hide()

    def _on_newline(self, event):
        """Handle Shift+Enter - insert newline in content."""
        self.entry.insert(tk.INSERT, "\n")
        return "break"

    def _on_submit(self, event):
        """Handle Enter key - save to inbox."""
        title = self.title_entry.get().strip()
        if title == self.title_placeholder:
            title = ""
        text = self.entry.get("1.0", "end-1c").strip()
        if text and text != self.placeholder:
            self._save_to_inbox(text, title)
        self.hide()
        return "break"

    def _on_cancel(self, event):
        """Handle Escape key - cancel."""
        self.hide()
        return "break"

    def _save_to_inbox(self, text: str, title: str = ""):
        """Save captured text to inbox as markdown file."""
        timestamp = datetime.now(timezone.utc)
        date_str = timestamp.strftime("%Y%m%d_%H%M%S")
        short_id = uuid.uuid4().hex[:8]

        # Use title for filename if provided, otherwise timestamp
        if title:
            # Sanitize title for filename (remove invalid chars)
            safe_title = "".join(c for c in title if c not in r'\/:*?"<>|')
            safe_title = safe_title.strip()[:50]  # Limit length
            filename = f"{safe_title}.md"
        else:
            filename = f"{date_str}_{short_id}.md"

        filepath = self.inbox_path / filename

        # Create markdown with frontmatter (title in frontmatter for extract_title)
        title_line = f'title: "{title}"\n' if title else ""
        content = f"""---
captured_at: "{timestamp.isoformat()}"
source: "capture_widget"
{title_line}---

{text}
"""
        filepath.write_text(content, encoding="utf-8")
        print(f"Saved: {filepath.name}")

    def _exit_app(self, icon=None, item=None):
        """Exit the application."""
        self._cleanup()
        self.root.quit()

    def run(self):
        """Run the widget."""
        print("=" * 50)
        print("Second Brain Capture Widget")
        print("=" * 50)
        print(f"Inbox: {self.inbox_path}")
        print(f"Hotkey: Alt+Space")
        print("Running in system tray. Right-click tray icon to exit.")
        print("=" * 50)

        try:
            # Run tray icon in separate thread
            tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            tray_thread.start()

            # Run tkinter mainloop
            self.root.mainloop()
        finally:
            self._cleanup()


def main():
    """Main entry point."""
    widget = CaptureWidget()
    widget.run()


if __name__ == "__main__":
    main()
