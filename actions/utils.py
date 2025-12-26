"""Cross-platform utilities for iHIM actions"""
import subprocess
import sys
import os
from pathlib import Path


# =============================================================================
# PATH UTILITIES
# =============================================================================

def get_workspace_path() -> Path:
    """Get workspace root path for current OS"""
    if sys.platform == "win32":
        return Path("C:/Users/<user>/workspace")
    else:  # darwin (Mac) or linux
        return Path.home() / "workspace"


def get_project_paths() -> dict:
    """Get all standard project paths"""
    workspace = get_workspace_path()
    return {
        "workspace": workspace,
        "ihim": workspace / "IHIM",
        "edgeflow_lp": workspace / "<business>",
        "edgeflow_web": workspace / "<business>" / "web",
        "legal": workspace / "Legal",
    }


# =============================================================================
# FILE/FOLDER OPERATIONS
# =============================================================================

def open_folder(path: Path) -> bool:
    """Open folder in file explorer (Windows Explorer / Mac Finder)"""
    path = Path(path)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(path)])
        else:  # darwin
            subprocess.Popen(["open", str(path)])
        return True
    except Exception:
        return False


def open_file(path: Path) -> bool:
    """Open file with default application"""
    path = Path(path)
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        else:  # darwin
            subprocess.Popen(["open", str(path)])
        return True
    except Exception:
        return False


# =============================================================================
# TERMINAL OPERATIONS
# =============================================================================

def open_terminal(path: Path, command: str = None) -> bool:
    """
    Open terminal at path, optionally run a command.

    Windows: Uses Windows Terminal (wt) with named window "iHIM"
             All iHIM terminals go to the same window as tabs
    Mac: Uses Terminal.app
    """
    path = Path(path)
    try:
        if sys.platform == "win32":
            if command:
                # Open new tab in Windows Terminal named "iHIM", run command
                subprocess.Popen(
                    f'wt --window iHIM nt -d "{path}" pwsh -NoExit -Command "{command}"',
                    shell=True
                )
            else:
                subprocess.Popen([
                    "wt", "--window", "iHIM", "nt",
                    "-d", str(path)
                ])
        else:  # darwin
            if command:
                # Create a temp script to run the command
                script = f'cd "{path}" && {command}'
                subprocess.Popen([
                    "osascript", "-e",
                    f'tell app "Terminal" to do script "{script}"'
                ])
            else:
                subprocess.Popen(["open", "-a", "Terminal", str(path)])
        return True
    except Exception:
        return False


def open_claude_code(path: Path) -> bool:
    """Open the agent harness CLI in a new terminal at the specified path"""
    return open_terminal(path, "claude")


# =============================================================================
# NPM / DEV SERVER OPERATIONS
# =============================================================================

def run_npm_script(path: Path, script: str = "dev") -> bool:
    """Run npm script in a new terminal window"""
    return open_terminal(path, f"npm run {script}")


def run_command_background(command: list, cwd: Path = None) -> bool:
    """Run a command in the background (no terminal window)"""
    try:
        subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except Exception:
        return False


# =============================================================================
# BROWSER OPERATIONS
# =============================================================================

def open_url(url: str) -> bool:
    """Open URL in default browser"""
    import webbrowser
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


def open_in_chrome(url: str) -> bool:
    """Open URL specifically in Chrome"""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["start", "chrome", url], shell=True)
        else:  # darwin
            subprocess.Popen(["open", "-a", "Google Chrome", url])
        return True
    except Exception:
        return False


# =============================================================================
# VS CODE OPERATIONS
# =============================================================================

def open_vscode(path: Path) -> bool:
    """Open VS Code in the specified folder"""
    path = Path(path)
    try:
        subprocess.Popen(["code", str(path)])
        return True
    except Exception:
        return False


def open_vscode_with_claude(path: Path) -> bool:
    """
    Open VS Code in folder and trigger the agent extension.
    """
    path = Path(path)
    try:
        # Open VS Code in folder
        subprocess.Popen(["code", str(path)])
        return True
    except Exception:
        return False


# =============================================================================
# PLATFORM INFO
# =============================================================================

def get_platform() -> str:
    """Get friendly platform name"""
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "mac"
    else:
        return "linux"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_mac() -> bool:
    return sys.platform == "darwin"
