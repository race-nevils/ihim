"""Compliance & Standards Library routes."""

from fastapi import APIRouter, Request
from pathlib import Path
import json

from api.errors import problem

router = APIRouter(tags=["compliance"])

# Import compliance loader at module level
try:
    from compliance.loader import ComplianceLoader
    compliance_loader = ComplianceLoader()
    COMPLIANCE_AVAILABLE = True
except ImportError:
    try:
        from IHIM.compliance.loader import ComplianceLoader
        compliance_loader = ComplianceLoader()
        COMPLIANCE_AVAILABLE = True
    except ImportError as e:
        print(f"Warning: Compliance system not available: {e}")
        compliance_loader = None
        COMPLIANCE_AVAILABLE = False


def _check_available(request: Request):
    if not COMPLIANCE_AVAILABLE:
        return problem(503, "Compliance system not available", instance=request.url.path)
    return None


@router.get("/api/compliance/modules")
async def get_compliance_modules(request: Request):
    """Get all available compliance modules."""
    if err := _check_available(request):
        return err

    try:
        modules = compliance_loader.load_all_modules()
        modules_list = []
        for module_id, module in modules.items():
            modules_list.append({
                "module_id": module.module_id,
                "name": module.name,
                "version": module.version,
                "category": module.category,
                "enabled": module.enabled,
                "priority": module.priority,
                "controls_count": len(module.controls),
                "description": module.metadata.get("description", "")
            })

        return {"success": True, "count": len(modules_list), "modules": modules_list}
    except Exception as e:
        return problem(500, f"Failed to load modules: {str(e)}", instance=request.url.path)


@router.get("/api/compliance/modules/{module_id}")
async def get_compliance_module_details(module_id: str, request: Request):
    """Get detailed information about a specific compliance module."""
    if err := _check_available(request):
        return err

    try:
        module = compliance_loader.load_module(module_id)
        if not module:
            return problem(404, f"Module '{module_id}' not found", instance=request.url.path)

        controls_list = []
        for control in module.controls:
            controls_list.append({
                "control_id": control.control_id,
                "name": control.name,
                "description": control.description,
                "enforcement_level": control.enforcement_level.value,
                "triggers": control.triggers,
                "rules_count": len(control.rules),
                "evidence_required": control.evidence_required,
                "evidence_retention_days": control.evidence_retention_days
            })

        return {
            "success": True,
            "module": {
                "module_id": module.module_id,
                "name": module.name,
                "version": module.version,
                "category": module.category,
                "enabled": module.enabled,
                "priority": module.priority,
                "controls": controls_list,
                "agent_instructions": module.agent_instructions,
                "guardrail_additions": module.guardrail_additions,
                "metadata": module.metadata
            }
        }
    except Exception as e:
        return problem(500, f"Failed to load module details: {str(e)}", instance=request.url.path)


@router.get("/api/compliance/active")
async def get_active_compliance_modules(request: Request):
    """Get currently active compliance modules."""
    if err := _check_available(request):
        return err

    try:
        active_modules = compliance_loader.load_active_modules()
        modules_list = []
        for module in active_modules:
            modules_list.append({
                "module_id": module.module_id,
                "name": module.name,
                "version": module.version,
                "category": module.category,
                "priority": module.priority,
                "controls_count": len(module.controls),
                "description": module.metadata.get("description", "")
            })

        return {"success": True, "count": len(modules_list), "modules": modules_list}
    except Exception as e:
        return problem(500, f"Failed to load active modules: {str(e)}", instance=request.url.path)


@router.post("/api/compliance/activate/{module_id}")
async def activate_compliance_module(module_id: str, request: Request):
    """Activate a compliance module."""
    if err := _check_available(request):
        return err

    try:
        success = compliance_loader.activate_module(module_id)
        if success:
            return {"success": True, "message": f"Module '{module_id}' activated", "module_id": module_id}
        return problem(404, f"Failed to activate module '{module_id}' - module not found", instance=request.url.path)
    except Exception as e:
        return problem(500, f"Activation failed: {str(e)}", instance=request.url.path)


@router.post("/api/compliance/deactivate/{module_id}")
async def deactivate_compliance_module(module_id: str, request: Request):
    """Deactivate a compliance module."""
    if err := _check_available(request):
        return err

    try:
        success = compliance_loader.deactivate_module(module_id)
        if success:
            return {"success": True, "message": f"Module '{module_id}' deactivated", "module_id": module_id}
        return problem(400, f"Failed to deactivate module '{module_id}'", instance=request.url.path)
    except Exception as e:
        return problem(500, f"Deactivation failed: {str(e)}", instance=request.url.path)


@router.get("/api/compliance/health")
async def compliance_health_check(request: Request):
    """Run health check on the compliance system."""
    if err := _check_available(request):
        return err

    try:
        health = compliance_loader.health_check()
        return {
            "success": True,
            "healthy": health["healthy"],
            "active_modules": health["active_modules"],
            "available_modules": health["available_modules"],
            "errors": health.get("errors", []),
            "warnings": health.get("warnings", [])
        }
    except Exception as e:
        return problem(500, f"Health check failed: {str(e)}", instance=request.url.path)


@router.get("/api/standards/references")
async def get_standards_references(request: Request):
    """Get reference links for standards and frameworks."""
    references_path = Path(__file__).parent.parent.parent / "data" / "standards_library" / "references" / "references.json"
    try:
        if references_path.exists():
            with open(references_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {"success": True, **data}
        else:
            return problem(404, "References file not found", instance=request.url.path)
    except Exception as e:
        return problem(500, str(e), instance=request.url.path)
