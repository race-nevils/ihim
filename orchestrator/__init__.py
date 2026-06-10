"""Orchestrator package — state types for the brain ingestion pipeline.

graph.py (the LangGraph wrapper) was removed in the 2026-06 refactor along
with the inbox watcher that invoked it; OrchestratorState remains because
handlers/brain.py types its pipeline dict with it.
"""
from .state import OrchestratorState

__all__ = ["OrchestratorState"]
