"""
Flow Management Routes - Flow Creation, Execution, and Monitoring

Provides endpoints for managing automated sensor collection flows:
- CRUD operations for flows (create, read, update, delete)
- Flow execution (on-demand and scheduled)
- Performance metrics and monitoring
- Alert management and threshold configuration
- Scheduler control (pause/resume/status)

Flows support step-by-step automation for sensor data collection with
scheduling, retry logic, and comprehensive performance tracking.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
import logging
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["flows"])


# =============================================================================
# FLOW MIGRATION
# =============================================================================

@router.post("/flows/migrate-stable-ids")
async def migrate_flow_stable_ids():
    """
    Migrate existing flows to use stable_device_id.
    This ensures flows can be matched to devices across IP/port changes.
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        logger.info("[API] Migrating flows to stable device IDs")
        migrated = 0
        failed = 0
        already_set = 0

        # Get all flows
        all_flows = deps.flow_manager.get_all_flows()
        logger.info(f"[API] Found {len(all_flows)} flows to check")

        for flow in all_flows:
            if flow.stable_device_id:
                already_set += 1
                continue

            # Get stable ID for this device
            try:
                stable_id = await deps.adb_bridge.get_device_serial(flow.device_id)
                if stable_id:
                    flow.stable_device_id = stable_id
                    deps.flow_manager.update_flow(flow.device_id, flow.flow_id, flow.dict())
                    migrated += 1
                    logger.debug(f"[API] Migrated flow {flow.flow_id} to stable ID {stable_id}")
                else:
                    failed += 1
                    logger.warning(f"[API] Could not get stable ID for flow {flow.flow_id}")
            except Exception as e:
                logger.warning(f"[API] Could not migrate flow {flow.flow_id}: {e}")
                failed += 1

        return {
            "success": True,
            "total_flows": len(all_flows),
            "migrated": migrated,
            "already_set": already_set,
            "failed": failed,
            "message": f"Migrated {migrated} flows, {already_set} already set, {failed} failed"
        }
    except Exception as e:
        logger.error(f"[API] Flow migration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# FLOW CRUD ENDPOINTS
# =============================================================================

@router.post("/flows")
async def create_flow(flow_data: dict):
    """
    Create a new flow

    Body:
        flow_data: Flow definition (SensorCollectionFlow dict)

    Returns:
        Created flow with generated flow_id
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        # Import here to avoid circular dependency
        from flow_models import SensorCollectionFlow

        # Get stable_device_id if not provided
        if not flow_data.get('stable_device_id') and flow_data.get('device_id'):
            stable_id = await deps.adb_bridge.get_device_serial(flow_data['device_id'])
            if stable_id:
                flow_data['stable_device_id'] = stable_id

        # Create flow from dict
        flow = SensorCollectionFlow(**flow_data)

        # Save flow
        success = deps.flow_manager.create_flow(flow)
        if not success:
            raise HTTPException(status_code=400, detail="Flow already exists")

        logger.info(f"[API] Created flow {flow.flow_id} for device {flow.device_id}")
        return flow.dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to create flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows")
async def list_flows(device_id: Optional[str] = None):
    """
    List all flows (optionally filtered by device)

    Args:
        device_id: Optional device ID filter

    Returns:
        List of flows
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        if device_id:
            flows = deps.flow_manager.get_device_flows(device_id)
        else:
            flows = deps.flow_manager.get_all_flows()

        return [f.dict() for f in flows]

    except Exception as e:
        logger.error(f"[API] Failed to list flows: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows/android-sync")
async def get_flows_for_android(
    stable_device_id: Optional[str] = None,
    adb_device_id: Optional[str] = None
):
    """
    Get flows enriched with embedded sensor definitions for Android execution.

    This endpoint is used by the Android companion app to sync flows with
    full sensor definitions embedded in CAPTURE_SENSORS steps, allowing
    Android to execute sensor capture without needing the server.

    Args:
        stable_device_id: Android stable device ID (from VisualMapperApp)
        adb_device_id: ADB device ID (IP:port format)

    Returns:
        List of flows with embedded_sensors populated in CAPTURE_SENSORS steps
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")
        if not deps.sensor_manager:
            raise HTTPException(status_code=503, detail="Sensor manager not initialized")

        logger.info(f"[API] Android sync request - stable_id={stable_device_id}, adb_id={adb_device_id}")

        # Find flows for this device
        all_flows = deps.flow_manager.get_all_flows()
        matching_flows = []

        for flow in all_flows:
            # Match by stable_device_id or device_id (ADB device ID)
            matches_stable = stable_device_id and flow.stable_device_id == stable_device_id
            matches_adb = adb_device_id and flow.device_id == adb_device_id

            if matches_stable or matches_adb:
                matching_flows.append(flow)

        logger.info(f"[API] Found {len(matching_flows)} flows for Android sync")

        # Get all sensors for device (for embedding in steps)
        device_sensors = {}
        if adb_device_id:
            sensors = deps.sensor_manager.get_all_sensors(adb_device_id)
            for sensor in sensors:
                device_sensors[sensor.sensor_id] = sensor

        # Enrich flows with embedded sensor definitions
        enriched_flows = []
        for flow in matching_flows:
            flow_dict = flow.dict()

            # Enrich CAPTURE_SENSORS steps with full sensor definitions
            enriched_steps = []
            for step in flow_dict.get('steps', []):
                step_type = step.get('step_type')
                if step_type == 'capture_sensors':
                    # Get sensor IDs from step
                    sensor_ids = step.get('sensor_ids', [])

                    # Embed full sensor definitions
                    embedded_sensors = []
                    for sensor_id in sensor_ids:
                        sensor = device_sensors.get(sensor_id)
                        if sensor:
                            # Convert sensor to dict for embedding
                            sensor_dict = sensor.dict() if hasattr(sensor, 'dict') else sensor.model_dump()
                            embedded_sensors.append(sensor_dict)
                        else:
                            logger.warning(f"[API] Sensor {sensor_id} not found for embedding")

                    step['embedded_sensors'] = embedded_sensors
                    logger.debug(f"[API] Embedded {len(embedded_sensors)} sensors in step")

                enriched_steps.append(step)

            flow_dict['steps'] = enriched_steps
            enriched_flows.append(flow_dict)

        logger.info(f"[API] Returning {len(enriched_flows)} enriched flows for Android")
        return enriched_flows

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to get flows for Android: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows/{device_id}/{flow_id}")
async def get_flow(device_id: str, flow_id: str):
    """
    Get a specific flow

    Args:
        device_id: Device ID
        flow_id: Flow ID

    Returns:
        Flow definition
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        flow = deps.flow_manager.get_flow(device_id, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        return flow.dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to get flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/flows/{device_id}/{flow_id}")
async def update_flow(device_id: str, flow_id: str, flow_data: dict):
    """
    Update an existing flow

    Args:
        device_id: Device ID
        flow_id: Flow ID
        flow_data: Updated flow definition

    Returns:
        Updated flow
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        # Import here to avoid circular dependency
        from flow_models import SensorCollectionFlow

        # Create flow from dict
        flow = SensorCollectionFlow(**flow_data)

        # Ensure IDs match
        if flow.device_id != device_id or flow.flow_id != flow_id:
            raise HTTPException(status_code=400, detail="Flow ID mismatch")

        # Update flow
        success = deps.flow_manager.update_flow(flow)
        if not success:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        # Reload flows in scheduler to reflect enabled/disabled changes
        if deps.flow_scheduler and deps.flow_scheduler.is_running():
            try:
                await deps.flow_scheduler.reload_flows(device_id)
                logger.info(f"[API] Reloaded scheduler flows for {device_id}")
            except Exception as e:
                logger.warning(f"[API] Failed to reload scheduler flows: {e}")

        logger.info(f"[API] Updated flow {flow_id} for device {device_id}")
        return flow.dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to update flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/flows/{device_id}/{flow_id}")
async def delete_flow(device_id: str, flow_id: str):
    """
    Delete a flow

    Args:
        device_id: Device ID
        flow_id: Flow ID

    Returns:
        Success message
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        success = deps.flow_manager.delete_flow(device_id, flow_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        # Cancel periodic task for deleted flow
        if deps.flow_scheduler and deps.flow_scheduler.is_running():
            try:
                # Cancel specific flow task if exists
                if flow_id in deps.flow_scheduler._periodic_tasks:
                    deps.flow_scheduler._periodic_tasks[flow_id].cancel()
                    del deps.flow_scheduler._periodic_tasks[flow_id]
                    logger.info(f"[API] Cancelled periodic task for deleted flow {flow_id}")
            except Exception as e:
                logger.warning(f"[API] Failed to cancel periodic task: {e}")

        logger.info(f"[API] Deleted flow {flow_id} for device {device_id}")
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
async def execute_flow_on_demand(device_id: str, flow_id: str):
    """
    Execute a flow on-demand (outside the scheduler) and return execution result

    Args:
        device_id: Device ID
        flow_id: Flow ID

    Returns:
        FlowExecutionResult with execution details
    """
    deps = get_deps()
    try:
        if not deps.flow_executor:
            raise HTTPException(status_code=503, detail="Flow executor not initialized")

        # Get flow
        flow = deps.flow_manager.get_flow(device_id, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        # Execute flow directly (synchronous for test/on-demand execution)
        logger.info(f"[API] Executing flow {flow_id} on-demand")
        result = await deps.flow_executor.execute_flow(flow)

        # Convert result to dict for JSON response
        result_dict = {
            "flow_id": result.flow_id,
            "success": result.success,
            "executed_steps": result.executed_steps,
            "failed_step": result.failed_step,
            "error_message": result.error_message,
            "captured_sensors": result.captured_sensors,
            "execution_time_ms": result.execution_time_ms,
            "timestamp": result.timestamp.isoformat() if result.timestamp else None
        }

        logger.info(f"[API] Flow {flow_id} execution complete: {result.success}")
        return result_dict

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to execute flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flows/{device_id}/{flow_id}/execute/android")
async def execute_flow_on_android(device_id: str, flow_id: str):
    """
    Execute a flow on Android companion app via MQTT

    This bypasses the normal execution routing and directly sends the flow
    to the Android app for execution. Use this for testing or when you
    explicitly want Android-side execution.

    Args:
        device_id: Device ID
        flow_id: Flow ID

    Returns:
        Result of MQTT command send (actual execution is async on Android)
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")
        if not deps.mqtt_manager:
            raise HTTPException(status_code=503, detail="MQTT manager not initialized")
        if not deps.mqtt_manager.is_connected():
            raise HTTPException(status_code=503, detail="MQTT not connected")

        # Get flow
        flow = deps.flow_manager.get_flow(device_id, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        logger.info(f"[API] Sending flow {flow_id} to Android for execution")

        # Import datetime for timestamp
        from datetime import datetime

        # Create execution payload
        payload = {
            "command": "execute_flow",
            "flow_id": flow.flow_id,
            "flow_name": flow.name,
            "sensors": [
                {
                    "sensor_id": sensor.sensor_id,
                    "name": sensor.name,
                    "source_type": sensor.source.source_type,
                    "source_config": sensor.source.model_dump() if hasattr(sensor.source, 'model_dump') else {}
                }
                for sensor in flow.sensors
            ],
            "timestamp": datetime.now().isoformat()
        }

        # Send to Android via MQTT
        success = await deps.mqtt_manager.publish_flow_command(
            device_id=device_id,
            flow_id=flow_id,
            payload=payload
        )

        if success:
            logger.info(f"[API] Flow {flow_id} sent to Android via MQTT")
            return {
                "success": True,
                "message": f"Flow {flow_id} sent to Android for execution",
                "execution_method": "android",
                "note": "Execution is asynchronous - results will be reported via MQTT callback"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to send flow command via MQTT")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to execute flow on Android: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flows/{device_id}/{flow_id}/execute/routed")
async def execute_flow_routed(device_id: str, flow_id: str):
    """
    Execute a flow using the execution router (respects execution_method field)

    This uses the smart routing logic:
    - "server": Execute via ADB on server
    - "android": Execute via MQTT to Android app
    - "auto": Try preferred_executor, fallback if fails

    Args:
        device_id: Device ID
        flow_id: Flow ID

    Returns:
        FlowExecutionResult with routing information
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")
        if not deps.flow_scheduler:
            raise HTTPException(status_code=503, detail="Flow scheduler not initialized")

        # Get flow
        flow = deps.flow_manager.get_flow(device_id, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        # Get execution method for logging
        execution_method = getattr(flow, 'execution_method', 'server')
        logger.info(f"[API] Executing flow {flow_id} via router (method={execution_method})")

        # Execute via router
        result = await deps.flow_scheduler.execution_router.execute_flow(flow)

        return {
            "success": result.success,
            "flow_id": flow_id,
            "configured_method": execution_method,
            "actual_method": getattr(result, 'execution_method', 'server'),
            "used_fallback": getattr(result, 'used_fallback', False),
            "error_message": result.error_message if hasattr(result, 'error_message') else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to execute flow via router: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows/{device_id}/execution-history")
async def get_execution_history(device_id: str, limit: int = 20):
    """
    Get recent execution history for a device

    Returns results from both server and Android execution,
    including success/failure status, duration, and timestamps.

    Args:
        device_id: Device ID
        limit: Maximum number of entries to return (default 20)

    Returns:
        List of execution history entries (most recent first)
    """
    deps = get_deps()
    try:
        if not deps.flow_scheduler:
            raise HTTPException(status_code=503, detail="Flow scheduler not initialized")

        # Get execution history from router
        history = deps.flow_scheduler.execution_router.get_execution_history(device_id, limit)

        return {
            "device_id": device_id,
            "count": len(history),
            "executions": history
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to get execution history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows/{device_id}/capabilities")
async def get_device_capabilities(device_id: str):
    """
    Get Android companion app capabilities for a device

    Returns capabilities reported by the companion app via MQTT,
    used for smart routing decisions in auto execution mode.

    Args:
        device_id: Device ID

    Returns:
        Device capabilities including accessibility status and feature list
    """
    deps = get_deps()
    try:
        if not deps.flow_scheduler:
            raise HTTPException(status_code=503, detail="Flow scheduler not initialized")

        # Get cached capabilities from router
        capabilities = deps.flow_scheduler.execution_router.get_device_capabilities(device_id)

        # Check if device is Android-capable
        is_capable = deps.flow_scheduler.execution_router.is_android_capable(device_id)

        return {
            "device_id": device_id,
            "android_capable": is_capable,
            "capabilities": capabilities if capabilities else {
                "message": "No companion app status received for this device"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to get device capabilities: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# PERFORMANCE METRICS
# =============================================================================

@router.get("/flows/metrics")
async def get_flow_metrics(device_id: Optional[str] = None):
    """
    Get performance metrics for flows

    Args:
        device_id: Optional device ID to filter metrics (if not provided, returns all)

    Returns:
        Performance metrics including:
        - Total executions
        - Success rate
        - Average execution time
        - Recent alerts
        - Queue depth
    """
    deps = get_deps()
    try:
        if not deps.performance_monitor:
            raise HTTPException(status_code=503, detail="Performance monitor not initialized")

        if device_id:
            # Get metrics for specific device
            metrics = deps.performance_monitor.get_metrics(device_id)
            return {"device_id": device_id, "metrics": metrics}
        else:
            # Get metrics for all devices
            all_metrics = deps.performance_monitor.get_all_metrics()
            return {"all_devices": all_metrics}

    except Exception as e:
        logger.error(f"[API] Failed to get flow metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows/alerts")
async def get_flow_alerts(device_id: Optional[str] = None, limit: int = 10):
    """
    Get recent performance alerts

    Args:
        device_id: Optional device ID to filter alerts
        limit: Maximum number of alerts to return (default: 10)

    Returns:
        List of recent alerts with severity, message, and recommendations
    """
    deps = get_deps()
    try:
        if not deps.performance_monitor:
            raise HTTPException(status_code=503, detail="Performance monitor not initialized")

        alerts = deps.performance_monitor.get_recent_alerts(device_id=device_id, limit=limit)

        return {
            "alerts": alerts,
            "count": len(alerts),
            "device_id": device_id
        }
    except Exception as e:
        logger.error(f"[API] Failed to get flow alerts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/flows/alerts")
async def clear_flow_alerts(device_id: Optional[str] = None):
    """
    Clear performance alerts

    Args:
        device_id: Optional device ID (if not provided, clears all alerts)

    Returns:
        Confirmation message
    """
    deps = get_deps()
    try:
        if not deps.performance_monitor:
            raise HTTPException(status_code=503, detail="Performance monitor not initialized")

        deps.performance_monitor.clear_alerts(device_id=device_id)

        message = f"Cleared alerts for {device_id}" if device_id else "Cleared all alerts"
        return {"success": True, "message": message}
    except Exception as e:
        logger.error(f"[API] Failed to clear flow alerts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows/thresholds")
async def get_alert_thresholds():
    """
    Get current alert threshold configuration

    Returns:
        Alert thresholds for queue depth, backlog ratio, and failure rates
    """
    deps = get_deps()
    try:
        if not deps.performance_monitor:
            raise HTTPException(status_code=503, detail="Performance monitor not initialized")

        return {
            "queue_depth_warning": deps.performance_monitor.QUEUE_DEPTH_WARNING,
            "queue_depth_critical": deps.performance_monitor.QUEUE_DEPTH_CRITICAL,
            "backlog_ratio": deps.performance_monitor.BACKLOG_RATIO,
            "failure_rate_warning": deps.performance_monitor.FAILURE_RATE_WARNING,
            "failure_rate_critical": deps.performance_monitor.FAILURE_RATE_CRITICAL,
            "alert_cooldown_seconds": deps.performance_monitor.ALERT_COOLDOWN_SECONDS
        }
    except Exception as e:
        logger.error(f"[API] Failed to get alert thresholds: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/flows/thresholds")
async def update_alert_thresholds(thresholds: dict):
    """
    Update alert threshold configuration

    Args:
        thresholds: Dictionary with threshold values to update

    Accepted fields:
        - queue_depth_warning: int
        - queue_depth_critical: int
        - backlog_ratio: float (0-1)
        - failure_rate_warning: float (0-1)
        - failure_rate_critical: float (0-1)
        - alert_cooldown_seconds: int

    Returns:
        Updated threshold configuration
    """
    deps = get_deps()
    try:
        if not deps.performance_monitor:
            raise HTTPException(status_code=503, detail="Performance monitor not initialized")

        # Update thresholds (with validation)
        if "queue_depth_warning" in thresholds:
            value = int(thresholds["queue_depth_warning"])
            if value < 1 or value > 100:
                raise HTTPException(status_code=400, detail="queue_depth_warning must be between 1 and 100")
            deps.performance_monitor.QUEUE_DEPTH_WARNING = value

        if "queue_depth_critical" in thresholds:
            value = int(thresholds["queue_depth_critical"])
            if value < 1 or value > 100:
                raise HTTPException(status_code=400, detail="queue_depth_critical must be between 1 and 100")
            deps.performance_monitor.QUEUE_DEPTH_CRITICAL = value

        if "backlog_ratio" in thresholds:
            value = float(thresholds["backlog_ratio"])
            if value < 0 or value > 1:
                raise HTTPException(status_code=400, detail="backlog_ratio must be between 0 and 1")
            deps.performance_monitor.BACKLOG_RATIO = value

        if "failure_rate_warning" in thresholds:
            value = float(thresholds["failure_rate_warning"])
            if value < 0 or value > 1:
                raise HTTPException(status_code=400, detail="failure_rate_warning must be between 0 and 1")
            deps.performance_monitor.FAILURE_RATE_WARNING = value

        if "failure_rate_critical" in thresholds:
            value = float(thresholds["failure_rate_critical"])
            if value < 0 or value > 1:
                raise HTTPException(status_code=400, detail="failure_rate_critical must be between 0 and 1")
            deps.performance_monitor.FAILURE_RATE_CRITICAL = value

        if "alert_cooldown_seconds" in thresholds:
            value = int(thresholds["alert_cooldown_seconds"])
            if value < 0 or value > 3600:
                raise HTTPException(status_code=400, detail="alert_cooldown_seconds must be between 0 and 3600")
            deps.performance_monitor.ALERT_COOLDOWN_SECONDS = value

        logger.info(f"[API] Updated alert thresholds: {thresholds}")

        # Return updated configuration
        return {
            "success": True,
            "message": "Alert thresholds updated",
            "thresholds": {
                "queue_depth_warning": deps.performance_monitor.QUEUE_DEPTH_WARNING,
                "queue_depth_critical": deps.performance_monitor.QUEUE_DEPTH_CRITICAL,
                "backlog_ratio": deps.performance_monitor.BACKLOG_RATIO,
                "failure_rate_warning": deps.performance_monitor.FAILURE_RATE_WARNING,
                "failure_rate_critical": deps.performance_monitor.FAILURE_RATE_CRITICAL,
                "alert_cooldown_seconds": deps.performance_monitor.ALERT_COOLDOWN_SECONDS
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to update alert thresholds: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SCHEDULER CONTROL
# =============================================================================

@router.get("/scheduler/status")
async def get_scheduler_status():
    """
    Get overall scheduler status

    Returns:
        Scheduler state including running/paused status and per-device info
    """
    deps = get_deps()
    try:
        if not deps.flow_scheduler:
            raise HTTPException(status_code=503, detail="Flow scheduler not initialized")

        status = deps.flow_scheduler.get_status()
        return {"success": True, "status": status}

    except Exception as e:
        logger.error(f"[API] Failed to get scheduler status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/pause")
async def pause_scheduler():
    """
    Pause periodic scheduling

    Note: Currently executing flows will complete, but no new periodic
    flows will be queued until resumed.
    """
    deps = get_deps()
    try:
        if not deps.flow_scheduler:
            raise HTTPException(status_code=503, detail="Flow scheduler not initialized")

        await deps.flow_scheduler.pause()
        return {"success": True, "message": "Scheduler paused"}

    except Exception as e:
        logger.error(f"[API] Failed to pause scheduler: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scheduler/resume")
async def resume_scheduler():
    """
    Resume periodic scheduling
    """
    deps = get_deps()
    try:
        if not deps.flow_scheduler:
            raise HTTPException(status_code=503, detail="Flow scheduler not initialized")

        await deps.flow_scheduler.resume()
        return {"success": True, "message": "Scheduler resumed"}

    except Exception as e:
        logger.error(f"[API] Failed to resume scheduler: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WIZARD ACTIVE STATE (prevents auto-sleep during flow editing)
# =============================================================================

@router.post("/wizard/active/{device_id}")
async def set_wizard_active(device_id: str):
    """
    Mark a device as having an active wizard session.
    Prevents auto-sleep after flow execution while wizard is open.
    """
    from server import wizard_active_devices

    wizard_active_devices.add(device_id)
    logger.info(f"[API] Wizard marked active for device {device_id}")
    return {
        "success": True,
        "device_id": device_id,
        "wizard_active": True,
        "active_devices": list(wizard_active_devices)
    }


@router.delete("/wizard/active/{device_id}")
async def set_wizard_inactive(device_id: str):
    """
    Mark a device as no longer having an active wizard session.
    Re-enables auto-sleep after flow execution.
    """
    from server import wizard_active_devices

    wizard_active_devices.discard(device_id)
    logger.info(f"[API] Wizard marked inactive for device {device_id}")
    return {
        "success": True,
        "device_id": device_id,
        "wizard_active": False,
        "active_devices": list(wizard_active_devices)
    }


@router.get("/wizard/active")
async def get_wizard_active_devices():
    """
    Get list of devices with active wizard sessions.
    """
    from server import wizard_active_devices

    return {
        "success": True,
        "active_devices": list(wizard_active_devices)
    }


@router.get("/scheduler/queue/{device_id}")
async def get_scheduler_queue(device_id: str):
    """
    Get queue information for a device

    Args:
        device_id: Device ID to check

    Returns:
        Queue depth and status for the device
    """
    deps = get_deps()
    try:
        if not deps.flow_scheduler:
            raise HTTPException(status_code=503, detail="Flow scheduler not initialized")

        queue_info = deps.flow_scheduler.get_queued_flows(device_id)
        metrics = deps.flow_scheduler.get_metrics(device_id)

        return {
            "success": True,
            "device_id": device_id,
            "queue": queue_info,
            "metrics": metrics
        }

    except Exception as e:
        logger.error(f"[API] Failed to get scheduler queue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# EXECUTION HISTORY ENDPOINTS
# =============================================================================

@router.get("/flows/{device_id}/{flow_id}/history")
async def get_flow_execution_history(device_id: str, flow_id: str, limit: int = 50):
    """
    Get execution history for a flow

    Args:
        device_id: Device ID
        flow_id: Flow ID
        limit: Maximum number of executions to return (default: 50)

    Returns:
        List of execution logs with detailed step-by-step information
    """
    deps = get_deps()
    try:
        if not deps.flow_executor or not deps.flow_executor.execution_history:
            raise HTTPException(status_code=503, detail="Execution history not initialized")

        history = deps.flow_executor.execution_history.get_history(flow_id, limit=limit)

        # Convert to dicts for JSON response
        history_dicts = [
            {
                "execution_id": log.execution_id,
                "flow_id": log.flow_id,
                "device_id": log.device_id,
                "started_at": log.started_at,
                "completed_at": log.completed_at,
                "success": log.success,
                "error": log.error,
                "duration_ms": log.duration_ms,
                "triggered_by": log.triggered_by,
                "total_steps": log.total_steps,
                "executed_steps": log.executed_steps,
                "steps": [
                    {
                        "step_index": step.step_index,
                        "step_type": step.step_type,
                        "description": step.description,
                        "started_at": step.started_at,
                        "completed_at": step.completed_at,
                        "success": step.success,
                        "error": step.error,
                        "duration_ms": step.duration_ms,
                        "details": step.details
                    }
                    for step in (log.steps or [])
                ]
            }
            for log in history
        ]

        return {
            "success": True,
            "flow_id": flow_id,
            "device_id": device_id,
            "history": history_dicts,
            "count": len(history_dicts)
        }

    except Exception as e:
        logger.error(f"[API] Failed to get execution history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows/{device_id}/{flow_id}/history/{execution_id}")
async def get_flow_execution_details(device_id: str, flow_id: str, execution_id: str):
    """
    Get detailed information about a specific execution

    Args:
        device_id: Device ID
        flow_id: Flow ID
        execution_id: Execution ID

    Returns:
        Detailed execution log with all step information
    """
    deps = get_deps()
    try:
        if not deps.flow_executor or not deps.flow_executor.execution_history:
            raise HTTPException(status_code=503, detail="Execution history not initialized")

        execution = deps.flow_executor.execution_history.get_execution(flow_id, execution_id)

        if not execution:
            raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

        # Convert to dict
        execution_dict = {
            "execution_id": execution.execution_id,
            "flow_id": execution.flow_id,
            "device_id": execution.device_id,
            "started_at": execution.started_at,
            "completed_at": execution.completed_at,
            "success": execution.success,
            "error": execution.error,
            "duration_ms": execution.duration_ms,
            "triggered_by": execution.triggered_by,
            "total_steps": execution.total_steps,
            "executed_steps": execution.executed_steps,
            "steps": [
                {
                    "step_index": step.step_index,
                    "step_type": step.step_type,
                    "description": step.description,
                    "started_at": step.started_at,
                    "completed_at": step.completed_at,
                    "success": step.success,
                    "error": step.error,
                    "duration_ms": step.duration_ms,
                    "details": step.details
                }
                for step in (execution.steps or [])
            ]
        }

        return {
            "success": True,
            "execution": execution_dict
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to get execution details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows/{device_id}/{flow_id}/latest")
async def get_latest_execution(device_id: str, flow_id: str):
    """
    Get the most recent execution log for a flow

    This is useful for UI status display (last run status, error message, etc.)

    Args:
        device_id: Device ID
        flow_id: Flow ID

    Returns:
        Latest execution log or null if no executions
    """
    deps = get_deps()
    try:
        if not deps.flow_executor or not deps.flow_executor.execution_history:
            raise HTTPException(status_code=503, detail="Execution history not initialized")

        latest = deps.flow_executor.execution_history.get_latest_execution(flow_id)

        if not latest:
            return {
                "success": True,
                "latest": None
            }

        # Convert to dict (summary only, without full step details)
        latest_dict = {
            "execution_id": latest.execution_id,
            "flow_id": latest.flow_id,
            "device_id": latest.device_id,
            "started_at": latest.started_at,
            "completed_at": latest.completed_at,
            "success": latest.success,
            "error": latest.error,
            "duration_ms": latest.duration_ms,
            "triggered_by": latest.triggered_by,
            "total_steps": latest.total_steps,
            "executed_steps": latest.executed_steps
        }

        return {
            "success": True,
            "latest": latest_dict
        }

    except Exception as e:
        logger.error(f"[API] Failed to get latest execution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows/{device_id}/{flow_id}/stats")
async def get_flow_stats(device_id: str, flow_id: str):
    """
    Get statistics for a flow

    Args:
        device_id: Device ID
        flow_id: Flow ID

    Returns:
        Execution statistics (success rate, avg duration, etc.)
    """
    deps = get_deps()
    try:
        if not deps.flow_executor or not deps.flow_executor.execution_history:
            raise HTTPException(status_code=503, detail="Execution history not initialized")

        stats = deps.flow_executor.execution_history.get_stats(flow_id)

        return {
            "success": True,
            "flow_id": flow_id,
            "device_id": device_id,
            "stats": stats
        }

    except Exception as e:
        logger.error(f"[API] Failed to get flow stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# FLOW TEMPLATES (Phase 9)
# =============================================================================

@router.get("/flow-templates")
async def list_templates():
    """
    List all available flow templates (built-in + user-created)

    Returns:
        List of templates with id, name, description, tags
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        templates = deps.flow_manager.list_templates()

        return {
            "success": True,
            "templates": templates,
            "count": len(templates)
        }

    except Exception as e:
        logger.error(f"[API] Failed to list templates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flow-templates/builtin")
async def get_builtin_templates():
    """
    Get only the built-in templates (not user-created)

    Returns:
        List of built-in templates
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        templates = deps.flow_manager.get_builtin_templates()

        return {
            "success": True,
            "templates": templates,
            "count": len(templates)
        }

    except Exception as e:
        logger.error(f"[API] Failed to get builtin templates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flow-templates/{template_id}")
async def get_template(template_id: str):
    """
    Get a specific template by ID

    Args:
        template_id: Template ID

    Returns:
        Template definition with steps
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        template = deps.flow_manager.get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

        return {
            "success": True,
            "template": template
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to get template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flow-templates")
async def create_template(template_data: dict):
    """
    Create a new flow template

    Body:
        template_data: Template definition with:
            - template_id: Unique template ID
            - name: Display name
            - description: Template description
            - steps: List of flow steps
            - tags: List of category tags (optional)

    Returns:
        Created template
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        template_id = template_data.get("template_id")
        name = template_data.get("name")
        description = template_data.get("description", "")
        steps = template_data.get("steps", [])
        tags = template_data.get("tags", [])

        if not template_id or not name:
            raise HTTPException(status_code=400, detail="template_id and name are required")

        if not steps:
            raise HTTPException(status_code=400, detail="Template must have at least one step")

        success = deps.flow_manager.save_template(
            template_id=template_id,
            name=name,
            description=description,
            steps=steps,
            tags=tags
        )

        if not success:
            raise HTTPException(status_code=400, detail="Template already exists")

        logger.info(f"[API] Created template {template_id}")

        return {
            "success": True,
            "template_id": template_id,
            "message": f"Template '{name}' created"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to create template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/flow-templates/{template_id}")
async def delete_template(template_id: str):
    """
    Delete a user-created template

    Args:
        template_id: Template ID

    Note: Built-in templates cannot be deleted
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        # Check if it's a built-in template
        builtin = deps.flow_manager.get_builtin_templates()
        if any(t.get("template_id") == template_id for t in builtin):
            raise HTTPException(status_code=400, detail="Cannot delete built-in templates")

        success = deps.flow_manager.delete_template(template_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

        logger.info(f"[API] Deleted template {template_id}")

        return {
            "success": True,
            "message": f"Template {template_id} deleted"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to delete template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flow-templates/{template_id}/create-flow")
async def create_flow_from_template(template_id: str, request_data: dict):
    """
    Create a new flow from a template

    Args:
        template_id: Template ID to use

    Body:
        request_data:
            - device_id: Target device ID (required)
            - flow_name: Name for the new flow (required)
            - overrides: Optional dict of step field overrides

    Returns:
        Created flow
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        device_id = request_data.get("device_id")
        flow_name = request_data.get("flow_name")
        overrides = request_data.get("overrides", {})

        if not device_id or not flow_name:
            raise HTTPException(status_code=400, detail="device_id and flow_name are required")

        # Get stable device ID if possible
        stable_device_id = None
        try:
            stable_device_id = await deps.adb_bridge.get_device_serial(device_id)
        except Exception:
            pass

        flow = deps.flow_manager.create_flow_from_template(
            template_id=template_id,
            device_id=device_id,
            flow_name=flow_name,
            overrides=overrides,
            stable_device_id=stable_device_id
        )

        if not flow:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

        logger.info(f"[API] Created flow {flow.flow_id} from template {template_id}")

        return {
            "success": True,
            "flow": flow.dict(),
            "message": f"Flow '{flow_name}' created from template"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to create flow from template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flows/{device_id}/{flow_id}/save-as-template")
async def save_flow_as_template(device_id: str, flow_id: str, request_data: dict):
    """
    Save an existing flow as a reusable template

    Args:
        device_id: Device ID
        flow_id: Flow ID

    Body:
        request_data:
            - template_name: Name for the template (required)
            - tags: List of category tags (optional)

    Returns:
        Created template ID
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        template_name = request_data.get("template_name")
        tags = request_data.get("tags", [])

        if not template_name:
            raise HTTPException(status_code=400, detail="template_name is required")

        template_id = deps.flow_manager.save_flow_as_template(
            device_id=device_id,
            flow_id=flow_id,
            template_name=template_name,
            tags=tags
        )

        if not template_id:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        logger.info(f"[API] Saved flow {flow_id} as template {template_id}")

        return {
            "success": True,
            "template_id": template_id,
            "message": f"Flow saved as template '{template_name}'"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to save flow as template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# FLOW IMPORT/EXPORT
# =============================================================================

@router.get("/flows/export/{device_id}")
async def export_device_flows(device_id: str, include_sensors: bool = True):
    """
    Export all flows for a device as JSON (for sharing/backup)

    Args:
        device_id: Device ID
        include_sensors: Include sensor definitions in export (default True)

    Returns:
        Exportable flow bundle with flows and optionally sensors
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        # Get flows
        flow_data = deps.flow_manager.export_flows(device_id)

        if not flow_data.get("flows"):
            raise HTTPException(status_code=404, detail=f"No flows found for device {device_id}")

        export_bundle = {
            "export_version": "1.0",
            "export_type": "device_flows",
            "exported_at": __import__('datetime').datetime.now().isoformat(),
            "device_id": device_id,
            "flows": flow_data.get("flows", []),
            "flow_count": len(flow_data.get("flows", []))
        }

        # Include sensors if requested
        if include_sensors and deps.sensor_manager:
            sensors = deps.sensor_manager.get_all_sensors(device_id)
            export_bundle["sensors"] = [s.dict() for s in sensors]
            export_bundle["sensor_count"] = len(sensors)

        logger.info(f"[API] Exported {len(flow_data.get('flows', []))} flows for {device_id}")
        return export_bundle

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to export flows: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flows/{device_id}/{flow_id}/export")
async def export_single_flow(device_id: str, flow_id: str, include_sensors: bool = True):
    """
    Export a single flow as JSON (for sharing)

    Args:
        device_id: Device ID
        flow_id: Flow ID
        include_sensors: Include referenced sensor definitions

    Returns:
        Single flow export bundle
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        flow = deps.flow_manager.get_flow(device_id, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        # Get app package from first launch_app step
        app_package = None
        for step in flow.steps:
            if step.step_type == "launch_app" and step.package:
                app_package = step.package
                break

        export_bundle = {
            "export_version": "1.0",
            "export_type": "single_flow",
            "exported_at": __import__('datetime').datetime.now().isoformat(),
            "app_package": app_package,
            "flow": flow.dict(),
            "flow_name": flow.name
        }

        # Include referenced sensors
        if include_sensors and deps.sensor_manager:
            sensor_ids = set()
            for step in flow.steps:
                if step.sensor_ids:
                    sensor_ids.update(step.sensor_ids)

            sensors = []
            for sensor_id in sensor_ids:
                sensor = deps.sensor_manager.get_sensor(device_id, sensor_id)
                if sensor:
                    sensors.append(sensor.dict())

            export_bundle["sensors"] = sensors
            export_bundle["sensor_count"] = len(sensors)

        logger.info(f"[API] Exported flow {flow_id}")
        return export_bundle

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to export flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flows/import/{device_id}")
async def import_flows(device_id: str, import_data: dict):
    """
    Import flows from an export bundle

    Args:
        device_id: Target device ID

    Body:
        import_data: Export bundle (from export endpoint)

    Returns:
        Import summary
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        export_type = import_data.get("export_type", "")
        flows_imported = 0
        sensors_imported = 0

        # Get stable device ID for the target device
        stable_device_id = None
        try:
            stable_device_id = await deps.adb_bridge.get_device_serial(device_id)
        except Exception:
            pass

        if export_type == "single_flow":
            # Import single flow
            flow_data = import_data.get("flow", {})
            if not flow_data:
                raise HTTPException(status_code=400, detail="No flow data in import")

            # Update device references
            flow_data["device_id"] = device_id
            flow_data["stable_device_id"] = stable_device_id
            # Generate new flow_id to avoid conflicts
            import uuid
            flow_data["flow_id"] = f"imported_{uuid.uuid4().hex[:8]}"

            from flow_models import SensorCollectionFlow
            flow = SensorCollectionFlow(**flow_data)
            deps.flow_manager.create_flow(flow)
            flows_imported = 1

        elif export_type == "device_flows":
            # Import multiple flows
            flows = import_data.get("flows", [])
            for flow_data in flows:
                flow_data["device_id"] = device_id
                flow_data["stable_device_id"] = stable_device_id
                import uuid
                flow_data["flow_id"] = f"imported_{uuid.uuid4().hex[:8]}"

                from flow_models import SensorCollectionFlow
                flow = SensorCollectionFlow(**flow_data)
                deps.flow_manager.create_flow(flow)
                flows_imported += 1

        elif export_type == "app_flow_bundle":
            # Import app-specific bundle (from bundled flows)
            flow_data = import_data.get("flow", {})
            if not flow_data:
                raise HTTPException(status_code=400, detail="No flow data in bundle")

            flow_data["device_id"] = device_id
            flow_data["stable_device_id"] = stable_device_id
            import uuid
            flow_data["flow_id"] = f"bundled_{uuid.uuid4().hex[:8]}"

            from flow_models import SensorCollectionFlow
            flow = SensorCollectionFlow(**flow_data)
            deps.flow_manager.create_flow(flow)
            flows_imported = 1

        else:
            raise HTTPException(status_code=400, detail=f"Unknown export type: {export_type}")

        # Import sensors if provided
        if deps.sensor_manager and import_data.get("sensors"):
            for sensor_data in import_data["sensors"]:
                try:
                    sensor_data["device_id"] = device_id
                    sensor_data["stable_device_id"] = stable_device_id
                    # Generate new sensor_id
                    import uuid
                    sensor_data["sensor_id"] = f"imported_{uuid.uuid4().hex[:8]}"
                    deps.sensor_manager.create_sensor(device_id, sensor_data)
                    sensors_imported += 1
                except Exception as e:
                    logger.warning(f"[API] Failed to import sensor: {e}")

        logger.info(f"[API] Imported {flows_imported} flows, {sensors_imported} sensors to {device_id}")

        return {
            "success": True,
            "flows_imported": flows_imported,
            "sensors_imported": sensors_imported,
            "message": f"Imported {flows_imported} flow(s) and {sensors_imported} sensor(s)"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to import flows: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# BUNDLED APP FLOWS (Pre-made flows for common apps)
# =============================================================================

@router.get("/app-flows")
async def list_bundled_app_flows():
    """
    List all bundled app flows (pre-made flows for common apps)

    Returns:
        List of app packages with available bundled flows
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        bundled_flows = deps.flow_manager.get_bundled_app_flows()

        # Group by app package
        apps = {}
        for flow in bundled_flows:
            pkg = flow.get("app_package", "unknown")
            if pkg not in apps:
                apps[pkg] = {
                    "app_package": pkg,
                    "app_name": flow.get("app_name", pkg),
                    "flows": []
                }
            apps[pkg]["flows"].append({
                "bundle_id": flow.get("bundle_id"),
                "name": flow.get("name"),
                "description": flow.get("description"),
                "step_count": len(flow.get("steps", [])),
                "sensors_included": len(flow.get("sensors", []))
            })

        return {
            "success": True,
            "apps": list(apps.values()),
            "total_flows": len(bundled_flows)
        }

    except Exception as e:
        logger.error(f"[API] Failed to list bundled flows: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/app-flows/{app_package}")
async def get_bundled_flows_for_app(app_package: str):
    """
    Get bundled flows for a specific app

    Args:
        app_package: Android package name (e.g., com.spotify.music)

    Returns:
        List of bundled flows for this app
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        bundled_flows = deps.flow_manager.get_bundled_app_flows()
        app_flows = [f for f in bundled_flows if f.get("app_package") == app_package]

        if not app_flows:
            return {
                "success": True,
                "app_package": app_package,
                "flows": [],
                "message": "No bundled flows available for this app"
            }

        return {
            "success": True,
            "app_package": app_package,
            "flows": app_flows
        }

    except Exception as e:
        logger.error(f"[API] Failed to get bundled flows for {app_package}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/app-flows/{bundle_id}/install")
async def install_bundled_flow(bundle_id: str, request_data: dict):
    """
    Install a bundled app flow to a device

    Args:
        bundle_id: Bundled flow ID

    Body:
        request_data:
            - device_id: Target device ID (required)

    Returns:
        Created flow
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        device_id = request_data.get("device_id")
        if not device_id:
            raise HTTPException(status_code=400, detail="device_id is required")

        # Get bundled flow
        bundled_flows = deps.flow_manager.get_bundled_app_flows()
        bundle = next((f for f in bundled_flows if f.get("bundle_id") == bundle_id), None)

        if not bundle:
            raise HTTPException(status_code=404, detail=f"Bundled flow {bundle_id} not found")

        # Get stable device ID
        stable_device_id = None
        try:
            stable_device_id = await deps.adb_bridge.get_device_serial(device_id)
        except Exception:
            pass

        # Create flow from bundle
        import uuid
        from flow_models import SensorCollectionFlow

        flow_data = {
            "flow_id": f"bundled_{uuid.uuid4().hex[:8]}",
            "device_id": device_id,
            "stable_device_id": stable_device_id,
            "name": bundle.get("name"),
            "description": bundle.get("description"),
            "steps": bundle.get("steps", []),
            "enabled": False  # Start disabled so user can review
        }

        flow = SensorCollectionFlow(**flow_data)
        deps.flow_manager.create_flow(flow)

        logger.info(f"[API] Installed bundled flow {bundle_id} to {device_id}")

        return {
            "success": True,
            "flow": flow.dict(),
            "message": f"Installed '{bundle.get('name')}' - review and enable when ready"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to install bundled flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SMART FLOW GENERATOR
# =============================================================================

@router.post("/flows/generate-smart")
async def generate_smart_flow(request_data: dict):
    """
    Generate a smart flow that automatically visits all known screens
    in an app's navigation graph and captures data from each screen.

    Body:
        device_id: Target device
        package_name: App package to generate flow for
        capture_mode: 'all_screens' | 'sensors_only' | 'custom'
        include_screenshots: Whether to capture screenshots at each screen
        sensor_ids: Optional list of specific sensor IDs to capture

    Returns:
        Generated flow ready for review and saving
    """
    deps = get_deps()
    try:
        device_id = request_data.get("device_id")
        package_name = request_data.get("package_name")
        capture_mode = request_data.get("capture_mode", "all_screens")
        include_screenshots = request_data.get("include_screenshots", True)
        sensor_ids = request_data.get("sensor_ids", [])

        if not device_id or not package_name:
            raise HTTPException(status_code=400, detail="device_id and package_name are required")

        # Get navigation graph for this app
        nav_manager = deps.navigation_manager
        if not nav_manager:
            raise HTTPException(status_code=503, detail="Navigation manager not initialized")

        graph = nav_manager.get_graph(package_name)
        if not graph or not graph.screens:
            return {
                "success": False,
                "error": "no_navigation_data",
                "message": f"No navigation data found for {package_name}. Record some flows first to learn the app's navigation."
            }

        # Get sensors for this device/app
        sensors_for_app = []
        if deps.sensor_manager:
            all_sensors = deps.sensor_manager.get_sensors_for_device(device_id)
            sensors_for_app = [s for s in all_sensors if s.get("source_app") == package_name]

        # Build smart flow steps
        steps = []
        screens = list(graph.screens.values())

        # Step 1: Launch the app
        steps.append({
            "step_type": "launch_app",
            "package": package_name,
            "description": f"Launch {package_name}",
            "validate_state": True,
            "recovery_action": "force_restart_app"
        })

        # Step 2: Wait for app to load
        steps.append({
            "step_type": "wait",
            "duration": 3000,
            "description": "Wait for app to fully load"
        })

        # Visit each screen using navigation graph
        visited_screens = set()
        current_screen = graph.home_screen_id

        # Start from home screen if available
        if current_screen and current_screen in graph.screens:
            visited_screens.add(current_screen)
            screen = graph.screens[current_screen]

            # Capture at home screen
            if include_screenshots:
                steps.append({
                    "step_type": "screenshot",
                    "expected_screen_id": current_screen,
                    "description": f"Capture home screen: {screen.display_name or screen.activity}"
                })

            # Capture sensors visible on this screen
            screen_sensors = [s for s in sensors_for_app if s.get("expected_screen_id") == current_screen]
            if screen_sensors:
                steps.append({
                    "step_type": "capture_sensors",
                    "sensor_ids": [s.get("sensor_id") for s in screen_sensors],
                    "expected_screen_id": current_screen,
                    "description": f"Capture sensors on {screen.display_name or 'home screen'}"
                })

        # Find paths to other screens using navigation graph
        for screen_id, screen in graph.screens.items():
            if screen_id in visited_screens:
                continue

            # Try to find a path to this screen
            if current_screen:
                path = nav_manager.find_path(package_name, current_screen, screen_id)
                if path and path.transitions:
                    # Add navigation steps
                    for transition in path.transitions:
                        action = transition.action
                        if action:
                            if action.action_type == "tap":
                                steps.append({
                                    "step_type": "tap",
                                    "x": action.x or 0,
                                    "y": action.y or 0,
                                    "description": action.description or f"Navigate to {screen.display_name or screen.activity}",
                                    "expected_screen_id": transition.source_screen_id
                                })
                            elif action.action_type == "swipe":
                                steps.append({
                                    "step_type": "swipe",
                                    "start_x": action.start_x or 0,
                                    "start_y": action.start_y or 0,
                                    "end_x": action.end_x or 0,
                                    "end_y": action.end_y or 0,
                                    "description": action.description or "Swipe"
                                })
                            elif action.action_type == "keycode":
                                if action.keycode == "KEYCODE_BACK":
                                    steps.append({
                                        "step_type": "go_back",
                                        "description": "Go back"
                                    })

                    # Wait for screen transition
                    steps.append({
                        "step_type": "wait",
                        "duration": 1000,
                        "description": f"Wait for {screen.display_name or screen.activity}"
                    })

                    # Update current screen
                    current_screen = screen_id
                    visited_screens.add(screen_id)

                    # Capture at this screen
                    if include_screenshots:
                        steps.append({
                            "step_type": "screenshot",
                            "expected_screen_id": screen_id,
                            "description": f"Capture screen: {screen.display_name or screen.activity}"
                        })

                    # Capture sensors on this screen
                    screen_sensors = [s for s in sensors_for_app if s.get("expected_screen_id") == screen_id]
                    if screen_sensors:
                        steps.append({
                            "step_type": "capture_sensors",
                            "sensor_ids": [s.get("sensor_id") for s in screen_sensors],
                            "expected_screen_id": screen_id,
                            "description": f"Capture sensors on {screen.display_name or screen.activity}"
                        })

        # If we captured specific sensor IDs
        if sensor_ids and capture_mode == "sensors_only":
            steps = [s for s in steps if s.get("step_type") in ["launch_app", "wait", "capture_sensors"]]
            # Only keep capture_sensors steps with our sensor IDs
            steps = [s for s in steps if s.get("step_type") != "capture_sensors" or
                     any(sid in sensor_ids for sid in s.get("sensor_ids", []))]

        # Get stable device ID
        stable_device_id = None
        try:
            stable_device_id = await deps.adb_bridge.get_device_serial(device_id)
        except Exception:
            pass

        # Generate flow ID
        import uuid
        flow_id = f"smart_{uuid.uuid4().hex[:8]}"

        # Build flow data
        app_name = package_name.split(".")[-1].title()
        flow_data = {
            "flow_id": flow_id,
            "device_id": device_id,
            "stable_device_id": stable_device_id,
            "name": f"Smart Flow: {app_name}",
            "description": f"Auto-generated flow covering {len(visited_screens)} screens in {package_name}",
            "app_package": package_name,
            "steps": steps,
            "enabled": False,  # Start disabled for review
            "update_interval": 300,  # 5 minutes default
            "auto_wake_before": True,
            "auto_sleep_after": True
        }

        logger.info(f"[API] Generated smart flow with {len(steps)} steps for {package_name}")

        return {
            "success": True,
            "flow": flow_data,
            "screens_covered": len(visited_screens),
            "total_screens": len(screens),
            "sensors_found": len(sensors_for_app),
            "message": f"Generated flow covering {len(visited_screens)}/{len(screens)} screens with {len(steps)} steps"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Smart flow generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flows/generate-smart/save")
async def save_generated_smart_flow(flow_data: dict):
    """
    Save a generated smart flow after user review.

    Body:
        flow_data: The flow data from generate-smart endpoint (possibly modified by user)

    Returns:
        Saved flow
    """
    deps = get_deps()
    try:
        if not deps.flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        from flow_models import SensorCollectionFlow

        # Create flow from data
        flow = SensorCollectionFlow(**flow_data)
        deps.flow_manager.create_flow(flow)

        logger.info(f"[API] Saved smart flow {flow.flow_id}")

        return {
            "success": True,
            "flow": flow.dict(),
            "message": f"Smart flow '{flow.name}' saved successfully"
        }

    except Exception as e:
        logger.error(f"[API] Failed to save smart flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
