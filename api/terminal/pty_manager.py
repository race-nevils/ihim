"""
PTY Manager - Manages pseudo-terminal sessions for WebSocket connections.

On Windows, uses ConPTY via pywinpty when available, falls back to subprocess.
On Unix, uses standard pty module.
Supports multiple concurrent terminal sessions (tabs).
"""
import asyncio
import subprocess
import sys
import os
import uuid
from typing import Dict, Optional, Callable, Union, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque

# Try to import pywinpty for better Windows ConPTY support
PYWINPTY_AVAILABLE = False
try:
    if sys.platform == "win32":
        import winpty
        PYWINPTY_AVAILABLE = True
except ImportError:
    pass

# Scrollback buffer size (lines)
SCROLLBACK_SIZE = 1000


@dataclass
class TerminalSession:
    """Represents a single terminal session."""
    id: str
    process: Union[subprocess.Popen, Any]  # subprocess.Popen or winpty.PtyProcess
    created_at: str
    title: str = "Terminal"
    cwd: str = ""
    shell: str = ""
    use_winpty: bool = False

    # Scrollback buffer for reconnection support
    scrollback: deque = field(default_factory=lambda: deque(maxlen=SCROLLBACK_SIZE))

    # Async reader task
    reader_task: Optional[asyncio.Task] = field(default=None, repr=False)

    # Active WebSocket connections (for multi-viewer support)
    connections: int = 0


