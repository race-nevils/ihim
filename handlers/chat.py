"""Chat handler: open terminal with LLM for direct conversation."""
import subprocess
import sys
from pathlib import Path
import shlex

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.ollama import OllamaAdapter
from orchestrator.state import OrchestratorState


def handle(state: OrchestratorState) -> OrchestratorState:
    """Handle chat intent: open terminal with reasoning model.

    Opens Windows Terminal with Ollama running the reasoning model,
    pre-populated with the user's question.

    Args:
        state: Current orchestrator state

    Returns:
        Updated state with action result
    """
    prompt = state.get("input_text", "")
    model = OllamaAdapter.REASON_MODEL  # Use reasoning model for chat

    try:
        # Escape the prompt for PowerShell
        # Replace single quotes with two single quotes for PS escaping
        escaped_prompt = prompt.replace("'", "''")

        # Build the command to run in terminal
        # Use Windows Terminal (wt) if available, fall back to PowerShell
        try:
            # Check if Windows Terminal is available
            subprocess.run(["wt", "--version"], capture_output=True, check=True)
            has_wt = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            has_wt = False

        if has_wt:
            # Open Windows Terminal with new tab
            cmd = [
                "wt", "new-tab",
                "--title", "LLM Chat",
                "powershell", "-NoExit", "-Command",
                f"Write-Host 'Starting chat with {model}...' -ForegroundColor Cyan; "
                f"ollama run {model} '{escaped_prompt}'"
            ]
        else:
            # Fallback to regular PowerShell window
            cmd = [
                "powershell", "-NoExit", "-Command",
                f"Write-Host 'Starting chat with {model}...' -ForegroundColor Cyan; "
                f"ollama run {model} '{escaped_prompt}'"
            ]

        # Launch the terminal (non-blocking)
        subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)

        state["result"] = {
            "action": "opened_terminal",
            "model": model,
            "prompt_length": len(prompt),
            "terminal": "wt" if has_wt else "powershell"
        }

    except Exception as e:
        state["error"] = f"Chat handler error: {str(e)}"
        state["result"] = {"action": "error", "error": str(e)}

    return state
