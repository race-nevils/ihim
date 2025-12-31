"""
Agent Spawner - Spawns 5 CLI tabs in one Windows Terminal window

Creates one Windows Terminal window called "AgentTeam" with 5 tabs,
each running the agent harness CLI with a tailored prompt.

Integrates with:
- Blackboard for agent coordination
- Feedback system for self-improvement
- Optimizer for enhanced prompts
"""

import subprocess
import sys
import json
import uuid
import time
import shlex
from pathlib import Path
from datetime import datetime

# Win32 API for window tracking (Windows only)
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    WM_CLOSE = 0x0010

# Module-level state: tracks the agent team window handle
_team_window_hwnd: int = None

# Import blackboard (with fallback for standalone usage)
try:
    from .blackboard import (
        init_blackboard,
        load_blackboard,
        clear_blackboard,
        get_blackboard_summary,
        Phase,
        BLACKBOARD_INSTRUCTIONS,
    )
    BLACKBOARD_AVAILABLE = True
except ImportError:
    try:
        from team.blackboard import (
            init_blackboard,
            load_blackboard,
            clear_blackboard,
            get_blackboard_summary,
            Phase,
            BLACKBOARD_INSTRUCTIONS,
        )
        BLACKBOARD_AVAILABLE = True
    except ImportError:
        BLACKBOARD_AVAILABLE = False
        BLACKBOARD_INSTRUCTIONS = ""

# Import optimizer (with fallback)
try:
    from .feedback.optimizer import apply_optimizations_to_prompt
    OPTIMIZER_AVAILABLE = True
except ImportError:
    OPTIMIZER_AVAILABLE = False
    def apply_optimizations_to_prompt(agent, prompt):
        return prompt


# Paths
WORKSPACE_PATH = Path("C:/Users/<user>/workspace")
IHIM_PATH = WORKSPACE_PATH / "IHIM"
TASKS_PATH = IHIM_PATH / "team" / "tasks"
RESULTS_PATH = IHIM_PATH / "team" / "results"
DATA_PATH = IHIM_PATH / "team" / "data"


def ensure_directories():
    """Ensure task, result, and data directories exist."""
    TASKS_PATH.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.mkdir(parents=True, exist_ok=True)
    DATA_PATH.mkdir(parents=True, exist_ok=True)


# --- Window Tracking Helpers (Windows only) ---

