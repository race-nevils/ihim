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
# Note: Python 3.14 has pydantic v1 compatibility issues with some langfuse versions
_LANGFUSE_AVAILABLE = False
_LANGFUSE_VERSION = None
try:
    # v3.x: observe is on main module, context via get_current_* functions
    from langfuse import observe as _observe
    from langfuse import get_client
    _LANGFUSE_AVAILABLE = True
    _LANGFUSE_VERSION = 3
    logger.info("Langfuse tracing enabled (v3.x)")
except Exception as e:
    # Catch ALL exceptions (not just ImportError) for Python 3.14 pydantic compat issues
    try:
        # v2.x: observe in decorators submodule
        from langfuse.decorators import observe as _observe, langfuse_context as _langfuse_context
        _LANGFUSE_AVAILABLE = True
        _LANGFUSE_VERSION = 2
        logger.info("Langfuse tracing enabled (v2.x)")
    except Exception as e2:
        logger.warning(f"Langfuse not available: {e} / {e2}")
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


class _V3Context:
    """Wrapper for Langfuse v3.x context API."""

    @staticmethod
    def update_current_observation(**kwargs):
        """Update current observation metadata using v3 API."""
        try:
            from langfuse import get_current_span
            span = get_current_span()
            if span:
                # v3.x uses update() method on span
                span.update(**kwargs)
        except Exception:
            pass  # Graceful degradation

    @staticmethod
    @contextmanager
    def span(name: str):
        """Create a tracing span using v3 API."""
        try:
            from langfuse import get_current_span
            parent = get_current_span()
            if parent:
                with parent.span(name=name) as child:
                    yield child
            else:
                yield None
        except Exception:
            yield None


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


# Export the context (version-appropriate or no-op)
if _LANGFUSE_VERSION == 3:
    langfuse_context = _V3Context()
elif _LANGFUSE_VERSION == 2:
    langfuse_context = _langfuse_context
else:
    langfuse_context = _NoOpContext()


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
    if _LANGFUSE_AVAILABLE and langfuse_context:
        with langfuse_context.span(name=name):
            yield
    else:
        yield


def is_tracing_enabled() -> bool:
    """Check if Langfuse tracing is available."""
    return _LANGFUSE_AVAILABLE
