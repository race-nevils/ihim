"""Flight Path routes — project dependency visualizer."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Optional

from api.errors import problem
from api.flightpath.scanner import scan_project, get_directory_graph

router = APIRouter(prefix="/api/flightpath", tags=["flightpath"])

# Known project paths for quick access
KNOWN_PROJECTS = {
    "workspace": Path(__file__).parent.parent.parent.parent,  # C:\Users\<user>\workspace
    "iHIM": Path(__file__).parent.parent.parent,  # C:\Users\<user>\workspace\IHIM
    "<business>": Path(__file__).parent.parent.parent.parent / "<business>",
}


class FlightPathRequest(BaseModel):
    """Request model for Flight Path scan."""
    project_path: Optional[str] = Field(None, description="Full path to project root")
    project_name: Optional[str] = Field(None, description="Known project name (workspace, iHIM, <business>)")
    max_depth: int = Field(default=3, ge=1, le=6, description="Max directory depth to scan")


def _resolve_project(req: FlightPathRequest, request: Request):
    """Resolve project path from request. Returns (Path, None) or (None, problem response)."""
    if req.project_name and req.project_name in KNOWN_PROJECTS:
        return KNOWN_PROJECTS[req.project_name], None
    elif req.project_path:
        return Path(req.project_path), None
    else:
        return None, problem(
            400,
            "Must provide either project_path or project_name",
            instance=request.url.path,
            known_projects=list(KNOWN_PROJECTS.keys()),
        )


def _validate_path(project_path: Path, request: Request):
    """Validate that the path exists and is a directory. Returns problem or None."""
    if not project_path.exists():
        return problem(404, f"Project path does not exist: {project_path}", instance=request.url.path)
    if not project_path.is_dir():
        return problem(400, f"Project path is not a directory: {project_path}", instance=request.url.path)
    return None


@router.get("/projects")
async def list_known_projects():
    """List known projects available for scanning."""
    return {
        "projects": [
            {"name": name, "path": str(path), "exists": path.exists()}
            for name, path in KNOWN_PROJECTS.items()
        ]
    }


@router.post("/scan")
async def scan_project_endpoint(req: FlightPathRequest, request: Request):
    """Scan a project and return the full dependency graph."""
    project_path, err = _resolve_project(req, request)
    if err:
        return err
    if err := _validate_path(project_path, request):
        return err

    try:
        graph = scan_project(str(project_path), req.max_depth)
        return {"success": True, "graph": graph.to_dict()}
    except Exception as e:
        return problem(500, f"Scan failed: {str(e)}", instance=request.url.path)


@router.post("/graph")
async def get_project_graph(req: FlightPathRequest, request: Request):
    """Get a high-level directory graph for visualization."""
    project_path, err = _resolve_project(req, request)
    if err:
        return err
    if err := _validate_path(project_path, request):
        return err

    try:
        graph = get_directory_graph(str(project_path), req.max_depth)
        return {"success": True, "graph": graph}
    except Exception as e:
        return problem(500, f"Graph generation failed: {str(e)}", instance=request.url.path)


@router.get("/graph/{project_name}")
async def get_known_project_graph(project_name: str, request: Request, max_depth: int = 3):
    """Quick access to graph for known projects."""
    if project_name not in KNOWN_PROJECTS:
        return problem(
            404,
            f"Unknown project: {project_name}",
            instance=request.url.path,
            known_projects=list(KNOWN_PROJECTS.keys()),
        )

    project_path = KNOWN_PROJECTS[project_name]
    if not project_path.exists():
        return problem(404, f"Project path does not exist: {project_path}", instance=request.url.path)

    try:
        max_depth = max(1, min(6, max_depth))
        graph = get_directory_graph(str(project_path), max_depth)
        return {"success": True, "graph": graph}
    except Exception as e:
        return problem(500, f"Graph generation failed: {str(e)}", instance=request.url.path)