def _get_wt_windows() -> set:
    """
    Enumerate all visible Windows Terminal window handles.

    Returns:
        Set of HWND integers for Windows Terminal windows
    """
    if sys.platform != "win32":
        return set()

    handles = set()

    def enum_callback(hwnd, _):
        # Check if it's a Windows Terminal window
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, 256)
        if class_name.value == "CASCADIA_HOSTING_WINDOW_CLASS":
            if user32.IsWindowVisible(hwnd):
                handles.add(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
    return handles


def _get_window_title(hwnd: int) -> str:
    """Get the title of a window by its handle."""
    if sys.platform != "win32":
        return ""
    length = user32.GetWindowTextLengthW(hwnd) + 1
    buffer = ctypes.create_unicode_buffer(length)
    user32.GetWindowTextW(hwnd, buffer, length)
    return buffer.value


def generate_session_id() -> str:
    """Generate a unique session ID for this spawn."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    short_uuid = str(uuid.uuid4())[:8]
    return f"spawn-{timestamp}-{short_uuid}"


def write_task_file(agent: str, prompt: str) -> Path:
    """
    Write a task file for an agent.

    The agent's the agent harness session will read this file to get its task.

    Args:
        agent: Agent name (e.g., "frontend-dev")
        prompt: The tailored prompt for this agent

    Returns:
        Path to the created task file
    """
    ensure_directories()

    task_file = TASKS_PATH / f"{agent}-task.md"
    task_file.write_text(prompt, encoding="utf-8")

    return task_file


AGENT_WINDOW_NAME = "iHIM-AgentTeam"


def spawn_single_agent(agent: str, prompt: str, working_dir: Path, is_first: bool = False) -> bool:
    """
    Spawn a single the agent harness CLI session in Windows Terminal.

    Args:
        agent: Agent name (e.g., "frontend-dev")
        prompt: The tailored prompt for this agent
        working_dir: Directory to start in
        is_first: If True, creates new window. If False, adds tab to existing window.

    Returns:
        True if spawn succeeded, False otherwise
    """
    if sys.platform != "win32":
        return False

    try:
        # Write prompt to a temp file (avoids command line escaping hell)
        prompt_file = TASKS_PATH / f"{agent}-prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        # Instruction for the agent
        instruction = f"Read the file {prompt_file} and execute the task described in it. You are the {agent} specialist."

        # [iHIM] prefix lets collapse_team() find and close this window
        tab_title = f"[iHIM] {agent}"

        if is_first:
            # First agent: create NEW NAMED window
            subprocess.Popen([
                'wt', '--window', AGENT_WINDOW_NAME,
                '--title', tab_title,
                '-d', str(working_dir),
                'cmd', '/k', f'claude {shlex.quote(instruction)}'
            ])
        else:
            # Subsequent agents: add tab to the NAMED window
            subprocess.Popen([
                'wt', '--window', AGENT_WINDOW_NAME,
                'nt',  # new-tab
                '--title', tab_title,
                '-d', str(working_dir),
                'cmd', '/k', f'claude {shlex.quote(instruction)}'
            ])
        return True
    except Exception as e:
        print(f"Failed to spawn {agent}: {e}")
        return False


def spawn_agent_team(routed_prompts: dict, feature_description: str = None) -> dict:
    """
    Spawn the agent harness CLI sessions - one per agent.

    Each agent gets its own terminal window with the agent harness.
    Initializes a blackboard for agent collaboration.

    Args:
        routed_prompts: dict mapping agent names to their tailored prompts
        feature_description: What we're building (for blackboard)

    Returns:
        dict with spawn status and details
    """
    ensure_directories()

    # Validate agent count (safety limit)
    if len(routed_prompts) > 10:
        return {
            "success": False,
            "message": f"Cannot spawn {len(routed_prompts)} agents. Maximum is 10.",
            "agents": [],
        }

    # Generate session ID
    session_id = generate_session_id()

    # Initialize blackboard for agent coordination (if available)
    agents = list(routed_prompts.keys())
    feature = feature_description or "Feature build"
    if BLACKBOARD_AVAILABLE:
        board = init_blackboard(feature, agents)
    else:
        board = None

    # Write task files for each agent
    task_files = {}
    for agent, prompt in routed_prompts.items():
        # Apply optimizations from feedback history
        optimized_prompt = apply_optimizations_to_prompt(agent, prompt)

        # Add session ID, blackboard info, and coordination instructions
        enhanced_prompt = f"""# Task for {agent}

## Session Info
- Session ID: {session_id}
- Blackboard: C:/Users/<user>/workspace/IHIM/team/blackboard.json
- Results output: C:/Users/<user>/workspace/IHIM/team/results/{agent}-result.json

---

{optimized_prompt}

---

{BLACKBOARD_INSTRUCTIONS}
"""
        task_file = write_task_file(agent, enhanced_prompt)
        task_files[agent] = str(task_file)

    if sys.platform != "win32":
        return {
            "success": False,
            "message": "Mac/Linux spawning not yet implemented",
            "agents": [],
        }

    global _team_window_hwnd

    # Capture existing WT windows BEFORE spawning
    windows_before = _get_wt_windows()

    agents = list(routed_prompts.keys())
    spawned = []
    failed = []

    # Spawn all agents - first one creates window, rest add as tabs
    for i, agent in enumerate(agents):
        prompt = routed_prompts[agent]
        is_first = (i == 0)

        if spawn_single_agent(agent, prompt, WORKSPACE_PATH, is_first=is_first):
            spawned.append(agent)
        else:
            failed.append(agent)

        # Small delay between spawns to let Windows Terminal catch up
        if not is_first:
            time.sleep(0.5)

    # Wait for the window to fully appear, then capture its handle
    if spawned:
        time.sleep(1.5)  # Give WT time to create the window
        windows_after = _get_wt_windows()
        new_windows = windows_after - windows_before

        # Find our window - prefer one with [iHIM] in title
        _team_window_hwnd = None
        for hwnd in new_windows:
            title = _get_window_title(hwnd)
            if "[iHIM]" in title:
                _team_window_hwnd = hwnd
                break
        else:
            # Fallback: take any new window
            if new_windows:
                _team_window_hwnd = new_windows.pop()

    if spawned:
        result = {
            "success": True,
            "message": f"Spawned {len(spawned)} agents" + (" with blackboard coordination" if BLACKBOARD_AVAILABLE else ""),
            "session_id": session_id,
            "agents": spawned,
            "failed": failed,
            "task_files": task_files,
            "spawned_at": datetime.now().isoformat(),
            "window_tracked": _team_window_hwnd is not None,
        }
        if BLACKBOARD_AVAILABLE:
            result["blackboard"] = "IHIM/team/blackboard.json"
            result["phase"] = Phase.PHASE_1_BUILD.value
        return result
    else:
        return {
            "success": False,
            "message": "Failed to spawn any agents",
            "agents": [],
        }


def collapse_team() -> dict:
    """
    Collapse the agent team - close the tracked agent window.

    Uses the window handle (HWND) captured at spawn time to close
    the exact window, regardless of which tab is active.
    """
    global _team_window_hwnd

    if sys.platform != "win32":
        return {"success": False, "message": "Only supported on Windows"}

    # Clean up task and prompt files regardless of window state
    for task_file in TASKS_PATH.glob("*-task.md"):
        task_file.unlink()
    for prompt_file in TASKS_PATH.glob("*-prompt.txt"):
        prompt_file.unlink()

    # Check if we have a tracked window
    if _team_window_hwnd is None:
        return {
            "success": False,
            "message": "No agent window tracked (spawn first, or window was already closed)",
            "collapsed_at": datetime.now().isoformat(),
        }

    # Verify window still exists
    if not user32.IsWindow(_team_window_hwnd):
        _team_window_hwnd = None
        return {
            "success": True,
            "message": "Agent window already closed",
            "collapsed_at": datetime.now().isoformat(),
        }

    # Send WM_CLOSE to the tracked window - graceful close
    result = user32.PostMessageW(_team_window_hwnd, WM_CLOSE, 0, 0)
    _team_window_hwnd = None

    if result:
        return {
            "success": True,
            "message": "Agent window closed",
            "collapsed_at": datetime.now().isoformat(),
        }
    else:
        return {
            "success": False,
            "message": "Failed to close window (PostMessage failed)",
        }


def get_team_status() -> dict:
    """
    Get the current status of the agent team.

    Checks for:
    - Task files (agents with pending work)
    - Result files (agents that have completed)

    Returns:
        dict with team status
    """
    ensure_directories()

    # Check task files
    pending_tasks = list(TASKS_PATH.glob("*-task.md"))

    # Check result files
    completed_results = list(RESULTS_PATH.glob("*-result.json"))

    agents_status = {}
    for agent in ["frontend-dev", "backend-dev", "devops", "qa-tester", "security-reviewer"]:
        task_file = TASKS_PATH / f"{agent}-task.md"
        result_file = RESULTS_PATH / f"{agent}-result.json"

        if result_file.exists():
            agents_status[agent] = "completed"
        elif task_file.exists():
            agents_status[agent] = "working"
        else:
            agents_status[agent] = "idle"

    return {
        "active": len(pending_tasks) > 0,
        "agents": agents_status,
        "pending_count": len(pending_tasks),
        "completed_count": len(completed_results),
    }


def collect_results() -> dict:
    """
    Collect all agent results.

    Returns:
        dict with all agent results
    """
    ensure_directories()

    results = {}
    for result_file in RESULTS_PATH.glob("*-result.json"):
        agent = result_file.stem.replace("-result", "")
        try:
            results[agent] = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception:
            results[agent] = {"error": "Failed to parse result file"}

    return results
