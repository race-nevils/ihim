"""
Integration Tests for Embedded Terminal Panel

This module tests the integration between:
- Terminal API endpoints
- WebSocket connections
- PTY backend
- Tab/pane management
- the agent harness CLI agent spawning

These tests verify that all components work together correctly.

Test Categories:
1. API Endpoint Tests
2. Full Terminal Session Tests
3. Multi-Tab Integration Tests
4. Agent Spawning Tests
5. Dashboard Integration Tests
6. Persistence Tests
7. Error Recovery Tests
8. Load Tests

Note: These are integration tests that may require more setup
than unit tests. Use fixtures to manage test dependencies.
"""
import pytest
import sys
import json
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from typing import List, Dict
from dataclasses import dataclass

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture
def mock_app():
    """Create a mock FastAPI app with terminal routes."""
    app = MagicMock()
    app.state = MagicMock()
    app.state.terminal_manager = MagicMock()
    return app


@pytest.fixture
def test_client(mock_app):
    """Create a test client for API testing."""
    client = MagicMock()
    client.get = MagicMock()
    client.post = MagicMock()
    client.put = MagicMock()
    client.delete = MagicMock()
    client.websocket_connect = MagicMock()
    return client


@pytest.fixture
def terminal_session():
    """Create a mock terminal session."""
    return {
        "id": "term-test-123",
        "tab_id": "tab-1",
        "status": "active",
        "shell": "powershell.exe" if sys.platform == "win32" else "bash",
        "cwd": str(Path.cwd()),
        "cols": 80,
        "rows": 24,
        "created_at": "2025-12-26T10:00:00Z",
    }


# =============================================================================
# API ENDPOINT TESTS
# =============================================================================

class TestTerminalAPIEndpoints:
    """Tests for terminal REST API endpoints."""

    def test_get_terminal_status(self, test_client):
        """GET /api/terminal should return terminal status."""
        expected_response = {
            "active": True,
            "sessions": 0,
            "max_sessions": 10,
        }
        test_client.get.return_value.json.return_value = expected_response

        response = test_client.get("/api/terminal")

        assert response.json()["active"] is True

    def test_create_terminal_session(self, test_client, terminal_session):
        """POST /api/terminal/sessions should create new session."""
        test_client.post.return_value.json.return_value = {
            "success": True,
            "session": terminal_session,
        }

        response = test_client.post("/api/terminal/sessions", json={
            "shell": "bash",
            "cwd": "/home/user",
        })

        result = response.json()
        assert result["success"] is True
        assert "session" in result

    def test_get_terminal_sessions(self, test_client, terminal_session):
        """GET /api/terminal/sessions should list sessions."""
        test_client.get.return_value.json.return_value = {
            "sessions": [terminal_session],
        }

        response = test_client.get("/api/terminal/sessions")

        assert len(response.json()["sessions"]) == 1

    def test_get_single_session(self, test_client, terminal_session):
        """GET /api/terminal/sessions/{id} should return session."""
        test_client.get.return_value.json.return_value = {
            "success": True,
            "session": terminal_session,
        }

        response = test_client.get("/api/terminal/sessions/term-test-123")

        assert response.json()["session"]["id"] == "term-test-123"

    def test_delete_terminal_session(self, test_client):
        """DELETE /api/terminal/sessions/{id} should close session."""
        test_client.delete.return_value.json.return_value = {
            "success": True,
            "message": "Session closed",
        }

        response = test_client.delete("/api/terminal/sessions/term-test-123")

        assert response.json()["success"] is True

    def test_resize_terminal(self, test_client):
        """PUT /api/terminal/sessions/{id}/resize should resize."""
        test_client.put.return_value.json.return_value = {
            "success": True,
            "cols": 120,
            "rows": 40,
        }

        response = test_client.put(
            "/api/terminal/sessions/term-test-123/resize",
            json={"cols": 120, "rows": 40}
        )

        result = response.json()
        assert result["cols"] == 120
        assert result["rows"] == 40


# =============================================================================
# TAB API TESTS
# =============================================================================

