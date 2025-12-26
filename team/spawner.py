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
from pathlib import Path
from datetime import datetime

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

        # Instruction for the agent - include a marker so we can identify agent processes
        instruction = f"Read the file {prompt_file} and execute the task described in it. You are the {agent} specialist."

        if is_first:
            # First agent: create NEW NAMED window
            # --window creates/targets a window by name
            subprocess.Popen([
                'wt', '--window', AGENT_WINDOW_NAME,
                '--title', agent,
                '-d', str(working_dir),
                'cmd', '/k', f'claude "{instruction}"'
            ])
        else:
            # Subsequent agents: add tab to the NAMED window (not -w 0)
            subprocess.Popen([
                'wt', '--window', AGENT_WINDOW_NAME,
                'nt',  # new-tab
                '--title', agent,
                '-d', str(working_dir),
                'cmd', '/k', f'claude "{instruction}"'
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

    agents = list(routed_prompts.keys())
    spawned = []
    failed = []

    # Spawn all agents - first one creates window, rest add as tabs
    import time
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

    if spawned:
        result = {
            "success": True,
            "message": f"Spawned {len(spawned)} agents" + (" with blackboard coordination" if BLACKBOARD_AVAILABLE else ""),
            "session_id": session_id,
            "agents": spawned,
            "failed": failed,
            "task_files": task_files,
            "spawned_at": datetime.now().isoformat(),
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
    Collapse the agent team - close the agent window.

    Only closes the iHIM-AgentTeam window, NOT your main the agent session.
    Uses window handles to close just the agent window without affecting
    other Windows Terminal windows.

    Returns:
        dict with collapse status
    """
    if sys.platform == "win32":
        try:
            tasks_path_str = str(TASKS_PATH).replace("\\", "\\\\")

            # PowerShell script that:
            # 1. Finds cmd.exe processes with our task path
            # 2. Gets their parent Windows Terminal window handle
            # 3. Closes that specific window (not process - to not affect other WT windows)
            # 4. Kills the cmd.exe processes
            result = subprocess.run(
                ['powershell', '-Command', '''
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Collections.Generic;

public class WTWindowCloser {
    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
    public static extern int GetClassName(IntPtr hWnd, System.Text.StringBuilder lpClassName, int nMaxCount);

    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

    public const uint WM_CLOSE = 0x0010;

    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    public static List<IntPtr> wtWindows = new List<IntPtr>();

    public static bool EnumWindowsCallback(IntPtr hWnd, IntPtr lParam) {
        var className = new System.Text.StringBuilder(256);
        GetClassName(hWnd, className, className.Capacity);
        if (className.ToString() == "CASCADIA_HOSTING_WINDOW_CLASS") {
            wtWindows.Add(hWnd);
        }
        return true;
    }

    public static IntPtr[] GetWTWindows() {
        wtWindows.Clear();
        EnumWindows(EnumWindowsCallback, IntPtr.Zero);
        return wtWindows.ToArray();
    }

    public static uint GetWindowPID(IntPtr hwnd) {
        uint pid;
        GetWindowThreadProcessId(hwnd, out pid);
        return pid;
    }
}
"@

$killed = 0
$windowClosed = $false
$targetPIDs = @()

# First, find all cmd.exe processes running our agent tasks
Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" | ForEach-Object {
    if ($_.CommandLine -like "*''' + tasks_path_str + '''*") {
        $targetPIDs += $_.ParentProcessId
    }
}

# Get unique parent PIDs (these should be Windows Terminal)
$targetPIDs = $targetPIDs | Select-Object -Unique

# Find the Windows Terminal window(s) that own our agent processes
$wtWindows = [WTWindowCloser]::GetWTWindows()
foreach ($hwnd in $wtWindows) {
    $windowPID = [WTWindowCloser]::GetWindowPID($hwnd)
    if ($targetPIDs -contains $windowPID) {
        # This is the agent team window - close it
        [WTWindowCloser]::PostMessage($hwnd, [WTWindowCloser]::WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero)
        $windowClosed = $true
    }
}

# Also kill any lingering cmd.exe processes (belt and suspenders)
Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" | ForEach-Object {
    if ($_.CommandLine -like "*''' + tasks_path_str + '''*") {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $killed++
    }
}

Write-Output "$killed|$windowClosed"
                '''],
                capture_output=True,
                text=True
            )

            output = result.stdout.strip()
            parts = output.split("|") if "|" in output else [output, "False"]
            killed_count = parts[0]
            window_closed = parts[1].lower() == "true"

            # Clean up task and prompt files
            for task_file in TASKS_PATH.glob("*-task.md"):
                task_file.unlink()
            for prompt_file in TASKS_PATH.glob("*-prompt.txt"):
                prompt_file.unlink()

            if window_closed:
                return {
                    "success": True,
                    "message": f"Closed agent window and {killed_count} agent(s)",
                    "collapsed_at": datetime.now().isoformat(),
                }
            elif int(killed_count) > 0:
                return {
                    "success": True,
                    "message": f"Collapsed {killed_count} agent(s) (window may have already closed)",
                    "collapsed_at": datetime.now().isoformat(),
                }
            else:
                return {
                    "success": True,
                    "message": "No active agents to collapse",
                    "collapsed_at": datetime.now().isoformat(),
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to collapse team: {str(e)}",
            }
    else:
        return {
            "success": False,
            "message": "Mac/Linux collapse not yet implemented",
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
