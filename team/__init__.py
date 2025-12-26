"""
Team Module - Agent Team Coordination for iHIM

This module handles:
- Smart routing: morphs 1 prompt → 5 tailored prompts
- Spawning: opens 5 CLI tabs in one Windows Terminal window
- State tracking: monitors agent status and results
"""

from .router import route_prompt
from .spawner import spawn_agent_team, collapse_team
from .state import TeamState
from .templates import get_agent_template

__all__ = [
    'route_prompt',
    'spawn_agent_team',
    'collapse_team',
    'TeamState',
    'get_agent_template',
]
