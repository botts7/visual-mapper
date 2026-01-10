"""
ML Training API Routes

Provides endpoints for:
- Viewing ML training status
- Exporting trained Q-table/model
- Resetting learning data
- Viewing training statistics
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ml", tags=["ml"])

# Data directory (same as ml_training_server.py)
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))


class MLStatus(BaseModel):
    """ML Training status response"""
    enabled: bool
    mode: str  # disabled, local, remote
    training_active: bool
    q_table_exists: bool
    q_table_size: int
    q_table_path: str
    last_updated: Optional[str]
    remote_host: Optional[str]


class MLStats(BaseModel):
    """ML Training statistics"""
    total_states: int
    total_actions: int
    total_updates: int
    avg_q_value: float
    max_q_value: float
    min_q_value: float
    exploration_rate: float
    last_training_time: Optional[str]


def get_q_table_path() -> Path:
    """Get the Q-table file path"""
    # Check multiple possible locations
    paths = [
        DATA_DIR / "ml" / "exploration_q_table.json",
        DATA_DIR / "exploration_q_table.json",
        Path("/config/visual_mapper/ml/exploration_q_table.json"),
        Path("/config/visual_mapper/exploration_q_table.json"),
    ]
    for path in paths:
        if path.exists():
            return path
    # Return default path even if doesn't exist
    return DATA_DIR / "ml" / "exploration_q_table.json"


def load_q_table() -> dict:
    """Load Q-table from file"""
    path = get_q_table_path()
    if not path.exists():
        return {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load Q-table: {e}")
        return {}


@router.get("/status")
async def get_ml_status() -> MLStatus:
    """Get current ML training status"""
    mode = os.getenv("ML_TRAINING_MODE", "disabled")
    remote_host = os.getenv("ML_REMOTE_HOST", "")

    q_table_path = get_q_table_path()
    q_table_exists = q_table_path.exists()

    q_table_size = 0
    last_updated = None

    if q_table_exists:
        try:
            q_table_size = q_table_path.stat().st_size
            mtime = q_table_path.stat().st_mtime
            last_updated = datetime.fromtimestamp(mtime).isoformat()
        except Exception as e:
            logger.error(f"Error reading Q-table stats: {e}")

    return MLStatus(
        enabled=mode != "disabled",
        mode=mode,
        training_active=mode == "local",  # TODO: Check actual training thread
        q_table_exists=q_table_exists,
        q_table_size=q_table_size,
        q_table_path=str(q_table_path),
        last_updated=last_updated,
        remote_host=remote_host if mode == "remote" else None
    )


@router.get("/stats")
async def get_ml_stats() -> MLStats:
    """Get ML training statistics"""
    q_table = load_q_table()

    if not q_table:
        return MLStats(
            total_states=0,
            total_actions=0,
            total_updates=0,
            avg_q_value=0.0,
            max_q_value=0.0,
            min_q_value=0.0,
            exploration_rate=1.0,
            last_training_time=None
        )

    # Parse Q-table structure
    # Format: {"state_hash": {"action": q_value, ...}, ...}
    total_states = len(q_table.get("q_values", {}))
    total_actions = 0
    all_q_values = []

    q_values = q_table.get("q_values", {})
    for state, actions in q_values.items():
        if isinstance(actions, dict):
            total_actions += len(actions)
            all_q_values.extend(actions.values())

    avg_q = sum(all_q_values) / len(all_q_values) if all_q_values else 0.0
    max_q = max(all_q_values) if all_q_values else 0.0
    min_q = min(all_q_values) if all_q_values else 0.0

    # Get metadata
    metadata = q_table.get("metadata", {})
    exploration_rate = metadata.get("epsilon", 1.0)
    total_updates = metadata.get("total_updates", 0)
    last_training = metadata.get("last_training_time")

    return MLStats(
        total_states=total_states,
        total_actions=total_actions,
        total_updates=total_updates,
        avg_q_value=round(avg_q, 4),
        max_q_value=round(max_q, 4),
        min_q_value=round(min_q, 4),
        exploration_rate=round(exploration_rate, 4),
        last_training_time=last_training
    )


@router.get("/export")
async def export_q_table():
    """Export Q-table as downloadable JSON file"""
    q_table_path = get_q_table_path()

    if not q_table_path.exists():
        raise HTTPException(status_code=404, detail="No Q-table found. Start ML training first.")

    # Return as downloadable file
    return FileResponse(
        path=str(q_table_path),
        filename=f"visual_mapper_q_table_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        media_type="application/json"
    )


@router.get("/export/json")
async def export_q_table_json():
    """Export Q-table as JSON response (for API consumption)"""
    q_table = load_q_table()

    if not q_table:
        raise HTTPException(status_code=404, detail="No Q-table found. Start ML training first.")

    return JSONResponse(content=q_table)


@router.post("/reset")
async def reset_ml_data():
    """Reset/clear all ML learning data"""
    q_table_path = get_q_table_path()

    deleted_files = []
    errors = []

    # Delete Q-table
    if q_table_path.exists():
        try:
            # Create backup first
            backup_path = q_table_path.with_suffix('.json.bak')
            q_table_path.rename(backup_path)
            deleted_files.append(str(q_table_path))
            logger.info(f"Backed up Q-table to {backup_path}")
        except Exception as e:
            errors.append(f"Failed to reset Q-table: {e}")

    # Also check for model files
    model_patterns = ["*_model.pt", "*.onnx", "*.tflite"]
    ml_dir = q_table_path.parent

    for pattern in model_patterns:
        for model_file in ml_dir.glob(pattern):
            try:
                backup = model_file.with_suffix(model_file.suffix + '.bak')
                model_file.rename(backup)
                deleted_files.append(str(model_file))
            except Exception as e:
                errors.append(f"Failed to reset {model_file}: {e}")

    if errors:
        return JSONResponse(
            status_code=207,  # Multi-Status
            content={
                "success": len(deleted_files) > 0,
                "deleted": deleted_files,
                "errors": errors,
                "message": "Partial reset - some files could not be deleted"
            }
        )

    return {
        "success": True,
        "deleted": deleted_files,
        "message": "ML data reset successfully. Backups created with .bak extension."
    }


@router.post("/import")
async def import_q_table(q_table_data: dict):
    """Import Q-table from JSON data"""
    q_table_path = get_q_table_path()

    # Ensure directory exists
    q_table_path.parent.mkdir(parents=True, exist_ok=True)

    # Backup existing if present
    if q_table_path.exists():
        backup_path = q_table_path.with_suffix('.json.bak')
        q_table_path.rename(backup_path)
        logger.info(f"Backed up existing Q-table to {backup_path}")

    # Write new Q-table
    try:
        with open(q_table_path, 'w') as f:
            json.dump(q_table_data, f, indent=2)

        return {
            "success": True,
            "path": str(q_table_path),
            "size": q_table_path.stat().st_size,
            "message": "Q-table imported successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to import Q-table: {e}")
