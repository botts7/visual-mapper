"""
Prerequisites Routes - API endpoints for prerequisite flow management

Endpoints for checking prerequisite status (accessibility, streaming, etc.),
linking flows as prerequisites, and managing auto-run settings.
"""

import logging
import time
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from routes import get_deps
from routes.auth import verify_companion_auth
from core.flows.prerequisite_flows import (
    get_prerequisite_manager,
    PREREQUISITE_TYPES
)
from core.streaming.companion_receiver import companion_stream_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prerequisites", tags=["prerequisites"])


# =============================================================================
# Request/Response Models
# =============================================================================

class LinkFlowRequest(BaseModel):
    flow_id: str


class SetAutoRunRequest(BaseModel):
    enabled: bool


class RunResultRequest(BaseModel):
    success: bool


# =============================================================================
# Status Check Helpers
# =============================================================================

def _extract_ip_from_device_id(device_id: str) -> str:
    """Extract IP address from a device ID like '192.0.2.124:5555'."""
    if ":" in device_id:
        return device_id.split(":")[0]
    return device_id


def _normalize_ip_for_comparison(ip: str) -> str:
    """Convert IP to underscore format for companion ID matching."""
    return ip.replace(".", "_")


def _device_ids_match(adb_device_id: str, companion_device_id: str) -> bool:
    """
    Check if an ADB device ID matches a companion device ID.

    ADB format: 192.0.2.124:5555
    Companion format: 192_0_2_124_5555
    """
    # Extract IP from ADB device ID
    adb_ip = _extract_ip_from_device_id(adb_device_id)
    adb_ip_normalized = _normalize_ip_for_comparison(adb_ip)

    # Check if companion ID starts with the same IP (in underscore format)
    return companion_device_id.startswith(adb_ip_normalized + "_")


async def check_accessibility_operational(deps, device_id: str) -> bool:
    """
    Check if accessibility service is actually responding/operational.

    This is Tier 2 of the 2-tier detection system - verifies the service
    is not just enabled but actually working.
    """
    try:
        # Method 1: Check companion streaming status (if streaming, accessibility works)
        if companion_stream_manager.is_streaming(device_id):
            logger.debug(f"[Prerequisites] {device_id} operational: companion is streaming")
            return True

        # Method 2: Check flow_scheduler capabilities (from MQTT status messages)
        if deps.flow_scheduler:
            caps = deps.flow_scheduler.get_device_capabilities(device_id)
            if caps:
                # Check if accessibility is enabled in the cached status
                if caps.get("accessibility_enabled"):
                    logger.debug(f"[Prerequisites] {device_id} operational: flow_scheduler has accessibility_enabled")
                    return True
                # Check capabilities list
                cap_list = caps.get("capabilities", [])
                if "accessibility" in cap_list or "ui_reading" in cap_list:
                    logger.debug(f"[Prerequisites] {device_id} operational: flow_scheduler has accessibility capability")
                    return True

        # Method 3: Check MQTT manager device capabilities
        if deps.mqtt_manager:
            if hasattr(deps.mqtt_manager, "get_device_capabilities"):
                caps = deps.mqtt_manager.get_device_capabilities(device_id)
                if caps and ("accessibility" in caps or "ui_tree" in caps):
                    logger.debug(f"[Prerequisites] {device_id} operational: mqtt_manager has capabilities")
                    return True

        # Method 4: Check recent MQTT announcement (if companion announced recently, it's operational)
        if deps.mqtt_manager:
            announced = deps.mqtt_manager.get_announced_devices()
            for dev in announced:
                if _device_ids_match(device_id, dev.get("device_id", "")):
                    # Check if announcement is recent (within 60 seconds)
                    ts = dev.get("timestamp", 0)
                    if ts > 0 and (time.time() * 1000 - ts) < 60000:
                        # Also check if capabilities are in announcement
                        caps = dev.get("capabilities", [])
                        if "accessibility" in caps or "ui_tree" in caps:
                            logger.debug(f"[Prerequisites] {device_id} operational: recent announcement with capabilities")
                            return True

        return False
    except Exception as e:
        logger.debug(f"[Prerequisites] Operational check failed for {device_id}: {e}")
        return False


