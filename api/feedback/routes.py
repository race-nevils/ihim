"""Feedback routes — self-improvement loop for agent teams."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api.errors import problem

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

# Lazy imports — these may not be installed
try:
    from team.feedback.aggregator import aggregate_session, get_session_feedback, save_session_feedback
    from team.feedback.metrics import get_metrics, update_metrics
    from team.feedback.processor import process_session_results, save_feedback_entry
    from team.feedback.optimizer import generate_optimizations, get_optimizations_for_agent

    FEEDBACK_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Feedback system not available: {e}")
    FEEDBACK_AVAILABLE = False


class ProcessFeedbackRequest(BaseModel):
    """Request model for processing session feedback."""
    session_id: str = Field(..., min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
    prompt: str = Field(default="", max_length=5000)


def _check_available(request: Request):
    """Return a problem response if feedback system is not available, else None."""
    if not FEEDBACK_AVAILABLE:
        return problem(503, "Feedback system not available", instance=request.url.path)
    return None


@router.get("/status")
async def feedback_status():
    """Check if feedback system is available."""
    return {
        "available": FEEDBACK_AVAILABLE,
        "message": "Feedback system active" if FEEDBACK_AVAILABLE else "Feedback system not loaded"
    }


@router.get("/session/{session_id}")
async def get_session_feedback_endpoint(session_id: str, request: Request):
    """Get aggregated feedback for a specific spawn session."""
    if err := _check_available(request):
        return err

    feedback = get_session_feedback(session_id)
    if feedback:
        return {"success": True, "feedback": feedback.model_dump(mode="json")}
    return problem(404, f"No feedback found for session {session_id}", instance=request.url.path)


@router.post("/process")
async def process_feedback(req: ProcessFeedbackRequest, request: Request):
    """Process agent results for a session and generate feedback."""
    if err := _check_available(request):
        return err

    try:
        entries = process_session_results(req.session_id)
        for entry in entries:
            save_feedback_entry(entry)

        session_feedback = aggregate_session(req.session_id, req.prompt)
        save_session_feedback(session_feedback)

        metrics = update_metrics(session_feedback)
        optimizations = generate_optimizations(session_feedback)

        return {
            "success": True,
            "session_id": req.session_id,
            "feedback": session_feedback.model_dump(mode="json"),
            "metrics": metrics.model_dump(mode="json"),
            "new_optimizations": len(optimizations)
        }
    except Exception as e:
        return problem(500, str(e), instance=request.url.path)


@router.get("/optimizations")
async def get_optimizations(request: Request):
    """Get all current prompt optimizations."""
    if err := _check_available(request):
        return err

    try:
        from team.feedback.optimizer import load_optimizations
        optimizations = load_optimizations()
        return {
            "count": len(optimizations),
            "optimizations": [opt.model_dump(mode="json") for opt in optimizations]
        }
    except Exception as e:
        return problem(500, str(e), instance=request.url.path)


@router.get("/optimizations/{agent}")
async def get_agent_optimizations(agent: str, request: Request):
    """Get optimizations that apply to a specific agent."""
    if err := _check_available(request):
        return err

    try:
        optimizations = get_optimizations_for_agent(agent)
        return {
            "agent": agent,
            "count": len(optimizations),
            "optimizations": [opt.model_dump(mode="json") for opt in optimizations]
        }
    except Exception as e:
        return problem(500, str(e), instance=request.url.path)
