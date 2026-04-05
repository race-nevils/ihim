"""Windows power event registration — pre-sleep GPU cleanup.

Registers for PBT_APMSUSPEND via PowerRegisterSuspendResumeNotification
so we can unload CUDA models BEFORE the NVIDIA driver must power-transition
the GPU.  Without this, active CUDA contexts cause DRIVER_POWER_STATE_FAILURE
(bugcheck 0x9F) during S3 sleep.

The callback fires on a Windows worker thread, so handlers must be
thread-safe (engine.on_system_suspend/resume use thread-safe model locks).
"""

import ctypes
import logging
import sys
from typing import Callable, Optional

logger = logging.getLogger(__name__)

PBT_APMSUSPEND = 4
PBT_APMRESUMESUSPEND = 7
_DEVICE_NOTIFY_CALLBACK = 2

_handle: Optional[ctypes.c_void_p] = None
# prevent garbage collection — pointers must live for process lifetime
_prevent_gc: list = []


def register(on_suspend: Callable, on_resume: Callable) -> bool:
    """Register for system suspend/resume notifications.

    Returns True on success.  No-op on non-Windows.
    Callbacks fire on a worker thread — must be thread-safe.
    """
    global _handle
    if sys.platform != "win32":
        return False
    if _handle is not None:
        return True  # already registered

    try:
        from ctypes import wintypes

        CALLBACK_TYPE = ctypes.WINFUNCTYPE(
            wintypes.ULONG,   # return
            ctypes.c_void_p,  # context
            wintypes.ULONG,   # type (PBT_APMSUSPEND, etc.)
            ctypes.c_void_p,  # setting
        )

        class _SUBSCRIBE_PARAMS(ctypes.Structure):
            _fields_ = [
                ("Callback", CALLBACK_TYPE),
                ("Context", ctypes.c_void_p),
            ]

        def _power_callback(context, event_type, setting):
            try:
                if event_type == PBT_APMSUSPEND:
                    logger.info("PBT_APMSUSPEND received")
                    on_suspend()
                elif event_type == PBT_APMRESUMESUSPEND:
                    logger.info("PBT_APMRESUMESUSPEND received")
                    on_resume()
            except Exception:
                logger.error("Power callback failed", exc_info=True)
            return 0

        cb = CALLBACK_TYPE(_power_callback)
        params = _SUBSCRIBE_PARAMS(Callback=cb, Context=None)
        handle = ctypes.c_void_p()

        result = ctypes.windll.powrprof.PowerRegisterSuspendResumeNotification(
            _DEVICE_NOTIFY_CALLBACK,
            ctypes.byref(params),
            ctypes.byref(handle),
        )
        if result != 0:
            logger.warning(
                "PowerRegisterSuspendResumeNotification failed: %d", result
            )
            return False

        _handle = handle
        _prevent_gc.extend([cb, params])
        logger.info("Registered for system power events (suspend/resume)")
        return True

    except Exception:
        logger.error("Failed to register for power events", exc_info=True)
        return False


def unregister() -> None:
    """Unregister from power notifications."""
    global _handle
    if _handle is not None:
        try:
            ctypes.windll.powrprof.PowerUnregisterSuspendResumeNotification(
                _handle
            )
            logger.info("Unregistered from power events")
        except Exception:
            pass
        _handle = None
        _prevent_gc.clear()
