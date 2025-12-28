"""
Smart Suggestions Routes - AI-Powered Sensor and Action Detection

Provides endpoints for analyzing UI elements and suggesting:
- Home Assistant sensors (battery, temperature, humidity, etc.)
- Home Assistant actions (buttons, switches, input fields, etc.)

Uses pattern detection and AI analysis to identify common sensor/action types.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
from datetime import datetime
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["suggestions"])


# Request models
class SuggestSensorsRequest(BaseModel):
    device_id: str


class SuggestActionsRequest(BaseModel):
    device_id: str


# =============================================================================
# SMART SENSOR SUGGESTIONS
# =============================================================================

@router.post("/suggest-sensors")
async def suggest_sensors(request: SuggestSensorsRequest):
    """
    Analyze current screen and suggest Home Assistant sensors

    Uses AI-powered pattern detection to identify common sensor types
    (battery, temperature, humidity, etc.) from UI elements.
    """
    deps = get_deps()
    try:
        logger.info(f"[API] Analyzing UI elements for sensor suggestions on {request.device_id}")

        # Get UI elements from device
        elements_response = await deps.adb_bridge.get_ui_elements(request.device_id)

        if not elements_response or 'elements' not in elements_response:
            elements = elements_response if isinstance(elements_response, list) else []
        else:
            elements = elements_response['elements']

        # Use sensor suggester to analyze elements
        from utils.sensor_suggester import get_sensor_suggester
        suggester = get_sensor_suggester()
        suggestions = suggester.suggest_sensors(elements)

        logger.info(f"[API] Generated {len(suggestions)} sensor suggestions for {request.device_id}")

        return {
            "success": True,
            "device_id": request.device_id,
            "suggestions": suggestions,
            "count": len(suggestions),
            "timestamp": datetime.now().isoformat()
        }

    except ValueError as e:
        logger.warning(f"[API] Sensor suggestion failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Sensor suggestion error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SMART ACTION SUGGESTIONS
# =============================================================================

@router.post("/suggest-actions")
async def suggest_actions(request: SuggestActionsRequest):
    """
    Analyze current screen and suggest Home Assistant actions

    Uses AI-powered pattern detection to identify actionable UI elements
    (buttons, switches, input fields, etc.) from UI elements.
    """
    deps = get_deps()
    try:
        logger.info(f"[API] Analyzing UI elements for action suggestions on {request.device_id}")

        # Get UI elements from device
        elements_response = await deps.adb_bridge.get_ui_elements(request.device_id)

        if not elements_response or 'elements' not in elements_response:
            elements = elements_response if isinstance(elements_response, list) else []
        else:
            elements = elements_response['elements']

        # Use action suggester to analyze elements
        from utils.action_suggester import get_action_suggester
        suggester = get_action_suggester()
        suggestions = suggester.suggest_actions(elements)

        logger.info(f"[API] Generated {len(suggestions)} action suggestions for {request.device_id}")

        return {
            "success": True,
            "device_id": request.device_id,
            "suggestions": suggestions,
            "count": len(suggestions),
            "timestamp": datetime.now().isoformat()
        }

    except ValueError as e:
        logger.warning(f"[API] Action suggestion failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Action suggestion error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
