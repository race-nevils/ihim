"""
Slash Commands API Module

Provides a comprehensive API for managing the agent harness commands,
including discovery, brainstorming, auto-invoke configuration, and
syncing with the harness/commands/ directory.
"""

from .models import (
    SlashCommand,
    SlashCommandIdea,
    CommandCategory,
    AutoInvokeConfig,
    CommandTrigger,
)
from .scanner import scan_commands_directory, sync_commands
from .routes import router

__all__ = [
    "SlashCommand",
    "SlashCommandIdea",
    "CommandCategory",
    "AutoInvokeConfig",
    "CommandTrigger",
    "scan_commands_directory",
    "sync_commands",
    "router",
]
