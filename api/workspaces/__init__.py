"""
Workspaces API module for iHIM.

Provides endpoints for viewing active git branches and parallel development sessions.
"""

from .routes import router

__all__ = ["router"]
