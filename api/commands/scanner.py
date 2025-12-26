"""
Scanner for harness/commands/ directory.

Discovers and parses commands markdown files to sync
with the command center data store.
"""

import re
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from .models import (
    SlashCommand,
    CommandCategory,
    CommandStatus,
    AutoInvokeConfig,
    CommandCenterData,
)


# Default paths
WORKSPACE_ROOT = Path("C:/Users/<user>/workspace")
COMMANDS_DIR = WORKSPACE_ROOT / "harness dir" / "commands"
DATA_FILE = WORKSPACE_ROOT / "IHIM" / "data" / "slash_commands.json"


def parse_command_markdown(file_path: Path) -> Optional[Dict]:
    """
    Parse a commands markdown file.

    Extracts:
    - Title (from # heading)
    - Description (first paragraph after title)
    - Sections (## headings and their content)

    Returns dict with parsed data or None if parsing fails.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        result = {
            "id": file_path.stem,
            "name": f"/{file_path.stem}",
            "file_path": str(file_path),
            "source": "file",
        }

        # Extract title (first # heading)
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if title_match:
            result["display_title"] = title_match.group(1).strip()

        # Extract first paragraph as short description
        paragraphs = re.split(r"\n\n+", content)
        for para in paragraphs:
            para = para.strip()
            # Skip the title and empty lines
            if para and not para.startswith("#"):
                # Take first sentence or first 100 chars
                first_sentence = re.split(r"[.!?]", para)[0]
                result["short_desc"] = first_sentence[:100].strip()
                result["description"] = para[:500].strip()
                break

        # Extract sections
        sections = {}
        current_section = None
        current_content = []

        for line in lines:
            if line.startswith("## "):
                if current_section:
                    sections[current_section] = "\n".join(current_content).strip()
                current_section = line[3:].strip().lower().replace(" ", "_")
                current_content = []
            elif current_section:
                current_content.append(line)

        if current_section:
            sections[current_section] = "\n".join(current_content).strip()

        result["sections"] = sections

        # Extract usage from "When to Use" or similar section
        for key in ["when_to_use", "usage", "how_to_use"]:
            if key in sections:
                result["usage"] = sections[key][:300]
                break

        return result

    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
        return None


def scan_commands_directory(commands_dir: Path = COMMANDS_DIR) -> List[Dict]:
    """
    Scan the harness/commands/ directory for command markdown files.

    Returns list of parsed command data.
    """
    results = []

    if not commands_dir.exists():
        return results

    for md_file in commands_dir.glob("*.md"):
        parsed = parse_command_markdown(md_file)
        if parsed:
            results.append(parsed)

    return results


def load_command_center_data(data_file: Path = DATA_FILE) -> Dict:
    """Load existing command center data from JSON file."""
    if data_file.exists():
        try:
            return json.loads(data_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"commands": [], "categories": {}, "ideas": [], "metadata": {}}


def save_command_center_data(data: Dict, data_file: Path = DATA_FILE):
    """Save command center data to JSON file."""
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def sync_commands(
    commands_dir: Path = COMMANDS_DIR,
    data_file: Path = DATA_FILE
) -> Dict:
    """
    Sync commands from harness/commands/ to the data store.

    - Adds new commands discovered in the directory
    - Updates existing commands if file has changed
    - Marks removed commands (but doesn't delete - preserves config)

    Returns sync result with counts and lists of changes.
    """
    scanned = scan_commands_directory(commands_dir)
    existing_data = load_command_center_data(data_file)

    existing_commands = {cmd["id"]: cmd for cmd in existing_data.get("commands", [])}
    scanned_ids = {cmd["id"] for cmd in scanned}

    added = []
    updated = []
    removed = []
    errors = []

    now = datetime.utcnow().isoformat() + "Z"

    for scanned_cmd in scanned:
        cmd_id = scanned_cmd["id"]

        if cmd_id in existing_commands:
            # Update existing command with scanned data
            existing = existing_commands[cmd_id]

            # Preserve user configuration
            preserved_fields = ["auto_invoke", "category", "examples", "related_commands"]
            for field in preserved_fields:
                if field in existing:
                    scanned_cmd[field] = existing[field]

            # Check if actually changed
            if existing.get("description") != scanned_cmd.get("description"):
                scanned_cmd["updated_at"] = now
                updated.append(cmd_id)

            # Merge
            existing_commands[cmd_id] = {**existing, **scanned_cmd}
        else:
            # New command
            scanned_cmd["created_at"] = now
            scanned_cmd["updated_at"] = now
            scanned_cmd["status"] = "active"
            scanned_cmd["auto_invoke"] = {"enabled": False, "triggers": []}

            # Assign default category based on command name
            if "session" in cmd_id or cmd_id in ["save", "endsession"]:
                scanned_cmd["category"] = "session"
            elif "git" in cmd_id or "push" in cmd_id or "commit" in cmd_id:
                scanned_cmd["category"] = "git"
            elif "audit" in cmd_id or "review" in cmd_id:
                scanned_cmd["category"] = "quality"
            else:
                scanned_cmd["category"] = "productivity"

            existing_commands[cmd_id] = scanned_cmd
            added.append(cmd_id)

    # Mark removed commands
    for cmd_id in existing_commands:
        if cmd_id not in scanned_ids:
            if existing_commands[cmd_id].get("source") == "file":
                existing_commands[cmd_id]["status"] = "deprecated"
                removed.append(cmd_id)

    # Update the data
    existing_data["commands"] = list(existing_commands.values())
    existing_data["metadata"]["last_sync"] = now
    existing_data["metadata"]["version"] = "1.1.0"

    save_command_center_data(existing_data, data_file)

    return {
        "synced": len(scanned),
        "added": added,
        "updated": updated,
        "removed": removed,
        "errors": errors,
    }


def get_command_file_content(command_id: str, commands_dir: Path = COMMANDS_DIR) -> Optional[str]:
    """
    Get the raw markdown content for a command.

    Useful for editing or displaying the full command definition.
    """
    file_path = commands_dir / f"{command_id}.md"
    if file_path.exists():
        return file_path.read_text(encoding="utf-8")
    return None


def infer_category_from_content(content: str) -> str:
    """
    Infer command category from its content.

    Uses keyword matching to suggest appropriate category.
    """
    content_lower = content.lower()

    category_keywords = {
        "session": ["session", "memory", "save", "checkpoint", "boot", "end"],
        "git": ["git", "push", "commit", "pull", "branch", "merge", "pr"],
        "quality": ["audit", "review", "test", "lint", "check", "verify"],
        "productivity": ["meeting", "prep", "focus", "standup", "retro"],
        "debug": ["debug", "trace", "log", "error", "fix"],
        "build": ["build", "deploy", "compile", "run", "start"],
    }

    scores = {}
    for category, keywords in category_keywords.items():
        scores[category] = sum(1 for kw in keywords if kw in content_lower)

    if scores:
        return max(scores, key=scores.get)

    return "productivity"  # default
