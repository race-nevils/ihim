"""
Terminal WebSocket Routes for iHIM Mission Control.

Provides WebSocket endpoints for real-time terminal I/O
and REST endpoints for session management.
"""
import asyncio
import json
import shlex
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel

from .pty_manager import pty_manager, TerminalSession

router = APIRouter(prefix="/api/terminal", tags=["terminal"])


# =============================================================================
# BACKEND INFO ENDPOINT
# =============================================================================

@router.get("/info")
async def get_terminal_info():
    """
    Get information about the terminal backend.

    Returns platform, available features, and configuration.
    Useful for frontend to know what capabilities are available.
    """
    return {
        "success": True,
        **pty_manager.backend_info
    }


# =============================================================================
# REST ENDPOINTS (Session Management)
# =============================================================================

class CreateSessionRequest(BaseModel):
    """Request to create a new terminal session."""
    title: str = "Terminal"
    cwd: Optional[str] = None


class CreateSessionResponse(BaseModel):
    """Response after creating a terminal session."""
    success: bool
    session_id: str
    title: str
    created_at: str
    cwd: str
    shell: str
    websocket_url: str


@router.get("/sessions")
async def list_sessions():
    """
    List all active terminal sessions.

    Returns session metadata for each active terminal tab.
    """
    sessions = pty_manager.list_sessions()
    return {
        "count": len(sessions),
        "sessions": sessions
    }


@router.post("/sessions")
async def create_session(request: CreateSessionRequest) -> CreateSessionResponse:
    """
    Create a new terminal session.

    The session is created but not connected yet.
    Connect via WebSocket at /api/terminal/ws/{session_id}.

    Args:
        title: Display name for the terminal tab.
        cwd: Working directory (defaults to workspace root).

    Returns:
        Session info including the WebSocket URL.
    """
    try:
        session = pty_manager.create_session(
            title=request.title,
            cwd=request.cwd
        )

        return CreateSessionResponse(
            success=True,
            session_id=session.id,
            title=session.title,
            created_at=session.created_at,
            cwd=session.cwd,
            shell=session.shell,
            websocket_url=f"/api/terminal/ws/{session.id}"
        )
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get details of a specific session."""
    session = pty_manager.get_session(session_id)
    if not session:
        return {"success": False, "error": "Session not found"}

    return {
        "success": True,
        "session": {
            "id": session.id,
            "title": session.title,
            "created_at": session.created_at,
            "cwd": session.cwd,
            "shell": session.shell,
            "alive": pty_manager._is_alive(session),
            "backend": "winpty" if session.use_winpty else "subprocess",
            "scrollback_lines": len(session.scrollback)
        }
    }


@router.get("/sessions/{session_id}/scrollback")
async def get_session_scrollback(session_id: str):
    """
    Get the scrollback buffer for a session.

    Returns the last N lines of terminal output.
    Useful for reconnecting to an existing session.
    """
    scrollback = pty_manager.get_scrollback(session_id)
    if scrollback is None:
        return {"success": False, "error": "Session not found"}

    return {
        "success": True,
        "session_id": session_id,
        "lines": scrollback,
        "count": len(scrollback)
    }


@router.delete("/sessions/{session_id}")
async def kill_session(session_id: str):
    """
    Kill a terminal session.

    Terminates the shell process and cleans up resources.
    """
    if pty_manager.kill_session(session_id):
        return {"success": True, "message": f"Session {session_id} killed"}
    return {"success": False, "error": "Session not found"}


@router.delete("/sessions")
async def kill_all_sessions():
    """Kill all terminal sessions."""
    count = pty_manager.kill_all()
    return {"success": True, "killed": count}


@router.post("/sessions/{session_id}/resize")
async def resize_session(session_id: str, cols: int = 80, rows: int = 24):
    """
    Resize a terminal session.

    Args:
        cols: Number of columns (width in characters).
        rows: Number of rows (height in characters).
    """
    if pty_manager.resize(session_id, cols, rows):
        return {"success": True}
    return {"success": False, "error": "Session not found"}


# =============================================================================
# WEBSOCKET ENDPOINT (Real-time Terminal I/O)
# =============================================================================

@router.websocket("/ws/{session_id}")
async def terminal_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for terminal I/O.

    Protocol:
    - Client sends: JSON with {type: "input", data: "..."} or {type: "resize", cols, rows}
    - Server sends: JSON with {type: "output", data: "..."} or binary data
    - Auto-creates session if it doesn't exist

    The connection stays open until the terminal exits or client disconnects.
    """
    await websocket.accept()

    # Auto-create session if it doesn't exist
    session = pty_manager.get_session(session_id)
    if not session:
        try:
            session = pty_manager.create_session(session_id=session_id)
        except Exception as e:
            await websocket.send_json({"type": "error", "message": f"Failed to create session: {e}"})
            await websocket.close()
            return

    # Track connection
    session.connections += 1

    # Check if session is alive
    if not pty_manager._is_alive(session):
        await websocket.send_json({"type": "error", "message": "Session already exited"})
        await websocket.close()
        session.connections -= 1
        return

    # Send initial session info with backend capabilities
    await websocket.send_json({
        "type": "connected",
        "session_id": session_id,
        "title": session.title,
        "shell": session.shell,
        "cwd": session.cwd,
        "backend": "winpty" if session.use_winpty else "subprocess",
        "scrollback_available": len(session.scrollback)
    })

    # Output callback - sends data to WebSocket
    async def send_output(data: bytes):
        try:
            await websocket.send_bytes(data)
        except Exception:
            pass

    # Exit callback
    exit_event = asyncio.Event()
    exit_code = [0]

    def on_exit(sid: str, code: int):
        exit_code[0] = code
        exit_event.set()

    pty_manager.set_exit_callback(session_id, on_exit)

    # Start output reader task (handles both winpty and subprocess)
    async def output_reader():
        loop = asyncio.get_event_loop()

        def read_chunk_subprocess():
            try:
                return session.process.stdout.read1(4096)
            except Exception as e:
                print(f"Terminal read error (subprocess): {e}")
                return None

        def read_chunk_winpty():
            try:
                data = session.process.read(4096)
                return data.encode('utf-8') if data else None
            except Exception as e:
                print(f"Terminal read error (winpty): {e}")
                return None

        read_chunk = read_chunk_winpty if session.use_winpty else read_chunk_subprocess

        while pty_manager._is_alive(session) and not exit_event.is_set():
            try:
                # Use short timeout for responsiveness
                chunk = await asyncio.wait_for(
                    loop.run_in_executor(None, read_chunk),
                    timeout=0.1
                )
                if chunk:
                    # Store in scrollback
                    pty_manager._add_to_scrollback(session, chunk)
                    await send_output(chunk)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

    # Start reader in background
    reader_task = asyncio.create_task(output_reader())

    try:
        while True:
            try:
                # Wait for client messages
                message = await websocket.receive()

                if message["type"] == "websocket.disconnect":
                    break

                # Handle text messages (could be special commands)
                if "text" in message:
                    text = message["text"]
                    try:
                        # Try to parse as JSON for special commands
                        data = json.loads(text)
                        msg_type = data.get("type")

                        if msg_type == "resize":
                            pty_manager.resize(
                                session_id,
                                data.get("cols", 80),
                                data.get("rows", 24)
                            )
                            continue
                        elif msg_type == "ping":
                            await websocket.send_json({"type": "pong"})
                            continue
                        elif msg_type == "input":
                            # Input from frontend: {type: "input", data: "keystrokes"}
                            input_data = data.get("data", "")
                            if input_data:
                                await pty_manager.write(session_id, input_data.encode())
                            continue
                    except json.JSONDecodeError:
                        # Not JSON - treat as raw input
                        pass

                    # Write raw text to terminal (fallback for non-JSON input)
                    await pty_manager.write(session_id, text.encode())

                # Handle binary messages (raw input)
                elif "bytes" in message:
                    await pty_manager.write(session_id, message["bytes"])

            except WebSocketDisconnect:
                break

    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})

    finally:
        # Cleanup
        session.connections -= 1
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass

        # Send exit message if process died
        if exit_event.is_set() or not pty_manager._is_alive(session):
            try:
                await websocket.send_json({
                    "type": "exit",
                    "code": pty_manager._get_exit_code(session)
                })
            except Exception as e:
                print(f"Terminal WebSocket exit message error: {e}")
                pass