class PTYManager:
    """
    Manages multiple PTY sessions for the terminal panel.

    Each session runs a shell (PowerShell on Windows, bash on Unix)
    and streams stdin/stdout over WebSocket.

    Features:
    - Multi-session support (tabs)
    - Scrollback buffer for reconnection
    - Optional pywinpty for proper Windows ConPTY
    - Async I/O for non-blocking operation
    """

    def __init__(self):
        self.sessions: Dict[str, TerminalSession] = {}
        self._on_output: Dict[str, Callable[[str, bytes], None]] = {}
        self._on_exit: Dict[str, Callable[[str, int], None]] = {}
        self._use_winpty = PYWINPTY_AVAILABLE

    @property
    def backend_info(self) -> dict:
        """Get info about the PTY backend being used."""
        return {
            "platform": sys.platform,
            "pywinpty_available": PYWINPTY_AVAILABLE,
            "using_winpty": self._use_winpty,
            "scrollback_size": SCROLLBACK_SIZE
        }

    def get_default_shell(self) -> tuple[str, list[str]]:
        """Get the default shell for this platform."""
        if sys.platform == "win32":
            # Use PowerShell for better Windows experience
            return "powershell.exe", [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NoExit"
            ]
        else:
            # Unix-like systems
            shell = os.environ.get("SHELL", "/bin/bash")
            return shell, [shell, "-i"]

    def create_session(
        self,
        session_id: Optional[str] = None,
        title: str = "Terminal",
        cwd: Optional[str] = None,
        cols: int = 80,
        rows: int = 24
    ) -> TerminalSession:
        """
        Create a new terminal session.

        Args:
            session_id: Optional custom ID. Generated if not provided.
            title: Display title for the terminal tab.
            cwd: Working directory. Defaults to workspace root.
            cols: Terminal width in columns.
            rows: Terminal height in rows.

        Returns:
            The created TerminalSession.
        """
        if session_id is None:
            session_id = str(uuid.uuid4())[:8]

        # Default to workspace root directory
        if cwd is None:
            cwd = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

        shell_name, shell_cmd = self.get_default_shell()
        use_winpty = False

        # Create the process
        try:
            if sys.platform == "win32" and self._use_winpty:
                # Use pywinpty for proper ConPTY support (better for xterm.js)
                try:
                    pty_process = winpty.PtyProcess.spawn(
                        shell_cmd,
                        cwd=cwd,
                        env={**os.environ, "TERM": "xterm-256color"},
                        dimensions=(rows, cols)
                    )
                    use_winpty = True
                    process = pty_process
                except Exception as e:
                    # Fallback to subprocess if winpty fails
                    print(f"pywinpty failed, falling back to subprocess: {e}")
                    process = self._create_subprocess(shell_cmd, cwd)
            elif sys.platform == "win32":
                # Windows: Use subprocess with pipes
                process = self._create_subprocess(shell_cmd, cwd)
            else:
                # Unix: Standard subprocess (could use pty module for better support)
                process = self._create_subprocess(shell_cmd, cwd)
        except Exception as e:
            raise RuntimeError(f"Failed to spawn shell: {e}")

        session = TerminalSession(
            id=session_id,
            process=process,
            created_at=datetime.utcnow().isoformat() + "Z",
            title=title,
            cwd=cwd,
            shell=shell_name,
            use_winpty=use_winpty
        )

        self.sessions[session_id] = session
        return session

    def _create_subprocess(self, shell_cmd: list, cwd: str) -> subprocess.Popen:
        """Create a subprocess with proper settings."""
        if sys.platform == "win32":
            return subprocess.Popen(
                shell_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env={**os.environ, "TERM": "xterm-256color"}
            )
        else:
            return subprocess.Popen(
                shell_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                bufsize=0,
                env={**os.environ, "TERM": "xterm-256color"}
            )

    def get_session(self, session_id: str) -> Optional[TerminalSession]:
        """Get a session by ID."""
        return self.sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        """List all active sessions."""
        return [
            {
                "id": s.id,
                "title": s.title,
                "created_at": s.created_at,
                "cwd": s.cwd,
                "shell": s.shell,
                "alive": self._is_alive(s),
                "backend": "winpty" if s.use_winpty else "subprocess",
                "connections": s.connections,
                "scrollback_lines": len(s.scrollback)
            }
            for s in self.sessions.values()
        ]

    def _is_alive(self, session: TerminalSession) -> bool:
        """Check if a session's process is still running."""
        if session.use_winpty:
            return session.process.isalive()
        else:
            return session.process.poll() is None

    async def write(self, session_id: str, data: bytes) -> bool:
        """
        Write data to a terminal session's stdin.

        Args:
            session_id: The session to write to.
            data: Raw bytes to write (could be user keystrokes).

        Returns:
            True if successful, False if session not found or dead.
        """
        session = self.sessions.get(session_id)
        if not session or not self._is_alive(session):
            return False

        try:
            if session.use_winpty:
                # winpty expects string, not bytes
                session.process.write(data.decode('utf-8', errors='replace'))
            else:
                session.process.stdin.write(data)
                session.process.stdin.flush()
            return True
        except (BrokenPipeError, OSError, Exception):
            return False

    async def read_output(
        self,
        session_id: str,
        callback: Callable[[bytes], None]
    ) -> None:
        """
        Start reading output from a terminal session.

        This runs continuously until the session ends.
        Output is passed to the callback function and stored in scrollback.

        Args:
            session_id: The session to read from.
            callback: Function called with each chunk of output.
        """
        session = self.sessions.get(session_id)
        if not session:
            return

        loop = asyncio.get_event_loop()

        def read_sync_subprocess():
            """Synchronous read from subprocess stdout."""
            try:
                chunk = session.process.stdout.read(4096)
                return chunk if chunk else None
            except (BrokenPipeError, OSError):
                return None

        def read_sync_winpty():
            """Synchronous read from winpty."""
            try:
                data = session.process.read(4096)
                return data.encode('utf-8') if data else None
            except Exception:
                return None

        read_sync = read_sync_winpty if session.use_winpty else read_sync_subprocess

        while self._is_alive(session):
            try:
                # Run blocking read in executor to not block the event loop
                chunk = await loop.run_in_executor(None, read_sync)
                if chunk:
                    # Store in scrollback buffer (split by lines)
                    self._add_to_scrollback(session, chunk)
                    callback(chunk)
                else:
                    await asyncio.sleep(0.01)  # Prevent tight loop on empty read
            except Exception:
                break

        # Process exited - notify
        exit_code = self._get_exit_code(session)
        if session_id in self._on_exit:
            self._on_exit[session_id](session_id, exit_code)

    def _add_to_scrollback(self, session: TerminalSession, data: bytes) -> None:
        """Add data to session scrollback buffer."""
        try:
            text = data.decode('utf-8', errors='replace')
            # Split into lines and add each
            for line in text.split('\n'):
                if line:  # Don't add empty lines
                    session.scrollback.append(line)
        except Exception:
            pass

    def get_scrollback(self, session_id: str) -> list[str]:
        """Get the scrollback buffer for a session."""
        session = self.sessions.get(session_id)
        if not session:
            return []
        return list(session.scrollback)

    def _get_exit_code(self, session: TerminalSession) -> int:
        """Get the exit code from a session's process."""
        if session.use_winpty:
            return session.process.exitstatus or 0
        else:
            return session.process.poll() or 0

    def resize(self, session_id: str, cols: int, rows: int) -> bool:
        """
        Resize a terminal session.

        With pywinpty, this properly resizes the ConPTY.
        With subprocess, this is a no-op (limited Windows support).
        """
        session = self.sessions.get(session_id)
        if not session:
            return False

        # Validate dimensions
        if cols < 1 or rows < 1:
            return False

        if session.use_winpty:
            try:
                session.process.setwinsize(rows, cols)
                return True
            except Exception:
                return False
        else:
            # Subprocess doesn't support resize on Windows
            # Return True for API compatibility
            return True

    def kill_session(self, session_id: str) -> bool:
        """
        Kill a terminal session.

        Args:
            session_id: The session to kill.

        Returns:
            True if killed, False if not found.
        """
        session = self.sessions.get(session_id)
        if not session:
            return False

        try:
            if session.use_winpty:
                # winpty has its own terminate method
                if session.process.isalive():
                    session.process.terminate()
            else:
                session.process.terminate()
                session.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            session.process.kill()
        except Exception:
            pass

        # Clean up reader task if exists
        if session.reader_task and not session.reader_task.done():
            session.reader_task.cancel()

        # Clean up callbacks
        self._on_output.pop(session_id, None)
        self._on_exit.pop(session_id, None)

        del self.sessions[session_id]
        return True

    def kill_all(self) -> int:
        """Kill all terminal sessions. Returns count killed."""
        session_ids = list(self.sessions.keys())
        count = 0
        for sid in session_ids:
            if self.kill_session(sid):
                count += 1
        return count

    def set_exit_callback(
        self,
        session_id: str,
        callback: Callable[[str, int], None]
    ) -> None:
        """Set a callback for when a session exits."""
        self._on_exit[session_id] = callback


# Global instance
pty_manager = PTYManager()