async def check_accessibility_status(deps, device_id: str) -> dict:
    """
    Check if accessibility service is enabled for a device.

    Uses a 2-tier detection system:
    - Tier 1: Check if ENABLED in Android settings (most reliable via ADB)
    - Tier 2: Check if OPERATIONAL (service is actually responding)

    Detection order (most reliable first):
    1. ADB settings check
    2. MQTT announcements with capabilities
    3. FlowScheduler capabilities (from status messages)
    4. Companion streaming status
    """
    result = {
        "enabled": False,
        "fully_operational": False,
        "source": "unknown"
    }

    try:
        # =========================================================================
        # TIER 1: Check if ENABLED in Android settings (most reliable)
        # =========================================================================
        if deps.adb_bridge:
            try:
                # Check if Visual Mapper accessibility service is enabled in Android settings
                accessibility_services = await deps.adb_bridge.shell_command(
                    device_id,
                    "settings get secure enabled_accessibility_services"
                )
                if accessibility_services and "visualmapper" in accessibility_services.lower():
                    result["enabled"] = True
                    result["source"] = "adb_settings"
                    logger.info(f"[Prerequisites] Accessibility ENABLED via ADB for {device_id}")
            except Exception as e:
                logger.debug(f"[Prerequisites] ADB accessibility check failed: {e}")

        # =========================================================================
        # TIER 2: Check if OPERATIONAL (service is responding)
        # =========================================================================
        if result["enabled"]:
            # If enabled via ADB, check if also operational
            operational = await check_accessibility_operational(deps, device_id)
            result["fully_operational"] = operational
            if operational:
                result["source"] = "adb_settings+operational"
                logger.info(f"[Prerequisites] Accessibility OPERATIONAL for {device_id}")

        # =========================================================================
        # FALLBACK: MQTT-based detection (if ADB not available or failed)
        # =========================================================================
        if not result["enabled"] and deps.mqtt_manager:
            # Get capabilities from companion announcements
            announced = deps.mqtt_manager.get_announced_devices()

            # Strategy 1: Match by android_id (most reliable - stable across IP changes)
            for dev in announced:
                android_id = dev.get("android_id")
                if android_id:
                    # Check if this android_id matches our device via companion_receiver
                    companion_id = companion_stream_manager.get_companion_by_android_id(android_id)
                    if companion_id:
                        # Found via android_id - check capabilities
                        capabilities = dev.get("capabilities", [])
                        if "accessibility" in capabilities or "ui_tree" in capabilities:
                            result["enabled"] = True
                            result["fully_operational"] = True
                            result["source"] = "android_id_match"
                            logger.info(f"[Prerequisites] Matched {device_id} via android_id {android_id[:8]}...")
                            return result

            # Strategy 2: Match by IP (handles IP format differences)
            for dev in announced:
                dev_id = dev.get("device_id", "")
                if _device_ids_match(device_id, dev_id):
                    capabilities = dev.get("capabilities", [])
                    if "accessibility" in capabilities or "ui_tree" in capabilities:
                        result["enabled"] = True
                        result["fully_operational"] = True
                        result["source"] = "mqtt_announcement"
                        logger.debug(f"[Prerequisites] Matched {device_id} to companion {dev_id}")
                        return result

            # Strategy 3: Check device capabilities via mqtt_manager
            if hasattr(deps.mqtt_manager, "get_device_capabilities"):
                caps = deps.mqtt_manager.get_device_capabilities(device_id)
                if caps and ("accessibility" in caps or "ui_tree" in caps):
                    result["enabled"] = True
                    result["fully_operational"] = True
                    result["source"] = "device_capabilities"
                    logger.debug(f"[Prerequisites] Matched {device_id} via device capabilities")
                    return result

            # Strategy 4: Check flow_scheduler capabilities (from status messages)
            if deps.flow_scheduler:
                caps = deps.flow_scheduler.get_device_capabilities(device_id)
                if caps:
                    if caps.get("accessibility_enabled") or "accessibility" in caps.get("capabilities", []):
                        result["enabled"] = True
                        result["fully_operational"] = True
                        result["source"] = "flow_scheduler"
                        logger.info(f"[Prerequisites] Found accessibility via flow_scheduler for {device_id}")
                        return result

        # Final fallback: Check if companion is streaming (implies accessibility works)
        if not result["enabled"]:
            if companion_stream_manager.is_streaming(device_id):
                result["enabled"] = True
                result["fully_operational"] = True
                result["source"] = "companion_streaming"
                logger.info(f"[Prerequisites] Accessibility inferred from streaming for {device_id}")

    except Exception as e:
        logger.warning(f"Error checking accessibility status for {device_id}: {e}")

    return result


