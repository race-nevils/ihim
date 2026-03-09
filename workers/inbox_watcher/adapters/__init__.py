"""Adapter registry for structured content ingestion.

Adapters decompose structured files into individual brain entries.
Registration happens at import time — each adapter module appends itself.
"""
from pathlib import Path
from typing import Optional

from .base import ContentAdapter

_adapters: list[ContentAdapter] = []


def register(adapter: ContentAdapter):
    """Register an adapter instance."""
    _adapters.append(adapter)


def get_adapter(file_path: Path) -> Optional[ContentAdapter]:
    """Find the first adapter that can handle this file."""
    for adapter in _adapters:
        if adapter.can_handle(file_path):
            return adapter
    return None


# Auto-register built-in adapters on import
from .heuristics_adapter import HeuristicsAdapter
from .standards_adapter import StandardsAdapter
from .compliance_adapter import ComplianceAdapter

register(HeuristicsAdapter())
register(StandardsAdapter())
register(ComplianceAdapter())
