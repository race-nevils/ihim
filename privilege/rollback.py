"""
Rollback Protection System

Creates checkpoints before risky operations and can restore state if needed.

Triggers:
- Before any L2 operation (manual, but recorded)
- Before L3 request
- After crossing trust threshold
- Daily scheduled

Recovery is always possible within the checkpoint retention period.
"""

import json
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Any
from enum import Enum

from .trust import TRUST_STATE_FILE, load_trust_state, save_trust_state, TrustState


# Checkpoints storage
CHECKPOINTS_DIR = Path(__file__).parent.parent / "data" / "checkpoints"
CHECKPOINTS_INDEX = CHECKPOINTS_DIR / "index.json"

# Retention period for checkpoints
CHECKPOINT_RETENTION_DAYS = 30


class CheckpointTrigger(Enum):
    """What triggered the checkpoint creation."""

    PRE_L2_OPERATION = "pre_l2"         # Before L2 operation
    PRE_ESCALATION = "pre_escalation"   # Before escalation request
    THRESHOLD_CROSSED = "threshold"     # Trust threshold crossed
    SCHEDULED = "scheduled"             # Daily scheduled
    MANUAL = "manual"                   # Manually requested


@dataclass
class Checkpoint:
    """A state checkpoint for rollback capability."""

    id: str
    trigger: str
    description: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    trust_score: float = 0.0
    privilege_level: str = "L0"
    file_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Checkpoint":
        return cls(**data)


def load_checkpoint_index() -> List[Checkpoint]:
    """Load checkpoint index from disk."""
    if CHECKPOINTS_INDEX.exists():
        try:
            data = json.loads(CHECKPOINTS_INDEX.read_text(encoding="utf-8"))
            return [Checkpoint.from_dict(c) for c in data.get("checkpoints", [])]
        except Exception as e:
            print(f"Warning: Failed to load checkpoint index: {e}")
    return []


def save_checkpoint_index(checkpoints: List[Checkpoint]) -> None:
    """Save checkpoint index to disk."""
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "checkpoints": [c.to_dict() for c in checkpoints],
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    CHECKPOINTS_INDEX.write_text(json.dumps(data, indent=2), encoding="utf-8")


def generate_checkpoint_id() -> str:
    """Generate a unique checkpoint ID."""
    import uuid
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"ckpt_{timestamp}_{uuid.uuid4().hex[:6]}"


def create_checkpoint(
    trigger: CheckpointTrigger,
    description: str,
) -> Checkpoint:
    """
    Create a checkpoint of the current privilege state.

    Args:
        trigger: What triggered the checkpoint
        description: Description of why checkpoint was created

    Returns:
        Created Checkpoint
    """
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load current state
    state = load_trust_state()

    # Generate checkpoint
    checkpoint_id = generate_checkpoint_id()
    checkpoint_file = CHECKPOINTS_DIR / f"{checkpoint_id}.json"

    # Save state to checkpoint file
    checkpoint_data = {
        "checkpoint_id": checkpoint_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "trigger": trigger.value,
        "description": description,
        "trust_state": state.to_dict(),
    }

    checkpoint_file.write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")

    # Create checkpoint record
    checkpoint = Checkpoint(
        id=checkpoint_id,
        trigger=trigger.value,
        description=description,
        trust_score=state.current_score,
        privilege_level=state.current_level,
        file_path=str(checkpoint_file),
    )

    # Add to index
    checkpoints = load_checkpoint_index()
    checkpoints.append(checkpoint)
    save_checkpoint_index(checkpoints)

    return checkpoint


