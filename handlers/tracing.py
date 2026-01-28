"""Langfuse tracing integration with graceful degradation.

Provides the @observe decorator and langfuse_context when Langfuse is available.
Falls back to no-op wrappers when Langfuse can't be imported (e.g., Python 3.14).

Usage:
    from handlers.tracing import observe, langfuse_context, TracingSpan

    @observe(name="my_function")
    def my_function():
        with TracingSpan("substep"):
            pass
        langfuse_context.update_current_observation(metadata={"key": "value"})
"""
import logging
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Try to import Langfuse (v3.x API changed)
_LANGFUSE_AVAILABLE = False
try:
    # v3.x: observe is on main module
    from langfuse import observe as _observe
    from langfuse import get_client
    _langfuse_context = None  # v3.x uses different context pattern
    _LANGFUSE_AVAILABLE = True
    logger.info("Langfuse tracing enabled (v3.x)")
except ImportError:
    try:
        # v2.x: observe in decorators submodule
        from langfuse.decorators import observe as _observe, langfuse_context as _langfuse_context
        _LANGFUSE_AVAILABLE = True
        logger.info("Langfuse tracing enabled (v2.x)")
    except Exception as e:
        logger.warning(f"Langfuse not available: {e}")
        _observe = None
        _langfuse_context = None


class _NoOpContext:
    """No-op context for when Langfuse isn't available."""

    @staticmethod
    def update_current_observation(**kwargs):
        """No-op: would update observation metadata."""
        pass

    @staticmethod
    @contextmanager
    def span(name: str):
        """No-op: would create a tracing span."""
        yield


def observe(name: str = None, **kwargs) -> Callable:
    """Decorator for tracing function calls.

    When Langfuse is available, traces the function with the given name.
    When not available, passes through without modification.

    Args:
        name: Name for the trace (defaults to function name)
        **kwargs: Additional Langfuse observe parameters
    """
    def decorator(func: Callable) -> Callable:
        if _LANGFUSE_AVAILABLE:
            return _observe(name=name or func.__name__, **kwargs)(func)

        @wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        return wrapper

    return decorator


# Export the context (real or no-op)
langfuse_context = _langfuse_context if _LANGFUSE_AVAILABLE else _NoOpContext()


@contextmanager
def TracingSpan(name: str):
    """Context manager for creating tracing spans.

    Usage:
        with TracingSpan("my_operation"):
            # traced code here
            pass

    Args:
        name: Name for the span
    """
    if _LANGFUSE_AVAILABLE:
        with langfuse_context.span(name=name):
            yield
    else:
        yield


def is_tracing_enabled() -> bool:
    """Check if Langfuse tracing is available."""
    return _LANGFUSE_AVAILABLE
