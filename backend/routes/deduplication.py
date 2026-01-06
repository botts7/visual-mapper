"""
Deduplication API Routes - Duplicate detection and optimization endpoints.

Provides:
- Check for similar sensors before creation
- Check for similar actions before creation
- Check for overlapping flows
- Get optimization suggestions
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["deduplication"])

# Dependency to get deduplication service
def get_dedup_service():
    from routes import get_deps
    deps = get_deps()
    if not hasattr(deps, 'dedup_service') or deps.dedup_service is None:
        # Create service if not exists
        from services.deduplication_service import DeduplicationService
        deps.dedup_service = DeduplicationService(
            sensor_manager=deps.sensor_manager,
            action_manager=deps.action_manager,
            flow_manager=deps.flow_manager
        )
    return deps.dedup_service


# =============================================================================
# SENSOR SIMILARITY
# =============================================================================

@router.post("/dedup/sensors/check")
async def check_sensor_similarity(
    request: Dict[str, Any],
    service = Depends(get_dedup_service)
):
    """
    Check if a sensor being created is similar to existing sensors.

    Args:
        request: {
            "device_id": str,
            "sensor": {resource_id, bounds, screen_activity, name, ...}
        }

    Returns:
        {
            "has_similar": bool,
            "matches": [SimilarMatch, ...],
            "recommendation": "use_existing" | "create_anyway" | null
        }
    """
    try:
        device_id = request.get("device_id")
        sensor = request.get("sensor", {})

        if not device_id or not sensor:
            raise HTTPException(status_code=400, detail="device_id and sensor required")

        matches = service.find_similar_sensors(device_id, sensor)

        return {
            "has_similar": len(matches) > 0,
            "matches": [m.to_dict() for m in matches],
            "recommendation": matches[0].recommendation.value if matches else None,
            "best_match": matches[0].to_dict() if matches else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Dedup API] Error checking sensor similarity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ACTION SIMILARITY
# =============================================================================

@router.post("/dedup/actions/check")
async def check_action_similarity(
    request: Dict[str, Any],
    service = Depends(get_dedup_service)
):
    """
    Check if an action being created is similar to existing actions.
    """
    try:
        device_id = request.get("device_id")
        action = request.get("action", {})

        if not device_id or not action:
            raise HTTPException(status_code=400, detail="device_id and action required")

        matches = service.find_similar_actions(device_id, action)

        return {
            "has_similar": len(matches) > 0,
            "matches": [m.to_dict() for m in matches],
            "recommendation": matches[0].recommendation.value if matches else None,
            "best_match": matches[0].to_dict() if matches else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Dedup API] Error checking action similarity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# FLOW OVERLAP
# =============================================================================

@router.post("/dedup/flows/check")
async def check_flow_overlap(
    request: Dict[str, Any],
    service = Depends(get_dedup_service)
):
    """
    Check if a flow being created overlaps with existing flows.
    """
    try:
        device_id = request.get("device_id")
        flow = request.get("flow", {})

        if not device_id or not flow:
            raise HTTPException(status_code=400, detail="device_id and flow required")

        matches = service.find_overlapping_flows(device_id, flow)

        return {
            "has_overlapping": len(matches) > 0,
            "matches": [m.to_dict() for m in matches],
            "recommendation": matches[0].recommendation.value if matches else None,
            "overlapping_sensors": list(set(
                sid for m in matches
                for sid in m.details.get("existing_sensors", [])
            )),
            "overlapping_screens": list(set(
                screen for m in matches
                for screen in m.details.get("existing_screens", [])
            ))
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Dedup API] Error checking flow overlap: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# OPTIMIZATION SUGGESTIONS
# =============================================================================

@router.get("/dedup/optimize/{device_id}")
async def get_optimization_suggestions(
    device_id: str,
    service = Depends(get_dedup_service)
):
    """
    Get all optimization suggestions for a device.

    Returns duplicate sensors, actions, and overlapping flows
    that could be consolidated.
    """
    try:
        suggestions = service.get_optimization_suggestions(device_id)
        return suggestions

    except Exception as e:
        logger.error(f"[Dedup API] Error getting optimization suggestions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dedup/stats")
async def get_deduplication_stats(
    service = Depends(get_dedup_service)
):
    """
    Get deduplication service statistics.
    """
    try:
        # Get active sessions
        active_sessions = len(service._sessions)

        return {
            "active_sessions": active_sessions,
            "thresholds": {
                "high_similarity": service.HIGH_SIMILARITY,
                "medium_similarity": service.MEDIUM_SIMILARITY,
                "low_similarity": service.LOW_SIMILARITY
            },
            "bounds_tolerance_px": service.BOUNDS_TOLERANCE
        }

    except Exception as e:
        logger.error(f"[Dedup API] Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
