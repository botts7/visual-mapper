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

        return {"flows": [f.dict() for f in flows]}

    except Exception as e:
        logger.error(f"[API] Failed to list flows: {e}", exc_info=True)
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
