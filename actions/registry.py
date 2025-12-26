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
    "edgeflow_workspace": {
        "name": "EdgeFlowAI LP Dev Workspace",
        "description": "VS Code + the agent + Dev Server (all-in-one)",
        "icon": "rocket",
        "category": "dev",
    },
    "edgeflow_dev": {
        "name": "EdgeFlow Dev Server",
        "description": "Start EdgeFlow LP dev server",
        "icon": "play",
        "category": "dev",
    },
    "explorer_workspace": {
        "name": "Open workspace Folder",
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
    },
    # Team actions
    "software_dev_team": {
        "name": "Feature Builder",
        "description": "Spawn 5 coding specialists in parallel",
        "icon": "rocket",
        "category": "actions",
        "has_input": True,  # This action needs user input (prompt)
    },
    "collapse_team": {
        "name": "Collapse Team",
        "description": "Close all agent tabs",
        "icon": "x",
        "category": "actions",
    },
}


def run_action(action_id: str) -> dict:
    """Execute an action and return result"""

    if action_id == "claude_workspace":
        if open_claude_code(PATHS["workspace"]):
            return {"success": True, "message": "Opening the agent harness"}
        return {"success": False, "message": "Failed to open the agent harness"}

    elif action_id == "edgeflow_workspace":
        # All-in-one: VS Code + the agent + Dev Server
        success = True
        if not open_vscode_with_claude(PATHS["workspace"]):
            success = False
        if not run_npm_script(PATHS["edgeflow_web"], "dev"):
            success = False
        if success:
            return {"success": True, "message": "Launching EdgeFlow workspace..."}
        return {"success": False, "message": "Some components failed to launch"}

    elif action_id == "edgeflow_dev":
        if run_npm_script(PATHS["edgeflow_web"], "dev"):
            return {"success": True, "message": "Starting EdgeFlow dev server"}
        return {"success": False, "message": "Failed to start dev server"}

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

    elif action_id == "software_dev_team":
        # This action is handled by the UI (shows input modal)
        # The actual spawn happens via POST /api/team/spawn
        return {"success": True, "message": "Opening team panel...", "show_input": True}

    elif action_id == "collapse_team":
        # Import here to avoid circular imports
        from team.spawner import collapse_team as do_collapse
        result = do_collapse()
        return result

    else:
        return {"success": False, "message": f"Unknown action: {action_id}"}
