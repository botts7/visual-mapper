"""
Action Management Routes - Home Assistant Action Creation and Execution

Provides endpoints for managing and executing Android UI actions:
- CRUD operations for actions (create, read, update, delete)
- Action execution (saved or inline actions)
- Import/export actions for backup and sharing
- MQTT integration for Home Assistant action discovery

Actions support comprehensive HA action types: button, switch, number, text,
select, scene, and custom automations.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import logging
from routes import get_deps
from utils.action_models import (
    ActionCreateRequest,
    ActionUpdateRequest,
    ActionExecutionRequest,
    ActionListResponse
)
from utils.error_handler import handle_api_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/actions", tags=["actions"])


# =============================================================================
# ACTION CRUD ENDPOINTS
# =============================================================================

@router.get("")
async def get_all_actions():
    """Get all actions across all devices (for dashboard stats)"""
    deps = get_deps()
    try:
        logger.info("[API] Getting all actions")
        # list_actions() without device_id returns all actions across all devices
        all_actions = deps.action_manager.list_actions()
        return [a.dict() for a in all_actions]
    except Exception as e:
        logger.error(f"[API] Get all actions failed: {e}")
        return {"error": str(e), "actions": []}


@router.post("")
async def create_action(request: ActionCreateRequest, device_id: str = Query(..., description="Device ID")):
    """Create a new action for a device"""
    deps = get_deps()
    try:
        logger.info(f"[API] Creating action for device {device_id}")

        action_def = deps.action_manager.create_action(
            device_id=device_id,
            action=request.action,
            tags=request.tags,
            source_app=request.source_app,
            # Navigation configuration (optional)
            target_app=request.target_app,
            prerequisite_actions=request.prerequisite_actions,
            navigation_sequence=request.navigation_sequence,
            validation_element=request.validation_element,
            return_home_after=request.return_home_after,
            max_navigation_attempts=request.max_navigation_attempts,
            navigation_timeout=request.navigation_timeout
        )

        # Publish MQTT discovery to Home Assistant
        mqtt_published = False
        if deps.mqtt_manager and deps.mqtt_manager.is_connected:
            try:
                mqtt_published = await deps.mqtt_manager.publish_action_discovery(action_def)
                if mqtt_published:
                    logger.info(f"[API] Published MQTT discovery for action {action_def.id}")
                else:
                    logger.warning(f"[API] Failed to publish MQTT discovery for {action_def.id}")
            except Exception as e:
                logger.error(f"[API] MQTT discovery failed for {action_def.id}: {e}")

        return {
            "success": True,
            "action": action_def.dict(),
            "mqtt_published": mqtt_published
        }
    except Exception as e:
        logger.error(f"[API] Create action failed: {e}")
        return handle_api_error(e)


@router.get("/{device_id}")
async def list_actions(device_id: str):
    """List all actions for a device"""
    deps = get_deps()
    try:
        logger.info(f"[API] Listing actions for device {device_id}")
        actions = deps.action_manager.list_actions(device_id)

        return ActionListResponse(
            actions=actions,
            total=len(actions),
            device_id=device_id
        )
    except Exception as e:
        logger.error(f"[API] List actions failed: {e}")
        return handle_api_error(e)


# =============================================================================
# IMPORT/EXPORT
# =============================================================================

@router.get("/export/{device_id}")
async def export_actions(device_id: str):
    """Export all actions for a device as JSON"""
    deps = get_deps()
    try:
        logger.info(f"[API] Exporting actions for device {device_id}")
        actions = deps.action_manager.list_actions(device_id)

        return {
            "success": True,
            "device_id": device_id,
            "actions": [action.dict() for action in actions],
            "count": len(actions)
        }
    except Exception as e:
        logger.error(f"[API] Export actions failed: {e}")
        return handle_api_error(e)


@router.post("/import/{device_id}")
async def import_actions(device_id: str, actions: list):
    """Import actions from JSON

    Request body:
    {
        "actions": [
            {
                "action": {...},
                "tags": [...]
            },
            ...
        ]
    }
    """
    deps = get_deps()
    try:
        logger.info(f"[API] Importing {len(actions)} actions for device {device_id}")

        imported_count = 0
        failed_count = 0

        for action_data in actions:
            try:
                action_def = deps.action_manager.create_action(
                    device_id=device_id,
                    action=action_data.get("action"),
                    tags=action_data.get("tags", [])
                )

                # Publish MQTT discovery for imported action
                if deps.mqtt_manager and deps.mqtt_manager.is_connected:
                    await deps.mqtt_manager.publish_action_discovery(action_def)

                imported_count += 1
            except Exception as e:
                logger.error(f"[API] Failed to import action: {e}")
                failed_count += 1

        return {
            "success": True,
            "device_id": device_id,
            "imported_count": imported_count,
            "failed_count": failed_count,
            "total": len(actions)
        }
    except Exception as e:
        logger.error(f"[API] Import actions failed: {e}")
        return handle_api_error(e)


@router.get("/{device_id}/{action_id}")
async def get_action(device_id: str, action_id: str):
    """Get a specific action"""
    deps = get_deps()
    try:
        logger.info(f"[API] Getting action {action_id} for device {device_id}")
        action_def = deps.action_manager.get_action(device_id, action_id)

        if not action_def:
            raise HTTPException(status_code=404, detail=f"Action {action_id} not found")

        return {
            "success": True,
            "action": action_def.dict()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Get action failed: {e}")
        return handle_api_error(e)


@router.put("/{device_id}/{action_id}")
async def update_action(device_id: str, action_id: str, request: ActionUpdateRequest):
    """Update an existing action"""
    deps = get_deps()
    try:
        logger.info(f"[API] Updating action {action_id} for device {device_id}")

        updated_action = deps.action_manager.update_action(
            device_id=device_id,
            action_id=action_id,
            action=request.action,
            tags=request.tags,
            # Navigation configuration (all optional for partial updates)
            target_app=request.target_app,
            prerequisite_actions=request.prerequisite_actions,
            navigation_sequence=request.navigation_sequence,
            validation_element=request.validation_element,
            return_home_after=request.return_home_after,
            max_navigation_attempts=request.max_navigation_attempts,
            navigation_timeout=request.navigation_timeout
        )

        # Republish MQTT discovery to update Home Assistant
        mqtt_updated = False
        if deps.mqtt_manager and deps.mqtt_manager.is_connected:
            try:
                mqtt_updated = await deps.mqtt_manager.publish_action_discovery(updated_action)
                if mqtt_updated:
                    logger.info(f"[API] Republished MQTT discovery for {action_id}")
                else:
                    logger.warning(f"[API] Failed to republish MQTT discovery for {action_id}")
            except Exception as e:
                logger.error(f"[API] MQTT republish failed for {action_id}: {e}")

        return {
            "success": True,
            "action": updated_action.dict(),
            "mqtt_updated": mqtt_updated
        }
    except Exception as e:
        logger.error(f"[API] Update action failed: {e}")
        return handle_api_error(e)


@router.delete("/{device_id}/{action_id}")
async def delete_action(device_id: str, action_id: str):
    """Delete an action and remove from Home Assistant"""
    deps = get_deps()
    try:
        logger.info(f"[API] Deleting action {action_id} for device {device_id}")

        # Get action before deleting (need it for MQTT removal)
        action_def = deps.action_manager.get_action(device_id, action_id)
        if not action_def:
            raise HTTPException(status_code=404, detail=f"Action {action_id} not found")

        # Remove from Home Assistant via MQTT (if MQTT is enabled)
        mqtt_removed = False
        if deps.mqtt_manager and deps.mqtt_manager.is_connected:
            try:
                mqtt_removed = await deps.mqtt_manager.remove_action_discovery(action_def)
                if mqtt_removed:
                    logger.info(f"[API] Removed action {action_id} from Home Assistant")
                else:
                    logger.warning(f"[API] Failed to remove action {action_id} from Home Assistant")
            except Exception as e:
                logger.error(f"[API] MQTT removal failed for {action_id}: {e}")

        # Delete from local storage
        deps.action_manager.delete_action(device_id, action_id)

        return {
            "success": True,
            "message": f"Action {action_id} deleted" + (" and removed from Home Assistant" if mqtt_removed else ""),
            "mqtt_removed": mqtt_removed
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Delete action failed: {e}")
        return handle_api_error(e)


# =============================================================================
# ACTION EXECUTION
# =============================================================================

@router.post("/execute")
async def execute_action_endpoint(request: ActionExecutionRequest, device_id: str):
    """Execute an action (saved or inline)

    Can execute either:
    - A saved action by action_id
    - An inline action definition

    Request body:
    {
        "action_id": "optional-saved-action-id",
        "action": {
            "type": "tap",
            "target": {...},
            ...
        }
    }
    """
    deps = get_deps()
    try:
        logger.info(f"[API] Executing action for device {device_id}")

        if request.action_id:
            # Execute saved action by ID
            logger.info(f"[API] Executing saved action {request.action_id}")
            result = await deps.action_executor.execute_action_by_id(
                deps.action_manager, device_id, request.action_id
            )
        else:
            # Execute inline action
            logger.info(f"[API] Executing inline action: {request.action.action_type}")
            result = await deps.action_executor.execute_action(request.action)

        return result.dict()
    except Exception as e:
        logger.error(f"[API] Execute action failed: {e}")
        return handle_api_error(e)