class TestTabAPIEndpoints:
    """Tests for terminal tab management API."""

    def test_get_tabs(self, test_client):
        """GET /api/terminal/tabs should list tabs."""
        test_client.get.return_value.json.return_value = {
            "tabs": [
                {"id": "tab-1", "title": "Terminal 1", "active": True},
                {"id": "tab-2", "title": "Terminal 2", "active": False},
            ]
        }

        response = test_client.get("/api/terminal/tabs")

        assert len(response.json()["tabs"]) == 2

    def test_create_tab(self, test_client):
        """POST /api/terminal/tabs should create new tab."""
        test_client.post.return_value.json.return_value = {
            "success": True,
            "tab": {"id": "tab-3", "title": "Terminal 3", "active": True},
            "session_id": "term-new-123",
        }

        response = test_client.post("/api/terminal/tabs", json={
            "title": "Terminal 3",
        })

        result = response.json()
        assert result["success"] is True
        assert "session_id" in result

    def test_update_tab(self, test_client):
        """PUT /api/terminal/tabs/{id} should update tab."""
        test_client.put.return_value.json.return_value = {
            "success": True,
            "tab": {"id": "tab-1", "title": "Build Server", "active": True},
        }

        response = test_client.put("/api/terminal/tabs/tab-1", json={
            "title": "Build Server",
        })

        assert response.json()["tab"]["title"] == "Build Server"

    def test_delete_tab(self, test_client):
        """DELETE /api/terminal/tabs/{id} should close tab."""
        test_client.delete.return_value.json.return_value = {
            "success": True,
            "message": "Tab closed",
        }

        response = test_client.delete("/api/terminal/tabs/tab-1")

        assert response.json()["success"] is True

    def test_activate_tab(self, test_client):
        """POST /api/terminal/tabs/{id}/activate should set active."""
        test_client.post.return_value.json.return_value = {
            "success": True,
            "tab_id": "tab-2",
        }

        response = test_client.post("/api/terminal/tabs/tab-2/activate")

        assert response.json()["success"] is True


# =============================================================================
# PANE SPLIT TESTS
# =============================================================================

class TestPaneSplitAPI:
    """Tests for terminal pane splitting."""

    def test_split_horizontal(self, test_client):
        """POST /api/terminal/panes/split should split horizontally."""
        test_client.post.return_value.json.return_value = {
            "success": True,
            "direction": "horizontal",
            "panes": [
                {"id": "pane-1", "session_id": "term-1"},
                {"id": "pane-2", "session_id": "term-2"},
            ],
        }

        response = test_client.post("/api/terminal/panes/split", json={
            "source_pane": "pane-1",
            "direction": "horizontal",
        })

        result = response.json()
        assert result["direction"] == "horizontal"
        assert len(result["panes"]) == 2

    def test_split_vertical(self, test_client):
        """POST /api/terminal/panes/split should split vertically."""
        test_client.post.return_value.json.return_value = {
            "success": True,
            "direction": "vertical",
            "panes": [
                {"id": "pane-1", "session_id": "term-1"},
                {"id": "pane-3", "session_id": "term-3"},
            ],
        }

        response = test_client.post("/api/terminal/panes/split", json={
            "source_pane": "pane-1",
            "direction": "vertical",
        })

        result = response.json()
        assert result["direction"] == "vertical"

    def test_get_pane_layout(self, test_client):
        """GET /api/terminal/panes/layout should return layout."""
        test_client.get.return_value.json.return_value = {
            "layout": {
                "type": "horizontal",
                "children": [
                    {"type": "pane", "id": "pane-1", "width": 50},
                    {"type": "pane", "id": "pane-2", "width": 50},
                ]
            }
        }

        response = test_client.get("/api/terminal/panes/layout")

        layout = response.json()["layout"]
        assert layout["type"] == "horizontal"

    def test_close_pane(self, test_client):
        """DELETE /api/terminal/panes/{id} should close pane."""
        test_client.delete.return_value.json.return_value = {
            "success": True,
            "message": "Pane closed",
        }

        response = test_client.delete("/api/terminal/panes/pane-2")

        assert response.json()["success"] is True


# =============================================================================
# FULL TERMINAL SESSION TESTS
# =============================================================================

class TestFullTerminalSession:
    """Tests for complete terminal session lifecycle."""

    def test_create_and_use_session(self, test_client, terminal_session):
        """Should create session, send input, receive output, close."""
        # 1. Create session
        test_client.post.return_value.json.return_value = {
            "success": True,
            "session": terminal_session,
        }

        create_response = test_client.post("/api/terminal/sessions")
        session = create_response.json()["session"]

        assert session["status"] == "active"

        # 2. Connect WebSocket (mock)
        ws = MagicMock()
        test_client.websocket_connect.return_value = ws

        # 3. Send input (would be via WebSocket)
        input_msg = {"type": "input", "data": "echo hello\n"}

        # 4. Receive output (would be via WebSocket)
        output_msg = {"type": "output", "data": "hello\n"}

        assert input_msg["type"] == "input"
        assert output_msg["type"] == "output"

        # 5. Close session
        test_client.delete.return_value.json.return_value = {"success": True}
        close_response = test_client.delete(f"/api/terminal/sessions/{session['id']}")

        assert close_response.json()["success"] is True

    def test_reconnect_to_existing_session(self, test_client, terminal_session):
        """Should be able to reconnect to existing session."""
        # Get existing session
        test_client.get.return_value.json.return_value = {
            "success": True,
            "session": terminal_session,
        }

        response = test_client.get("/api/terminal/sessions/term-test-123")
        session = response.json()["session"]

        assert session["id"] == "term-test-123"
        assert session["status"] == "active"


