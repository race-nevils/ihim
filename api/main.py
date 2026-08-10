"""iHIM API server — application factory.

Everything here is explicit: routers are imported directly and registered in
one list. The only graceful degradation is for the two audio-hardware modules
(stt, recorder), which need sounddevice/pyaudiowpatch and may legitimately
be absent on a non-Windows or stripped environment. Every other import error
is a real bug and should crash the boot loudly.

Entry point contract (restart commands, startup shim, testing suites):
    uvicorn api.main:app --port <port>   (cwd = IHIM/)
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import runtime
from api.errors import register_exception_handlers
from api.middleware import register_middleware
from api.site import router as site_router
from api.server import router as server_router, start_cpu_sampler, stop_cpu_sampler
from api.preferences import router as preferences_router
from api.todos import router as todos_router
from api.yt.routes import router as yt_router

logger = logging.getLogger(__name__)

# Audio-hardware modules: the only tolerated soft imports.
try:
    from api.stt.routes import router as stt_router
except ImportError as e:  # pragma: no cover - hardware-dependent
    stt_router = None
    logger.warning("STT unavailable (audio deps missing): %s", e)
try:
    from api.recorder.routes import router as recorder_router
except ImportError as e:  # pragma: no cover - hardware-dependent
    recorder_router = None
    logger.warning("Recorder unavailable (audio deps missing): %s", e)

STT_AUTOSTART = os.environ.get("IHIM_STT_AUTOSTART", "1") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime.mark_started()
    _write_pid_file()
    start_cpu_sampler()

    # Recover recordings orphaned by a crash mid-capture
    if recorder_router is not None:
        try:
            from api.recorder.recovery import recover_orphaned_recordings
            recovered = recover_orphaned_recordings(runtime.DATA_DIR / "local" / "recordings")
            if recovered:
                logger.info("Recorder: recovered %d orphaned recording(s)", len(recovered))
        except Exception as e:
            logger.warning("Recorder recovery failed: %s", e)

    # STT dictation engine — global hotkey + GPU model. Env-gated so test
    # instances (e.g. port 7778) never register a second system-wide hotkey
    # or contend for VRAM with the live instance.
    if stt_router is not None and STT_AUTOSTART:
        try:
            from tools.stt.engine import get_engine, verify_restart_task
            from tools.stt.power import register as register_power
            engine = get_engine()
            engine.start_listening()
            register_power(on_suspend=engine.on_system_suspend, on_resume=engine.on_system_resume)
            if verify_restart_task():
                logger.info("STT: hotkey listener + power events registered; restart task verified")
            else:
                logger.warning(
                    "Scheduled task 'iHIM Restart' NOT registered — the "
                    "post-sleep/watchdog self-restart lane is DEAD; run "
                    "IHIM/scripts/install-resume-watchdog.ps1"
                )
        except Exception as e:
            logger.warning("STT autostart failed (non-fatal): %s", e)
    elif stt_router is not None:
        logger.info("STT autostart disabled (IHIM_STT_AUTOSTART=0)")

    yield

    logger.info("Shutdown: cleaning up")
    await stop_cpu_sampler()
    if stt_router is not None and STT_AUTOSTART:
        try:
            from tools.stt.engine import get_engine
            from tools.stt.power import unregister as unregister_power
            get_engine().stop_listening()
            unregister_power()
            logger.info("Shutdown: stt listener + power events stopped")
        except Exception as e:
            logger.warning("Shutdown: stt stop failed: %s", e)
    if recorder_router is not None:
        try:
            from api.recorder.routes import _active_workers
            for rec_id, proc in list(_active_workers.items()):
                try:
                    proc.kill()
                    logger.info("Shutdown: killed transcription worker %s", rec_id)
                except Exception:
                    pass
            _active_workers.clear()
        except Exception as e:
            logger.warning("Shutdown: worker cleanup failed: %s", e)
    try:
        from api.yt.routes import _active_workers as _yt_workers
        for job_id, proc in list(_yt_workers.items()):
            try:
                proc.kill()
                logger.info("Shutdown: killed YT worker %s", job_id)
            except Exception:
                pass
        _yt_workers.clear()
    except Exception as e:
        logger.warning("Shutdown: YT worker cleanup failed: %s", e)
    _remove_pid_file()
    logger.info("Shutdown complete")


def _write_pid_file() -> None:
    try:
        runtime.PID_PATH.parent.mkdir(parents=True, exist_ok=True)
        runtime.PID_PATH.write_text(json.dumps({
            "pid": os.getpid(),
            "port": int(os.environ.get("IHIM_PORT", 0)) or None,
        }), encoding="utf-8")
    except OSError as e:
        logger.warning("Could not write pid file: %s", e)


def _remove_pid_file() -> None:
    try:
        if runtime.PID_PATH.exists():
            data = json.loads(runtime.PID_PATH.read_text(encoding="utf-8"))
            if data.get("pid") == os.getpid():
                runtime.PID_PATH.unlink()
    except (OSError, json.JSONDecodeError):
        pass


def create_app() -> FastAPI:
    app = FastAPI(title="iHIM", description="the operator's command center", lifespan=lifespan)

    origins = [o.strip() for o in os.environ.get(
        "IHIM_CORS_ORIGINS",
        "http://localhost:7777,http://127.0.0.1:7777,http://localhost:7778,http://127.0.0.1:7778",
    ).split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    register_middleware(app)

    routers = [
        site_router, server_router, preferences_router,
        todos_router, yt_router,
    ]
    if stt_router is not None:
        routers.append(stt_router)
    if recorder_router is not None:
        routers.append(recorder_router)
    for r in routers:
        app.include_router(r)

    static_dir = runtime.UI_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
    else:
        logger.warning("Static directory not found: %s", static_dir)

    return app


app = create_app()
