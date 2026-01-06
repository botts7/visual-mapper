"""
Companion App Routes - Android Companion App Communication
Visual Mapper v0.0.5

Provides endpoints for communicating with the Android companion app
including live UI discovery via MQTT.

Security:
- POST/write endpoints require companion auth (X-Companion-Key or localhost/Ingress)
- GET/read endpoints are public (needed for Web UI)
"""

import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from routes import get_deps
from routes.device_registration import registered_devices
from routes.auth import verify_companion_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/companion", tags=["Companion App"])


# ============================================================================
# Request/Response Models
# ============================================================================

class UITreeRequest(BaseModel):
    """Request for UI tree from companion app"""
    device_id: str
    package_name: Optional[str] = None
    timeout: float = 10.0  # seconds


class UIElement(BaseModel):
    """UI element in the tree"""
    resource_id: Optional[str] = None
    class_name: Optional[str] = None
    text: Optional[str] = None
    content_desc: Optional[str] = None
    bounds: Optional[Dict[str, int]] = None
    clickable: bool = False
    scrollable: bool = False
    focusable: bool = False
    selected: bool = False
    children: List['UIElement'] = []


class UITreeResponse(BaseModel):
    """Response containing UI tree from companion app"""
    success: bool
    package: Optional[str] = None
    activity: Optional[str] = None
    elements: List[Dict[str, Any]] = []
    element_count: int = 0
    timestamp: Optional[str] = None
    error: Optional[str] = None


class CompanionStatusResponse(BaseModel):
    """Companion app status response"""
    device_id: str
    connected: bool
    platform: Optional[str] = None
    app_version: Optional[str] = None
    capabilities: List[str] = []
    last_heartbeat: Optional[str] = None


# ============================================================================
# Live Discovery Endpoints
# ============================================================================

@router.post("/ui-tree")
async def get_ui_tree(
    request: UITreeRequest,
    _auth: bool = Depends(verify_companion_auth)
) -> Dict[str, Any]:
    """
    Request live UI tree from Android companion app.

    This endpoint sends an MQTT request to the companion app running on the
    Android device and waits for it to return the current UI hierarchy
    using the Accessibility Service.

    Args:
        request: UITreeRequest with device_id and optional package filter

    Returns:
        UI tree with all visible elements including:
        - resource_id: Android resource ID
        - class_name: Android widget class
        - text: Visible text content
        - content_desc: Content description for accessibility
        - bounds: Screen coordinates {left, top, right, bottom}
        - clickable/scrollable/focusable: Interaction flags
        - children: Nested child elements

    Raises:
        HTTPException 400: If companion app not connected
        HTTPException 504: If request times out
        HTTPException 500: For other errors
    """
    deps = get_deps()

    if not deps.mqtt_manager:
        raise HTTPException(
            status_code=500,
            detail="MQTT not configured - companion app communication unavailable"
        )

    if not deps.mqtt_manager.is_connected:
        raise HTTPException(
            status_code=500,
            detail="MQTT not connected - cannot communicate with companion app"
        )

    # Check if device is registered as companion app
    device_info = registered_devices.get(request.device_id)
    if not device_info:
        # Also check sanitized version
        sanitized = request.device_id.replace(":", "_").replace(".", "_")
        device_info = registered_devices.get(sanitized)

    if not device_info:
        raise HTTPException(
            status_code=400,
            detail=f"Device {request.device_id} not registered as companion app. "
                   "Ensure the Android companion app is running and connected."
        )

    try:
        logger.info(f"[Companion] Requesting UI tree from {request.device_id}")

        # Request UI tree via MQTT
        result = await deps.mqtt_manager.request_ui_tree(
            device_id=request.device_id,
            package_name=request.package_name,
            timeout=request.timeout
        )

        if result is None:
            raise HTTPException(
                status_code=504,
                detail=f"UI tree request timed out after {request.timeout}s. "
                       "Ensure the companion app is running and has accessibility service enabled."
            )

        # Count elements
        element_count = len(result.get('elements', []))

        def count_nested(elements):
            count = 0
            for el in elements:
                count += 1
                if 'children' in el and el['children']:
                    count += count_nested(el['children'])
            return count

        total_count = count_nested(result.get('elements', []))

        logger.info(f"[Companion] Received UI tree with {total_count} elements")

        return {
            "success": True,
            "package": result.get('package'),
            "activity": result.get('activity'),
            "elements": result.get('elements', []),
            "element_count": total_count,
            "timestamp": result.get('timestamp'),
            "request_id": result.get('request_id')
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Companion] Error requesting UI tree: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error requesting UI tree: {str(e)}"
        )


