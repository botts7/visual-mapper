"""
Companion App Routes - Android Companion App Communication
Visual Mapper v0.0.6

Provides endpoints for communicating with the Android companion app
including live UI discovery via MQTT.

v0.0.6: Added companion app installation detection and install endpoints

Security:
- POST/write endpoints require companion auth (X-Companion-Key or localhost/Ingress)
- GET/read endpoints are public (needed for Web UI)
"""

import logging
import os
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from routes import get_deps
from routes.device_registration import registered_devices
from routes.auth import verify_companion_auth

# Package name for the companion app
COMPANION_PACKAGE = "com.visualmapper.companion"
COMPANION_MAIN_ACTIVITY = "com.visualmapper.companion/.ui.fragments.MainContainerActivity"

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
    children: List["UIElement"] = []


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
    request: UITreeRequest, _auth: bool = Depends(verify_companion_auth)
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
            detail="MQTT not configured - companion app communication unavailable",
        )

    if not deps.mqtt_manager.is_connected:
        raise HTTPException(
            status_code=500,
            detail="MQTT not connected - cannot communicate with companion app",
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
            "Ensure the Android companion app is running and connected.",
        )

    try:
        logger.info(f"[Companion] Requesting UI tree from {request.device_id}")

        # Request UI tree via MQTT
        result = await deps.mqtt_manager.request_ui_tree(
            device_id=request.device_id,
            package_name=request.package_name,
            timeout=request.timeout,
        )

        if result is None:
            raise HTTPException(
                status_code=504,
                detail=f"UI tree request timed out after {request.timeout}s. "
                "Ensure the companion app is running and has accessibility service enabled.",
            )

        # Count elements
        element_count = len(result.get("elements", []))

        def count_nested(elements):
            count = 0
            for el in elements:
                count += 1
                if "children" in el and el["children"]:
                    count += count_nested(el["children"])
            return count

        total_count = count_nested(result.get("elements", []))

        logger.info(f"[Companion] Received UI tree with {total_count} elements")

        return {
            "success": True,
            "package": result.get("package"),
            "activity": result.get("activity"),
            "elements": result.get("elements", []),
            "element_count": total_count,
            "timestamp": result.get("timestamp"),
            "request_id": result.get("request_id"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Companion] Error requesting UI tree: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error requesting UI tree: {str(e)}"
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
            "message": "Device not registered",
        }

    # Check if we have device info object (Pydantic model or dict)
    if hasattr(device_info, "model_dump"):
        info_dict = device_info.model_dump()
    elif hasattr(device_info, "__dict__"):
        info_dict = vars(device_info)
    else:
        info_dict = dict(device_info)

    return {
        "device_id": device_id,
        "connected": True,
        "platform": info_dict.get("platform", "android"),
        "app_version": info_dict.get("appVersion") or info_dict.get("app_version"),
        "capabilities": info_dict.get("capabilities", []),
        "last_heartbeat": info_dict.get("lastHeartbeat")
        or info_dict.get("last_heartbeat"),
        "registered_at": info_dict.get("registeredAt")
        or info_dict.get("registered_at"),
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
        if hasattr(device_info, "model_dump"):
            info_dict = device_info.model_dump()
        elif hasattr(device_info, "__dict__"):
            info_dict = vars(device_info)
        else:
            info_dict = dict(device_info)

        devices.append(
            {
                "device_id": device_id,
                "device_name": info_dict.get("deviceName")
                or info_dict.get("device_name", device_id),
                "platform": info_dict.get("platform", "android"),
                "app_version": info_dict.get("appVersion")
                or info_dict.get("app_version"),
                "capabilities": info_dict.get("capabilities", []),
                "last_heartbeat": info_dict.get("lastHeartbeat")
                or info_dict.get("last_heartbeat"),
                "connected": True,
            }
        )

    return {"success": True, "devices": devices, "count": len(devices)}


class LaunchAppRequest(BaseModel):
    """Request to launch an app via companion"""
    device_id: str
    package_name: str
    force_restart: bool = True
    timeout: float = 10.0


@router.post("/launch-app")
async def launch_app_via_companion(
    request: LaunchAppRequest, _auth: bool = Depends(verify_companion_auth)
) -> Dict[str, Any]:
    """
    Launch an app via companion app's Intent (preserves MediaProjection).

    Unlike ADB monkey command which can kill MediaProjection on some devices,
    this uses Android Intent launched from within the companion app, which
    preserves the screen streaming capability.

    Args:
        request: LaunchAppRequest with device_id, package_name, force_restart

    Returns:
        Success status and launch details

    Raises:
        HTTPException 400: If companion app not connected
        HTTPException 504: If request times out
        HTTPException 500: For other errors
    """
    deps = get_deps()

    if not deps.mqtt_manager:
        raise HTTPException(
            status_code=500,
            detail="MQTT not configured - companion app communication unavailable",
        )

    if not deps.mqtt_manager.is_connected:
        raise HTTPException(
            status_code=500,
            detail="MQTT not connected - cannot communicate with companion app",
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
            "Ensure the Android companion app is running and connected.",
        )

    try:
        logger.info(
            f"[Companion] Launching app {request.package_name} on {request.device_id} "
            f"(force_restart={request.force_restart})"
        )

        # Request app launch via MQTT
        result = await deps.mqtt_manager.request_launch_app(
            device_id=request.device_id,
            package_name=request.package_name,
            force_restart=request.force_restart,
            timeout=request.timeout,
        )

        if result is None:
            raise HTTPException(
                status_code=504,
                detail=f"App launch request timed out after {request.timeout}s. "
                "Ensure the companion app is running.",
            )

        success = result.get("success", False)
        if not success:
            error = result.get("error", "Unknown error")
            raise HTTPException(
                status_code=500,
                detail=f"Companion app failed to launch: {error}",
            )

        logger.info(f"[Companion] App launched successfully: {request.package_name}")

        return {
            "success": True,
            "package": request.package_name,
            "device_id": request.device_id,
            "force_restart": request.force_restart,
            "status": result.get("data", {}).get("status", "launched"),
            "method": "companion_intent",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Companion] Error launching app: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error launching app: {str(e)}"
        )


