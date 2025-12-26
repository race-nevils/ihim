"""
Data models for the Slash Command Center.

Provides structured types for commands, brainstorm ideas,
auto-invoke configuration, and command categories.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class TriggerType(str, Enum):
    """Types of auto-invoke triggers."""
    EVENT = "event"           # Triggered by system events
    SCHEDULE = "schedule"     # Time-based triggers
    CONDITION = "condition"   # Conditional triggers (e.g., file changed)
    HOOK = "hook"             # the agent harness hook integration
    MANUAL = "manual"         # User-invoked only


class CommandStatus(str, Enum):
    """Status of a commands."""
    ACTIVE = "active"         # Fully implemented and available
    BETA = "beta"             # Testing phase
    PLANNED = "planned"       # Designed but not implemented
    DEPRECATED = "deprecated" # Phasing out


class IdeaStatus(str, Enum):
    """Status of a command idea."""
    BRAINSTORM = "brainstorm"   # Initial idea
    DESIGNING = "designing"     # Being fleshed out
    APPROVED = "approved"       # Ready for implementation
    IMPLEMENTED = "implemented" # Now a real command
    REJECTED = "rejected"       # Won't implement


class CommandTrigger(BaseModel):
    """Configuration for an auto-invoke trigger."""
    type: TriggerType = TriggerType.MANUAL
    event: Optional[str] = Field(None, description="Event name (e.g., 'session_end', 'file_saved')")
    condition: Optional[str] = Field(None, description="Condition expression")
    schedule: Optional[str] = Field(None, description="Cron-like schedule")
    hook_name: Optional[str] = Field(None, description="the agent harness hook to integrate with")
    description: str = Field("", description="Human-readable trigger description")


class AutoInvokeConfig(BaseModel):
    """Configuration for automatic command invocation."""
    enabled: bool = False
    triggers: List[CommandTrigger] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100, description="Execution priority (0-100)")
    cooldown_seconds: int = Field(default=0, ge=0, description="Minimum time between invocations")
    requires_confirmation: bool = Field(default=True, description="Ask user before auto-invoking")


class CommandCategory(BaseModel):
    """A category for organizing commands."""
    id: str
    name: str
    description: str
    icon: str = ""
    sort_order: int = 0


class SlashCommand(BaseModel):
    """
    A commands in the command center.

    This is the full representation of a command with all metadata
    needed for the command center UI and auto-invoke system.
    """
    id: str = Field(..., description="Unique identifier (e.g., 'save', 'endsession')")
    name: str = Field(..., description="Display name with slash (e.g., '/save')")
    short_desc: str = Field(..., description="One-line description for lists", alias="shortDesc")
    description: str = Field(..., description="Full description with usage details")
    category: str = Field(..., description="Category ID")
    status: CommandStatus = CommandStatus.ACTIVE

    # Source information
    file_path: Optional[str] = Field(None, description="Path to .md file in harness/commands/")
    source: str = Field("file", description="Where command is defined: 'file', 'builtin', 'skill'")

    # Auto-invoke configuration
    auto_invoke: AutoInvokeConfig = Field(default_factory=AutoInvokeConfig)

    # Usage hints
    usage: str = Field("", description="When/how to use this command")
    examples: List[str] = Field(default_factory=list, description="Example invocations")
    related_commands: List[str] = Field(default_factory=list, description="Related command IDs")

    # Metadata
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        populate_by_name = True


class SlashCommandIdea(BaseModel):
    """
    A brainstorm idea for a potential commands.

    Ideas can be promoted to real commands after design and approval.
    """
    id: str = Field(..., description="Unique identifier")
    name: str = Field(..., description="Proposed command name (e.g., '/focus')")
    description: str = Field(..., description="What this command would do")
    status: IdeaStatus = IdeaStatus.BRAINSTORM

    # Design details (filled in as idea matures)
    proposed_category: Optional[str] = None
    use_cases: List[str] = Field(default_factory=list)
    implementation_notes: str = ""
    priority: int = Field(default=50, ge=0, le=100, description="How important is this?")

    # Auto-invoke potential
    auto_invoke_potential: bool = Field(False, description="Could this be auto-invoked?")
    potential_triggers: List[str] = Field(default_factory=list, description="Possible triggers")

    # Metadata
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    created_by: str = Field(default="user", description="Who proposed this idea")
    votes: int = Field(default=0, description="Upvotes for prioritization")
    notes: List[str] = Field(default_factory=list, description="Discussion notes")


class CommandCenterData(BaseModel):
    """
    Complete commands center data structure.

    This is what gets persisted to slash_commands.json.
    """
    commands: List[SlashCommand] = Field(default_factory=list)
    categories: Dict[str, CommandCategory] = Field(default_factory=dict)
    ideas: List[SlashCommandIdea] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Configuration
    auto_invoke_enabled: bool = Field(default=False, description="Global auto-invoke toggle")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() + "Z" if v else None
        }


# Request/Response models for API

class CreateIdeaRequest(BaseModel):
    """Request to create a new command idea."""
    name: str = Field(..., min_length=2, max_length=50)
    description: str = Field(..., min_length=10, max_length=1000)
    proposed_category: Optional[str] = None
    use_cases: List[str] = Field(default_factory=list)
    auto_invoke_potential: bool = False
    potential_triggers: List[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100)


class UpdateIdeaRequest(BaseModel):
    """Request to update an existing idea."""
    name: Optional[str] = Field(None, min_length=2, max_length=50)
    description: Optional[str] = Field(None, min_length=10, max_length=1000)
    status: Optional[IdeaStatus] = None
    proposed_category: Optional[str] = None
    use_cases: Optional[List[str]] = None
    implementation_notes: Optional[str] = None
    priority: Optional[int] = Field(None, ge=0, le=100)
    auto_invoke_potential: Optional[bool] = None
    potential_triggers: Optional[List[str]] = None


class PromoteIdeaRequest(BaseModel):
    """Request to promote an idea to a real command."""
    category: str
    short_desc: str = Field(..., alias="shortDesc")
    usage: str = ""
    examples: List[str] = Field(default_factory=list)

    class Config:
        populate_by_name = True


class UpdateAutoInvokeRequest(BaseModel):
    """Request to update auto-invoke settings for a command."""
    enabled: bool
    triggers: List[CommandTrigger] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100)
    cooldown_seconds: int = Field(default=0, ge=0)
    requires_confirmation: bool = True


class SyncResultResponse(BaseModel):
    """Response from syncing commands with file system."""
    synced: int
    added: List[str]
    updated: List[str]
    removed: List[str]
    errors: List[str]