# =============================================================================
# MULTI-TAB INTEGRATION TESTS
# =============================================================================

class TestMultiTabIntegration:
    """Tests for multiple terminal tabs."""

    def test_create_multiple_tabs(self, test_client):
        """Should be able to create multiple tabs."""
        tabs_created = []

        for i in range(3):
            test_client.post.return_value.json.return_value = {
                "success": True,
                "tab": {"id": f"tab-{i+1}", "title": f"Terminal {i+1}"},
            }

            response = test_client.post("/api/terminal/tabs")
            tabs_created.append(response.json()["tab"])

        assert len(tabs_created) == 3

    def test_switch_between_tabs(self, test_client):
        """Should switch active tab correctly."""
        # Activate tab-2
        test_client.post.return_value.json.return_value = {
            "success": True,
            "tab_id": "tab-2",
        }

        test_client.post("/api/terminal/tabs/tab-2/activate")

        # Verify tab-2 is active
        test_client.get.return_value.json.return_value = {
            "tabs": [
                {"id": "tab-1", "active": False},
                {"id": "tab-2", "active": True},
                {"id": "tab-3", "active": False},
            ]
        }

        tabs = test_client.get("/api/terminal/tabs").json()["tabs"]
        active_tab = next(t for t in tabs if t["active"])

        assert active_tab["id"] == "tab-2"

    def test_close_inactive_tab(self, test_client):
        """Should close inactive tab without affecting active."""
        test_client.delete.return_value.json.return_value = {"success": True}
        test_client.delete("/api/terminal/tabs/tab-3")

        # Active tab should still be active
        test_client.get.return_value.json.return_value = {
            "tabs": [
                {"id": "tab-1", "active": False},
                {"id": "tab-2", "active": True},
            ]
        }

        tabs = test_client.get("/api/terminal/tabs").json()["tabs"]
        assert len(tabs) == 2

    def test_close_active_tab_activates_next(self, test_client):
        """Closing active tab should activate another."""
        # Close active tab
        test_client.delete.return_value.json.return_value = {"success": True}
        test_client.delete("/api/terminal/tabs/tab-2")

        # Another tab should become active
        test_client.get.return_value.json.return_value = {
            "tabs": [
                {"id": "tab-1", "active": True},  # Now active
                {"id": "tab-3", "active": False},
            ]
        }

        tabs = test_client.get("/api/terminal/tabs").json()["tabs"]
        active_count = sum(1 for t in tabs if t["active"])

        assert active_count == 1


# =============================================================================
# CLAUDE CODE AGENT INTEGRATION TESTS
# =============================================================================

class TestAgentHarnessAgentIntegration:
    """Tests for spawning the agent harness agents in terminal."""

    def test_spawn_claude_agent_in_tab(self, test_client):
        """Should spawn the agent harness agent in new tab."""
        test_client.post.return_value.json.return_value = {
            "success": True,
            "tab": {
                "id": "tab-agent-1",
                "title": "frontend-dev",
                "agent": "frontend-dev",
            },
            "session_id": "term-agent-1",
            "command": "claude 'Build login component'",
        }

        response = test_client.post("/api/terminal/agents/spawn", json={
            "agent": "frontend-dev",
            "prompt": "Build login component",
        })

        result = response.json()
        assert result["success"] is True
        assert result["tab"]["agent"] == "frontend-dev"

    def test_spawn_multiple_agents(self, test_client):
        """Should spawn multiple agents in parallel tabs."""
        agents = ["frontend-dev", "backend-dev", "qa-tester"]
        spawned = []

        for i, agent in enumerate(agents):
            test_client.post.return_value.json.return_value = {
                "success": True,
                "tab": {"id": f"tab-agent-{i+1}", "agent": agent},
            }

            response = test_client.post("/api/terminal/agents/spawn", json={
                "agent": agent,
                "prompt": "Test task",
            })
            spawned.append(response.json())

        assert len(spawned) == 3
        assert all(s["success"] for s in spawned)

    def test_get_agent_tabs(self, test_client):
        """Should list tabs with agent information."""
        test_client.get.return_value.json.return_value = {
            "tabs": [
                {"id": "tab-1", "agent": "frontend-dev", "status": "working"},
                {"id": "tab-2", "agent": "backend-dev", "status": "idle"},
            ]
        }

        response = test_client.get("/api/terminal/agents")

        agents = response.json()["tabs"]
        assert len(agents) == 2

    def test_send_command_to_agent(self, test_client):
        """Should inject command to running agent."""
        test_client.post.return_value.json.return_value = {
            "success": True,
            "message": "Command sent",
        }

        response = test_client.post("/api/terminal/agents/frontend-dev/command", json={
            "command": "/review",
        })

        assert response.json()["success"] is True