def check_streaming_status(deps, device_id: str) -> dict:
    """
    Check if screen streaming is active for a device.

    Returns status with separate fields:
    - active: Currently receiving frames
    - permission_granted: Streaming permission was previously granted
    - companion_announced: Companion is announcing via MQTT (on network)
    - companion_connected: Companion is connected via WebSocket (streaming ready)
    - needs_server_update: Companion announced but not connected (server IP may have changed)
    """
    result = {
        "active": False,
        "permission_granted": False,
        "source": None,
        "quality": None,
        "companion_announced": False,
        "companion_connected": False,
        "needs_server_update": False,
        "companion_ip": None
    }

    try:
        # Check if companion is announced via MQTT (on the network)
        if deps.mqtt_manager:
            announced = deps.mqtt_manager.get_announced_devices()
            for dev in announced:
                if _device_ids_match(device_id, dev.get("device_id", "")):
                    result["companion_announced"] = True
                    # Extract companion IP from announcement
                    comp_id = dev.get("device_id", "")
                    if comp_id:
                        # Convert 192_0_2_10_5555 to 192.0.2.10
                        parts = comp_id.replace("_", ".").split(".")
                        if len(parts) >= 4:
                            result["companion_ip"] = ".".join(parts[:4])
                    break

        # Check companion streaming first (preferred)
        if companion_stream_manager.is_streaming(device_id):
            result["active"] = True
            result["permission_granted"] = True
            result["companion_connected"] = True
            result["source"] = "companion"

            # Get additional stats
            stats = companion_stream_manager.get_stats(device_id)
            if stats:
                result["fps"] = stats.get("fps")
                result["frame_count"] = stats.get("frame_count")

            return result

        # Check if companion has WebSocket connection (even if not actively streaming frames)
        if companion_stream_manager.find_companion_for_device(device_id):
            result["companion_connected"] = True

        # Check if companion has ever streamed (permission was granted before)
        # This helps distinguish "permission not granted" from "streaming stopped"
        if hasattr(companion_stream_manager, 'has_ever_streamed'):
            if companion_stream_manager.has_ever_streamed(device_id):
                result["permission_granted"] = True
                result["source"] = "companion_history"

        # Detect server IP change: companion announced via MQTT but not connected via WebSocket
        if result["companion_announced"] and not result["companion_connected"]:
            result["needs_server_update"] = True
            logger.info(f"[Prerequisites] Companion for {device_id} announced via MQTT but not connected - server IP may have changed")

        # Check if ADB streaming is active
        if deps.stream_manager:
            # StreamManager doesn't have is_streaming but we can check
            # if there are active stream sessions
            pass

    except Exception as e:
        logger.warning(f"Error checking streaming status for {device_id}: {e}")

    return result


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("/types")
async def get_prerequisite_types(
    _auth: bool = Depends(verify_companion_auth)
):
    """
    Get all available prerequisite types and their metadata.
    """
    return {
        "success": True,
        "types": PREREQUISITE_TYPES
    }


