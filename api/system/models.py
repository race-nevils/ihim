"""
Data models for system topology and health monitoring.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime


class HealthStatus(str, Enum):
    """Health status levels for components."""
    HEALTHY = "healthy"      # Green - operational, no errors
    DEGRADED = "degraded"    # Yellow - operational but slow/stale
    ERROR = "error"          # Red - exception, missing, validation failure
    INACTIVE = "inactive"    # Gray - not initialized or dormant


class ComponentType(str, Enum):
    """Types of system components."""
    ROOT = "root"            # iHIM Command Center
    API = "api"              # API endpoints and server
    TEAM = "team"            # Agent team system
    DATA = "data"            # Data stores (JSON files)
    FEEDBACK = "feedback"    # Feedback/learning system
    SANITY = "sanity"        # Validation system
    UI = "ui"                # UI assets
    LEARNING = "learning"    # Self-improvement system (debrief, heuristics)
    GUARD = "guard"          # Guardrails and safety systems


@dataclass
class ComponentNode:
    """A node in the system topology."""
    id: str                              # Unique identifier (e.g., "api-server")
    name: str                            # Display name (e.g., "API Server")
    type: ComponentType                  # Component category
    parent: Optional[str] = None         # Parent node ID
    children: List[str] = field(default_factory=list)  # Child node IDs
    description: str = ""                # What this component does
    file_path: Optional[str] = None      # Associated file/directory path


@dataclass
class ComponentHealth:
    """Health status for a component."""
    id: str                              # Component ID
    status: HealthStatus                 # Current health status
    message: str = ""                    # Status message or error
    last_check: str = ""                 # ISO timestamp of last check
    last_activity: Optional[str] = None  # ISO timestamp of last activity
    metrics: Dict[str, Any] = field(default_factory=dict)  # Component-specific metrics


@dataclass
class SystemEdge:
    """A connection between two components."""
    source: str                          # Source node ID
    target: str                          # Target node ID
    edge_type: str = "dependency"        # "dependency", "data-flow", "parent-child"


@dataclass
class SystemTopology:
    """Complete system topology with nodes and edges."""
    nodes: List[ComponentNode] = field(default_factory=list)
    edges: List[SystemEdge] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "type": n.type.value,
                    "parent": n.parent,
                    "children": n.children,
                    "description": n.description,
                    "file_path": n.file_path,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "type": e.edge_type,
                }
                for e in self.edges
            ],
            "timestamp": self.timestamp,
        }


@dataclass
class SystemHealth:
    """Complete health status for all components."""
    components: List[ComponentHealth] = field(default_factory=list)
    overall_status: HealthStatus = HealthStatus.HEALTHY
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "components": [
                {
                    "id": c.id,
                    "status": c.status.value,
                    "message": c.message,
                    "last_check": c.last_check,
                    "last_activity": c.last_activity,
                    "metrics": c.metrics,
                }
                for c in self.components
            ],
            "overall_status": self.overall_status.value,
            "timestamp": self.timestamp,
        }