# =============================================================================
# QUICK SPAWN ENDPOINT (Create + Return WebSocket URL)
# =============================================================================

@router.post("/spawn")
async def spawn_terminal(
    title: str = Query("Terminal"),
    cwd: Optional[str] = None
):
    """
    Quick spawn a terminal and return connection info.

    Convenience endpoint that creates a session and returns
    everything needed to connect.
    """
    try:
        session = pty_manager.create_session(title=title, cwd=cwd)
        return {
            "success": True,
            "session_id": session.id,
            "websocket_url": f"ws://localhost:7777/api/terminal/ws/{session.id}",
            "title": session.title,
            "shell": session.shell
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# AGENT DISPATCH ENDPOINTS (For Mission Control)
# =============================================================================

@router.post("/dispatch")
async def dispatch_agent(prompt: str, title: str = "the agent Agent"):
    """
    Dispatch an agent in a new terminal.

    Creates a terminal, runs `claude` with the given prompt,
    and returns the session info for monitoring.

    Args:
        prompt: The task for the agent.
        title: Display title for the terminal tab.

    Returns:
        Session info with WebSocket URL.
    """
    try:
        # Create session with the agent harness command
        session = pty_manager.create_session(title=title)

        # Send the claude command
        # Use shlex.quote() for proper shell escaping (SEC-001 fix)
        escaped_prompt = shlex.quote(prompt.replace('\n', ' '))
        command = f'claude {escaped_prompt}\n'

        await pty_manager.write(session.id, command.encode())

        return {
            "success": True,
            "session_id": session.id,
            "websocket_url": f"ws://localhost:7777/api/terminal/ws/{session.id}",
            "title": title,
            "prompt": prompt
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