def rollback_to_checkpoint(checkpoint_id: str) -> Optional[TrustState]:
    """
    Rollback trust state to a specific checkpoint.

    Args:
        checkpoint_id: ID of checkpoint to restore

    Returns:
        Restored TrustState or None if checkpoint not found
    """
    checkpoints = load_checkpoint_index()

    for checkpoint in checkpoints:
        if checkpoint.id == checkpoint_id:
            if checkpoint.file_path and Path(checkpoint.file_path).exists():
                # Load checkpoint data
                data = json.loads(Path(checkpoint.file_path).read_text(encoding="utf-8"))
                trust_state_data = data.get("trust_state", {})

                # Restore trust state
                restored_state = TrustState.from_dict(trust_state_data)

                # Add rollback event to history
                restored_state.history.append({
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "event_type": "rollback",
                    "level": restored_state.current_level,
                    "operation": f"Rolled back to checkpoint {checkpoint_id}",
                    "delta": 0,
                    "details": checkpoint.description,
                })

                save_trust_state(restored_state)
                return restored_state

            return None

    return None


def get_checkpoint_by_id(checkpoint_id: str) -> Optional[Checkpoint]:
    """Get a specific checkpoint by ID."""
    checkpoints = load_checkpoint_index()
    for checkpoint in checkpoints:
        if checkpoint.id == checkpoint_id:
            return checkpoint
    return None


def list_checkpoints(limit: int = 20) -> List[Checkpoint]:
    """
    List recent checkpoints.

    Args:
        limit: Maximum number of checkpoints to return

    Returns:
        List of recent Checkpoints (newest first)
    """
    checkpoints = load_checkpoint_index()
    # Sort by created_at descending
    checkpoints.sort(key=lambda c: c.created_at, reverse=True)
    return checkpoints[:limit]


def cleanup_old_checkpoints() -> int:
    """
    Remove checkpoints older than retention period.

    Returns:
        Number of checkpoints removed
    """
    checkpoints = load_checkpoint_index()
    cutoff = datetime.utcnow() - timedelta(days=CHECKPOINT_RETENTION_DAYS)

    original_count = len(checkpoints)
    to_keep = []

    for checkpoint in checkpoints:
        created = datetime.fromisoformat(checkpoint.created_at.rstrip("Z"))
        if created > cutoff:
            to_keep.append(checkpoint)
        else:
            # Delete checkpoint file
            if checkpoint.file_path and Path(checkpoint.file_path).exists():
                Path(checkpoint.file_path).unlink()

    save_checkpoint_index(to_keep)
    return original_count - len(to_keep)


def auto_checkpoint_if_needed() -> Optional[Checkpoint]:
    """
    Create automatic checkpoint if conditions are met.

    Called periodically to ensure we have recent checkpoints.

    Returns:
        Created Checkpoint or None if not needed
    """
    checkpoints = load_checkpoint_index()

    if not checkpoints:
        # No checkpoints exist - create initial one
        return create_checkpoint(
            CheckpointTrigger.SCHEDULED,
            "Initial privilege state checkpoint"
        )

    # Check if last checkpoint is older than 24 hours
    latest = max(checkpoints, key=lambda c: c.created_at)
    latest_time = datetime.fromisoformat(latest.created_at.rstrip("Z"))

    if (datetime.utcnow() - latest_time).total_seconds() > 86400:  # 24 hours
        return create_checkpoint(
            CheckpointTrigger.SCHEDULED,
            "Daily scheduled checkpoint"
        )

    return None


def get_rollback_status() -> Dict[str, Any]:
    """
    Get current rollback system status.

    Returns:
        Status dict with checkpoint info
    """
    checkpoints = load_checkpoint_index()

    if not checkpoints:
        return {
            "status": "no_checkpoints",
            "message": "No checkpoints available",
            "checkpoint_count": 0,
            "oldest": None,
            "newest": None,
        }

    checkpoints.sort(key=lambda c: c.created_at)

    return {
        "status": "healthy",
        "checkpoint_count": len(checkpoints),
        "oldest": checkpoints[0].created_at if checkpoints else None,
        "newest": checkpoints[-1].created_at if checkpoints else None,
        "retention_days": CHECKPOINT_RETENTION_DAYS,
    }
