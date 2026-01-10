"""
Flow Service - Business logic for flow management
Handles validation, persistence (via FlowManager), and execution strategy (Hybrid/Standalone).

Phase 2 Refactor: Single Source of Truth for validation.
All step type schemas are defined here and exposed via /api/flow-schema endpoint.
"""

import logging
import asyncio
from typing import Dict, List, Optional, Any
from fastapi import HTTPException

from core.flows import SensorCollectionFlow, FlowStep, FlowExecutionResult
from services.device_identity import get_device_identity_resolver

logger = logging.getLogger(__name__)

# =============================================================================
# Phase 2: Centralized Step Type Schemas
# =============================================================================
# This is the SINGLE SOURCE OF TRUTH for step validation.
# Frontend should consume this via GET /api/flow-schema
# =============================================================================

STEP_SCHEMAS: Dict[str, Dict[str, Any]] = {
    # =========================================================================
    # App Control
    # =========================================================================
    "launch_app": {
        "name": "Launch App",
        "description": "Launch an Android app by package name",
        "required": ["package"],
        "optional": ["expected_activity", "description"],
        "fields": {
            "package": {"type": "string", "description": "Android package name (e.g., com.spotify.music)"},
            "expected_activity": {"type": "string", "description": "Expected activity after launch"},
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "restart_app": {
        "name": "Restart App",
        "description": "Force stop and relaunch an app",
        "required": ["package"],
        "optional": ["description"],
        "fields": {
            "package": {"type": "string", "description": "Android package name"},
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "go_home": {
        "name": "Go Home",
        "description": "Press the home button",
        "required": [],
        "optional": ["description"],
        "fields": {
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "go_back": {
        "name": "Go Back",
        "description": "Press the back button",
        "required": [],
        "optional": ["description"],
        "fields": {
            "description": {"type": "string", "description": "Step description"}
        }
    },

    # =========================================================================
    # Basic Gestures
    # =========================================================================
    "tap": {
        "name": "Tap",
        "description": "Tap at specific coordinates",
        "required": ["x", "y"],
        "optional": ["duration", "description", "screen_activity", "screen_package"],
        "fields": {
            "x": {"type": "integer", "description": "X coordinate"},
            "y": {"type": "integer", "description": "Y coordinate"},
            "duration": {"type": "integer", "description": "Tap duration in ms (for long press)"},
            "screen_activity": {"type": "string", "description": "Activity when recorded"},
            "screen_package": {"type": "string", "description": "Package when recorded"},
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "swipe": {
        "name": "Swipe",
        "description": "Swipe from one point to another",
        "required": ["start_x", "start_y", "end_x", "end_y"],
        "optional": ["duration", "description"],
        "fields": {
            "start_x": {"type": "integer", "description": "Start X coordinate"},
            "start_y": {"type": "integer", "description": "Start Y coordinate"},
            "end_x": {"type": "integer", "description": "End X coordinate"},
            "end_y": {"type": "integer", "description": "End Y coordinate"},
            "duration": {"type": "integer", "description": "Swipe duration in ms", "default": 300},
            "description": {"type": "string", "description": "Step description"}
        }
    },

    # =========================================================================
    # Timing
    # =========================================================================
    "wait": {
        "name": "Wait",
        "description": "Wait for a duration before next step",
        "required": ["duration"],
        "optional": ["description"],
        "fields": {
            "duration": {"type": "integer", "description": "Duration in milliseconds", "min": 100, "max": 60000},
            "description": {"type": "string", "description": "Step description"}
        }
    },

    # =========================================================================
    # Text Input
    # =========================================================================
    "text": {
        "name": "Text Input",
        "description": "Type text into a focused input field",
        "required": ["text"],
        "optional": ["description"],
        "fields": {
            "text": {"type": "string", "description": "Text to type"},
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "keyevent": {
        "name": "Key Event",
        "description": "Send an Android keycode",
        "required": ["keycode"],
        "optional": ["description"],
        "fields": {
            "keycode": {"type": "string", "description": "Android keycode (e.g., KEYCODE_ENTER, KEYCODE_BACK)"},
            "description": {"type": "string", "description": "Step description"}
        }
    },

    # =========================================================================
    # Sensor & Action
    # =========================================================================
    "capture_sensors": {
        "name": "Capture Sensors",
        "description": "Capture sensor values from the current screen",
        "required": ["sensor_ids"],
        "optional": ["description"],
        "fields": {
            "sensor_ids": {"type": "array", "items": "string", "description": "List of sensor IDs to capture"},
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "execute_action": {
        "name": "Execute Action",
        "description": "Execute a Home Assistant action",
        "required": ["action_id"],
        "optional": ["description"],
        "fields": {
            "action_id": {"type": "string", "description": "Action ID to execute"},
            "description": {"type": "string", "description": "Step description"}
        }
    },

    # =========================================================================
    # Screen Validation
    # =========================================================================
    "validate_screen": {
        "name": "Validate Screen",
        "description": "Verify the current screen matches expected state",
        "required": [],
        "optional": ["expected_activity", "expected_ui_elements", "validation_element", "state_match_threshold", "recovery_action", "ui_elements_required", "description"],
        "fields": {
            "expected_activity": {"type": "string", "description": "Expected Android activity name"},
            "expected_ui_elements": {"type": "array", "items": "object", "description": "Expected UI elements (text, class, resource-id)"},
            "validation_element": {"type": "object", "description": "Single element to verify presence"},
            "state_match_threshold": {"type": "number", "description": "Similarity threshold (0.0-1.0)", "default": 0.80},
            "recovery_action": {"type": "string", "enum": ["force_restart_app", "skip_step", "fail"], "default": "force_restart_app"},
            "ui_elements_required": {"type": "integer", "description": "Minimum elements that must match", "default": 1},
            "description": {"type": "string", "description": "Step description"}
        }
    },

    # =========================================================================
    # Conditional & Flow Control
    # =========================================================================
    "conditional": {
        "name": "Conditional",
        "description": "Execute different steps based on a condition",
        "required": ["condition"],
        "optional": ["true_steps", "false_steps", "description"],
        "fields": {
            "condition": {"type": "string", "description": "Condition to evaluate"},
            "true_steps": {"type": "array", "items": "FlowStep", "description": "Steps if condition is true"},
            "false_steps": {"type": "array", "items": "FlowStep", "description": "Steps if condition is false"},
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "loop": {
        "name": "Loop",
        "description": "Repeat a set of steps N times",
        "required": ["iterations", "loop_steps"],
        "optional": ["loop_variable", "description"],
        "fields": {
            "iterations": {"type": "integer", "description": "Number of iterations", "min": 1, "max": 100},
            "loop_steps": {"type": "array", "items": "FlowStep", "description": "Steps to repeat"},
            "loop_variable": {"type": "string", "description": "Variable name for loop counter"},
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "break_loop": {
        "name": "Break Loop",
        "description": "Exit the current loop early",
        "required": [],
        "optional": ["description"],
        "fields": {
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "continue_loop": {
        "name": "Continue Loop",
        "description": "Skip to next loop iteration",
        "required": [],
        "optional": ["description"],
        "fields": {
            "description": {"type": "string", "description": "Step description"}
        }
    },

    # =========================================================================
    # Variables
    # =========================================================================
    "set_variable": {
        "name": "Set Variable",
        "description": "Store a value in a variable",
        "required": ["variable_name", "variable_value"],
        "optional": ["description"],
        "fields": {
            "variable_name": {"type": "string", "description": "Variable name"},
            "variable_value": {"type": "string", "description": "Value to set (can include ${var} references)"},
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "increment": {
        "name": "Increment Variable",
        "description": "Increment a numeric variable",
        "required": ["variable_name"],
        "optional": ["increment_by", "description"],
        "fields": {
            "variable_name": {"type": "string", "description": "Variable name to increment"},
            "increment_by": {"type": "integer", "description": "Amount to increment by", "default": 1},
            "description": {"type": "string", "description": "Step description"}
        }
    },

    # =========================================================================
    # Screen Power Control (Headless Mode)
    # =========================================================================
    "wake_screen": {
        "name": "Wake Screen",
        "description": "Wake up the device screen",
        "required": [],
        "optional": ["description"],
        "fields": {
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "sleep_screen": {
        "name": "Sleep Screen",
        "description": "Turn off the device screen",
        "required": [],
        "optional": ["description"],
        "fields": {
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "ensure_screen_on": {
        "name": "Ensure Screen On",
        "description": "Verify screen is on, wake if needed",
        "required": [],
        "optional": ["description"],
        "fields": {
            "description": {"type": "string", "description": "Step description"}
        }
    },

    # =========================================================================
    # Special Actions
    # =========================================================================
    "pull_refresh": {
        "name": "Pull to Refresh",
        "description": "Perform a pull-to-refresh gesture",
        "required": [],
        "optional": ["validate_timestamp", "timestamp_element", "refresh_max_retries", "refresh_retry_delay", "description"],
        "fields": {
            "validate_timestamp": {"type": "boolean", "description": "Validate timestamp changed after refresh", "default": False},
            "timestamp_element": {"type": "object", "description": "Element containing timestamp"},
            "refresh_max_retries": {"type": "integer", "description": "Max refresh retries", "default": 3},
            "refresh_retry_delay": {"type": "integer", "description": "Delay between retries in ms", "default": 2000},
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "stitch_capture": {
        "name": "Stitch Capture",
        "description": "Capture and stitch multiple screenshots (server-side)",
        "required": [],
        "optional": ["sensor_ids", "description"],
        "fields": {
            "sensor_ids": {"type": "array", "items": "string", "description": "Sensors to capture from stitched view"},
            "description": {"type": "string", "description": "Step description"}
        }
    },
    "screenshot": {
        "name": "Screenshot",
        "description": "Capture a screenshot at current screen",
        "required": [],
        "optional": ["description"],
        "fields": {
            "description": {"type": "string", "description": "Step description"}
        }
    }
}

# Schema version for cache busting
SCHEMA_VERSION = "2.0.0"

class FlowService:
    def __init__(self, flow_manager, flow_executor, mqtt_manager=None, adb_bridge=None):
        self.flow_manager = flow_manager
        self.flow_executor = flow_executor
        self.mqtt_manager = mqtt_manager
        self.adb_bridge = adb_bridge

    async def create_flow(self, flow_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new flow with validation and hybrid checks.
        """
        # Validate required fields
        self._validate_flow_data(flow_data)

        # Get stable_device_id if not provided
        if not flow_data.get('stable_device_id') and flow_data.get('device_id') and self.adb_bridge:
            try:
                stable_id = await self.adb_bridge.get_device_serial(flow_data['device_id'])
                if stable_id:
                    flow_data['stable_device_id'] = stable_id
            except Exception as e:
                logger.warning(f"[FlowService] Failed to get stable ID for {flow_data.get('device_id')}: {e}")

        if flow_data.get('device_id') and flow_data.get('stable_device_id'):
            try:
                resolver = get_device_identity_resolver(str(self.flow_manager.data_dir))
                resolver.register_device(flow_data['device_id'], flow_data['stable_device_id'])
            except Exception as e:
                logger.warning(f"[FlowService] Failed to register device mapping: {e}")

        # Create flow object
        try:
            flow = SensorCollectionFlow(**flow_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid flow data: {e}")

        # Check hybrid status (warn if Android offline but flow requires it)
        warning = await self._check_hybrid_status(flow)

        # Save flow
        success = self.flow_manager.create_flow(flow)
        if not success:
            existing = self.flow_manager.get_flow(flow.device_id, flow.flow_id)
            if existing:
                logger.warning(f"[FlowService] Duplicate flow_id: {flow.flow_id} for {flow.device_id}")
                raise HTTPException(status_code=409, detail="Flow already exists")
            logger.error(f"[FlowService] Failed to create flow {flow.flow_id} for {flow.device_id}")
            raise HTTPException(status_code=500, detail="Failed to create flow (check server logs)")

        result = flow.dict()
        if warning:
            result['warning'] = warning
            
        return result

    async def update_flow(self, device_id: str, flow_id: str, flow_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing flow.
        """
        self._validate_flow_data(flow_data)

        # Create flow object
        try:
            flow = SensorCollectionFlow(**flow_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid flow data: {e}")

        # Ensure IDs match
        if flow.device_id != device_id or flow.flow_id != flow_id:
            raise HTTPException(status_code=400, detail="Flow ID mismatch")

        # Hybrid check
        warning = await self._check_hybrid_status(flow)

        # Update flow
        success = self.flow_manager.update_flow(flow)
        if not success:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        result = flow.dict()
        if warning:
            result['warning'] = warning
            
        return result

    def delete_flow(self, device_id: str, flow_id: str) -> bool:
        """
        Delete a flow.
        """
        success = self.flow_manager.delete_flow(device_id, flow_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")
        return True

    def get_flow(self, device_id: str, flow_id: str) -> Dict[str, Any]:
        """
        Get a flow.
        """
        flow = self.flow_manager.get_flow(device_id, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")
        return flow.dict()

    def list_flows(self, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List flows.
        """
        if device_id:
            flows = self.flow_manager.get_device_flows(device_id)
        else:
            flows = self.flow_manager.get_all_flows()
        return [f.dict() for f in flows]

    async def execute_flow(self, device_id: str, flow_id: str, execution_method: str = "auto", learn_mode: bool = False) -> Dict[str, Any]:
        """
        Phase 2: Execute a flow with proper execution routing.

        Execution Methods:
        - "server": Execute via ADB (flow_executor) - server controls device
        - "android": Execute via MQTT (companion app) - Android handles gestures
        - "auto": Smart routing based on flow settings and device status

        Auto Routing Logic:
        1. Use flow.execution_method if specified
        2. If "auto", prefer flow.preferred_executor
        3. Fall back to flow.fallback_executor if preferred fails
        4. Default to "server" if nothing specified

        Args:
            device_id: Device identifier
            flow_id: Flow identifier
            execution_method: Execution routing method
            learn_mode: If True, capture UI elements at each screen to improve navigation graph
        """
        if not self.flow_executor:
            raise HTTPException(status_code=503, detail="Flow executor not initialized")

        flow = self.flow_manager.get_flow(device_id, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        # Determine actual execution method
        actual_method = self._resolve_execution_method(flow, execution_method)

        # Check Android connectivity if needed for Android execution
        android_active = False
        if self.mqtt_manager:
            android_active = self.mqtt_manager.is_connected

        # If Android requested but offline, try fallback
        if actual_method == "android" and not android_active:
            fallback = getattr(flow, 'fallback_executor', 'server')
            logger.warning(f"Android offline for flow {flow_id}, falling back to {fallback}")

            if fallback == "android":
                # No fallback available
                raise HTTPException(status_code=503, detail="Android companion app is offline and no fallback available")
            actual_method = fallback

        # Execute based on resolved method
        logger.info(f"Executing flow {flow_id} via {actual_method} (requested: {execution_method}, learn_mode={learn_mode})")

        if actual_method == "android":
            result = await self._execute_via_mqtt(flow)
        else:
            # For server execution, ensure device is unlocked first (like scheduler does)
            await self._auto_unlock_if_needed(flow.device_id)
            # Default to server execution via ADB
            result = await self.flow_executor.execute_flow(flow, learn_mode=learn_mode)

        # Convert to dict
        response = {
            "flow_id": result.flow_id,
            "success": result.success,
            "executed_steps": result.executed_steps,
            "failed_step": result.failed_step,
            "error_message": result.error_message,
            "captured_sensors": result.captured_sensors,
            "step_results": [sr.dict() for sr in result.step_results] if result.step_results else [],
            "execution_time_ms": result.execution_time_ms,
            "timestamp": result.timestamp.isoformat() if result.timestamp else None,
            "android_active": android_active,
            "execution_method": actual_method
        }

        # Add learning stats if learn_mode was enabled
        if learn_mode and hasattr(result, 'learned_screens'):
            response["learned_screens"] = result.learned_screens

        return response

    def _resolve_execution_method(self, flow, requested_method: str) -> str:
        """
        Resolve the actual execution method based on request and flow settings.

        Priority:
        1. Explicit request (if not "auto")
        2. Flow's execution_method (if not "auto")
        3. Flow's preferred_executor
        4. Default to "server"
        """
        # If explicit method requested (not auto), use it
        if requested_method and requested_method != "auto":
            return requested_method

        # Check flow's own execution_method
        flow_method = getattr(flow, 'execution_method', 'auto')
        if flow_method and flow_method != "auto":
            return flow_method

        # Check preferred executor
        preferred = getattr(flow, 'preferred_executor', 'server')
        return preferred if preferred else 'server'

    async def _auto_unlock_if_needed(self, device_id: str) -> bool:
        """
        Ensure device is unlocked before flow execution.

        Always tries swipe-to-unlock if device is locked.
        Uses PIN/passcode if AUTO_UNLOCK strategy is configured.

        Returns True if device is ready (unlocked or successfully unlocked).
        Returns False if device is locked and couldn't be unlocked.
        """
        from utils.device_security import DeviceSecurityManager, LockStrategy
        from pathlib import Path
        import os

        # Use same DATA_DIR as main.py
        data_dir = Path(os.getenv("DATA_DIR", "./data"))
        security_manager = DeviceSecurityManager(data_dir=str(data_dir))

        # STEP 1: Check if device is locked (do this FIRST, before config check)
        try:
            is_locked = await self.adb_bridge.is_locked(device_id)
            if not is_locked:
                logger.debug(f"[FlowService] Device {device_id} already unlocked")
                return True
        except Exception as e:
            logger.warning(f"[FlowService] Could not check lock status: {e}")
            return True  # Continue anyway

        logger.info(f"[FlowService] Device {device_id} is LOCKED - attempting unlock")

        # STEP 2: Check security config
        security_config = security_manager.get_lock_config(device_id)

        # Also try stable_device_id if available
        if not security_config:
            try:
                stable_id = await self.adb_bridge.get_stable_device_id(device_id)
                if stable_id and stable_id != device_id:
                    security_config = security_manager.get_lock_config(stable_id)
                    if security_config:
                        logger.debug(f"[FlowService] Found security config via stable_device_id: {stable_id}")
            except Exception as e:
                logger.debug(f"[FlowService] Could not get stable_device_id: {e}")

        has_auto_unlock = security_config and security_config.get('strategy') == LockStrategy.AUTO_UNLOCK.value

        # DEBUG: Log security config status
        if security_config:
            logger.info(f"[FlowService] Security config found: strategy={security_config.get('strategy')}, has_auto_unlock={has_auto_unlock}")
        else:
            logger.warning(f"[FlowService] No security config found for device {device_id}")

        # STEP 3: Try swipe-to-unlock first (works for no-PIN devices)
        try:
            logger.info(f"[FlowService] Calling unlock_screen for {device_id}")
            await self.adb_bridge.unlock_screen(device_id)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f"[FlowService] Swipe unlock failed: {e}")

        # Check if unlocked after swipe
        is_locked = await self.adb_bridge.is_locked(device_id)
        if not is_locked:
            logger.info(f"[FlowService] Device unlocked via swipe")
            return True

        # STEP 4: Try PIN/passcode (only if AUTO_UNLOCK configured)
        if has_auto_unlock:
            passcode = security_manager.get_passcode(device_id)
            # Also try stable_device_id for passcode
            if not passcode:
                try:
                    stable_id = await self.adb_bridge.get_stable_device_id(device_id)
                    if stable_id and stable_id != device_id:
                        passcode = security_manager.get_passcode(stable_id)
                except:
                    pass
        else:
            passcode = None
            logger.debug(f"[FlowService] No AUTO_UNLOCK config - skipping PIN attempt")

        if passcode:
            logger.info(f"[FlowService] Found passcode, attempting PIN unlock for {device_id}")
            try:
                unlock_success = await self.adb_bridge.unlock_device(device_id, passcode)
                if unlock_success:
                    logger.info(f"[FlowService] Device unlocked with passcode")
                    return True
                else:
                    logger.warning(f"[FlowService] unlock_device returned False")
            except Exception as e:
                logger.error(f"[FlowService] Passcode unlock error: {e}")
        else:
            logger.warning(f"[FlowService] No passcode found for {device_id} (has_auto_unlock={has_auto_unlock})")

        # Final check
        is_locked = await self.adb_bridge.is_locked(device_id)
        if is_locked:
            logger.error(f"[FlowService] Failed to unlock device {device_id}")
            return False

        return True

    async def _execute_via_mqtt(self, flow) -> 'FlowExecutionResult':
        """
        Phase 2: Execute flow via MQTT to Android companion app.

        This sends the flow to the companion app which executes it locally
        using the AccessibilityService for gestures.
        """
        from core.flows import FlowExecutionResult, StepResult
        from datetime import datetime
        import asyncio
        import json

        if not self.mqtt_manager or not self.mqtt_manager.is_connected:
            raise HTTPException(status_code=503, detail="MQTT not connected")

        # Prepare flow payload for Android
        flow_payload = {
            "flow_id": flow.flow_id,
            "device_id": flow.device_id,
            "name": flow.name,
            "steps": [step.dict() if hasattr(step, 'dict') else step for step in flow.steps],
            "stop_on_error": flow.stop_on_error,
            "flow_timeout": flow.flow_timeout
        }

        # Publish execution request to MQTT
        topic = f"visual_mapper/{flow.device_id}/flow/{flow.flow_id}/execute"
        start_time = datetime.now()

        try:
            self.mqtt_manager.publish(topic, json.dumps(flow_payload))
            logger.info(f"Published flow execution request to {topic}")

            # For now, return a pending result
            # In a full implementation, we'd wait for a response via MQTT callback
            # or use a result queue

            return FlowExecutionResult(
                flow_id=flow.flow_id,
                success=True,  # Optimistic - actual result comes via MQTT callback
                executed_steps=0,
                failed_step=None,
                error_message=None,
                captured_sensors={},
                step_results=[],
                execution_time_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                timestamp=datetime.now()
            )

        except Exception as e:
            logger.error(f"Failed to execute flow via MQTT: {e}")
            return FlowExecutionResult(
                flow_id=flow.flow_id,
                success=False,
                executed_steps=0,
                failed_step=0,
                error_message=f"MQTT execution failed: {str(e)}",
                captured_sensors={},
                step_results=[],
                execution_time_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                timestamp=datetime.now()
            )

    def _validate_flow_data(self, flow_data: Dict[str, Any]):
        """
        Phase 2: Comprehensive validation using STEP_SCHEMAS.

        Validates:
        1. Required flow fields (flow_id, device_id, steps)
        2. Each step has a valid step_type from STEP_SCHEMAS
        3. Each step has all required fields for its type
        4. Field values are of correct types
        """
        if not flow_data.get('flow_id'):
            raise HTTPException(status_code=400, detail="flow_id is required")
        if not flow_data.get('device_id'):
            raise HTTPException(status_code=400, detail="device_id is required")
        if not flow_data.get('steps') or len(flow_data.get('steps')) == 0:
            raise HTTPException(status_code=400, detail="Flow must have at least one step")

        # Validate each step against STEP_SCHEMAS
        for i, step in enumerate(flow_data.get('steps', [])):
            step_num = i + 1
            step_type = step.get('step_type')

            # Check step_type exists
            if not step_type:
                raise HTTPException(
                    status_code=400,
                    detail=f"Step {step_num}: missing step_type"
                )

            # Check step_type is valid
            schema = STEP_SCHEMAS.get(step_type)
            if not schema:
                valid_types = ", ".join(sorted(STEP_SCHEMAS.keys()))
                raise HTTPException(
                    status_code=400,
                    detail=f"Step {step_num}: unknown step_type '{step_type}'. Valid types: {valid_types}"
                )

            # Check required fields
            for field in schema.get('required', []):
                value = step.get(field)
                if value is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Step {step_num} ({step_type}): missing required field '{field}'"
                    )

                # Type validation for required fields
                field_def = schema.get('fields', {}).get(field, {})
                field_type = field_def.get('type')

                if field_type == 'integer' and not isinstance(value, (int, float)):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Step {step_num} ({step_type}): field '{field}' must be an integer"
                    )
                elif field_type == 'string' and not isinstance(value, str):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Step {step_num} ({step_type}): field '{field}' must be a string"
                    )
                elif field_type == 'array' and not isinstance(value, list):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Step {step_num} ({step_type}): field '{field}' must be an array"
                    )

                # Min/max validation for integers
                if field_type == 'integer' and isinstance(value, (int, float)):
                    min_val = field_def.get('min')
                    max_val = field_def.get('max')
                    if min_val is not None and value < min_val:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Step {step_num} ({step_type}): field '{field}' must be >= {min_val}"
                        )
                    if max_val is not None and value > max_val:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Step {step_num} ({step_type}): field '{field}' must be <= {max_val}"
                        )

                # Enum validation
                enum_values = field_def.get('enum')
                if enum_values and value not in enum_values:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Step {step_num} ({step_type}): field '{field}' must be one of {enum_values}"
                    )

            # Recursively validate nested steps (for conditional, loop)
            if step_type == 'conditional':
                for nested_steps_field in ['true_steps', 'false_steps']:
                    nested_steps = step.get(nested_steps_field)
                    if nested_steps:
                        nested_flow_data = {'flow_id': 'nested', 'device_id': 'nested', 'steps': nested_steps}
                        try:
                            self._validate_flow_data(nested_flow_data)
                        except HTTPException as e:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Step {step_num} ({step_type}).{nested_steps_field}: {e.detail}"
                            )

            if step_type == 'loop':
                loop_steps = step.get('loop_steps')
                if loop_steps:
                    nested_flow_data = {'flow_id': 'nested', 'device_id': 'nested', 'steps': loop_steps}
                    try:
                        self._validate_flow_data(nested_flow_data)
                    except HTTPException as e:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Step {step_num} ({step_type}).loop_steps: {e.detail}"
                        )

        logger.debug(f"Flow validation passed: {len(flow_data.get('steps', []))} steps")

    def get_step_schema(self) -> Dict[str, Any]:
        """
        Phase 2: Return the step type schema for frontend consumption.

        The frontend should call GET /api/flow-schema to get this data
        and dynamically render forms based on the schema.
        """
        return {
            "version": SCHEMA_VERSION,
            "step_types": STEP_SCHEMAS,
            "categories": {
                "app_control": ["launch_app", "restart_app", "go_home", "go_back"],
                "gestures": ["tap", "swipe"],
                "timing": ["wait"],
                "input": ["text", "keyevent"],
                "sensors": ["capture_sensors", "execute_action"],
                "validation": ["validate_screen"],
                "flow_control": ["conditional", "loop", "break_loop", "continue_loop"],
                "variables": ["set_variable", "increment"],
                "screen_power": ["wake_screen", "sleep_screen", "ensure_screen_on"],
                "special": ["pull_refresh", "stitch_capture", "screenshot"]
            }
        }

    async def _check_hybrid_status(self, flow: SensorCollectionFlow) -> Optional[str]:
        """
        Check if flow requires Android interaction and if device is online.
        Returns a warning message if offline, or None if OK.
        """
        requires_android = any(step.step_type in ['capture_sensors', 'execute_action'] for step in flow.steps)
        
        if requires_android and self.mqtt_manager:
            # Check if MQTT is connected (global check for now)
            # Ideal: check if specific device sent heartbeat recently
            if not self.mqtt_manager.is_connected:
                return "Flow saved, but Android device is offline. Sync required for sensor steps."
        
        return None
