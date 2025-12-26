"""
System topology builder - defines all iHIM components and their connections.
"""

from pathlib import Path
from typing import Optional
from .models import ComponentNode, SystemEdge, SystemTopology, ComponentType


# Base paths
IHIM_ROOT = Path("C:/Users/<user>/workspace/IHIM")


def build_topology() -> SystemTopology:
    """
    Build the complete iHIM system topology.

    Returns a graph of all components and their connections.
    """
    nodes = []
    edges = []

    # =========================================================================
    # ROOT NODE - iHIM Command Center
    # =========================================================================
    nodes.append(ComponentNode(
        id="ihim-root",
        name="iHIM Command Center",
        type=ComponentType.ROOT,
        description="Central control hub for all iHIM systems",
        file_path=str(IHIM_ROOT),
    ))

    # =========================================================================
    # API SYSTEM
    # =========================================================================
    nodes.append(ComponentNode(
        id="api-server",
        name="API Server",
        type=ComponentType.API,
        parent="ihim-root",
        description="FastAPI server handling all HTTP requests",
        file_path=str(IHIM_ROOT / "api" / "main.py"),
    ))

    nodes.append(ComponentNode(
        id="actions-registry",
        name="Actions Registry",
        type=ComponentType.API,
        parent="api-server",
        description="Registry of all available iHIM actions",
        file_path=str(IHIM_ROOT / "actions" / "registry.py"),
    ))

    nodes.append(ComponentNode(
        id="slash-commands",
        name="Slash Commands",
        type=ComponentType.API,
        parent="api-server",
        description="Command center for the agent harness commands",
        file_path=str(IHIM_ROOT / "api" / "commands"),
    ))

    # =========================================================================
    # TEAM SYSTEM
    # =========================================================================
    nodes.append(ComponentNode(
        id="team-system",
        name="Agent Team",
        type=ComponentType.TEAM,
        parent="ihim-root",
        description="5-agent specialist team for feature building",
        file_path=str(IHIM_ROOT / "team"),
    ))

    nodes.append(ComponentNode(
        id="team-spawner",
        name="Spawner",
        type=ComponentType.TEAM,
        parent="team-system",
        description="Spawns the agent harness sessions in Windows Terminal",
        file_path=str(IHIM_ROOT / "team" / "spawner.py"),
    ))

    nodes.append(ComponentNode(
        id="team-router",
        name="Router",
        type=ComponentType.TEAM,
        parent="team-system",
        description="Routes prompts to specialized agents",
        file_path=str(IHIM_ROOT / "team" / "router.py"),
    ))

    nodes.append(ComponentNode(
        id="team-state",
        name="State Manager",
        type=ComponentType.TEAM,
        parent="team-system",
        description="Tracks agent lifecycle and status",
        file_path=str(IHIM_ROOT / "team" / "state.py"),
    ))

    # =========================================================================
    # BLACKBOARD (Agent Coordination)
    # =========================================================================
    nodes.append(ComponentNode(
        id="blackboard",
        name="Blackboard",
        type=ComponentType.DATA,
        parent="ihim-root",
        description="Shared coordination space for agents",
        file_path=str(IHIM_ROOT / "team" / "blackboard.json"),
    ))

    # =========================================================================
    # FEEDBACK SYSTEM
    # =========================================================================
    nodes.append(ComponentNode(
        id="feedback-system",
        name="Feedback System",
        type=ComponentType.FEEDBACK,
        parent="ihim-root",
        description="Self-improvement through agent result analysis",
        file_path=str(IHIM_ROOT / "team" / "feedback"),
    ))

    nodes.append(ComponentNode(
        id="feedback-processor",
        name="Processor",
        type=ComponentType.FEEDBACK,
        parent="feedback-system",
        description="Parses agent result files",
        file_path=str(IHIM_ROOT / "team" / "feedback" / "processor.py"),
    ))

    nodes.append(ComponentNode(
        id="feedback-aggregator",
        name="Aggregator",
        type=ComponentType.FEEDBACK,
        parent="feedback-system",
        description="Combines feedback into session insights",
        file_path=str(IHIM_ROOT / "team" / "feedback" / "aggregator.py"),
    ))

    nodes.append(ComponentNode(
        id="feedback-optimizer",
        name="Optimizer",
        type=ComponentType.FEEDBACK,
        parent="feedback-system",
        description="Generates prompt improvements",
        file_path=str(IHIM_ROOT / "team" / "feedback" / "optimizer.py"),
    ))

    nodes.append(ComponentNode(
        id="feedback-metrics",
        name="Metrics",
        type=ComponentType.FEEDBACK,
        parent="feedback-system",
        description="Tracks improvement trends",
        file_path=str(IHIM_ROOT / "team" / "feedback" / "metrics.py"),
    ))

    # =========================================================================
    # DATA STORES
    # =========================================================================
    nodes.append(ComponentNode(
        id="data-stores",
        name="Data Stores",
        type=ComponentType.DATA,
        parent="ihim-root",
        description="Persistent JSON data files",
        file_path=str(IHIM_ROOT / "data"),
    ))

    nodes.append(ComponentNode(
        id="data-tasks",
        name="Tasks",
        type=ComponentType.DATA,
        parent="data-stores",
        description="Task list data",
        file_path=str(IHIM_ROOT / "data" / "tasks.json"),
    ))

    nodes.append(ComponentNode(
        id="data-notes",
        name="Notes",
        type=ComponentType.DATA,
        parent="data-stores",
        description="Quick notes data",
        file_path=str(IHIM_ROOT / "data" / "notes.json"),
    ))

    nodes.append(ComponentNode(
        id="data-slash-commands",
        name="Slash Commands Data",
        type=ComponentType.DATA,
        parent="data-stores",
        description="Slash command definitions and brainstorm ideas",
        file_path=str(IHIM_ROOT / "data" / "slash_commands.json"),
    ))

    nodes.append(ComponentNode(
        id="data-team-state",
        name="Team State",
        type=ComponentType.DATA,
        parent="data-stores",
        description="Agent team state persistence",
        file_path=str(IHIM_ROOT / "team" / "team_state.json"),
    ))

    # =========================================================================
    # SANITY CHECK
    # =========================================================================
    nodes.append(ComponentNode(
        id="sanity-check",
        name="Sanity Check",
        type=ComponentType.SANITY,
        parent="ihim-root",
        description="System validation and health checks",
        file_path=str(IHIM_ROOT / "sanity" / "check.py"),
    ))

    # =========================================================================
    # UI ASSETS
    # =========================================================================
    nodes.append(ComponentNode(
        id="ui-assets",
        name="UI Assets",
        type=ComponentType.UI,
        parent="ihim-root",
        description="Dashboard HTML and static files",
        file_path=str(IHIM_ROOT / "ui"),
    ))

    nodes.append(ComponentNode(
        id="ui-dashboard",
        name="Dashboard",
        type=ComponentType.UI,
        parent="ui-assets",
        description="Main iHIM dashboard interface",
        file_path=str(IHIM_ROOT / "ui" / "index.html"),
    ))

    nodes.append(ComponentNode(
        id="ui-styles",
        name="Styles",
        type=ComponentType.UI,
        parent="ui-assets",
        description="CSS styling",
        file_path=str(IHIM_ROOT / "ui" / "static" / "style.css"),
    ))

    # =========================================================================
    # EDGES (Connections)
    # =========================================================================

    # Parent-child edges (from parent definitions above)
    for node in nodes:
        if node.parent:
            edges.append(SystemEdge(
                source=node.parent,
                target=node.id,
                edge_type="parent-child",
            ))
            # Also add to parent's children list
            parent_node = next((n for n in nodes if n.id == node.parent), None)
            if parent_node:
                parent_node.children.append(node.id)

    # Data flow edges
    edges.append(SystemEdge(source="api-server", target="actions-registry", edge_type="dependency"))
    edges.append(SystemEdge(source="api-server", target="team-system", edge_type="dependency"))
    edges.append(SystemEdge(source="api-server", target="data-stores", edge_type="data-flow"))
    edges.append(SystemEdge(source="team-spawner", target="blackboard", edge_type="data-flow"))
    edges.append(SystemEdge(source="team-spawner", target="team-state", edge_type="data-flow"))
    edges.append(SystemEdge(source="feedback-processor", target="feedback-aggregator", edge_type="data-flow"))
    edges.append(SystemEdge(source="feedback-aggregator", target="feedback-optimizer", edge_type="data-flow"))
    edges.append(SystemEdge(source="feedback-optimizer", target="team-spawner", edge_type="data-flow"))
    edges.append(SystemEdge(source="sanity-check", target="api-server", edge_type="dependency"))
    edges.append(SystemEdge(source="slash-commands", target="data-slash-commands", edge_type="data-flow"))

    return SystemTopology(nodes=nodes, edges=edges)


# Cached topology (rebuilt on demand)
_cached_topology: Optional[SystemTopology] = None


def get_system_topology(refresh: bool = False) -> SystemTopology:
    """
    Get the system topology, using cache unless refresh is requested.
    """
    global _cached_topology
    if _cached_topology is None or refresh:
        _cached_topology = build_topology()
    return _cached_topology


def get_node_by_id(node_id: str) -> Optional[ComponentNode]:
    """
    Get a specific node by its ID.
    """
    topology = get_system_topology()
    return next((n for n in topology.nodes if n.id == node_id), None)