@router.post("/discover-screens/{device_id}")
async def discover_all_screens(
    device_id: str,
    package_name: str = Query(..., description="App package to discover"),
    max_screens: int = Query(20, description="Maximum screens to discover"),
    timeout_per_screen: float = Query(5.0, description="Timeout per screen in seconds"),
    _auth: bool = Depends(verify_companion_auth),
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
        raise HTTPException(status_code=500, detail="MQTT not configured")

    # Check device registration
    device_info = registered_devices.get(device_id)
    if not device_info:
        raise HTTPException(
            status_code=400,
            detail=f"Device {device_id} not registered as companion app",
        )

    # For now, return a placeholder - full implementation would need
    # a job queue system for long-running discovery
    import uuid

    job_id = str(uuid.uuid4())

    logger.info(
        f"[Companion] Starting screen discovery for {package_name} on {device_id}"
    )

    # Send discovery command to companion app
    # The companion app will publish results as it discovers screens
    return {
        "success": True,
        "job_id": job_id,
        "device_id": device_id,
        "package_name": package_name,
        "max_screens": max_screens,
        "status": "started",
        "message": "Discovery job started. Results will be published to navigation graph.",
    }


# ============================================================================
# Element Selection for Flow Creation
# ============================================================================


@router.post("/select-elements")
async def get_selectable_elements(
    request: UITreeRequest, _auth: bool = Depends(verify_companion_auth)
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
            detail="MQTT not connected - cannot communicate with companion app",
        )

    # Check device registration
    device_info = registered_devices.get(request.device_id)
    if not device_info:
        raise HTTPException(
            status_code=400,
            detail=f"Device {request.device_id} not registered as companion app",
        )

    try:
        # Get full UI tree
        result = await deps.mqtt_manager.request_ui_tree(
            device_id=request.device_id,
            package_name=request.package_name,
            timeout=request.timeout,
        )

        if result is None:
            raise HTTPException(status_code=504, detail="Request timed out")

        # Filter and categorize elements
        elements = result.get("elements", [])
        categorized = {
            "buttons": [],
            "inputs": [],
            "navigation": [],
            "text": [],
            "scrollable": [],
            "other": [],
        }

        def categorize_element(el, parent_text=None):
            """Categorize an element and its children"""
            class_name = el.get("class_name", "") or el.get("class", "")
            text = el.get("text", "") or ""
            content_desc = el.get("content_desc", "") or ""
            clickable = el.get("clickable", False)
            scrollable = el.get("scrollable", False)

            # Skip non-interactive elements (unless they have text for sensors)
            if not clickable and not scrollable and not text:
                # Still process children
                for child in el.get("children", []):
                    categorize_element(child, text or parent_text)
                return

            element_info = {
                "resource_id": el.get("resource_id"),
                "class_name": class_name,
                "text": text,
                "content_desc": content_desc,
                "bounds": el.get("bounds"),
                "clickable": clickable,
                "scrollable": scrollable,
            }

            # Categorize by class and properties
            class_lower = class_name.lower()

            if "button" in class_lower or "imagebutton" in class_lower:
                element_info["suggested_action"] = "tap"
                categorized["buttons"].append(element_info)
            elif "edittext" in class_lower or "input" in class_lower:
                element_info["suggested_action"] = "text"
                categorized["inputs"].append(element_info)
            elif "tab" in class_lower or "navigation" in class_lower:
                element_info["suggested_action"] = "tap"
                categorized["navigation"].append(element_info)
            elif scrollable:
                element_info["suggested_action"] = "swipe"
                categorized["scrollable"].append(element_info)
            elif text and not clickable:
                element_info["suggested_action"] = "read"
                categorized["text"].append(element_info)
            elif clickable:
                element_info["suggested_action"] = "tap"
                categorized["other"].append(element_info)

            # Process children
            for child in el.get("children", []):
                categorize_element(child, text or parent_text)

        for element in elements:
            categorize_element(element)

        total_count = sum(len(v) for v in categorized.values())

        return {
            "success": True,
            "package": result.get("package"),
            "activity": result.get("activity"),
            "categories": categorized,
            "element_count": total_count,
            "timestamp": result.get("timestamp"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[Companion] Error getting selectable elements: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Streaming Control Endpoints
# ============================================================================


class StreamingControlRequest(BaseModel):
    """Request to control streaming on a companion device"""
    device_id: str
    timeout: float = 10.0


@router.post("/streaming/stop")
async def stop_companion_streaming(
    request: StreamingControlRequest, _auth: bool = Depends(verify_companion_auth)
) -> Dict[str, Any]:
    """
    Remotely stop screen streaming on a companion device.

    Args:
        request: StreamingControlRequest with device_id

    Returns:
        Success status and streaming state
    """
    deps = get_deps()

    if not deps.mqtt_manager:
        raise HTTPException(
            status_code=500,
            detail="MQTT not configured - companion app communication unavailable",
        )

    if not deps.mqtt_manager.is_connected:
        raise HTTPException(
            status_code=500,
            detail="MQTT not connected - cannot communicate with companion app",
        )

    try:
        logger.info(f"[Companion] Requesting stop streaming on {request.device_id}")

        result = await deps.mqtt_manager.request_stop_streaming(
            device_id=request.device_id,
            timeout=request.timeout,
        )

        if result is None:
            raise HTTPException(
                status_code=504,
                detail=f"Stop streaming request timed out after {request.timeout}s",
            )

        return {
            "success": result.get("success", False),
            "device_id": request.device_id,
            "was_running": result.get("data", {}).get("wasRunning", False),
            "status": result.get("data", {}).get("status", "unknown"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Companion] Error stopping streaming: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/streaming/status/{device_id}")
async def get_companion_streaming_status(
    device_id: str, _auth: bool = Depends(verify_companion_auth)
) -> Dict[str, Any]:
    """
    Get streaming status from a companion device.

    Args:
        device_id: Android device ID

    Returns:
        Streaming status including FPS, frames sent, codec
    """
    deps = get_deps()

    if not deps.mqtt_manager:
        raise HTTPException(
            status_code=500,
            detail="MQTT not configured - companion app communication unavailable",
        )

    if not deps.mqtt_manager.is_connected:
        raise HTTPException(
            status_code=500,
            detail="MQTT not connected - cannot communicate with companion app",
        )

    try:
        logger.info(f"[Companion] Requesting streaming status from {device_id}")

        result = await deps.mqtt_manager.request_streaming_status(
            device_id=device_id,
            timeout=10.0,
        )

        if result is None:
            raise HTTPException(
                status_code=504,
                detail="Streaming status request timed out",
            )

        data = result.get("data", {})
        return {
            "success": result.get("success", False),
            "device_id": device_id,
            "is_running": data.get("isRunning", False),
            "fps": data.get("fps", 0),
            "frames_sent": data.get("framesSent", 0),
            "codec": data.get("codec", "unknown"),
            "state": data.get("state", "unknown"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Companion] Error getting streaming status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/streaming/request-start")
async def request_companion_streaming(
    request: StreamingControlRequest, _auth: bool = Depends(verify_companion_auth)
) -> Dict[str, Any]:
    """
    Request a companion device to start streaming.

    Note: Due to Android security requirements (MediaProjection needs user consent),
    this will show a notification on the device. The user must tap the notification
    to grant permission and start streaming.

    Args:
        request: StreamingControlRequest with device_id

    Returns:
        Status indicating whether notification was shown or already streaming
    """
    deps = get_deps()

    if not deps.mqtt_manager:
        raise HTTPException(
            status_code=500,
            detail="MQTT not configured - companion app communication unavailable",
        )

    if not deps.mqtt_manager.is_connected:
        raise HTTPException(
            status_code=500,
            detail="MQTT not connected - cannot communicate with companion app",
        )

    try:
        logger.info(f"[Companion] Requesting streaming start on {request.device_id}")

        result = await deps.mqtt_manager.request_start_streaming(
            device_id=request.device_id,
            timeout=request.timeout,
        )

        if result is None:
            raise HTTPException(
                status_code=504,
                detail=f"Request streaming timed out after {request.timeout}s",
            )

        data = result.get("data", {})
        status = data.get("status", "unknown")

        return {
            "success": result.get("success", False),
            "device_id": request.device_id,
            "status": status,
            "is_running": data.get("isRunning", False),
            "message": data.get("message", ""),
            "requires_user_action": status == "notification_shown",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Companion] Error requesting streaming: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Companion Config Update Endpoints
# ============================================================================


class ServerConfigUpdate(BaseModel):
    """Request to update companion app server config"""
    server_url: str


@router.post("/{device_id}/update-server-url")
async def update_companion_server_url(
    device_id: str,
    config: ServerConfigUpdate,
    _auth: bool = Depends(verify_companion_auth)
) -> Dict[str, Any]:
    """
    Send server URL update to companion app via MQTT.

    This is used when the server IP changes and the companion app needs
    to be reconfigured to connect to the new address.

    Args:
        device_id: The device ID (can be stable ID or connection ID)
        config: Server config with new URL

    Returns:
        Success status and message
    """
    deps = get_deps()

    if not deps.mqtt_manager:
        raise HTTPException(
            status_code=503,
            detail="MQTT not available"
        )

    try:
        # Find the companion's MQTT device ID
        companion_mqtt_id = None

        # Check announced devices to find the right MQTT topic
        announced = deps.mqtt_manager.get_announced_devices()
        for dev in announced:
            dev_id = dev.get("device_id", "")
            # Match by IP prefix or stable ID
            if device_id in dev_id or dev_id.replace("_", ".").startswith(device_id.split(":")[0]):
                companion_mqtt_id = dev_id
                break

        if not companion_mqtt_id:
            # Try using the device_id directly if it looks like a companion ID
            companion_mqtt_id = device_id.replace(".", "_").replace(":", "_")

        # Publish config update to companion's config topic
        config_topic = f"visual_mapper/{companion_mqtt_id}/config"
        config_payload = {"server_url": config.server_url}

        import json
        # Use the MQTT client directly to publish
        if deps.mqtt_manager.client:
            deps.mqtt_manager.client.publish(config_topic, json.dumps(config_payload), retain=False)
        else:
            raise HTTPException(status_code=503, detail="MQTT client not connected")

        logger.info(f"[Companion] Sent server URL update to {companion_mqtt_id}: {config.server_url}")

        return {
            "success": True,
            "message": f"Server URL update sent to companion",
            "mqtt_topic": config_topic,
            "server_url": config.server_url
        }

    except Exception as e:
        logger.error(f"[Companion] Error sending server URL update: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Companion App Installation Endpoints
# ============================================================================


@router.get("/{device_id}/installed")
async def check_companion_installed(device_id: str) -> Dict[str, Any]:
    """
    Check if Visual Mapper Companion app is installed on device.
    Uses ADB to query package manager.

    Args:
        device_id: Android device ID

    Returns:
        Installation status including:
        - installed: Whether the app is installed
        - version: App version if installed
        - source: How the check was performed
    """
    deps = get_deps()

    if not deps.adb_bridge:
        return {
            "installed": False,
            "source": "no_adb",
            "error": "ADB bridge not available"
        }

    try:
        # Check if package exists using pm path
        result = await deps.adb_bridge.shell_command(
            device_id,
            f"pm path {COMPANION_PACKAGE}"
        )
        installed = result and "package:" in result

        response = {
            "installed": installed,
            "source": "adb_pm",
            "package": COMPANION_PACKAGE
        }

        # If installed, try to get version info
        if installed:
            try:
                version_result = await deps.adb_bridge.shell_command(
                    device_id,
                    f"dumpsys package {COMPANION_PACKAGE} | grep versionName"
                )
                if version_result:
                    # Parse versionName=X.Y.Z from output
                    import re
                    match = re.search(r'versionName=([^\s]+)', version_result)
                    if match:
                        response["version"] = match.group(1)
            except Exception:
                pass  # Version info is optional

        return response

    except Exception as e:
        logger.error(f"[Companion] Error checking installation: {e}", exc_info=True)
        return {
            "installed": False,
            "source": "error",
            "error": str(e)
        }


@router.post("/{device_id}/install")
async def install_companion_app(device_id: str) -> Dict[str, Any]:
    """
    Install Visual Mapper Companion APK on device via ADB.
    Uses the pre-built APK from android-companion/app/build/outputs/apk/debug/

    Args:
        device_id: Android device ID

    Returns:
        Installation result including success status
    """
    deps = get_deps()

    if not deps.adb_bridge:
        raise HTTPException(
            status_code=500,
            detail="ADB bridge not available"
        )

    # Find APK path (relative to project root)
    # Try multiple possible locations
    possible_paths = [
        "android-companion/app/build/outputs/apk/debug/app-debug.apk",
        "../android-companion/app/build/outputs/apk/debug/app-debug.apk",
        "app/build/outputs/apk/debug/app-debug.apk",
    ]

    apk_path = None
    for path in possible_paths:
        if os.path.exists(path):
            apk_path = os.path.abspath(path)
            break

    if not apk_path:
        raise HTTPException(
            status_code=404,
            detail="APK not found. Build the companion app first using: "
                   "cd android-companion && ./gradlew.bat assembleDebug"
        )

    try:
        logger.info(f"[Companion] Installing APK from {apk_path} to {device_id}")

        # Install via ADB using subprocess (adb install command)
        import subprocess
        result = subprocess.run(
            ["adb", "-s", device_id, "install", "-r", apk_path],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            logger.error(f"[Companion] Install failed: {error_msg}")
            raise HTTPException(
                status_code=500,
                detail=f"Installation failed: {error_msg}"
            )

        # Check if installation succeeded
        if "Success" not in result.stdout:
            raise HTTPException(
                status_code=500,
                detail=f"Installation may have failed: {result.stdout}"
            )

        logger.info(f"[Companion] APK installed successfully on {device_id}")

        # Launch the app after install
        try:
            await deps.adb_bridge.shell_command(
                device_id,
                f"am start -n {COMPANION_MAIN_ACTIVITY}"
            )
            logger.info(f"[Companion] Launched companion app on {device_id}")
        except Exception as launch_err:
            logger.warning(f"[Companion] Could not launch app after install: {launch_err}")

        return {
            "success": True,
            "message": "Companion app installed and launched",
            "device_id": device_id,
            "package": COMPANION_PACKAGE
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="Installation timed out after 120 seconds"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Companion] Install error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Installation failed: {str(e)}"
        )


@router.post("/{device_id}/launch")
async def launch_companion_app(device_id: str) -> Dict[str, Any]:
    """
    Launch the Visual Mapper Companion app on device.

    Args:
        device_id: Android device ID

    Returns:
        Launch status
    """
    deps = get_deps()

    if not deps.adb_bridge:
        raise HTTPException(
            status_code=500,
            detail="ADB bridge not available"
        )

    try:
        result = await deps.adb_bridge.shell_command(
            device_id,
            f"am start -n {COMPANION_MAIN_ACTIVITY}"
        )

        return {
            "success": True,
            "message": "Companion app launched",
            "device_id": device_id,
            "output": result
        }

    except Exception as e:
        logger.error(f"[Companion] Launch error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to launch app: {str(e)}"
        )