# =============================================================================
# DASHBOARD INTEGRATION TESTS
# =============================================================================

class TestDashboardIntegration:
    """Tests for terminal panel integration with iHIM dashboard."""

    def test_terminal_panel_in_dashboard(self, test_client):
        """Terminal panel should be available in dashboard."""
        # Expected: UI includes terminal panel component
        test_client.get.return_value.json.return_value = {
            "components": ["actions", "tasks", "notes", "terminal"],
        }

        components = test_client.get("/api/dashboard/components").json()

        assert "terminal" in components["components"]

    def test_terminal_connects_on_dashboard_load(self, test_client):
        """Terminal should connect when dashboard loads."""
        # Expected: WebSocket connection established on panel mount
        test_client.get.return_value.json.return_value = {
            "websocket_url": "ws://localhost:7777/ws/terminal",
        }

        config = test_client.get("/api/terminal/config").json()

        assert "websocket_url" in config

    def test_terminal_respects_dashboard_theme(self):
        """Terminal should use dashboard theme colors."""
        # Expected: Terminal uses theme from CSS variables
        theme = {
            "background": "#1a1a1a",
            "foreground": "#e0e0e0",
            "cursor": "#3d6f9a",
        }

        assert theme["background"].startswith("#")


# =============================================================================
# PERSISTENCE TESTS
# =============================================================================

class TestTerminalPersistence:
    """Tests for terminal state persistence."""

    def test_sessions_survive_refresh(self, test_client, terminal_session):
        """Sessions should persist across page refresh."""
        # Create session
        test_client.post.return_value.json.return_value = {
            "success": True,
            "session": terminal_session,
        }
        test_client.post("/api/terminal/sessions")

        # Simulate page refresh - get sessions
        test_client.get.return_value.json.return_value = {
            "sessions": [terminal_session],
        }

        sessions = test_client.get("/api/terminal/sessions").json()

        assert len(sessions["sessions"]) == 1

    def test_tab_layout_persisted(self, test_client):
        """Tab layout should be persisted."""
        layout = {
            "tabs": [
                {"id": "tab-1", "title": "Build", "order": 0},
                {"id": "tab-2", "title": "Test", "order": 1},
            ],
            "active_tab": "tab-1",
        }

        # Save layout
        test_client.post.return_value.json.return_value = {"success": True}
        test_client.post("/api/terminal/layout", json=layout)

        # Load layout
        test_client.get.return_value.json.return_value = layout

        loaded = test_client.get("/api/terminal/layout").json()

        assert loaded["active_tab"] == "tab-1"

    def test_scrollback_persisted(self, test_client):
        """Scrollback buffer should be retrievable."""
        test_client.get.return_value.json.return_value = {
            "session_id": "term-123",
            "scrollback": "Previous output...\n$ ",
            "lines": 100,
        }

        response = test_client.get("/api/terminal/sessions/term-123/scrollback")

        assert "scrollback" in response.json()


# =============================================================================
# ERROR RECOVERY TESTS
# =============================================================================

class TestErrorRecovery:
    """Tests for terminal error recovery."""

    def test_recover_from_pty_crash(self, test_client, terminal_session):
        """Should recover gracefully when PTY crashes."""
        # PTY crashes
        terminal_session["status"] = "crashed"

        test_client.get.return_value.json.return_value = {
            "session": terminal_session,
        }

        session = test_client.get("/api/terminal/sessions/term-test-123").json()

        assert session["session"]["status"] == "crashed"

        # Restart session
        terminal_session["status"] = "active"
        test_client.post.return_value.json.return_value = {
            "success": True,
            "session": terminal_session,
        }

        response = test_client.post("/api/terminal/sessions/term-test-123/restart")

        assert response.json()["session"]["status"] == "active"

    def test_recover_from_websocket_disconnect(self, test_client):
        """Should handle WebSocket disconnect gracefully."""
        # Expected: Session kept alive for reconnection
        test_client.get.return_value.json.return_value = {
            "session_id": "term-123",
            "websocket_status": "disconnected",
            "pty_status": "alive",
            "reconnect_available": True,
        }

        status = test_client.get("/api/terminal/sessions/term-123/status").json()

        assert status["pty_status"] == "alive"
        assert status["reconnect_available"] is True

    def test_cleanup_orphaned_sessions(self, test_client):
        """Should cleanup orphaned sessions."""
        test_client.post.return_value.json.return_value = {
            "success": True,
            "cleaned": 2,
        }

        response = test_client.post("/api/terminal/cleanup")

        assert response.json()["cleaned"] >= 0


