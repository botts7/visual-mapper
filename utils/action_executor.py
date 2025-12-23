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
        action_id: str
    ) -> ActionExecutionResult:
        """
        Execute a saved action by ID and record result

        Args:
            action_manager: ActionManager instance
            device_id: Device ID
            action_id: Action ID

        Returns:
            ActionExecutionResult

        Raises:
            ActionNotFoundError: If action not found
        """
        # Get action definition
        action_def = action_manager.get_action(device_id, action_id)

        # Execute action
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

                    # Create action instance
                    step_action = action_class(**action_dict)

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
