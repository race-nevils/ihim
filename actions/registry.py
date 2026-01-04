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
    "task_list": {
        "name": "Task List",
        "description": "Manage your tasks and priorities",
        "icon": "checklist",
        "category": "tools",
        "has_modal": True,
    },
    "quick_notes": {
        "name": "Quick Notes",
        "description": "Jot down ideas, notes, and reminders",
        "icon": "note",
        "category": "tools",
        "has_modal": True,
    },
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
    "heuristics": {
        "name": "Tricks & Heuristics",
        "description": "Debugging tricks and patterns that work",
        "icon": "lightbulb",
        "category": "tools",
        "has_modal": True,
    },
    "standards_library": {
        "name": "Standards Library",
        "description": "Compliance modules - HIPAA, SOC 2, and more",
        "icon": "shield",
        "category": "tools",
        "has_modal": True,
    },
    "c2pa_verify": {
        "name": "C2PA Verify",
        "description": "Verify C2PA content authenticity and sign images",
        "icon": "verified",
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

    elif action_id == "task_list":
        # Handled by UI (modal)
        return {"success": True, "message": "Opening task list..."}

    elif action_id == "quick_notes":
        # Handled by UI (modal)
        return {"success": True, "message": "Opening notes..."}

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

    elif action_id == "heuristics":
        # Handled by UI (modal for viewing/adding heuristics)
        return {"success": True, "message": "Opening Tricks & Heuristics..."}

    elif action_id == "standards_library":
        # Handled by UI (modal for managing compliance modules)
        return {"success": True, "message": "Opening Standards Library..."}

    elif action_id == "c2pa_verify":
        # Handled by UI (modal for C2PA verification and signing)
        return {"success": True, "message": "Opening C2PA Verify..."}

    elif action_id == "software_dev_team":
        # This action is handled by the UI (shows input modal)
        # The actual spawn happens via POST /api/team/spawn
        return {"success": True, "message": "Opening team panel...", "show_input": True}

    elif action_id == "agent_team_builder":
        # Handled by UI (modal for designing custom agent teams)
        return {"success": True, "message": "Opening Team Builder..."}

    elif action_id == "restart_server":
        # Handled by frontend - calls /api/server/restart directly
        return {"success": True, "message": "Use the restart endpoint", "redirect": "/api/server/restart"}

    else:
        return {"success": False, "message": f"Unknown action: {action_id}"}
