"""Action Registry - All available actions in iHIM"""
from actions.utils import (
    get_project_paths,
    open_folder,
    open_claude_code,
    run_npm_script,
    open_vscode_with_claude,
    get_platform,
)

# Get paths for current platform
PATHS = get_project_paths()

# Action definitions
ACTIONS = {
    "claude_workspace": {
        "name": "the agent harness CLI: workspace",
        "description": "Open the agent harness in workspace (full context)",
        "icon": "cli",
        "category": "dev",
    },
    "explorer_workspace": {
        "name": "workspace",
        "description": "Open workspace in file browser",
        "icon": "folder",
        "category": "files",
    },
    # Tools
    "flight_path": {
        "name": "Flight Path",
        "description": "Visual map of project dependencies and structure",
        "icon": "flightpath",
        "category": "tools",
        "has_modal": True,
    },
    "slash_commands": {
        "name": "Slash Commands",
        "description": "Command center for all commands",
        "icon": "slash",
        "category": "tools",
        "has_modal": True,
        "hidden": True,  # Consolidated into Mission Control
    },
    "mission_control": {
        "name": "Mission Control",
        "description": "Terminal, Commands, Feature Builder, Team Builder - all in one",
        "icon": "terminal",
        "category": "tools",
        "has_modal": True,
    },
    "stopwatch": {
        "name": "Stopwatch",
        "description": "Spawn multiple independent stopwatches on screen",
        "icon": "timer",
        "category": "tools",
    },
    "standards_library": {
        "name": "Standards Library",
        "description": "Compliance modules - HIPAA, SOC 2, and more",
        "icon": "shield",
        "category": "tools",
        "has_modal": True,
    },
    "google_calendar": {
        "name": "Google Calendar",
        "description": "View upcoming events and sync with Google Calendar",
        "icon": "calendar",
        "category": "tools",
        "has_modal": True,
    },
    "health": {
        "name": "Health",
        "description": "Hybrid home workout program + nutrition plan",
        "icon": "heart-pulse",
        "category": "tools",
        "has_modal": True,
    },
    "workspaces": {
        "name": "Workspaces",
        "description": "Active git branches and parallel development sessions",
        "icon": "git-branch",
        "category": "tools",
        "has_modal": True,
    },
    "vault": {
        "name": "Vault",
        "description": "Tasks, projects, and document browser",
        "icon": "archive",
        "category": "tools",
        "has_modal": True,
    },
    # Team actions (consolidated into Mission Control)
    "software_dev_team": {
        "name": "Feature Builder",
        "description": "Spawn 5 coding specialists in parallel",
        "icon": "rocket",
        "category": "actions",
        "has_input": True,
        "hidden": True,  # Consolidated into Mission Control
    },
    "agent_team_builder": {
        "name": "Team Builder",
        "description": "Design and spawn custom agent teams (3-5 agents)",
        "icon": "users",
        "category": "actions",
        "has_modal": True,
        "hidden": True,  # Consolidated into Mission Control
    },
    "meeting_recorder": {
        "name": "Meeting Recorder",
        "description": "Record meetings with dual-channel audio capture and transcription",
        "icon": "mic",
        "category": "tools",
        "has_modal": True,
    },
    "stt": {
        "name": "STT Dictation",
        "description": "Hold-to-dictate with Whisper + LLM cleanup — text appears where you type",
        "icon": "mic",
        "category": "tools",
        "has_modal": True,
    },
    # System actions
    "restart_server": {
        "name": "Restart Server",
        "description": "Kill and restart iHIM (self-destruct)",
        "icon": "restart",
        "category": "system",
    },
}


def run_action(action_id: str) -> dict:
    """Execute an action and return result"""

    if action_id == "claude_workspace":
        if open_claude_code(PATHS["workspace"]):
            return {"success": True, "message": "Opening the agent harness"}
        return {"success": False, "message": "Failed to open the agent harness"}

    elif action_id == "explorer_workspace":
        if open_folder(PATHS["workspace"]):
            return {"success": True, "message": "Opening workspace folder"}
        return {"success": False, "message": "Failed to open folder"}

    elif action_id == "flight_path":
        # Handled by UI (modal)
        return {"success": True, "message": "Opening Flight Path..."}

    elif action_id == "slash_commands":
        # Handled by UI (modal)
        return {"success": True, "message": "Opening Slash Command Center..."}

    elif action_id == "mission_control":
        # Handled by UI (modal)
        return {"success": True, "message": "Opening Mission Control..."}

    elif action_id == "stopwatch":
        # Handled by UI (spawns floating stopwatch widgets)
        return {"success": True, "message": "Opening Stopwatch..."}

    elif action_id == "standards_library":
        # Handled by UI (modal for managing compliance modules)
        return {"success": True, "message": "Opening Standards Library..."}

    elif action_id == "google_calendar":
        # Handled by UI (modal for Google Calendar)
        return {"success": True, "message": "Opening Google Calendar..."}

    elif action_id == "health":
        # Handled by UI (modal for Health program)
        return {"success": True, "message": "Opening Health..."}

    elif action_id == "workspaces":
        # Handled by UI (modal for Workspaces)
        return {"success": True, "message": "Opening Workspaces..."}

    elif action_id == "vault":
        # Handled by UI (modal for Vault)
        return {"success": True, "message": "Opening Vault..."}

    elif action_id == "software_dev_team":
        # This action is handled by the UI (shows input modal)
        # The actual spawn happens via POST /api/team/spawn
        return {"success": True, "message": "Opening team panel...", "show_input": True}

    elif action_id == "agent_team_builder":
        # Handled by UI (modal for designing custom agent teams)
        return {"success": True, "message": "Opening Team Builder..."}

    elif action_id == "meeting_recorder":
        # Handled by UI (modal for meeting recorder)
        return {"success": True, "message": "Opening Meeting Recorder..."}

    elif action_id == "stt":
        # Handled by UI (modal for STT dictation)
        return {"success": True, "message": "Opening STT Dictation..."}

    elif action_id == "restart_server":
        # Handled by frontend - calls /api/server/restart directly
        return {"success": True, "message": "Use the restart endpoint", "redirect": "/api/server/restart"}

    else:
        return {"success": False, "message": f"Unknown action: {action_id}"}
