"""
Action Executor for Visual Mapper

Executes device actions defined in action_models.py using ADB bridge.
Handles all action types including macros.
"""

import asyncio
import logging
import time
from typing import Optional, List, Dict, Any

from utils.action_models import (
    ActionType,
    ActionDefinition,
    ActionExecutionResult,
    TapAction,
    SwipeAction,
    TextInputAction,
    KeyEventAction,
    LaunchAppAction,
    DelayAction,
    MacroAction,
)
from utils.error_handler import (
    VisualMapperError,
    logger,
    ErrorContext,
    DeviceNotFoundError,
    ActionExecutionError
)

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Executes device actions via ADB bridge"""

    def __init__(self, adb_bridge):
        """
        Initialize Action Executor

        Args:
            adb_bridge: ADBBridge instance for device communication
        """
        self.adb_bridge = adb_bridge
        logger.info("[ActionExecutor] Initialized")

    async def execute_action(
        self,
        action: ActionType,
        record_result: bool = False
    ) -> ActionExecutionResult:
        """
        Execute a single action

        Args:
            action: Action to execute (any ActionType)
            record_result: Whether to record execution result (for saved actions)

        Returns:
            ActionExecutionResult with success status and timing

        Raises:
            ActionExecutionError: If execution fails
            DeviceNotFoundError: If device not connected
        """
        start_time = time.time()

        try:
            # Verify device is connected
            if action.device_id not in self.adb_bridge.devices:
                raise DeviceNotFoundError(action.device_id)

            # Check if action is enabled
            if not action.enabled:
                raise ActionExecutionError(
                    f"Action '{action.name}' is disabled",
                    action_type=action.action_type
                )

            logger.info(f"[ActionExecutor] Executing {action.action_type} action '{action.name}' on {action.device_id}")

            # Route to specific handler based on action type
            if action.action_type == "tap":
                await self._execute_tap(action)
            elif action.action_type == "swipe":
                await self._execute_swipe(action)
            elif action.action_type == "text":
                await self._execute_text_input(action)
            elif action.action_type == "keyevent":
                await self._execute_keyevent(action)
            elif action.action_type == "launch_app":
                await self._execute_launch_app(action)
            elif action.action_type == "delay":
                await self._execute_delay(action)
            elif action.action_type == "macro":
                await self._execute_macro(action)
            else:
                raise ActionExecutionError(
                    f"Unknown action type: {action.action_type}",
                    action_type=action.action_type
                )

            # Calculate execution time
            execution_time = (time.time() - start_time) * 1000  # Convert to ms

            result = ActionExecutionResult(
                success=True,
                message=f"Action '{action.name}' executed successfully",
                execution_time=execution_time,
                action_type=action.action_type,
                details={
                    "device_id": action.device_id,
                    "action_name": action.name
                }
            )

            logger.info(f"[ActionExecutor] ✅ Action executed in {execution_time:.1f}ms")
            return result

        except DeviceNotFoundError:
            # Re-raise device errors
            raise

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000

            logger.error(f"[ActionExecutor] ❌ Action execution failed: {e}")

            # Return failure result
            result = ActionExecutionResult(
                success=False,
                message=f"Action execution failed: {str(e)}",
                execution_time=execution_time,
                action_type=action.action_type,
                details={
                    "device_id": action.device_id,
                    "action_name": action.name,
                    "error": str(e)
                }
            )

            return result

    async def execute_action_by_id(
        self,
        action_manager,
        device_id: str,
        action_id: str,
        skip_navigation: bool = False
    ) -> ActionExecutionResult:
        """
        Execute a saved action by ID and record result.

        If the action has navigation config (target_app, prerequisite_actions,
        navigation_sequence), it will navigate to the correct screen first.

        Args:
            action_manager: ActionManager instance
            device_id: Device ID
            action_id: Action ID
            skip_navigation: If True, skip navigation even if action has nav config.
                           Use this when executing from within a flow that already
                           navigated to the correct screen.

        Returns:
            ActionExecutionResult

        Raises:
            ActionNotFoundError: If action not found
        """
        # Get action definition
        action_def = action_manager.get_action(device_id, action_id)

        # Check if action has navigation config (and we should use it)
        has_navigation = (
            action_def.target_app or
            action_def.prerequisite_actions or
            action_def.navigation_sequence
        )

        if has_navigation and not skip_navigation:
            # Execute with navigation wrapper
            logger.info(f"[ActionExecutor] Action has navigation config, navigating first")
            result = await self._execute_with_navigation(action_def, action_manager)
        elif has_navigation and skip_navigation:
            # Called from flow context - check if we're already on correct screen
            # If validation_element is set, verify we're on the right screen
            # If not, still run navigation (flow may have navigated to wrong place)
            if action_def.validation_element:
                already_on_screen = await self._validate_screen(
                    action_def.action.device_id,
                    action_def.validation_element,
                    max_attempts=1,  # Quick check, no retries
                    timeout=1
                )
                if already_on_screen:
                    logger.debug(f"[ActionExecutor] Already on correct screen, skipping navigation")
                    result = await self.execute_action(action_def.action)
                else:
                    logger.info(f"[ActionExecutor] Not on correct screen, running navigation anyway")
                    result = await self._execute_with_navigation(action_def, action_manager)
            else:
                # No validation element - trust the flow got us there
                logger.debug(f"[ActionExecutor] Skipping navigation (called from flow context)")
                result = await self.execute_action(action_def.action)
        else:
            # No navigation config - direct execution (backward compatible)
            result = await self.execute_action(action_def.action)

        # Record execution result
        action_manager.record_execution(
            device_id,
            action_id,
            result.success,
            result.message
        )

        # Add action_id to result
        result.action_id = action_id

        return result

    async def _execute_with_navigation(
        self,
        action_def: ActionDefinition,
        action_manager
    ) -> ActionExecutionResult:
        """
        Execute action with navigation steps.

        Process:
        1. Launch target app (if specified)
        2. Execute prerequisite actions
        3. Execute navigation sequence
        4. Validate correct screen (if specified)
        5. Execute the actual action
        6. Return home (if specified)

        Args:
            action_def: Action definition with navigation config
            action_manager: ActionManager for looking up prerequisite actions

        Returns:
            ActionExecutionResult
        """
        device_id = action_def.action.device_id
        start_time = time.time()

        try:
            # Step 1: Launch target app if specified
            if action_def.target_app:
                logger.info(f"[ActionExecutor] Launching target app: {action_def.target_app}")
                success = await self.adb_bridge.launch_app(device_id, action_def.target_app)
                if not success:
                    raise ActionExecutionError(
                        f"Failed to launch target app: {action_def.target_app}",
                        action_type=action_def.action.action_type
                    )
                await asyncio.sleep(2)  # Wait for app to load

            # Step 2: Execute prerequisite actions
            for prereq_id in action_def.prerequisite_actions:
                logger.info(f"[ActionExecutor] Executing prerequisite action: {prereq_id}")
                try:
                    prereq_def = action_manager.get_action(device_id, prereq_id)
                    prereq_result = await self.execute_action(prereq_def.action)
                    if not prereq_result.success:
                        raise ActionExecutionError(
                            f"Prerequisite action {prereq_id} failed: {prereq_result.message}",
                            action_type=action_def.action.action_type
                        )
                    await asyncio.sleep(0.5)  # Brief delay between actions
                except Exception as e:
                    logger.warning(f"[ActionExecutor] Prerequisite action {prereq_id} failed: {e}")
                    # Continue with other prerequisites

            # Step 3: Execute navigation sequence
            if action_def.navigation_sequence:
                logger.info(f"[ActionExecutor] Executing {len(action_def.navigation_sequence)} navigation steps")
                for i, nav_step in enumerate(action_def.navigation_sequence):
                    await self._execute_navigation_step(device_id, nav_step)
                    logger.debug(f"[ActionExecutor] Navigation step {i+1} complete")

            # Step 4: Validate screen if specified
            if action_def.validation_element:
                logger.info(f"[ActionExecutor] Validating screen...")
                validated = await self._validate_screen(
                    device_id,
                    action_def.validation_element,
                    action_def.max_navigation_attempts,
                    action_def.navigation_timeout
                )
                if not validated:
                    raise ActionExecutionError(
                        "Screen validation failed - not on expected screen",
                        action_type=action_def.action.action_type
                    )

            # Step 5: Execute the actual action
            logger.info(f"[ActionExecutor] Executing action: {action_def.action.name}")
            result = await self.execute_action(action_def.action)

            # Step 6: Return home if specified
            if action_def.return_home_after:
                logger.info(f"[ActionExecutor] Returning to home screen")
                await self.adb_bridge.keyevent(device_id, "KEYCODE_HOME")

            return result

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"[ActionExecutor] Navigation execution failed: {e}")
            return ActionExecutionResult(
                success=False,
                message=f"Navigation failed: {str(e)}",
                execution_time=execution_time,
                action_type=action_def.action.action_type,
                details={"error": str(e)}
            )

    async def _execute_navigation_step(self, device_id: str, step: Dict[str, Any]) -> None:
        """
        Execute a single navigation step.

        Supported step types: tap, swipe, wait, keyevent, text

        Args:
            device_id: Target device
            step: Step configuration dict with step_type and params
        """
        step_type = step.get("step_type", "").lower()

        if step_type == "tap":
            await self.adb_bridge.tap(device_id, step["x"], step["y"])
        elif step_type == "swipe":
            await self.adb_bridge.swipe(
                device_id,
                step["start_x"], step["start_y"],
                step["end_x"], step["end_y"],
                step.get("duration", 300)
            )
        elif step_type == "wait":
            duration_ms = step.get("duration", 1000)
            await asyncio.sleep(duration_ms / 1000.0)
        elif step_type == "keyevent":
            await self.adb_bridge.keyevent(device_id, step["keycode"])
        elif step_type == "text":
            await self.adb_bridge.type_text(device_id, step["text"])
        else:
            logger.warning(f"[ActionExecutor] Unknown navigation step type: {step_type}")

    async def _validate_screen(
        self,
        device_id: str,
        validation_element: Dict[str, Any],
        max_attempts: int,
        timeout: int
    ) -> bool:
        """
        Validate that the correct screen is displayed.

        Args:
            device_id: Target device
            validation_element: Element to search for (text, class, resource_id)
            max_attempts: Max validation attempts
            timeout: Total timeout in seconds

        Returns:
            True if validation passed, False otherwise
        """
        poll_interval = timeout / max_attempts

        for attempt in range(max_attempts):
            try:
                # Get UI hierarchy
                ui_elements = await self.adb_bridge.get_ui_elements(device_id, bounds_only=False)

                # Search for validation element
                expected_text = validation_element.get("text")
                expected_class = validation_element.get("class")
                expected_resource_id = validation_element.get("resource_id")

                for element in ui_elements:
                    # Check text match
                    if expected_text and expected_text in element.get("text", ""):
                        logger.debug(f"[ActionExecutor] Validation passed: found text '{expected_text}'")
                        return True

                    # Check resource_id match
                    if expected_resource_id and expected_resource_id in element.get("resource_id", ""):
                        logger.debug(f"[ActionExecutor] Validation passed: found resource_id '{expected_resource_id}'")
                        return True

                    # Check class match (with text)
                    if expected_class and expected_text:
                        if element.get("class") == expected_class and expected_text in element.get("text", ""):
                            logger.debug(f"[ActionExecutor] Validation passed: found {expected_class} with text")
                            return True

                logger.debug(f"[ActionExecutor] Validation attempt {attempt+1}/{max_attempts} - element not found")

            except Exception as e:
                logger.warning(f"[ActionExecutor] Validation error: {e}")

            # Wait before next attempt
            if attempt < max_attempts - 1:
                await asyncio.sleep(poll_interval)

        return False

    # Individual action handlers

    async def _execute_tap(self, action: TapAction) -> None:
        """Execute tap action"""
        with ErrorContext("executing tap action", ActionExecutionError):
            await self.adb_bridge.tap(action.device_id, action.x, action.y)
            logger.debug(f"[ActionExecutor] Tapped at ({action.x}, {action.y})")

    async def _execute_swipe(self, action: SwipeAction) -> None:
        """Execute swipe action"""
        with ErrorContext("executing swipe action", ActionExecutionError):
            await self.adb_bridge.swipe(
                action.device_id,
                action.x1, action.y1,
                action.x2, action.y2,
                action.duration
            )
            logger.debug(f"[ActionExecutor] Swiped from ({action.x1},{action.y1}) to ({action.x2},{action.y2})")

    async def _execute_text_input(self, action: TextInputAction) -> None:
        """Execute text input action"""
        with ErrorContext("executing text input action", ActionExecutionError):
            await self.adb_bridge.type_text(action.device_id, action.text)
            logger.debug(f"[ActionExecutor] Typed text: {action.text[:50]}")

    async def _execute_keyevent(self, action: KeyEventAction) -> None:
        """Execute key event action"""
        with ErrorContext("executing keyevent action", ActionExecutionError):
            await self.adb_bridge.keyevent(action.device_id, action.keycode)
            logger.debug(f"[ActionExecutor] Key event: {action.keycode}")

    async def _execute_launch_app(self, action: LaunchAppAction) -> None:
        """Execute app launch action"""
        with ErrorContext("executing launch app action", ActionExecutionError):
            success = await self.adb_bridge.launch_app(action.device_id, action.package_name)
            if not success:
                raise ActionExecutionError(
                    f"Failed to launch app: {action.package_name}",
                    action_type="launch_app"
                )
            logger.debug(f"[ActionExecutor] Launched app: {action.package_name}")

    async def _execute_delay(self, action: DelayAction) -> None:
        """Execute delay action"""
        logger.debug(f"[ActionExecutor] Delaying for {action.duration}ms")
        await asyncio.sleep(action.duration / 1000.0)  # Convert ms to seconds

    async def _execute_macro(self, action: MacroAction) -> None:
        """
        Execute macro action (sequence of actions)

        Note: Macro actions contain a list of action dicts, not ActionType objects.
        We need to deserialize each one and execute it.
        """
        with ErrorContext("executing macro action", ActionExecutionError):
            logger.info(f"[ActionExecutor] Executing macro '{action.name}' with {len(action.actions)} steps")

            for i, action_dict in enumerate(action.actions):
                try:
                    # Deserialize action dict to ActionType
                    # The action_dict should have 'action_type' field
                    action_type = action_dict.get("action_type")

                    if not action_type:
                        raise ActionExecutionError(
                            f"Macro step {i+1} missing action_type",
                            action_type="macro"
                        )

                    # Import action models to deserialize
                    from utils.action_models import (
                        TapAction, SwipeAction, TextInputAction,
                        KeyEventAction, LaunchAppAction, DelayAction
                    )

                    # Map action_type to class
                    action_classes = {
                        "tap": TapAction,
                        "swipe": SwipeAction,
                        "text": TextInputAction,
                        "keyevent": KeyEventAction,
                        "launch_app": LaunchAppAction,
                        "delay": DelayAction,
                    }

                    action_class = action_classes.get(action_type)
                    if not action_class:
                        raise ActionExecutionError(
                            f"Unknown action type in macro: {action_type}",
                            action_type="macro"
                        )

                    # Normalize field names between flow format and action format
                    # Flow format: start_x/start_y/end_x/end_y, Action format: x1/y1/x2/y2
                    normalized_dict = dict(action_dict)
                    if action_type == "swipe":
                        # Convert flow format to action format if needed
                        if "start_x" in normalized_dict and "x1" not in normalized_dict:
                            normalized_dict["x1"] = normalized_dict.pop("start_x")
                        if "start_y" in normalized_dict and "y1" not in normalized_dict:
                            normalized_dict["y1"] = normalized_dict.pop("start_y")
                        if "end_x" in normalized_dict and "x2" not in normalized_dict:
                            normalized_dict["x2"] = normalized_dict.pop("end_x")
                        if "end_y" in normalized_dict and "y2" not in normalized_dict:
                            normalized_dict["y2"] = normalized_dict.pop("end_y")
                        # Remove step_type if present (flow format uses step_type)
                        normalized_dict.pop("step_type", None)

                    # Create action instance
                    step_action = action_class(**normalized_dict)

                    # Execute step
                    logger.debug(f"[ActionExecutor] Macro step {i+1}/{len(action.actions)}: {action_type}")
                    await self.execute_action(step_action)

                except Exception as e:
                    error_msg = f"Macro step {i+1} failed: {e}"
                    logger.error(f"[ActionExecutor] {error_msg}")

                    if action.stop_on_error:
                        raise ActionExecutionError(error_msg, action_type="macro")
                    else:
                        # Continue execution even if step fails
                        logger.warning(f"[ActionExecutor] Continuing macro despite error")

            logger.info(f"[ActionExecutor] ✅ Macro '{action.name}' completed")

    # Batch execution

    async def execute_multiple(
        self,
        actions: List[ActionType],
        stop_on_error: bool = False
    ) -> List[ActionExecutionResult]:
        """
        Execute multiple actions sequentially

        Args:
            actions: List of actions to execute
            stop_on_error: Stop execution if any action fails

        Returns:
            List of ActionExecutionResults (one per action)
        """
        results = []

        logger.info(f"[ActionExecutor] Executing {len(actions)} actions sequentially")

        for i, action in enumerate(actions):
            try:
                result = await self.execute_action(action)
                results.append(result)

                if not result.success and stop_on_error:
                    logger.warning(f"[ActionExecutor] Stopping batch execution at action {i+1} due to failure")
                    break

            except Exception as e:
                logger.error(f"[ActionExecutor] Batch execution error at action {i+1}: {e}")

                # Create error result
                error_result = ActionExecutionResult(
                    success=False,
                    message=str(e),
                    execution_time=0,
                    action_type=action.action_type,
                    details={"error": str(e)}
                )
                results.append(error_result)

                if stop_on_error:
                    logger.warning(f"[ActionExecutor] Stopping batch execution at action {i+1} due to error")
                    break

        logger.info(f"[ActionExecutor] Batch execution complete: {len(results)} actions executed")
        return results