@router.get("/{device_id}/status")
async def get_prerequisite_status(
    device_id: str,
    _auth: bool = Depends(verify_companion_auth)
):
    """
    Check all prerequisite services for a device.

    Returns status of accessibility, streaming, and any saved
    prerequisite flow configurations.
    """
    deps = get_deps()
    prereq_manager = get_prerequisite_manager(deps.data_dir)

    # Check accessibility status
    accessibility_status = await check_accessibility_status(deps, device_id)

    # Check streaming status
    streaming_status = check_streaming_status(deps, device_id)

    # Get saved prerequisite configs
    prereq_config = prereq_manager.get_all_prerequisites(device_id)

    return {
        "success": True,
        "device_id": device_id,
        "prerequisites": {
            "accessibility": {
                "enabled": accessibility_status.get("enabled", False),
                "fully_operational": accessibility_status.get("fully_operational", False),
                "source": accessibility_status.get("source"),
                "flow_id": prereq_config.get("enable_accessibility", {}).get("flow_id"),
                "auto_run": prereq_config.get("enable_accessibility", {}).get("auto_run", False),
                "last_run": prereq_config.get("enable_accessibility", {}).get("last_run")
            },
            "streaming": {
                "active": streaming_status.get("active", False),
                "permission_granted": streaming_status.get("permission_granted", False),
                "source": streaming_status.get("source"),
                "fps": streaming_status.get("fps"),
                "companion_announced": streaming_status.get("companion_announced", False),
                "companion_connected": streaming_status.get("companion_connected", False),
                "needs_server_update": streaming_status.get("needs_server_update", False),
                "companion_ip": streaming_status.get("companion_ip"),
                "flow_id": prereq_config.get("start_streaming", {}).get("flow_id"),
                "auto_run": prereq_config.get("start_streaming", {}).get("auto_run", False),
                "last_run": prereq_config.get("start_streaming", {}).get("last_run")
            },
            "overlay_permission": {
                "enabled": False,  # TODO: Implement check
                "flow_id": prereq_config.get("grant_overlay_permission", {}).get("flow_id"),
                "auto_run": prereq_config.get("grant_overlay_permission", {}).get("auto_run", False),
                "last_run": prereq_config.get("grant_overlay_permission", {}).get("last_run")
            }
        }
    }


@router.get("/{device_id}/{prereq_type}")
async def get_prerequisite_detail(
    device_id: str,
    prereq_type: str,
    _auth: bool = Depends(verify_companion_auth)
):
    """
    Get detailed info about a specific prerequisite for a device.

    Includes guidance steps for creating the flow.
    """
    if prereq_type not in PREREQUISITE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown prerequisite type: {prereq_type}")

    deps = get_deps()
    prereq_manager = get_prerequisite_manager(deps.data_dir)

    type_info = PREREQUISITE_TYPES[prereq_type]
    config = prereq_manager.get_prerequisite_config(device_id, prereq_type)

    return {
        "success": True,
        "device_id": device_id,
        "prereq_type": prereq_type,
        "name": type_info["name"],
        "description": type_info["description"],
        "guidance_steps": type_info.get("guidance_steps", []),
        "required_by": type_info.get("required_by", []),
        "config": config or {
            "flow_id": None,
            "auto_run": False
        }
    }


