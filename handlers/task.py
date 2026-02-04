"""Task handler: stub that delegates to the brain handler.

Tasks (todos, reminders, appointments) are currently processed through
the brain pipeline, which already handles calendar auto-push for events.
This handler exists so the orchestrator graph can route "task" intents
without crashing.
"""
import logging

logger = logging.getLogger(__name__)


def handle(state):
    """Handle task intent by delegating to the brain handler.

    The brain handler already classifies, stores, and auto-pushes
    calendar events, so task-intent notes get full processing.
    """
    from handlers.brain import handle as brain_handle
    logger.info("Task intent detected, routing through brain handler")
    return brain_handle(state)
