"""
Smart Suggestions Routes - AI-Powered Sensor and Action Detection

Provides endpoints for analyzing UI elements and suggesting:
- Home Assistant sensors (battery, temperature, humidity, etc.)
- Home Assistant actions (buttons, switches, input fields, etc.)

Uses pattern detection and AI analysis to identify common sensor/action types.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging
from datetime import datetime
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(tags=["suggestions"])


# Request models
class SuggestSensorsRequest(BaseModel):
    device_id: Optional[str] = None
    package_name: Optional[str] = None


class SuggestActionsRequest(BaseModel):
    device_id: Optional[str] = None
    package_name: Optional[str] = None


# =============================================================================
# SMART SENSOR SUGGESTIONS
# =============================================================================


@router.get("/api/devices/suggest-sensors")
@router.post("/api/devices/suggest-sensors")
@router.get("/api/suggestions/sensors")
@router.post("/api/suggestions/sensors")
async def suggest_sensors(
    request: Optional[SuggestSensorsRequest] = None, device_id: Optional[str] = None
):
    """
    Analyze current screen and suggest Home Assistant sensors.
    Supports both GET (with query param) and POST (with body).
    """
    deps = get_deps()
    try:
        did = device_id or (request.device_id if request else None)
        if not did:
            raise HTTPException(status_code=400, detail="device_id is required")

        logger.info(f"[API] Analyzing UI elements for sensor suggestions on {did}")

        # Get UI elements from device
        elements_response = await deps.adb_bridge.get_ui_elements(did)

        if not elements_response or "elements" not in elements_response:
            elements = elements_response if isinstance(elements_response, list) else []
        else:
            elements = elements_response["elements"]

        # Use sensor suggester to analyze elements
        from utils.sensor_suggester import get_sensor_suggester

        suggester = get_sensor_suggester()
        suggestions = suggester.suggest_sensors(elements)

        logger.info(f"[API] Generated {len(suggestions)} sensor suggestions for {did}")

        return {
            "success": True,
            "device_id": did,
            "suggestions": suggestions,
            "count": len(suggestions),
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"[API] Sensor suggestion failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Sensor suggestion error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SMART ACTION SUGGESTIONS
# =============================================================================


@router.get("/api/devices/suggest-actions")
@router.post("/api/devices/suggest-actions")
@router.get("/api/suggestions/actions")
@router.post("/api/suggestions/actions")
async def suggest_actions(
    request: Optional[SuggestActionsRequest] = None, device_id: Optional[str] = None
):
    """
    Analyze current screen and suggest Home Assistant actions.
    Supports both GET and POST.
    """
    deps = get_deps()
    try:
        did = device_id or (request.device_id if request else None)
        if not did:
            raise HTTPException(status_code=400, detail="device_id is required")

        logger.info(f"[API] Analyzing UI elements for action suggestions on {did}")

        # Get UI elements from device
        elements_response = await deps.adb_bridge.get_ui_elements(did)

        if not elements_response or "elements" not in elements_response:
            elements = elements_response if isinstance(elements_response, list) else []
        else:
            elements = elements_response["elements"]

        # Use action suggester to analyze elements
        from utils.action_suggester import get_action_suggester

        suggester = get_action_suggester()
        suggestions = suggester.suggest_actions(elements)

        logger.info(f"[API] Generated {len(suggestions)} action suggestions for {did}")

        return {
            "success": True,
            "device_id": did,
            "suggestions": suggestions,
            "count": len(suggestions),
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"[API] Action suggestion failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Action suggestion error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