@router.post("/{device_id}/{prereq_type}/link-flow")
async def link_prerequisite_flow(
    device_id: str,
    prereq_type: str,
    request: LinkFlowRequest,
    _auth: bool = Depends(verify_companion_auth)
):
    """
    Link an existing flow as a prerequisite flow.

    The linked flow will be available to run when the prerequisite
    is not met.
    """
    if prereq_type not in PREREQUISITE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown prerequisite type: {prereq_type}")

    deps = get_deps()
    prereq_manager = get_prerequisite_manager(deps.data_dir)

    # Verify flow exists
    if deps.flow_manager:
        flow = deps.flow_manager.get_flow(device_id, request.flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow not found: {request.flow_id}")

    success = prereq_manager.link_flow(device_id, prereq_type, request.flow_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to link flow")

    logger.info(f"Linked flow {request.flow_id} to {prereq_type} for {device_id}")

    return {
        "success": True,
        "message": f"Flow linked to {prereq_type}",
        "device_id": device_id,
        "prereq_type": prereq_type,
        "flow_id": request.flow_id
    }


@router.delete("/{device_id}/{prereq_type}/link-flow")
async def unlink_prerequisite_flow(
    device_id: str,
    prereq_type: str,
    _auth: bool = Depends(verify_companion_auth)
):
    """
    Remove the flow link from a prerequisite.
    """
    if prereq_type not in PREREQUISITE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown prerequisite type: {prereq_type}")

    deps = get_deps()
    prereq_manager = get_prerequisite_manager(deps.data_dir)

    success = prereq_manager.unlink_flow(device_id, prereq_type)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to unlink flow")

    return {
        "success": True,
        "message": f"Flow unlinked from {prereq_type}",
        "device_id": device_id,
        "prereq_type": prereq_type
    }


@router.post("/{device_id}/{prereq_type}/set-auto-run")
async def set_prerequisite_auto_run(
    device_id: str,
    prereq_type: str,
    request: SetAutoRunRequest,
    _auth: bool = Depends(verify_companion_auth)
):
    """
    Enable or disable auto-run for a prerequisite.

    When auto_run is enabled, the linked flow will automatically
    run when entering a feature that requires this prerequisite.
    """
    if prereq_type not in PREREQUISITE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown prerequisite type: {prereq_type}")

    deps = get_deps()
    prereq_manager = get_prerequisite_manager(deps.data_dir)

    success = prereq_manager.set_auto_run(device_id, prereq_type, request.enabled)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to set auto-run")

    logger.info(f"Set auto_run={request.enabled} for {prereq_type} on {device_id}")

    return {
        "success": True,
        "message": f"Auto-run {'enabled' if request.enabled else 'disabled'} for {prereq_type}",
        "device_id": device_id,
        "prereq_type": prereq_type,
        "auto_run": request.enabled
    }


@router.post("/{device_id}/{prereq_type}/record-run")
async def record_prerequisite_run(
    device_id: str,
    prereq_type: str,
    request: RunResultRequest,
    _auth: bool = Depends(verify_companion_auth)
):
    """
    Record that a prerequisite flow was run.

    Used to track success/failure counts and last run time.
    """
    if prereq_type not in PREREQUISITE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown prerequisite type: {prereq_type}")

    deps = get_deps()
    prereq_manager = get_prerequisite_manager(deps.data_dir)

    success = prereq_manager.record_run(device_id, prereq_type, request.success)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to record run")

    return {
        "success": True,
        "message": f"Recorded {'successful' if request.success else 'failed'} run for {prereq_type}",
        "device_id": device_id,
        "prereq_type": prereq_type
    }


@router.get("/{device_id}/{prereq_type}/guidance")
async def get_prerequisite_guidance(
    device_id: str,
    prereq_type: str,
    _auth: bool = Depends(verify_companion_auth)
):
    """
    Get guidance steps for creating a prerequisite flow.

    These steps can be shown to the user while they record
    the prerequisite flow.
    """
    if prereq_type not in PREREQUISITE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown prerequisite type: {prereq_type}")

    deps = get_deps()
    prereq_manager = get_prerequisite_manager(deps.data_dir)

    type_info = PREREQUISITE_TYPES[prereq_type]

    return {
        "success": True,
        "prereq_type": prereq_type,
        "name": type_info["name"],
        "description": type_info["description"],
        "steps": type_info.get("guidance_steps", [])
    }