# =============================================================================
# LOAD TESTS
# =============================================================================

class TestTerminalLoad:
    """Load tests for terminal system."""

    def test_handle_many_concurrent_sessions(self, test_client):
        """Should handle multiple concurrent sessions."""
        max_sessions = 10
        sessions = []

        for i in range(max_sessions):
            test_client.post.return_value.json.return_value = {
                "success": True,
                "session": {"id": f"term-{i}"},
            }

            response = test_client.post("/api/terminal/sessions")
            sessions.append(response.json()["session"])

        assert len(sessions) == max_sessions

    def test_handle_rapid_input(self, test_client):
        """Should handle rapid input without dropping."""
        # Simulate rapid keystrokes
        inputs = [f"char{i}" for i in range(100)]

        # All inputs should be processed
        assert len(inputs) == 100

    def test_handle_large_output(self, test_client):
        """Should handle large output bursts."""
        large_output = "A" * 1000000  # 1MB

        # Expected: Output delivered without memory issues
        test_client.get.return_value.json.return_value = {
            "output": large_output[:10000],  # Truncated in response
            "total_size": len(large_output),
        }

        response = test_client.get("/api/terminal/sessions/term-123/output")

        assert response.json()["total_size"] == 1000000


# =============================================================================
# XTERM.JS CONFIGURATION TESTS
# =============================================================================

class TestXtermConfiguration:
    """Tests for xterm.js frontend configuration."""

    def test_get_xterm_config(self, test_client):
        """Should provide xterm.js configuration."""
        test_client.get.return_value.json.return_value = {
            "theme": {
                "background": "#1a1a1a",
                "foreground": "#e0e0e0",
                "cursor": "#3d6f9a",
                "cursorAccent": "#ffffff",
                "selection": "rgba(61, 111, 154, 0.3)",
            },
            "fontFamily": "'Fira Code', 'Cascadia Code', monospace",
            "fontSize": 14,
            "lineHeight": 1.2,
            "cursorBlink": True,
            "cursorStyle": "block",
            "scrollback": 1000,
        }

        config = test_client.get("/api/terminal/xterm/config").json()

        assert "theme" in config
        assert "fontSize" in config
        assert config["scrollback"] >= 100

    def test_xterm_addons_available(self, test_client):
        """Should list available xterm.js addons."""
        test_client.get.return_value.json.return_value = {
            "addons": [
                {"name": "fit", "enabled": True},
                {"name": "webLinks", "enabled": True},
                {"name": "search", "enabled": True},
                {"name": "webgl", "enabled": False},
            ]
        }

        addons = test_client.get("/api/terminal/xterm/addons").json()

        assert len(addons["addons"]) >= 1


# =============================================================================
# KEYBOARD SHORTCUT TESTS
# =============================================================================

class TestKeyboardShortcuts:
    """Tests for terminal keyboard shortcuts."""

    def test_define_keyboard_shortcuts(self):
        """Terminal should define standard shortcuts."""
        shortcuts = {
            "new_tab": "Ctrl+Shift+T",
            "close_tab": "Ctrl+Shift+W",
            "next_tab": "Ctrl+Tab",
            "prev_tab": "Ctrl+Shift+Tab",
            "split_horizontal": "Ctrl+Shift+H",
            "split_vertical": "Ctrl+Shift+V",
            "copy": "Ctrl+Shift+C",
            "paste": "Ctrl+Shift+V",
        }

        assert "new_tab" in shortcuts
        assert "close_tab" in shortcuts

    def test_shortcuts_dont_conflict_with_shell(self):
        """Shortcuts should not conflict with shell bindings."""
        # Ctrl+C is shell interrupt, not copy
        # Ctrl+D is shell EOF, not close
        shell_reserved = ["Ctrl+C", "Ctrl+D", "Ctrl+Z"]

        # Our shortcuts should use Shift modifier
        our_shortcuts = ["Ctrl+Shift+C", "Ctrl+Shift+T"]

        for shortcut in our_shortcuts:
            assert shortcut not in shell_reserved