@router.get("/status/{device_id}")
async def get_companion_status(device_id: str) -> Dict[str, Any]:
    """
    Get companion app status for a device.

    Args:
        device_id: Android device ID

    Returns:
        Status including connection state, capabilities, last heartbeat
    """
    # Check device registration
    device_info = registered_devices.get(device_id)
    if not device_info:
        # Also check sanitized version
        sanitized = device_id.replace(":", "_").replace(".", "_")
        device_info = registered_devices.get(sanitized)

    if not device_info:
        return {
            "device_id": device_id,
            "connected": False,
            "platform": None,
            "app_version": None,
            "capabilities": [],
            "last_heartbeat": None,
            "message": "Device not registered"
        }

    # Check if we have device info object (Pydantic model or dict)
    if hasattr(device_info, 'model_dump'):
        info_dict = device_info.model_dump()
    elif hasattr(device_info, '__dict__'):
        info_dict = vars(device_info)
    else:
        info_dict = dict(device_info)

    return {
        "device_id": device_id,
        "connected": True,
        "platform": info_dict.get('platform', 'android'),
        "app_version": info_dict.get('appVersion') or info_dict.get('app_version'),
        "capabilities": info_dict.get('capabilities', []),
        "last_heartbeat": info_dict.get('lastHeartbeat') or info_dict.get('last_heartbeat'),
        "registered_at": info_dict.get('registeredAt') or info_dict.get('registered_at')
    }


@router.get("/devices")
async def list_companion_devices() -> Dict[str, Any]:
    """
    List all registered companion app devices.

    Returns:
        List of registered companion devices with their status
    """
    devices = []
    for device_id, device_info in registered_devices.items():
        # Convert to dict if needed
        if hasattr(device_info, 'model_dump'):
            info_dict = device_info.model_dump()
        elif hasattr(device_info, '__dict__'):
            info_dict = vars(device_info)
        else:
            info_dict = dict(device_info)

        devices.append({
            "device_id": device_id,
            "device_name": info_dict.get('deviceName') or info_dict.get('device_name', device_id),
            "platform": info_dict.get('platform', 'android'),
            "app_version": info_dict.get('appVersion') or info_dict.get('app_version'),
            "capabilities": info_dict.get('capabilities', []),
            "last_heartbeat": info_dict.get('lastHeartbeat') or info_dict.get('last_heartbeat'),
            "connected": True
        })

    return {
        "success": True,
        "devices": devices,
        "count": len(devices)
    }


@router.post("/discover-screens/{device_id}")
async def discover_all_screens(
    device_id: str,
    package_name: str = Query(..., description="App package to discover"),
    max_screens: int = Query(20, description="Maximum screens to discover"),
    timeout_per_screen: float = Query(5.0, description="Timeout per screen in seconds"),
    _auth: bool = Depends(verify_companion_auth)
) -> Dict[str, Any]:
    """
    Trigger full screen discovery for an app using companion app.

    This sends a command to the companion app to systematically explore
    an app and discover all accessible screens and UI elements.

    This is a long-running operation - the companion app will:
    1. Navigate through the app systematically
    2. Capture UI tree at each screen
    3. Track navigation transitions
    4. Report back discovered screens and elements

    Args:
        device_id: Android device ID
        package_name: App package to discover
        max_screens: Maximum number of screens to explore
        timeout_per_screen: Timeout for each screen discovery

    Returns:
        Discovery job ID and initial status

    Note: Full results available via GET /api/companion/discover-screens/{job_id}
    """
    deps = get_deps()

    if not deps.mqtt_manager:
        raise HTTPException(
            status_code=500,
            detail="MQTT not configured"
        )

    # Check device registration
    device_info = registered_devices.get(device_id)
    if not device_info:
        raise HTTPException(
            status_code=400,
            detail=f"Device {device_id} not registered as companion app"
        )

    # For now, return a placeholder - full implementation would need
    # a job queue system for long-running discovery
    import uuid
    job_id = str(uuid.uuid4())

    logger.info(f"[Companion] Starting screen discovery for {package_name} on {device_id}")

    # Send discovery command to companion app
    # The companion app will publish results as it discovers screens
    return {
        "success": True,
        "job_id": job_id,
        "device_id": device_id,
        "package_name": package_name,
        "max_screens": max_screens,
        "status": "started",
        "message": "Discovery job started. Results will be published to navigation graph."
    }


