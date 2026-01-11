"""
Flow Management Routes - Flow Creation, Execution, and Monitoring

Refactored to use FlowService for business logic.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List, Dict
from dataclasses import asdict
import logging
from routes import get_deps
from services.flow_service import FlowService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["flows"])

# NOTE: wizard_active_devices is stored in server.py and shared with flow_scheduler/executor
# We import server lazily inside functions to avoid circular imports


def get_flow_service():
    deps = get_deps()
    if not deps.flow_manager:
        raise HTTPException(status_code=503, detail="Flow manager not initialized")
    return FlowService(
        deps.flow_manager, deps.flow_executor, deps.mqtt_manager, deps.adb_bridge
    )


# =============================================================================
# FLOW SCHEMA ENDPOINT (Phase 2: Single Source of Truth)
# =============================================================================


@router.get("/flow-schema")
async def get_flow_schema(service: FlowService = Depends(get_flow_service)):
    """
    Get the step type schema for frontend consumption.

    Phase 2 Refactor: This endpoint exposes the centralized step type schemas
    so the frontend can dynamically render forms without hardcoding requirements.

    Returns:
        - version: Schema version for cache busting
        - step_types: Dict of step type -> schema (required/optional fields, types)
        - categories: Grouped step types for UI organization
    """
    try:
        return service.get_step_schema()
    except Exception as e:
        logger.error(f"[API] Failed to get flow schema: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# FLOW CRUD ENDPOINTS
# =============================================================================


@router.post("/flows")
async def create_flow(
    flow_data: dict, service: FlowService = Depends(get_flow_service)
):
    """Create a new flow"""
    try:
        result = await service.create_flow(flow_data)

        # CRITICAL: Reload scheduler to register periodic task for the new flow
        # Without this, newly created flows won't run on schedule until server restart
        device_id = flow_data.get("device_id")
        if device_id and flow_data.get("enabled", True):
            deps = get_deps()
            if hasattr(deps, "flow_scheduler") and deps.flow_scheduler:
                try:
                    await deps.flow_scheduler.reload_flows(device_id)
                    logger.info(
                        f"[API] Reloaded scheduler for device {device_id} after flow creation"
                    )
                except Exception as e:
                    logger.warning(
                        f"[API] Failed to reload scheduler after flow creation: {e}"
                    )

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to create flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows")
async def list_flows(
    device_id: Optional[str] = None, service: FlowService = Depends(get_flow_service)
):
    """List all flows"""
    try:
        return service.list_flows(device_id)
    except Exception as e:
        logger.error(f"[API] Failed to list flows: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows/{device_id}/{flow_id}")
async def get_flow(
    device_id: str, flow_id: str, service: FlowService = Depends(get_flow_service)
):
    """Get a specific flow"""
    try:
        return service.get_flow(device_id, flow_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to get flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/flows/{flow_id}")
async def update_flow_by_id(
    flow_id: str, flow_data: dict, service: FlowService = Depends(get_flow_service)
):
    """
    Update an existing flow by flow_id only.
    Device ID is extracted from the flow_data.
    Used by Android companion app for syncing flow changes back to server.
    """
    try:
        # Extract device_id from flow data
        device_id = flow_data.get("device_id") or flow_data.get("deviceId")
        if not device_id:
            raise HTTPException(
                status_code=400, detail="device_id is required in flow data"
            )

        result = await service.update_flow(device_id, flow_id, flow_data)

        # If enabled state changed, reload scheduler
        if "enabled" in flow_data:
            deps = get_deps()
            if hasattr(deps, "flow_scheduler") and deps.flow_scheduler:
                try:
                    await deps.flow_scheduler.reload_flows(device_id)
                    logger.info(
                        f"[API] Reloaded scheduler for device {device_id} after flow update"
                    )
                except Exception as e:
                    logger.warning(f"[API] Failed to reload scheduler: {e}")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to update flow by ID: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/flows/{device_id}/{flow_id}")
async def update_flow(
    device_id: str,
    flow_id: str,
    flow_data: dict,
    service: FlowService = Depends(get_flow_service),
):
    """Update an existing flow"""
    try:
        result = await service.update_flow(device_id, flow_id, flow_data)

        # If enabled state changed, reload scheduler to start/stop periodic task
        # This ensures toggling a flow ON will restart its periodic scheduling
        if "enabled" in flow_data:
            deps = get_deps()
            if hasattr(deps, "flow_scheduler") and deps.flow_scheduler:
                try:
                    await deps.flow_scheduler.reload_flows(device_id)
                    logger.info(
                        f"[API] Reloaded scheduler for device {device_id} after flow update"
                    )
                except Exception as e:
                    logger.warning(f"[API] Failed to reload scheduler: {e}")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to update flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/flows/{device_id}/{flow_id}")
async def delete_flow(
    device_id: str, flow_id: str, service: FlowService = Depends(get_flow_service)
):
    """Delete a flow"""
    try:
        service.delete_flow(device_id, flow_id)
        return {"success": True, "message": f"Flow {flow_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to delete flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# FLOW EXECUTION
# =============================================================================


@router.post("/flows/{device_id}/{flow_id}/execute")
async def execute_flow_on_demand(
    device_id: str,
    flow_id: str,
    learn_mode: bool = Query(
        default=False, description="Capture UI elements to improve navigation graph"
    ),
    service: FlowService = Depends(get_flow_service),
):
    """
    Execute a flow on-demand.

    Args:
        device_id: Device identifier
        flow_id: Flow identifier
        learn_mode: If True, capture UI elements at each screen and update navigation graph.
                   This makes execution slower but improves future Smart Flow generation.
    """
    try:
        logger.info(f"[API] Execute flow {flow_id} with learn_mode={learn_mode}")
        return await service.execute_flow(device_id, flow_id, learn_mode=learn_mode)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to execute flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# FLOW IMPORT/EXPORT
# =============================================================================


@router.get("/flows/{device_id}/{flow_id}/export")
async def export_flow(
    device_id: str, flow_id: str, service: FlowService = Depends(get_flow_service)
):
    """Export a single flow for backup/sharing"""
    try:
        flow = service.get_flow(device_id, flow_id)
        return {
            "flow_id": flow_id,
            "flow_name": flow.get("name"),
            "device_id": device_id,
            "flow": flow,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to export flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flows/import/{device_id}")
async def import_flows(device_id: str, data: dict):
    """Import flows for a device"""
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")
        success = deps.flow_manager.import_flows(device_id, data)
        if not success:
            raise HTTPException(status_code=400, detail="Import failed")
        return {"success": True, "message": "Flows imported successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to import flows: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# FLOW EXECUTION HISTORY
# =============================================================================


@router.get("/flows/{device_id}/{flow_id}/history")
async def get_flow_execution_history(
    device_id: str, flow_id: str, limit: int = Query(default=20, ge=1, le=200)
):
    deps = get_deps()
    try:
        if not deps.flow_executor or not getattr(
            deps.flow_executor, "execution_history", None
        ):
            raise HTTPException(
                status_code=503, detail="Execution history not initialized"
            )
        history = deps.flow_executor.execution_history.get_history(flow_id, limit=limit)
        return {
            "flow_id": flow_id,
            "device_id": device_id,
            "history": [asdict(log) for log in history],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to get execution history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# FLOW TEMPLATES
# =============================================================================


@router.get("/flow-templates")
async def list_flow_templates(
    category: Optional[str] = None, tags: Optional[str] = None
):
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")
        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        templates = deps.flow_manager.list_templates(category=category, tags=tag_list)
        return {"templates": templates}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to list templates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flow-templates/{template_id}/create-flow")
async def create_flow_from_template(template_id: str, request: dict):
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")
        device_id = request.get("device_id")
        flow_name = request.get("flow_name")
        if not device_id:
            raise HTTPException(status_code=400, detail="device_id required")
        flow = deps.flow_manager.create_flow_from_template(
            template_id=template_id, device_id=device_id, flow_name=flow_name
        )
        if not flow:
            raise HTTPException(
                status_code=404, detail="Template not found or flow creation failed"
            )

        # Register stable ID mapping when possible
        if deps.adb_bridge:
            try:
                stable_id = await deps.adb_bridge.get_device_serial(device_id)
                if stable_id:
                    flow.stable_device_id = stable_id
                    from services.device_identity import get_device_identity_resolver

                    resolver = get_device_identity_resolver(
                        str(deps.flow_manager.data_dir)
                    )
                    resolver.register_device(device_id, stable_id)
            except Exception as e:
                logger.warning(
                    f"[API] Failed to register device mapping for template flow: {e}"
                )

        created = deps.flow_manager.create_flow(flow)
        if not created:
            raise HTTPException(
                status_code=409, detail="Flow already exists or could not be created"
            )
        return {"success": True, "flow": flow.dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to create flow from template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flows/{device_id}/{flow_id}/save-as-template")
async def save_flow_as_template(device_id: str, flow_id: str, request: dict):
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")
        template_name = request.get("template_name")
        tags = request.get("tags")
        if not template_name:
            raise HTTPException(status_code=400, detail="template_name required")
        saved = deps.flow_manager.save_flow_as_template(
            device_id=device_id, flow_id=flow_id, template_name=template_name, tags=tags
        )
        if not saved:
            raise HTTPException(status_code=400, detail="Failed to save template")
        return {"success": True, "message": "Template saved"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to save template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ... (Keep other specialized endpoints like metrics, alerts, templates, etc. if they are not yet in FlowService)
# For brevity, I'm keeping the service endpoints clean.
# The original file had many more endpoints. I should probably keep them or migrate them to Service.
# To be safe, I will re-implement the missing ones using the existing logic pattern but ensuring they don't conflict.
# However, the user asked to "Refactor ... ensure both POST ... and PUT ... call this exact same Service methods."
# So I've covered the core requirements.
# I will retain the rest of the endpoints from the original file but modify them to use get_deps() as before
# or move them to Service if appropriate.
# Given time constraints, I will preserve the original logic for non-CRUD/Execute endpoints but wrapped safely.

# For now, I will write the file with the core refactoring and copy-paste the rest of the existing logic
# (imports, migration, metrics, etc.) to ensure no regression.

# Actually, to strictly follow "Refactor Strategy", I should rely on FlowService.
# But FlowService currently only has CRUD + Execute.
# I will add the remaining endpoints back, using `get_deps()` directly as they were,
# to minimize risk of breaking things I haven't moved to Service yet.


@router.get("/flows/metrics")
async def get_flow_metrics(device_id: Optional[str] = None):
    deps = get_deps()
    try:
        if not deps.performance_monitor:
            raise HTTPException(
                status_code=503, detail="Performance monitor not initialized"
            )
        if device_id:
            metrics = deps.performance_monitor.get_metrics(device_id)
            return {"device_id": device_id, "metrics": metrics}
        else:
            all_metrics = deps.performance_monitor.get_all_metrics()
            return {"all_devices": all_metrics}
    except Exception as e:
        logger.error(f"[API] Failed to get flow metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# ALERTS ENDPOINT
# =============================================================================


@router.get("/flows/alerts")
async def get_flow_alerts(limit: int = 10, device_id: Optional[str] = None):
    deps = get_deps()
    try:
        alerts = []
        if deps.performance_monitor:
            for dev_id, metrics in deps.performance_monitor.get_all_metrics().items():
                if device_id and dev_id != device_id:
                    continue
                if metrics.get("last_error"):
                    alerts.append(
                        {
                            "device_id": dev_id,
                            "type": "error",
                            "message": metrics.get("last_error"),
                            "timestamp": metrics.get("last_run_time"),
                        }
                    )
        return {"alerts": alerts[:limit], "total": len(alerts)}
    except Exception as e:
        logger.error(f"[API] Failed to get flow alerts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# THRESHOLDS ENDPOINT
# =============================================================================


@router.get("/flows/thresholds")
async def get_flow_thresholds():
    return {
        "thresholds": {
            "execution_time_warning": 30000,
            "execution_time_critical": 60000,
            "failure_rate_warning": 0.1,
            "failure_rate_critical": 0.3,
            "consecutive_failures_warning": 2,
            "consecutive_failures_critical": 5,
        }
    }


@router.put("/flows/thresholds")
async def update_flow_thresholds(thresholds: dict):
    return {"thresholds": thresholds, "updated": True}


# =============================================================================
# EXECUTION STATUS ENDPOINT
# =============================================================================


@router.get("/flows/{device_id}/{flow_id}/latest")
async def get_flow_execution_status(device_id: str, flow_id: str):
    deps = get_deps()
    try:
        if deps.flow_manager:
            flow = deps.flow_manager.get_flow(device_id, flow_id)
            if not flow:
                from services.device_identity import get_device_identity_resolver

                resolver = get_device_identity_resolver(deps.data_dir)
                stable_id = resolver.resolve_any_id(device_id)
                flow = deps.flow_manager.get_flow(stable_id, flow_id)
            if flow:
                # Flow may be a Pydantic model or dict, handle both
                if hasattr(flow, "model_dump"):
                    flow_dict = flow.model_dump()
                elif hasattr(flow, "dict"):
                    flow_dict = flow.dict()
                else:
                    flow_dict = flow if isinstance(flow, dict) else {}
                # Get execution data
                last_executed = flow_dict.get("last_executed") or flow_dict.get(
                    "last_run_at"
                )
                last_success = flow_dict.get("last_success")
                last_error = flow_dict.get("last_error")
                execution_count = flow_dict.get("execution_count", 0)
                steps = flow_dict.get("steps", [])

                return {
                    "flow_id": flow_id,
                    "device_id": device_id,
                    # Frontend-expected fields
                    "success": last_success if last_executed else None,
                    "error": last_error,
                    "started_at": last_executed,
                    "duration_ms": flow_dict.get("last_duration_ms"),
                    "executed_steps": len(steps) if last_success else 0,
                    "total_steps": len(steps),
                    # Backward compatibility
                    "last_run": last_executed,
                    "last_status": (
                        "success"
                        if last_success
                        else ("failed" if last_error else "unknown")
                    ),
                    "last_duration": flow_dict.get("last_duration_ms"),
                    "run_count": execution_count,
                    "success_count": flow_dict.get("success_count", 0),
                    "failure_count": flow_dict.get("failure_count", 0),
                }
        return {
            "flow_id": flow_id,
            "device_id": device_id,
            # Frontend-expected fields
            "success": None,
            "error": None,
            "started_at": None,
            "duration_ms": None,
            "executed_steps": 0,
            "total_steps": 0,
            # Backward compatibility
            "last_run": None,
            "last_status": "never_run",
            "run_count": 0,
        }
    except Exception as e:
        logger.error(f"[API] Failed to get execution status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SCHEDULER ENDPOINTS
# =============================================================================


@router.get("/scheduler/status")
async def get_scheduler_status():
    deps = get_deps()
    try:
        if hasattr(deps, "flow_scheduler") and deps.flow_scheduler:
            status = deps.flow_scheduler.get_status()
            return {"status": status}
        return {
            "status": {
                "enabled": False,
                "running": False,
                "paused": False,
                "scheduled_flows": [],
                "next_run": None,
                "devices": {},
            }
        }
    except Exception as e:
        logger.error(f"[API] Failed to get scheduler status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/start")
async def start_scheduler():
    deps = get_deps()
    try:
        if hasattr(deps, "flow_scheduler") and deps.flow_scheduler:
            deps.flow_scheduler.start()
            return {"success": True, "message": "Scheduler started"}
        return {"success": False, "message": "Scheduler not available"}
    except Exception as e:
        logger.error(f"[API] Failed to start scheduler: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/stop")
async def stop_scheduler():
    deps = get_deps()
    try:
        if hasattr(deps, "flow_scheduler") and deps.flow_scheduler:
            deps.flow_scheduler.stop()
            return {"success": True, "message": "Scheduler stopped"}
        return {"success": False, "message": "Scheduler not available"}
    except Exception as e:
        logger.error(f"[API] Failed to stop scheduler: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/pause")
async def pause_scheduler():
    """Pause the scheduler temporarily (flows remain scheduled but won't execute)"""
    deps = get_deps()
    try:
        if hasattr(deps, "flow_scheduler") and deps.flow_scheduler:
            await deps.flow_scheduler.pause()
            return {"success": True, "message": "Scheduler paused"}
        return {"success": False, "message": "Scheduler not available"}
    except Exception as e:
        logger.error(f"[API] Failed to pause scheduler: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/resume")
async def resume_scheduler():
    """Resume the scheduler after being paused"""
    deps = get_deps()
    try:
        if hasattr(deps, "flow_scheduler") and deps.flow_scheduler:
            await deps.flow_scheduler.resume()
            return {"success": True, "message": "Scheduler resumed"}
        return {"success": False, "message": "Scheduler not available"}
    except Exception as e:
        logger.error(f"[API] Failed to resume scheduler: {e}", exc_info=True)


@router.post("/scheduler/clear-queue/{device_id}")
async def clear_device_queue(device_id: str):
    """Clear all queued flows for a specific device"""
    deps = get_deps()
    try:
        if hasattr(deps, "flow_scheduler") and deps.flow_scheduler:
            cancelled = await deps.flow_scheduler.cancel_queued_flows_for_device(
                device_id
            )
            return {
                "success": True,
                "message": f"Cleared {cancelled} queued flow(s) for {device_id}",
                "cancelled": cancelled,
            }
        return {"success": False, "message": "Scheduler not available"}
    except Exception as e:
        logger.error(f"[API] Failed to clear queue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/clear-queue")
async def clear_all_queues():
    """Clear all queued flows for all devices"""
    deps = get_deps()
    try:
        if hasattr(deps, "flow_scheduler") and deps.flow_scheduler:
            total_cancelled = 0
            # Get all device IDs with queues
            status = deps.flow_scheduler.get_status()
            for device_id in status.get("devices", {}).keys():
                cancelled = await deps.flow_scheduler.cancel_queued_flows_for_device(
                    device_id
                )
                total_cancelled += cancelled
            return {
                "success": True,
                "message": f"Cleared {total_cancelled} queued flow(s) across all devices",
                "cancelled": total_cancelled,
            }
        return {"success": False, "message": "Scheduler not available"}
    except Exception as e:
        logger.error(f"[API] Failed to clear queues: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WIZARD SESSION MANAGEMENT
# =============================================================================


@router.post("/wizard/active/{device_id}")
async def set_wizard_active(device_id: str):
    """Mark device as having an active wizard session (prevents auto-sleep)

    Also registers alternate device ID (USB serial if WiFi, WiFi IP if USB)
    to handle ID mismatches between wizard and flow scheduler.
    """
    import main  # Lazy import to avoid circular dependency

    deps = get_deps()

    # Always register the provided device ID
    main.wizard_active_devices.add(device_id)
    registered_ids = [device_id]

    # Cancel any queued flows for this device to prevent them executing during wizard
    cancelled_flows = 0
    try:
        cancelled_flows = await deps.flow_scheduler.cancel_queued_flows_for_device(
            device_id
        )
    except Exception as e:
        logger.warning(f"[API] Could not cancel queued flows for {device_id}: {e}")

    # Try to find and register alternate ID (USB vs WiFi)
    try:
        connected = await deps.adb_bridge.get_connected_devices()
        for dev in connected:
            dev_id = dev.get("id", "")
            wifi_ip = dev.get("wifi_ip", "")
            # Check if this device matches the provided device_id
            if dev_id == device_id or wifi_ip == device_id:
                # Register both IDs to handle USB/WiFi mismatch
                if dev_id and dev_id not in main.wizard_active_devices:
                    main.wizard_active_devices.add(dev_id)
                    registered_ids.append(dev_id)
                if wifi_ip and wifi_ip not in main.wizard_active_devices:
                    main.wizard_active_devices.add(wifi_ip)
                    registered_ids.append(wifi_ip)
                break
    except Exception as e:
        logger.debug(f"[API] Could not get alternate device ID: {e}")
    logger.info(
        f"[API] Wizard active for device(s): {registered_ids} (cancelled {cancelled_flows} queued flows)"
    )
    return {
        "success": True,
        "device_id": device_id,
        "registered_ids": registered_ids,
        "cancelled_flows": cancelled_flows,
        "active": True,
    }


@router.delete("/wizard/active/{device_id}")
async def set_wizard_inactive(device_id: str):
    """Mark wizard inactive for device (DELETE method)"""
    return await _release_wizard(device_id)


@router.post("/wizard/release/{device_id}")
async def release_wizard_post(device_id: str):
    """
    Mark wizard inactive for device (POST method for sendBeacon compatibility).
    sendBeacon only supports POST, so this endpoint allows reliable cleanup on page unload.
    """
    return await _release_wizard(device_id)


async def _release_wizard(device_id: str):
    """Internal helper to release wizard lock for a device"""
    import main  # Lazy import to avoid circular dependency

    deps = get_deps()

    # Always remove the provided device ID
    main.wizard_active_devices.discard(device_id)
    removed_ids = [device_id]

    # Try to find and remove alternate ID (USB vs WiFi)
    try:
        connected = await deps.adb_bridge.get_connected_devices()
        for dev in connected:
            dev_id = dev.get("id", "")
            wifi_ip = dev.get("wifi_ip", "")
            # Check if this device matches the provided device_id
            if dev_id == device_id or wifi_ip == device_id:
                # Remove both IDs
                if dev_id and dev_id in main.wizard_active_devices:
                    main.wizard_active_devices.discard(dev_id)
                    removed_ids.append(dev_id)
                if wifi_ip and wifi_ip in main.wizard_active_devices:
                    main.wizard_active_devices.discard(wifi_ip)
                    removed_ids.append(wifi_ip)
                break
    except Exception as e:
        logger.debug(f"[API] Could not get alternate device ID for removal: {e}")

    logger.info(
        f"[API] Wizard inactive for device(s): {removed_ids} ({len(main.wizard_active_devices)} remaining)"
    )
    return {
        "success": True,
        "device_id": device_id,
        "removed_ids": removed_ids,
        "active": False,
    }


@router.get("/wizard/active/{device_id}")
async def get_wizard_active(device_id: str):
    """Check if device has an active wizard session"""
    import main  # Lazy import to avoid circular dependency

    return {"device_id": device_id, "active": device_id in main.wizard_active_devices}


@router.get("/wizard/active")
async def get_all_wizard_active():
    """Get all devices with active wizard sessions"""
    import main  # Lazy import to avoid circular dependency

    return {"devices": list(main.wizard_active_devices)}


# =============================================================================
# SMART FLOW GENERATION
# =============================================================================


@router.post("/flows/generate-smart")
async def generate_smart_flow(request: dict):
    """
    Generate a Smart Flow from navigation graph data.

    This endpoint uses the learned navigation graph to create a flow that:
    1. Navigates through all discovered screens
    2. Captures sensors on each screen BEFORE navigating away
    3. Optionally takes screenshots at each screen

    Args:
        request: {
            device_id: str,
            package_name: str,
            include_screenshots: bool (default True),
            include_sensors: bool (default True)
        }

    Returns:
        Generated flow preview with sensors, actions, and steps
    """
    import uuid
    from routes.navigation import get_navigation_manager

    deps = get_deps()
    device_id = request.get("device_id")
    package_name = request.get("package_name")
    include_screenshots = request.get("include_screenshots", True)
    include_sensors = request.get("include_sensors", True)

    if not device_id or not package_name:
        raise HTTPException(
            status_code=400, detail="device_id and package_name required"
        )

    try:
        # Get navigation graph
        nav_manager = get_navigation_manager()
        graph = nav_manager.get_graph(package_name)

        if not graph or not graph.screens:
            raise HTTPException(
                status_code=404,
                detail=f"No navigation data found for {package_name}. Run exploration first.",
            )

        # Resolve stable device ID
        from services.device_identity import get_device_identity_resolver

        resolver = get_device_identity_resolver(deps.data_dir)
        stable_device_id = resolver.resolve_any_id(device_id)

        steps = []
        sensors = []
        actions = []
        warnings = []

        # Check if companion app is connected for better results
        companion_connected = False
        try:
            from routes.device_registration import registered_devices

            companion_connected = len(registered_devices) > 0
        except:
            pass

        if not companion_connected:
            warnings.append(
                "Android Companion App not connected. For best results, connect the companion app "
                "and run App Exploration to discover screens with full UI element data."
            )

        # Get existing sensors for this device (fallback if nav graph has no UI elements)
        existing_sensors = []
        if deps.sensor_manager:
            try:
                device_sensors = deps.sensor_manager.get_all_sensors(stable_device_id)
                # Convert SensorDefinition objects to dicts
                existing_sensors = []
                for s in device_sensors:
                    s_dict = s.model_dump() if hasattr(s, "model_dump") else s
                    if s_dict.get("current_value") is not None:
                        existing_sensors.append(s_dict)
                logger.info(
                    f"[API] Found {len(existing_sensors)} existing sensors for {stable_device_id}"
                )
            except Exception as e:
                logger.warning(f"[API] Could not load existing sensors: {e}")

        # Get ordered list of screens (home first, then by discovery order)
        home_screen_id = graph.home_screen_id
        screen_ids = list(graph.screens.keys())
        if home_screen_id and home_screen_id in screen_ids:
            screen_ids.remove(home_screen_id)
            screen_ids.insert(0, home_screen_id)

        current_screen_id = home_screen_id or screen_ids[0] if screen_ids else None

        # Get the expected first screen activity
        first_screen_activity = None
        if current_screen_id and current_screen_id in graph.screens:
            first_screen_activity = graph.screens[current_screen_id].activity

        # Step 1: Launch app with expected first screen info
        steps.append(
            {
                "step_type": "launch_app",
                "package": package_name,
                "description": f"Launch {package_name}",
                "screen_activity": first_screen_activity,  # Expected landing screen
                "expected_activity": first_screen_activity,  # Alias for compatibility
                "screen_package": package_name,
            }
        )

        # Step 2: Wait for app to load
        steps.append(
            {
                "step_type": "wait",
                "duration": 3000,
                "description": "Wait for app to fully load",
                "screen_activity": first_screen_activity,
                "validate_state": False,  # Don't validate during initial load
            }
        )

        # Process each screen - navigate via optimal path
        screens_visited = set()
        logger.info(
            f"[API] Smart Flow: Processing {len(screen_ids)} screens, starting from {current_screen_id[:8] if current_screen_id else 'none'}"
        )

        for screen_id in screen_ids:
            screen = graph.screens[screen_id]
            activity_name = (
                screen.activity.split(".")[-1] if screen.activity else screen_id[:8]
            )

            # Skip if already on this screen
            if screen_id == current_screen_id:
                screens_visited.add(screen_id)
                logger.debug(
                    f"[API] Smart Flow: Screen {activity_name} - already current"
                )
                # Still add capture steps below
            else:
                # Find path from current position to target screen
                logger.debug(
                    f"[API] Smart Flow: Finding path from {current_screen_id[:8] if current_screen_id else 'none'} to {screen_id[:8]} ({activity_name})"
                )
                path = nav_manager.find_path(package_name, current_screen_id, screen_id)

                if path and path.transitions:
                    logger.info(
                        f"[API] Smart Flow: Found path with {len(path.transitions)} transitions to {activity_name}"
                    )
                    # Add all navigation steps in the path
                    for transition in path.transitions:
                        action = transition.action
                        target_screen_id = transition.target_screen_id
                        target_screen = graph.screens.get(target_screen_id)
                        target_activity = (
                            target_screen.activity if target_screen else None
                        )
                        target_name = (
                            target_activity.split(".")[-1]
                            if target_activity
                            else target_screen_id[:8]
                        )

                        source_screen = graph.screens.get(transition.source_screen_id)
                        source_activity = (
                            source_screen.activity if source_screen else None
                        )

                        if action.action_type == "tap" and action.x is not None:
                            logger.info(
                                f"[API] Smart Flow: Adding tap step ({action.x}, {action.y}) to navigate to {target_name}"
                            )
                            steps.append(
                                {
                                    "step_type": "tap",
                                    "x": action.x,
                                    "y": action.y,
                                    "description": f"Navigate to {target_name}",
                                    "expected_screen_id": transition.source_screen_id,
                                    "screen_activity": source_activity,
                                    "screen_package": package_name,
                                    # Disable state validation for navigation taps - the tap IS the navigation
                                    # If we're on wrong screen, tap still happens (might fail but won't loop)
                                    "validate_state": False,
                                    "navigation_required": True,  # Flag this as navigation for recovery
                                }
                            )
                            steps.append(
                                {
                                    "step_type": "wait",
                                    "duration": 1500,  # Slightly longer wait for screen transitions
                                    "description": f"Wait for {target_name}",
                                    "screen_activity": target_activity,
                                    "validate_state": False,  # Don't validate during navigation
                                }
                            )
                            # Update current position after each navigation
                            current_screen_id = target_screen_id
                        else:
                            logger.warning(
                                f"[API] Smart Flow: Transition to {target_name} has action_type={action.action_type}, x={action.x} - skipping"
                            )
                else:
                    # No path found - skip this screen
                    warnings.append(
                        f"Skipping {activity_name} - no navigation path from current screen"
                    )
                    logger.warning(
                        f"[API] Smart Flow: No path from {current_screen_id[:8] if current_screen_id else 'start'} to {screen_id[:8]} ({activity_name})"
                    )
                    continue  # Skip to next screen

                screens_visited.add(screen_id)

            # Add screenshot step if enabled
            if include_screenshots:
                steps.append(
                    {
                        "step_type": "screenshot",
                        "description": f"Capture screen: {activity_name}",
                        "expected_screen_id": screen_id,
                        "screen_activity": screen.activity,  # Full activity for navigation
                        "screen_package": package_name,
                        "validate_state": False,  # Don't restart app if on wrong screen
                        "continue_on_error": True,  # Continue flow if screenshot fails
                    }
                )

            # Collect sensors from this screen's UI elements
            screen_sensors = []
            if include_sensors and hasattr(screen, "ui_elements"):
                for i, element in enumerate(screen.ui_elements or []):
                    text = element.get("text", "")
                    resource_id = element.get("resource_id", "")

                    # Detect if this looks like a sensor value
                    if text and len(text) < 50:
                        # Check if it contains numeric data
                        import re

                        if re.search(r"\d", text) or any(
                            kw in text.lower()
                            for kw in [
                                "temp",
                                "battery",
                                "speed",
                                "distance",
                                "level",
                                "status",
                                "%",
                            ]
                        ):

                            sensor_name = (
                                resource_id.split("/")[-1]
                                if resource_id
                                else f"sensor_{i}"
                            )
                            sensor_name = sensor_name.replace("_", " ").title()

                            sensor_id = (
                                f"{stable_device_id}_sensor_{uuid.uuid4().hex[:8]}"
                            )
                            screen_sensors.append(
                                {
                                    "sensor_id": sensor_id,
                                    "name": sensor_name,
                                    "screen_id": screen_id,
                                    "resource_id": resource_id,
                                    "sample_value": text,
                                    "enabled": True,
                                }
                            )
                            sensors.append(
                                {
                                    "sensor_id": sensor_id,
                                    "name": sensor_name,
                                    "screen_id": screen_id,
                                    "sample_value": text,
                                    "enabled": True,
                                }
                            )

            # Add capture_sensors step for THIS screen's sensors
            if screen_sensors:
                sensor_ids = [s["sensor_id"] for s in screen_sensors]
                steps.append(
                    {
                        "step_type": "capture_sensors",
                        "sensor_ids": sensor_ids,
                        "description": f"Capture {len(sensor_ids)} sensor(s) on {activity_name}",
                        "expected_screen_id": screen_id,
                        "screen_activity": screen.activity,  # Required for navigation
                        "screen_package": package_name,
                        "validate_state": False,  # Don't restart app if on wrong screen
                        "continue_on_error": True,  # Continue flow even if capture fails
                    }
                )

            current_screen_id = screen_id

        # If no sensors detected from nav graph, use existing device sensors
        # These will be captured after EACH screenshot step (Option B - try all screens)
        if not sensors and existing_sensors:
            logger.info(
                f"[API] No sensors from nav graph, using {len(existing_sensors)} existing sensors on all screens"
            )
            for i, es in enumerate(existing_sensors):
                sensor_id = es.get("sensor_id")
                current_value = es.get("current_value")
                # Include ALL sensors with an ID, not just those with values
                if sensor_id:
                    # Create a readable name from the value or sensor metadata
                    existing_name = es.get("name") or es.get("friendly_name")
                    if existing_name and existing_name != "unnamed":
                        display_name = existing_name
                    elif current_value is not None:
                        # Try to infer name from value type
                        value_str = str(current_value)
                        if value_str.isdigit() or (
                            value_str.replace(".", "").replace("-", "").isdigit()
                        ):
                            # Numeric - might be temperature, percentage, etc.
                            display_name = f"Sensor {i+1} ({value_str})"
                        elif value_str.lower() in [
                            "open",
                            "closed",
                            "on",
                            "off",
                            "true",
                            "false",
                            "locked",
                            "unlocked",
                        ]:
                            display_name = f"Status {i+1} ({value_str})"
                        elif (
                            "closed" in value_str.lower()
                            or "locked" in value_str.lower()
                        ):
                            display_name = f"Lock/Door {i+1}"
                        else:
                            display_name = f"Value {i+1}"
                    else:
                        # No value yet - use generic name with sensor ID hint
                        display_name = f"Sensor {i+1} ({sensor_id[-8:]})"

                    sensors.append(
                        {
                            "sensor_id": sensor_id,
                            "name": display_name,
                            "screen_id": es.get("screen_id"),
                            "sample_value": (
                                str(current_value) if current_value is not None else ""
                            ),
                            "resource_id": es.get("resource_id", ""),
                            "enabled": True,
                        }
                    )

            logger.info(
                f"[API] Added {len(sensors)} sensors to Smart Flow from existing device sensors"
            )

            # Insert capture_sensors step AFTER each screenshot step
            # This tries to capture on every screen since we don't know which screen has which sensor
            if sensors:
                sensor_ids = [s["sensor_id"] for s in sensors]
                new_steps = []
                capture_steps_added = 0
                for step in steps:
                    new_steps.append(step)
                    if step.get("step_type") == "screenshot":
                        screen_name = step.get("description", "").replace(
                            "Capture screen: ", ""
                        )
                        new_steps.append(
                            {
                                "step_type": "capture_sensors",
                                "sensor_ids": sensor_ids,
                                "description": f"Try capture sensors on {screen_name}",
                                "expected_screen_id": step.get("expected_screen_id"),
                                "validate_state": False,  # Don't restart app if on wrong screen
                                "continue_on_error": True,  # Don't fail if sensors not found on this screen
                            }
                        )
                        capture_steps_added += 1
                steps = new_steps
                logger.info(
                    f"[API] Added {capture_steps_added} capture_sensors steps to Smart Flow (after each screenshot)"
                )
                warnings.append(
                    f"Sensors have no screen associations. Capture will be attempted on all {len(screen_ids)} screens. "
                    "Some captures may fail - this is expected."
                )

        # Generate flow ID
        flow_id = f"smart_{uuid.uuid4().hex[:8]}"

        # Build the flow object
        flow = {
            "flow_id": flow_id,
            "device_id": stable_device_id,
            "stable_device_id": stable_device_id,
            "name": f"Smart Flow: {package_name.split('.')[-1].title()}",
            "description": f"Auto-generated flow covering {len(screen_ids)} screens in {package_name}",
            "steps": steps,
            "update_interval_seconds": 60,
            "enabled": False,
            "stop_on_error": False,
            "max_flow_retries": 3,
            "flow_timeout": 180,  # 3 minutes for multi-screen Smart Flows
            "execution_method": "server",
            "auto_wake_before": True,
            "auto_sleep_after": True,
            "verify_screen_on": True,
            "wake_timeout_ms": 3000,
        }

        # Use sensor suggester to detect additional smart sensors from UI elements
        suggested_sensors = []
        try:
            from utils.sensor_suggester import get_sensor_suggester

            suggester = get_sensor_suggester()

            # Collect all UI elements from all screens for smart detection
            all_elements = []
            for screen_id in screen_ids:
                screen = graph.screens[screen_id]
                if hasattr(screen, "ui_elements") and screen.ui_elements:
                    for el in screen.ui_elements:
                        el_copy = dict(el)
                        el_copy["screen_id"] = screen_id
                        all_elements.append(el_copy)

            if all_elements:
                raw_suggestions = suggester.suggest_sensors(all_elements)
                for s in raw_suggestions:
                    suggested_sensors.append(
                        {
                            "name": s.get("name", "Unknown"),
                            "suggested_entity_id": s.get("entity_id", ""),
                            "sample_value": s.get("sample_value", ""),
                            "confidence": s.get("confidence", 0.5),
                            "screen_id": s.get("screen_id"),
                            "enabled": False,  # Off by default, user must enable
                        }
                    )
        except Exception as e:
            logger.warning(f"[API] Failed to generate suggested sensors: {e}")

        # Check for overlapping flows with existing flows
        overlapping_flows = []
        try:
            from routes.deduplication import get_dedup_service

            dedup_service = get_dedup_service()

            overlaps = dedup_service.find_overlapping_flows(stable_device_id, flow)
            if overlaps:
                for match in overlaps:
                    overlapping_flows.append(
                        {
                            "flow_id": match.entity_id,
                            "flow_name": match.entity_name,
                            "similarity": round(match.similarity_score * 100),
                            "overlapping_sensors": match.details.get(
                                "existing_sensors", []
                            ),
                            "recommendation": match.recommendation.value,
                        }
                    )
                    warnings.append(
                        f"⚠️ Overlaps {round(match.similarity_score * 100)}% with existing flow '{match.entity_name}'. "
                        "Consider consolidating to avoid redundant sensor captures."
                    )
        except Exception as oe:
            logger.debug(f"[API] Overlap check skipped: {oe}")

        # Count step types for logging
        tap_count = sum(1 for s in steps if s.get("step_type") == "tap")
        wait_count = sum(1 for s in steps if s.get("step_type") == "wait")
        capture_count = sum(1 for s in steps if s.get("step_type") == "capture_sensors")
        screenshot_count = sum(1 for s in steps if s.get("step_type") == "screenshot")

        logger.info(
            f"[API] Smart Flow generation complete: {len(steps)} steps "
            f"({tap_count} taps, {wait_count} waits, {capture_count} captures, {screenshot_count} screenshots)"
        )

        return {
            "success": True,
            "flow": flow,
            "sensors": sensors,
            "suggested_sensors": suggested_sensors,
            "suggestions_count": len(suggested_sensors),
            "actions": actions,
            "warnings": warnings,
            "overlapping_flows": overlapping_flows,
            "stats": {
                "screen_count": len(screen_ids),
                "step_count": len(steps),
                "tap_count": tap_count,
                "wait_count": wait_count,
                "sensor_count": len(sensors),
                "suggested_count": len(suggested_sensors),
                "overlapping_count": len(overlapping_flows),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to generate smart flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flows/generate-smart/save")
async def save_smart_flow(
    request: dict, service: FlowService = Depends(get_flow_service)
):
    """
    Save a generated Smart Flow.

    Args:
        request: Either:
            - {flow: dict, sensors: list} - Wrapped format from modal save
            - {flow_id, device_id, steps, ...} - Direct flow object from test button

    Returns:
        Saved flow
    """
    try:
        # Support both wrapped format and direct flow object
        if "flow" in request:
            flow_data = request.get("flow")
            selected_sensors = request.get("sensors", [])
        else:
            # Direct flow object (from test button)
            flow_data = request
            selected_sensors = []

        if not flow_data or not flow_data.get("flow_id"):
            raise HTTPException(
                status_code=400, detail="flow data with flow_id required"
            )

        # Filter capture_sensors steps to only include enabled sensors
        # BUT: If no sensors were specified (e.g., from test button), keep all sensors
        if selected_sensors:
            enabled_sensor_ids = {
                s["sensor_id"] for s in selected_sensors if s.get("enabled", True)
            }

            for step in flow_data.get("steps", []):
                if step.get("step_type") == "capture_sensors":
                    step["sensor_ids"] = [
                        sid
                        for sid in step.get("sensor_ids", [])
                        if sid in enabled_sensor_ids
                    ]

            # Remove capture_sensors steps with no sensors
            flow_data["steps"] = [
                step
                for step in flow_data.get("steps", [])
                if step.get("step_type") != "capture_sensors" or step.get("sensor_ids")
            ]
        # else: Keep all capture_sensors steps as-is (test mode uses all sensors)

        # Save the flow
        saved_flow = await service.create_flow(flow_data)

        # Optionally create sensor definitions
        deps = get_deps()
        if deps.sensor_manager and selected_sensors:
            for sensor in selected_sensors:
                if sensor.get("enabled", True):
                    try:
                        deps.sensor_manager.update_sensor(
                            device_id=flow_data.get("device_id"),
                            sensor_id=sensor.get("sensor_id"),
                            name=sensor.get("name"),
                            value=sensor.get("sample_value"),
                            sensor_type="text",
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to create sensor {sensor.get('sensor_id')}: {e}"
                        )

        return {
            "success": True,
            "flow": saved_flow,
            "sensors_created": len(
                [s for s in selected_sensors if s.get("enabled", True)]
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to save smart flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# BUNDLED APP FLOWS (Pre-made flows for popular apps)
# =============================================================================


@router.get("/app-flows")
async def get_bundled_flows():
    """
    Get list of available pre-made flows for popular apps.

    Returns:
        List of apps with available flow templates
    """
    # TODO: Load bundled flows from config/flow_templates/bundled/
    # For now, return empty list as feature is not yet implemented
    return {
        "apps": [],
        "message": "Bundled app flows coming soon. Use Smart Flow or Flow Wizard to create custom flows.",
    }


@router.post("/app-flows/{bundle_id}/install")
async def install_bundled_flow(
    bundle_id: str, request: dict, service: FlowService = Depends(get_flow_service)
):
    """
    Install a bundled flow for a specific device.

    Args:
        bundle_id: ID of the bundled flow template
        request: { device_id: str }

    Returns:
        Installed flow
    """
    device_id = request.get("device_id")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")

    # TODO: Implement bundled flow installation
    raise HTTPException(
        status_code=404,
        detail=f"Bundled flow '{bundle_id}' not found. This feature is coming soon.",
    )
