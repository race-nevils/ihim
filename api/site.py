"""Dashboard shell serving: root HTML, PWA assets, boot-id cache busting.

Cache-busting model (carried from the proven pre-refactor design):
- BOOT_ID regenerates per server start; an inline importmap rewrites every
  /static/js/*.js import to ?v=BOOT_ID so Chrome's aggressive ES-module cache
  can never serve stale modules.
- /api/boot-id additionally reports a static-file fingerprint (max mtime), so
  the frontend can hot-reload the page when files change on disk without a
  server restart.
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

from api.errors import problem
from api.runtime import BOOT_ID, UI_DIR

router = APIRouter(tags=["site"])

_STATIC_DIR = UI_DIR / "static"
_INDEX_PATH = UI_DIR / "index.html"
_MANIFEST_PATH = UI_DIR / "manifest.json"
_SW_PATH = UI_DIR / "sw.js"


def _build_import_map(boot_id: str) -> str:
    """Importmap remapping every JS module URL to its versioned form."""
    js_dir = _STATIC_DIR / "js"
    if not js_dir.exists():
        return ""
    imports = {}
    for js_file in sorted(js_dir.rglob("*.js")):
        url_path = f"/static/{js_file.relative_to(_STATIC_DIR).as_posix()}"
        imports[url_path] = f"{url_path}?v={boot_id}"
    if not imports:
        return ""
    return f'<script type="importmap">\n{json.dumps({"imports": imports}, indent=2)}\n</script>'


def _static_fingerprint() -> str:
    """Max mtime across ui/ — changes whenever any UI file is edited."""
    max_mtime = 0.0
    if _STATIC_DIR.exists():
        for root, _dirs, files in os.walk(_STATIC_DIR):
            for name in files:
                try:
                    max_mtime = max(max_mtime, os.path.getmtime(os.path.join(root, name)))
                except OSError:
                    pass
    try:
        max_mtime = max(max_mtime, _INDEX_PATH.stat().st_mtime)
    except OSError:
        pass
    return str(int(max_mtime))


@router.get("/")
async def root():
    """Serve the dashboard, reading from disk so HTML edits apply instantly."""
    if not _INDEX_PATH.exists():
        return problem(500, "ui/index.html missing")
    html = _INDEX_PATH.read_text(encoding="utf-8")
    html = html.replace("__IMPORT_MAP__", _build_import_map(BOOT_ID))
    html = html.replace("__BOOT_ID__", BOOT_ID)
    return Response(content=html, media_type="text/html")


@router.get("/api/boot-id")
async def boot_id():
    """Boot ID + static fingerprint; the frontend polls this to self-reload."""
    return {"boot_id": BOOT_ID, "static_fp": _static_fingerprint()}


@router.get("/manifest.json")
async def manifest():
    """W3C Web App Manifest (PWA installability)."""
    if not _MANIFEST_PATH.exists():
        return problem(404, "manifest.json not found")
    return Response(content=_MANIFEST_PATH.read_bytes(), media_type="application/manifest+json")


@router.get("/sw.js")
async def service_worker():
    """Service worker, served from root scope."""
    if not _SW_PATH.exists():
        return problem(404, "sw.js not found")
    return Response(
        content=_SW_PATH.read_bytes(),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )
