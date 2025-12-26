"""
System Module - Real-time topology and health monitoring for iHIM.

Provides:
- System topology (nodes and connections)
- Component health checks
- Live status updates for Flight Path visualization
"""

from .models import ComponentNode, ComponentHealth, SystemTopology, HealthStatus
from .topology import get_system_topology, get_node_by_id
from .health import check_all_health, check_component_health

__all__ = [
    'ComponentNode',
    'ComponentHealth',
    'SystemTopology',
    'HealthStatus',
    'get_system_topology',
    'get_node_by_id',
    'check_all_health',
    'check_component_health',
]