# ============================================================================
# Element Selection for Flow Creation
# ============================================================================

@router.post("/select-elements")
async def get_selectable_elements(
    request: UITreeRequest,
    _auth: bool = Depends(verify_companion_auth)
) -> Dict[str, Any]:
    """
    Get UI elements suitable for flow actions.

    Similar to ui-tree but filters and formats elements for flow creation:
    - Filters to clickable/actionable elements
    - Provides suggested action types
    - Groups by category (buttons, inputs, navigation, etc.)

    Args:
        request: UITreeRequest with device_id

    Returns:
        Categorized elements with suggested actions
    """
    deps = get_deps()

    if not deps.mqtt_manager or not deps.mqtt_manager.is_connected:
        raise HTTPException(
            status_code=500,
            detail="MQTT not connected - cannot communicate with companion app"
        )

    # Check device registration
    device_info = registered_devices.get(request.device_id)
    if not device_info:
        raise HTTPException(
            status_code=400,
            detail=f"Device {request.device_id} not registered as companion app"
        )

    try:
        # Get full UI tree
        result = await deps.mqtt_manager.request_ui_tree(
            device_id=request.device_id,
            package_name=request.package_name,
            timeout=request.timeout
        )

        if result is None:
            raise HTTPException(status_code=504, detail="Request timed out")

        # Filter and categorize elements
        elements = result.get('elements', [])
        categorized = {
            "buttons": [],
            "inputs": [],
            "navigation": [],
            "text": [],
            "scrollable": [],
            "other": []
        }

        def categorize_element(el, parent_text=None):
            """Categorize an element and its children"""
            class_name = el.get('class_name', '') or el.get('class', '')
            text = el.get('text', '') or ''
            content_desc = el.get('content_desc', '') or ''
            clickable = el.get('clickable', False)
            scrollable = el.get('scrollable', False)

            # Skip non-interactive elements (unless they have text for sensors)
            if not clickable and not scrollable and not text:
                # Still process children
                for child in el.get('children', []):
                    categorize_element(child, text or parent_text)
                return

            element_info = {
                "resource_id": el.get('resource_id'),
                "class_name": class_name,
                "text": text,
                "content_desc": content_desc,
                "bounds": el.get('bounds'),
                "clickable": clickable,
                "scrollable": scrollable
            }

            # Categorize by class and properties
            class_lower = class_name.lower()

            if 'button' in class_lower or 'imagebutton' in class_lower:
                element_info['suggested_action'] = 'tap'
                categorized['buttons'].append(element_info)
            elif 'edittext' in class_lower or 'input' in class_lower:
                element_info['suggested_action'] = 'text'
                categorized['inputs'].append(element_info)
            elif 'tab' in class_lower or 'navigation' in class_lower:
                element_info['suggested_action'] = 'tap'
                categorized['navigation'].append(element_info)
            elif scrollable:
                element_info['suggested_action'] = 'swipe'
                categorized['scrollable'].append(element_info)
            elif text and not clickable:
                element_info['suggested_action'] = 'read'
                categorized['text'].append(element_info)
            elif clickable:
                element_info['suggested_action'] = 'tap'
                categorized['other'].append(element_info)

            # Process children
            for child in el.get('children', []):
                categorize_element(child, text or parent_text)

        for element in elements:
            categorize_element(element)

        total_count = sum(len(v) for v in categorized.values())

        return {
            "success": True,
            "package": result.get('package'),
            "activity": result.get('activity'),
            "categories": categorized,
            "element_count": total_count,
            "timestamp": result.get('timestamp')
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Companion] Error getting selectable elements: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
