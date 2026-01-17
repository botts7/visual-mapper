"""
Visual Mapper - Flow Executor (Phase 8)
Unified execution engine for sensor collection flows
"""

import logging
import asyncio
import time
import uuid
import os
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from PIL import Image
import io

from .flow_models import (
    SensorCollectionFlow,
    FlowStep,
    FlowStepType,
    FlowExecutionResult,
    StepResult,
)
from utils.element_finder import SmartElementFinder, ElementMatch
from utils.device_security import DeviceSecurityManager, LockStrategy
from .flow_execution_history import FlowExecutionHistory, FlowExecutionLog, FlowStepLog
from core.navigation_manager import NavigationManager
from ml_components.navigation_models import compute_screen_id, extract_ui_landmarks

logger = logging.getLogger(__name__)


class FlowExecutor:
    """
    Unified execution engine for sensor collection flows
    Executes all flow step types with retry logic and error recovery
    """

    def __init__(
        self,
        adb_bridge,
        sensor_manager,
        text_extractor,
        mqtt_manager,
        flow_manager,
        screenshot_stitcher,
        performance_monitor=None,
        execution_history=None,
        navigation_manager=None,
        action_manager=None,
        action_executor=None,
    ):
        """
        Initialize flow executor

        Args:
            adb_bridge: ADB bridge for device communication
            sensor_manager: Sensor manager for sensor CRUD
            text_extractor: Text extraction engine
            mqtt_manager: MQTT manager for publishing
            flow_manager: Flow manager for updating flow state
            screenshot_stitcher: Screenshot stitcher for scroll capture
            performance_monitor: Optional PerformanceMonitor for metrics tracking
            execution_history: Optional FlowExecutionHistory for detailed logging
            navigation_manager: Optional NavigationManager for smart screen navigation
            action_manager: Optional ActionManager for action lookup
            action_executor: Optional ActionExecutor for action execution
        """
        self.adb_bridge = adb_bridge
        self.sensor_manager = sensor_manager
        self.text_extractor = text_extractor
        self.mqtt_manager = mqtt_manager
        self.flow_manager = flow_manager
        self.screenshot_stitcher = screenshot_stitcher
        self.performance_monitor = performance_monitor
        self.execution_history = execution_history or FlowExecutionHistory()
        self.element_finder = SmartElementFinder()
        # Use same DATA_DIR as main.py for security configs
        data_dir = Path(os.getenv("DATA_DIR", "./data"))
        self.security_manager = DeviceSecurityManager(data_dir=str(data_dir))
        self.navigation_manager = navigation_manager or NavigationManager()
        self.action_manager = action_manager
        self.action_executor = action_executor

        # Step type to handler mapping
        self.step_handlers = {
            FlowStepType.LAUNCH_APP: self._execute_launch_app,
            FlowStepType.WAIT: self._execute_wait,
            FlowStepType.TAP: self._execute_tap,
            FlowStepType.SWIPE: self._execute_swipe,
            FlowStepType.TEXT: self._execute_text,
            FlowStepType.KEYEVENT: self._execute_keyevent,
            FlowStepType.CAPTURE_SENSORS: self._execute_capture_sensors,
            FlowStepType.VALIDATE_SCREEN: self._execute_validate_screen,
            FlowStepType.GO_HOME: self._execute_go_home,
            FlowStepType.GO_BACK: self._execute_go_back,
            FlowStepType.CONDITIONAL: self._execute_conditional,
            FlowStepType.PULL_REFRESH: self._execute_pull_refresh,
            FlowStepType.RESTART_APP: self._execute_restart_app,
            FlowStepType.STITCH_CAPTURE: self._execute_stitch_capture,
            FlowStepType.SCREENSHOT: self._execute_screenshot,
            # Screen power control (headless mode)
            FlowStepType.WAKE_SCREEN: self._execute_wake_screen,
            FlowStepType.SLEEP_SCREEN: self._execute_sleep_screen,
            FlowStepType.ENSURE_SCREEN_ON: self._execute_ensure_screen_on,
            # Phase 9: Advanced flow control
            FlowStepType.LOOP: self._execute_loop,
            FlowStepType.SET_VARIABLE: self._execute_set_variable,
            FlowStepType.INCREMENT: self._execute_increment,
            FlowStepType.BREAK_LOOP: self._execute_break_loop,
            FlowStepType.CONTINUE_LOOP: self._execute_continue_loop,
            # Action execution
            FlowStepType.EXECUTE_ACTION: self._execute_action,
        }

        # Variable context for flow execution (Phase 9)
        self._variable_context: Dict[str, Any] = {}

        # Session cache for runtime deduplication
        # Prevents redundant sensor captures within the same execution cycle
        self._session_captured_sensors: Dict[str, Any] = {}

        # Track sensors skipped due to interval (for logging)
        self._sensors_skipped_by_interval: Dict[str, float] = {}

        logger.info("[FlowExecutor] Initialized")

    def _analyze_skippable_steps(self, flow: SensorCollectionFlow) -> set[int]:
        """
        Pre-analyze flow to determine which steps can be skipped based on sensor intervals.

        Returns a set of step indices that can be skipped.

        Logic:
        - Find each capture_sensors step
        - Check if ALL sensors in that step can be skipped (not due for update)
        - If yes, also mark preceding navigation steps (tap, swipe) as skippable
          (up to the previous capture_sensors or launch_app step)
        """
        skippable_steps = set()
        device_id = flow.device_id

        # Navigation step types that can be skipped if their target capture is skippable
        nav_step_types = {"tap", "swipe", "wait"}

        # Find all capture_sensors steps and check if they can be skipped
        for i, step in enumerate(flow.steps):
            if step.step_type != "capture_sensors":
                continue

            if not step.sensor_ids:
                continue

            # Check if ALL sensors in this step can be skipped
            all_skippable = True
            for sensor_id in step.sensor_ids:
                sensor = self.sensor_manager.get_sensor(device_id, sensor_id)
                if not sensor:
                    sensor = self._find_sensor_by_stable_id(device_id, sensor_id)

                needs_update, _ = self._sensor_needs_update(sensor, device_id)
                if needs_update:
                    all_skippable = False
                    break

            if not all_skippable:
                continue

            # This capture_sensors step can be skipped
            skippable_steps.add(i)

            # Walk backwards to find navigation steps leading to this capture
            # Stop at: another capture_sensors, launch_app, restart_app, or start of flow
            j = i - 1
            while j >= 0:
                prev_step = flow.steps[j]
                prev_type = prev_step.step_type

                # Stop at boundary steps
                if prev_type in {"capture_sensors", "launch_app", "restart_app", "go_home"}:
                    break

                # Mark navigation steps as skippable
                if prev_type in nav_step_types:
                    skippable_steps.add(j)

                j -= 1

        return skippable_steps

    def _calculate_dynamic_timeout(self, flow: SensorCollectionFlow) -> int:
        """
        Calculate a dynamic timeout based on flow complexity.

        Returns the recommended minimum timeout in seconds.

        Formula:
        - Base: 30 seconds (app launch, setup)
        - Per navigation step (tap, swipe, wait): +2 seconds
        - Per capture_sensors step: +5 seconds (screenshot + UI dump + extraction)
        - Per sensor in capture steps: +1 second

        The returned value is the MINIMUM recommended timeout.
        If flow.flow_timeout is higher, we use the configured value.
        """
        base_timeout = 30
        nav_time = 0
        capture_time = 0

        for step in flow.steps:
            step_type = step.step_type
            if step_type in {"tap", "swipe", "wait", "go_back", "go_home"}:
                nav_time += 2
            elif step_type == "capture_sensors":
                capture_time += 5
                # Add time per sensor
                if step.sensor_ids:
                    capture_time += len(step.sensor_ids) * 1
            elif step_type in {"launch_app", "restart_app"}:
                nav_time += 5  # App launch takes longer
            else:
                nav_time += 1  # Other steps

        calculated = base_timeout + nav_time + capture_time
        return calculated

    async def auto_unlock_if_needed(self, device_id: str) -> dict:
        """
        Unified device unlock method with retry logic and debounce protection.

        This method is called by both FlowService (on-demand execution) and
        FlowScheduler (periodic execution) to ensure consistent unlock behavior.

        Features:
        - Debounce: Prevents rapid unlock attempts (5 second minimum between attempts)
        - Retry: Up to 3 unlock attempts with progressive delays (2s, 3s, 4s)
        - Cooldown check: Respects device lockout cooldown from ADB bridge
        - Swipe + PIN: Tries swipe first, then PIN if AUTO_UNLOCK configured

        Returns dict with:
        - success: True if device is ready (unlocked or successfully unlocked)
        - error: Error message if unlock failed (only present if success=False)
        - reason: Reason code (only present if success=False)
        """
        from utils.device_security import LockStrategy

        MAX_UNLOCK_ATTEMPTS = 3
        RETRY_DELAYS = [2.0, 3.0, 4.0]

        # Check unlock cooldown (prevents device lockout)
        unlock_status = self.adb_bridge.get_unlock_status(device_id)
        if unlock_status.get("in_cooldown"):
            cooldown_remaining = unlock_status.get("cooldown_remaining_seconds", 0)
            logger.warning(
                f"[FlowExecutor] Device {device_id} in unlock cooldown ({cooldown_remaining:.0f}s remaining)"
            )
            return {
                "success": False,
                "error": f"Device is in unlock cooldown ({int(cooldown_remaining)}s remaining). Too many failed unlock attempts.",
                "reason": "cooldown"
            }

        # Get security config (try both device_id and stable_device_id)
        security_config = self.security_manager.get_lock_config(device_id)
        if not security_config:
            try:
                stable_id = await self.adb_bridge.get_device_serial(device_id)
                if stable_id and stable_id != device_id:
                    security_config = self.security_manager.get_lock_config(stable_id)
            except Exception as e:
                logger.debug(f"[FlowExecutor] Could not get security config via stable_id: {e}")

        has_auto_unlock = (
            security_config
            and security_config.get("strategy") == LockStrategy.AUTO_UNLOCK.value
        )

        # Get passcode if AUTO_UNLOCK configured
        passcode = None
        if has_auto_unlock:
            passcode = self.security_manager.get_passcode(device_id)
            if not passcode:
                try:
                    stable_id = await self.adb_bridge.get_device_serial(device_id)
                    if stable_id and stable_id != device_id:
                        passcode = self.security_manager.get_passcode(stable_id)
                except Exception as e:
                    logger.debug(f"[FlowExecutor] Could not get passcode via stable_id: {e}")

        # Unlock attempts with retry logic
        for attempt in range(MAX_UNLOCK_ATTEMPTS):
            # Check if device is locked
            is_locked = await self.adb_bridge.is_locked(device_id)
            if not is_locked:
                if attempt > 0:
                    logger.info(
                        f"[FlowExecutor] Device {device_id} unlocked after {attempt} attempts"
                    )
                else:
                    logger.debug(f"[FlowExecutor] Device {device_id} already unlocked")
                return {"success": True}

            # Log unlock attempt
            if attempt == 0:
                logger.info(f"[FlowExecutor] Device {device_id} is locked - attempting unlock")
            else:
                logger.info(
                    f"[FlowExecutor] Unlock attempt {attempt + 1}/{MAX_UNLOCK_ATTEMPTS} for {device_id}"
                )

            # Check if AUTO_UNLOCK is configured - if not, return helpful error on first attempt
            if attempt == 0 and not has_auto_unlock:
                # Device is locked but AUTO_UNLOCK not configured - tell user what to do
                logger.warning(
                    f"[FlowExecutor] Device {device_id} is locked but AUTO_UNLOCK not configured"
                )
                return {
                    "success": False,
                    "error": "Device is locked but unlock is not configured. Go to Device Settings > Security and enable AUTO_UNLOCK with your PIN/passcode.",
                    "reason": "not_configured"
                }

            # If passcode is configured, try PIN unlock FIRST (faster than swipe attempts)
            # This matches the behavior of the "Test Unlock" button which works quickly
            if passcode:
                logger.info(f"[FlowExecutor] Attempting PIN unlock for {device_id}")
                try:
                    if await self.adb_bridge.unlock_device(device_id, passcode):
                        logger.info(f"[FlowExecutor] Device unlocked with PIN")
                        return {"success": True}
                except Exception as e:
                    logger.warning(f"[FlowExecutor] PIN unlock failed: {e}")

                # Check if we unlocked after PIN attempt
                if not await self.adb_bridge.is_locked(device_id):
                    logger.info(f"[FlowExecutor] Device {device_id} unlocked")
                    return {"success": True}
            else:
                # No passcode configured - try swipe-to-unlock
                try:
                    unlock_success = await self.adb_bridge.unlock_screen(device_id)
                    await asyncio.sleep(0.5)

                    if unlock_success and not await self.adb_bridge.is_locked(device_id):
                        logger.info(f"[FlowExecutor] Device unlocked via swipe")
                        return {"success": True}
                except Exception as e:
                    logger.warning(f"[FlowExecutor] Swipe unlock failed: {e}")

            # Wait before retry
            if attempt < MAX_UNLOCK_ATTEMPTS - 1:
                delay = RETRY_DELAYS[attempt]
                logger.debug(f"[FlowExecutor] Waiting {delay}s before retry...")
                await asyncio.sleep(delay)

        # All attempts failed
        logger.error(
            f"[FlowExecutor] Failed to unlock device {device_id} after {MAX_UNLOCK_ATTEMPTS} attempts"
        )
        return {
            "success": False,
            "error": f"Failed to unlock device after {MAX_UNLOCK_ATTEMPTS} attempts. Check that your PIN/passcode is correct in Device Settings > Security.",
            "reason": "unlock_failed"
        }

    def _sensor_needs_update(self, sensor, device_id: str) -> tuple[bool, float]:
        """
        Check if a sensor needs to be updated based on its individual update_interval_seconds.

        Returns:
            tuple: (needs_update: bool, seconds_until_next: float)
                   If needs_update is False, seconds_until_next shows when it will need updating
        """
        if not sensor:
            return True, 0  # If sensor not found, try to capture anyway

        # If no last_updated, sensor has never been captured - needs update
        if not sensor.last_updated:
            return True, 0

        # Calculate time since last update
        now = datetime.now()
        last_updated = sensor.last_updated

        # Handle string datetime (from JSON deserialization)
        if isinstance(last_updated, str):
            try:
                last_updated = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                # Remove timezone for comparison if naive datetime
                if last_updated.tzinfo is not None:
                    last_updated = last_updated.replace(tzinfo=None)
            except ValueError:
                return True, 0  # Can't parse, needs update

        elapsed_seconds = (now - last_updated).total_seconds()
        interval = sensor.update_interval_seconds

        if elapsed_seconds >= interval:
            return True, 0  # Interval elapsed, needs update

        # Doesn't need update yet
        seconds_until_next = interval - elapsed_seconds
        return False, seconds_until_next

    async def execute_flow(
        self,
        flow: SensorCollectionFlow,
        device_lock: Optional[asyncio.Lock] = None,
        learn_mode: bool = False,
        strict_mode: bool = False,
        repair_mode: bool = False,
        force_execute: bool = False,
    ) -> FlowExecutionResult:
        """
        Execute complete flow with configurable execution modes.

        Args:
            flow: Flow to execute
            device_lock: Optional device lock (from scheduler)
            learn_mode: If True, capture UI elements at each screen and update navigation graph.
                       Makes execution slower but improves future Smart Flow generation.
            strict_mode: If True, fail steps when navigation doesn't reach expected screen.
                        Default False maintains backward compatibility (warn but continue).
            repair_mode: If True, auto-update element bounds when drift is detected.
                        Fixes "Element moved Xpx" issues automatically.
            force_execute: If True, execute ALL steps regardless of sensor update intervals.
                          Useful for manual testing - bypasses "sensors not due" skip logic.

        Returns:
            FlowExecutionResult with success/failure details

        Process:
        1. Execute each step sequentially
        2. Retry failed steps if retry_on_failure=True
        3. Stop on error if stop_on_error=True
        4. Capture sensors at designated steps
        5. Publish to MQTT in real-time
        6. Update flow metrics
        7. (Learn Mode) Capture UI elements and update navigation graph
        8. (Strict Mode) Fail on navigation errors instead of continuing
        9. (Repair Mode) Auto-update drifted element bounds
        """
        start_time = time.time()
        result = FlowExecutionResult(
            flow_id=flow.flow_id,
            success=False,
            executed_steps=0,
            captured_sensors={},
            execution_time_ms=0,
            # Set execution mode flags
            strict_mode=strict_mode,
            repair_mode=repair_mode,
            force_execute=force_execute,
        )

        # Track learned screens if learn_mode is enabled
        learned_screens = []

        # Log enabled modes
        enabled_modes = []
        if learn_mode:
            enabled_modes.append("Learn")
        if strict_mode:
            enabled_modes.append("Strict")
        if repair_mode:
            enabled_modes.append("Repair")
        if force_execute:
            enabled_modes.append("Force")
        if enabled_modes:
            logger.info(f"[FlowExecutor] Execution modes: {', '.join(enabled_modes)}")

        # Create execution log for history tracking
        execution_log = FlowExecutionLog(
            execution_id=str(uuid.uuid4()),
            flow_id=flow.flow_id,
            device_id=flow.device_id,
            started_at=datetime.now().isoformat(),
            triggered_by="scheduler",  # TODO: Pass this as parameter when called from API/manual
            total_steps=len(flow.steps),
            steps=[],
        )

        # Clear variable context at start of each flow (Phase 9)
        self.clear_variable_context()

        # Clear session cache for this execution
        self._session_captured_sensors = {}

        # Pre-analyze flow for page-skipping optimization
        # This identifies steps that can be skipped because all sensors in them are not due for update
        # force_execute bypasses this optimization entirely
        if force_execute:
            skippable_steps = set()
            logger.info(f"[FlowExecutor] Force execute: ALL steps will run (ignoring sensor intervals)")
        else:
            skippable_steps = self._analyze_skippable_steps(flow)
            if skippable_steps:
                logger.info(f"[FlowExecutor] Page-skip optimization: {len(skippable_steps)} steps can be skipped (sensors not due)")

        # Dynamic timeout calculation - use the higher of configured or calculated minimum
        calculated_timeout = self._calculate_dynamic_timeout(flow)
        effective_timeout = max(flow.flow_timeout, calculated_timeout)
        if effective_timeout > flow.flow_timeout:
            logger.info(f"[FlowExecutor] Auto-adjusting timeout: {flow.flow_timeout}s -> {effective_timeout}s (based on {len(flow.steps)} steps)")
            # Temporarily override for this execution
            original_timeout = flow.flow_timeout
            flow.flow_timeout = effective_timeout

        logger.info(f"[FlowExecutor] Starting flow {flow.flow_id} ({flow.name})")

        try:
            # Auto-wake screen if headless mode enabled
            if flow.auto_wake_before:
                logger.info(f"  [Headless] Auto-waking screen before flow")
                wake_success = await self.adb_bridge.ensure_screen_on(
                    flow.device_id, timeout_ms=flow.wake_timeout_ms
                )
                if not wake_success:
                    if flow.verify_screen_on:
                        result.error_message = (
                            "Failed to wake screen for headless execution"
                        )
                        logger.error(f"  [Headless] {result.error_message}")
                        result.execution_time_ms = int(
                            (time.time() - start_time) * 1000
                        )
                        return result
                    else:
                        logger.warning(
                            f"  [Headless] Screen wake failed, continuing anyway (verify_screen_on=False)"
                        )

            # Wait briefly for lock screen to stabilize after wake
            # (screen wakes first, then lock screen appears ~500ms later)
            await asyncio.sleep(0.5)

            # NOTE: Auto-unlock is now handled by FlowScheduler before calling execute_flow()
            # This ensures centralized lock management based on device security config (AUTO_UNLOCK strategy)

            # ========== ENSURE KNOWN STARTING POINT ==========
            # Go to home screen and relaunch app for consistent flow execution
            target_package = self._get_target_package(flow)
            first_expected_activity = self._get_first_expected_activity(flow)
            start_from_current = getattr(flow, "start_from_current_screen", False)

            # Check if first step is LAUNCH_APP
            first_step = flow.steps[0] if flow.steps else None
            first_step_is_launch = (
                first_step and first_step.step_type == FlowStepType.LAUNCH_APP
            )

            if start_from_current:
                logger.info(
                    "[FlowExecutor] start_from_current_screen enabled - skipping app reset"
                )
            elif first_step_is_launch:
                # First step is LAUNCH_APP - check if already on correct screen before resetting
                if target_package:
                    # Smart check: skip reset if already on correct screen
                    try:
                        current_activity = await self.adb_bridge.get_current_activity(
                            flow.device_id
                        )
                        current_pkg = (
                            current_activity.split("/")[0]
                            if current_activity and "/" in current_activity
                            else current_activity
                        )
                        expected_activity = (
                            first_step.expected_activity or first_step.screen_activity
                        )

                        # Skip reset if already on correct screen
                        if expected_activity and self._activity_matches(
                            current_activity, expected_activity
                        ):
                            logger.info(
                                f"[FlowExecutor] Already on correct screen - skipping app reset"
                            )
                        elif current_pkg == target_package and not expected_activity:
                            logger.info(
                                f"[FlowExecutor] Already on target app - skipping app reset"
                            )
                        else:
                            logger.info(
                                "[FlowExecutor] Resetting app state before launch_app step"
                            )
                            reset_success = await self._reset_app_state(
                                flow.device_id, target_package
                            )
                            if not reset_success:
                                logger.warning(
                                    "[FlowExecutor] Failed to reset app state, continuing anyway..."
                                )
                    except Exception as e:
                        logger.debug(
                            f"[FlowExecutor] Could not check current state: {e}"
                        )
                        # Fall back to reset on error
                        reset_success = await self._reset_app_state(
                            flow.device_id, target_package
                        )
                else:
                    logger.debug(
                        "[FlowExecutor] No target package found, skipping app reset"
                    )
            elif target_package:
                logger.info(
                    f"[FlowExecutor] Ensuring known starting point for: {target_package}"
                )
                if first_expected_activity:
                    logger.info(
                        f"[FlowExecutor] First expected screen: {first_expected_activity.split('/')[-1] if '/' in first_expected_activity else first_expected_activity}"
                    )
                init_success = await self._ensure_known_starting_point(
                    flow.device_id, target_package, first_expected_activity
                )
                if not init_success:
                    logger.warning(
                        "[FlowExecutor] Failed to initialize starting point, continuing anyway..."
                    )
            else:
                logger.debug(
                    "[FlowExecutor] No target package found, skipping initialization"
                )
            # ==================================================

            # Track starting activity for backtrack
            starting_activity = None
            navigation_depth = 0  # Count of screen-changing taps
            if flow.backtrack_after:
                try:
                    starting_activity = await self.adb_bridge.get_current_activity(
                        flow.device_id
                    )
                    logger.debug(
                        f"[FlowExecutor] Tracking start activity for backtrack: {starting_activity}"
                    )
                except Exception as e:
                    logger.debug(f"[FlowExecutor] Could not get starting activity: {e}")

            # Execute steps sequentially
            for i, step in enumerate(flow.steps):
                # Timeout check
                elapsed = time.time() - start_time
                if elapsed > flow.flow_timeout:
                    result.error_message = f"Flow timeout after {elapsed:.1f}s (limit: {flow.flow_timeout}s)"
                    result.failed_step = i
                    logger.warning(f"  {result.error_message}")
                    break

                # Page-skip optimization: skip steps that lead to sensors not due for update
                if i in skippable_steps:
                    step_desc = step.description or f"Step {i+1}: {step.step_type}"
                    logger.info(f"  [Skip] {step_desc} (sensors not due for update)")
                    result.executed_steps += 1  # Count as executed (skipped successfully)
                    continue

                # Log step execution
                step_desc = step.description or f"Step {i+1}: {step.step_type}"
                logger.info(f"  Executing: {step_desc}")

                # Create step log
                step_start = time.time()
                step_log = FlowStepLog(
                    step_index=i,
                    step_type=step.step_type,
                    description=step_desc,
                    started_at=datetime.now().isoformat(),
                    success=False,
                )

                # Track sensors captured before this step (to find new ones)
                sensors_before = set(result.captured_sensors.keys())

                # If a tap leads to a different screen, set expected_activity to help navigation
                if step.step_type == FlowStepType.TAP and not step.expected_activity:
                    next_step = flow.steps[i + 1] if i + 1 < len(flow.steps) else None
                    if next_step and next_step.screen_activity and step.screen_activity:
                        if next_step.screen_activity != step.screen_activity:
                            step.expected_activity = next_step.screen_activity

                # Track activity before step for backtrack counting
                activity_before_step = None
                if flow.backtrack_after and step.step_type == FlowStepType.TAP:
                    try:
                        activity_before_step = (
                            await self.adb_bridge.get_current_activity(flow.device_id)
                        )
                    except Exception as e:
                        logger.debug(f"[FlowExecutor] Could not get activity before step: {e}")

                # Execute step with retry
                try:
                    success = await self._execute_step_with_retry(
                        flow.device_id, step, result
                    )

                    step_log.success = success

                    # Build step result with details
                    step_result = StepResult(
                        step_index=i,
                        step_type=step.step_type,
                        description=step_desc,
                        success=success,
                        details={},
                    )

                    # Add details based on step type
                    if step.step_type == FlowStepType.CAPTURE_SENSORS:
                        # Find sensors captured in this step
                        sensors_after = set(result.captured_sensors.keys())
                        new_sensors = sensors_after - sensors_before
                        if new_sensors:
                            step_result.details["sensors"] = {
                                sid: {
                                    "value": result.captured_sensors.get(sid),
                                    "name": self._get_sensor_name(flow.device_id, sid),
                                }
                                for sid in new_sensors
                            }

                    elif step.step_type == FlowStepType.EXECUTE_ACTION:
                        # Add action info
                        if hasattr(step, "action_id") and step.action_id:
                            step_result.details["action_id"] = step.action_id
                            step_result.details["action_result"] = (
                                "executed" if success else "failed"
                            )

                    result.step_results.append(step_result)

                    if not success:
                        step_log.error = f"Step failed: {step.step_type}"
                        step_result.error_message = f"Step failed: {step.step_type}"
                        result.failed_step = i
                        if not result.error_message:
                            result.error_message = (
                                f"Step {i+1} failed: {step.step_type}"
                            )
                        logger.warning(f"  Step {i+1} failed: {step.step_type}")

                        if flow.stop_on_error:
                            logger.info(f"  Stopping flow (stop_on_error=True)")
                            # Complete step log
                            step_log.completed_at = datetime.now().isoformat()
                            step_log.duration_ms = int(
                                (time.time() - step_start) * 1000
                            )
                            execution_log.steps.append(step_log)
                            break

                    result.executed_steps += 1

                    # Track navigation depth for backtrack (count screen-changing taps)
                    if (
                        flow.backtrack_after
                        and step.step_type == FlowStepType.TAP
                        and success
                        and activity_before_step
                    ):
                        try:
                            activity_after_step = (
                                await self.adb_bridge.get_current_activity(
                                    flow.device_id
                                )
                            )
                            if (
                                activity_after_step
                                and activity_after_step != activity_before_step
                            ):
                                # Screen changed - increment navigation depth
                                navigation_depth += 1
                                logger.debug(
                                    f"  [Backtrack] Navigation depth now: {navigation_depth}"
                                )
                        except Exception as e:
                            logger.debug(f"[FlowExecutor] Could not track activity for backtrack: {e}")

                    # Learn Mode: Capture UI elements after screen-changing steps
                    # Learn from BOTH successes AND failures (failures help understand what went wrong)
                    if learn_mode:
                        learn_step_types = {
                            FlowStepType.SCREENSHOT,
                            FlowStepType.LAUNCH_APP,
                            FlowStepType.RESTART_APP,
                            FlowStepType.TAP,
                            FlowStepType.SWIPE,
                            FlowStepType.GO_HOME,
                            FlowStepType.GO_BACK,
                        }
                        if step.step_type in learn_step_types:
                            try:
                                # Get package from step or from flow's first launch_app step
                                step_package = getattr(
                                    step, "package", None
                                ) or getattr(step, "screen_package", None)
                                learned = await self._learn_current_screen(
                                    flow.device_id, step_package
                                )
                                if learned:
                                    # Add step outcome context to learned data
                                    learned['step_success'] = success
                                    learned['step_type'] = step.step_type.value
                                    learned['step_index'] = i
                                    learned['expected_activity'] = getattr(step, 'expected_activity', None)

                                    learned_screens.append(learned)

                                    if success:
                                        logger.info(
                                            f"  [Learn Mode] Captured screen: {learned.get('activity', 'unknown')[:50]}"
                                        )
                                    else:
                                        logger.info(
                                            f"  [Learn Mode] Captured FAILURE context at: {learned.get('activity', 'unknown')[:50]}"
                                        )
                            except Exception as learn_err:
                                logger.warning(
                                    f"  [Learn Mode] Failed to learn screen: {learn_err}"
                                )

                except Exception as step_error:
                    step_log.success = False
                    step_log.error = str(step_error)
                    logger.error(f"  Step {i+1} error: {step_error}")

                    # Add failed step result
                    result.step_results.append(
                        StepResult(
                            step_index=i,
                            step_type=step.step_type,
                            description=step_desc,
                            success=False,
                            error_message=str(step_error),
                        )
                    )

                finally:
                    # Complete step log
                    step_log.completed_at = datetime.now().isoformat()
                    step_log.duration_ms = int((time.time() - step_start) * 1000)
                    execution_log.steps.append(step_log)

            # Mark success if all steps executed
            result.success = result.executed_steps == len(flow.steps)

            # Update flow metadata
            flow.last_executed = datetime.now()
            flow.execution_count += 1

            if result.success:
                flow.success_count += 1
                flow.last_success = True
                flow.last_error = None
                logger.info(
                    f"[FlowExecutor] Flow {flow.flow_id} completed successfully"
                )

                # Backtrack: Navigate back to starting screen for faster next run
                if flow.backtrack_after and navigation_depth > 0:
                    logger.info(
                        f"  [Backtrack] Navigating back {navigation_depth} screen(s) to starting position"
                    )
                    try:
                        for back_step in range(navigation_depth):
                            await self.adb_bridge.keyevent(
                                flow.device_id, "KEYCODE_BACK"
                            )
                            await asyncio.sleep(0.4)  # Brief wait between backs

                        # Verify we're back at starting activity
                        if starting_activity:
                            await asyncio.sleep(0.3)
                            current = await self.adb_bridge.get_current_activity(
                                flow.device_id
                            )
                            if current and self._activity_matches(
                                current, starting_activity
                            ):
                                logger.info(
                                    f"  [Backtrack] Successfully returned to starting screen"
                                )
                            else:
                                logger.debug(
                                    f"  [Backtrack] Ended on {current}, started on {starting_activity}"
                                )
                    except Exception as e:
                        logger.warning(f"  [Backtrack] Failed to navigate back: {e}")
                elif flow.backtrack_after:
                    logger.debug(f"  [Backtrack] No navigation to backtrack (depth=0)")
            else:
                flow.failure_count += 1
                flow.last_success = False
                flow.last_error = result.error_message
                logger.error(
                    f"[FlowExecutor] Flow {flow.flow_id} failed: {result.error_message}"
                )

            # Save updated flow state
            self.flow_manager.update_flow(flow)

        except Exception as e:
            result.success = False
            result.error_message = f"Flow execution error: {str(e)}"
            logger.error(
                f"[FlowExecutor] Flow {flow.flow_id} error: {e}", exc_info=True
            )

        finally:
            # Auto-sleep screen ONLY if flow was successful (don't sleep if failed - user might be using it!)
            if flow.auto_sleep_after and result.success:
                # Check if wizard is active on this device - skip sleep if so
                # NOTE: Device may have multiple IDs (USB serial vs WiFi IP) - check all
                try:
                    from main import wizard_active_devices

                    # Check if any of the wizard active devices match this device
                    wizard_active = False
                    device_id = flow.device_id

                    # Direct match
                    if device_id in wizard_active_devices:
                        wizard_active = True
                    else:
                        # Check alternative IDs - device might be registered by WiFi IP but flow uses USB serial
                        # Get all connected devices and check if any match
                        try:
                            connected = await self.adb_bridge.get_connected_devices()
                            for dev in connected:
                                dev_id = dev.get("id", "")
                                wifi_ip = dev.get("wifi_ip", "")

                                # If this device matches the flow's device
                                if dev_id == device_id or wifi_ip == device_id:
                                    # Check if either ID is in wizard_active
                                    if (
                                        dev_id in wizard_active_devices
                                        or wifi_ip in wizard_active_devices
                                    ):
                                        wizard_active = True
                                        logger.info(
                                            f"  [Headless] Device {device_id} matched wizard active via {dev_id}/{wifi_ip}"
                                        )
                                        break
                        except Exception as e:
                            logger.debug(
                                f"  [Headless] Could not check alternative device IDs: {e}"
                            )

                    if wizard_active:
                        logger.info(
                            f"  [Headless] Skipping auto-sleep - wizard active on device {flow.device_id}"
                        )
                    else:
                        logger.info(
                            f"  [Headless] Auto-sleeping screen after successful flow"
                        )
                        await self.adb_bridge.sleep_screen(flow.device_id)
                except ImportError:
                    # Fallback if import fails (shouldn't happen)
                    logger.info(
                        f"  [Headless] Auto-sleeping screen after successful flow"
                    )
                    await self.adb_bridge.sleep_screen(flow.device_id)
                except Exception as sleep_error:
                    logger.warning(
                        f"  [Headless] Failed to sleep screen: {sleep_error}"
                    )

        result.execution_time_ms = int((time.time() - start_time) * 1000)

        # Complete execution log
        execution_log.completed_at = datetime.now().isoformat()
        execution_log.duration_ms = result.execution_time_ms
        execution_log.success = result.success
        execution_log.error = result.error_message
        execution_log.executed_steps = result.executed_steps

        # Save execution log to history
        try:
            self.execution_history.add_execution(execution_log)
        except Exception as e:
            logger.error(f"[FlowExecutor] Failed to save execution history: {e}")

        logger.info(
            f"[FlowExecutor] Flow {flow.flow_id} finished in {result.execution_time_ms}ms"
        )
        logger.info(f"  Steps executed: {result.executed_steps}/{len(flow.steps)}")
        logger.info(f"  Sensors captured: {len(result.captured_sensors)}")

        # Add learned screens to result if learn_mode was enabled
        if learn_mode and learned_screens:
            result.learned_screens = learned_screens
            logger.info(f"  Screens learned: {len(learned_screens)}")

        # Record execution metrics (if performance monitor enabled)
        if self.performance_monitor:
            try:
                await self.performance_monitor.record_execution(flow, result)
            except Exception as e:
                logger.error(f"[FlowExecutor] Failed to record metrics: {e}")

        return result

    async def _learn_current_screen(
        self, device_id: str, package: str = None
    ) -> Optional[Dict]:
        """
        Learn Mode: Capture UI elements from current screen and update navigation graph.

        Args:
            device_id: Device identifier
            package: Package name (if known)

        Returns:
            Dict with learned screen info, or None if learning failed
        """
        try:
            # Get current activity info
            activity_info = await self.adb_bridge.get_current_activity(
                device_id, as_dict=True
            )
            if not activity_info:
                return None

            current_package = activity_info.get("package", package or "unknown")
            current_activity = activity_info.get("activity", "unknown")

            # Skip system overlays (NotificationShade = Samsung lock screen, StatusBar, etc.)
            skip_activities = {
                "NotificationShade",
                "StatusBar",
                "Keyguard",
                "LockScreen",
                "BiometricPrompt",
            }
            for skip_activity in skip_activities:
                if skip_activity in current_activity:
                    logger.debug(
                        f"  [Learn Mode] Skipping system overlay: {current_activity}"
                    )
                    return None

            # Skip system/launcher screens
            skip_packages = {
                "com.android.launcher",
                "com.samsung.android.launcher",
                "com.google.android.apps.nexuslauncher",
                "com.android.systemui",
                "com.samsung.android.app.cocktailbarservice",
            }
            if current_package in skip_packages:
                logger.debug(
                    f"  [Learn Mode] Skipping system/launcher screen: {current_package}"
                )
                return None

            # If expected package is provided, verify we're on the right app
            if package and current_package != package:
                logger.debug(
                    f"  [Learn Mode] Wrong app - expected {package}, got {current_package}"
                )
                return None

            # Capture UI elements (full mode for learning)
            ui_elements = await self.adb_bridge.get_ui_elements(
                device_id, force_refresh=True, bounds_only=False
            )

            if not ui_elements:
                logger.debug(f"  [Learn Mode] No UI elements captured")
                return None

            # Filter to meaningful elements (with text, resource_id, or clickable)
            meaningful_elements = []
            for el in ui_elements:
                text = el.get("text", "").strip()
                resource_id = el.get("resource_id", "").strip()
                is_clickable = el.get("clickable", False)
                content_desc = el.get("content_desc", "").strip()

                if text or resource_id or is_clickable or content_desc:
                    meaningful_elements.append(
                        {
                            "text": text,
                            "resource_id": resource_id,
                            "bounds": el.get("bounds"),
                            "class": el.get("class", ""),
                            "clickable": is_clickable,
                            "content_desc": content_desc,
                        }
                    )

            # Add screen to navigation graph
            screen = self.navigation_manager.add_screen(
                package=current_package,
                activity=current_activity,
                ui_elements=meaningful_elements,
                display_name=(
                    current_activity.split(".")[-1] if current_activity else None
                ),
                learned_from="learn_mode",
            )

            return {
                "package": current_package,
                "activity": current_activity,
                "screen_id": screen.screen_id if screen else None,
                "element_count": len(meaningful_elements),
                "clickable_count": sum(
                    1 for el in meaningful_elements if el.get("clickable")
                ),
            }

        except Exception as e:
            logger.warning(f"  [Learn Mode] Screen learning failed: {e}")
            return None

    async def _execute_step_with_retry(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Execute step with retry logic

        Args:
            device_id: Device ID
            step: Step to execute
            result: Result object to update

        Returns:
            True if step succeeded, False otherwise
        """
        max_attempts = step.max_retries if step.retry_on_failure else 1

        for attempt in range(max_attempts):
            try:
                # Phase 8: State validation before step execution
                # Skip validation for certain steps:
                # - launch/restart: app just needs to be open
                # - capture_sensors: just needs UI elements to be present, not exact screen
                skip_validation_steps = {
                    "launch_app",
                    "restart_app",
                    "go_home",
                    "go_back",
                    "capture_sensors",
                }
                # Normalize step_type for comparison (lowercase, stripped)
                normalized_step_type = (
                    step.step_type.lower().strip() if step.step_type else ""
                )
                step_type_in_skip = normalized_step_type in skip_validation_steps

                # Skip validation for navigation taps/swipes that should transition screens
                is_navigation_transition = (
                    normalized_step_type in {"tap", "swipe"}
                    and step.expected_activity
                    and step.screen_activity
                    and step.expected_activity != step.screen_activity
                )
                if is_navigation_transition:
                    step_type_in_skip = True
                should_validate = step.validate_state and not step_type_in_skip

                # Debug logging to diagnose validation issues
                logger.debug(
                    f"  [StepValidation] step_type='{step.step_type}' normalized='{normalized_step_type}'"
                )
                logger.debug(
                    f"  [StepValidation] step_type in skip_validation_steps: {step_type_in_skip}"
                )
                logger.debug(
                    f"  [StepValidation] validate_state={step.validate_state}, should_validate={should_validate}"
                )

                # Validate if we have ANY validation data (not just screenshot)
                has_validation_data = (
                    step.expected_screenshot
                    or step.expected_ui_elements
                    or step.expected_activity
                    or step.screen_activity  # From recording - can validate we're in same activity
                )
                logger.debug(
                    f"  [StepValidation] has_validation_data={has_validation_data}"
                )
                if should_validate and has_validation_data:
                    logger.debug(f"  Validating state before {step.step_type}")
                    state_valid = await self._validate_state_and_recover(
                        device_id, step, result
                    )
                    if not state_valid:
                        logger.warning(
                            f"  State validation failed for {step.step_type}"
                        )
                        if attempt < max_attempts - 1:
                            logger.info(
                                f"  Retrying step after state recovery (attempt {attempt+2}/{max_attempts})"
                            )
                            await asyncio.sleep(1)
                            continue
                        else:
                            result.error_message = (
                                "State validation failed after recovery attempts"
                            )
                            return False

                # Get handler for this step type
                handler = self.step_handlers.get(step.step_type)
                if not handler:
                    raise ValueError(f"Unknown step type: {step.step_type}")

                # Execute handler
                success = await handler(device_id, step, result)

                if success:
                    return True

                # Retry if more attempts available
                if attempt < max_attempts - 1:
                    logger.info(
                        f"  Retrying step {step.step_type} (attempt {attempt+2}/{max_attempts})"
                    )
                    await asyncio.sleep(1)  # Brief delay before retry

            except Exception as e:
                logger.error(f"  Step execution error: {e}", exc_info=True)
                if attempt == max_attempts - 1:
                    result.error_message = str(e)
                    return False
                else:
                    logger.info(
                        f"  Retrying after error (attempt {attempt+2}/{max_attempts})"
                    )
                    await asyncio.sleep(1)

        return False

    # ============================================================================
    # Step Handlers
    # ============================================================================

    async def _extract_timestamp_text(
        self, device_id: str, timestamp_element: Dict[str, Any]
    ) -> Optional[str]:
        """
        Extract text from timestamp element for validation

        Args:
            device_id: Device ID
            timestamp_element: Element config with bounds, text, resource-id

        Returns:
            Current timestamp text or None if not found
        """
        try:
            # Get current screen elements
            elements_response = await self.adb_bridge.get_ui_elements(device_id)
            if not elements_response or "elements" not in elements_response:
                return None

            elements = elements_response["elements"]

            # Find element by matching resource-id (most reliable) or bounds
            for el in elements:
                # Match by resource-id (most reliable)
                if timestamp_element.get("resource-id"):
                    if el.get("resource-id") == timestamp_element.get("resource-id"):
                        return el.get("text", "").strip()

                # Match by bounds (if resource-id not available)
                if timestamp_element.get("bounds"):
                    ts_bounds = timestamp_element["bounds"]
                    el_bounds = el.get("bounds", {})

                    # Check if bounds match (with small tolerance of ±10px)
                    if (
                        abs(el_bounds.get("x", 0) - ts_bounds.get("x", 0)) < 10
                        and abs(el_bounds.get("y", 0) - ts_bounds.get("y", 0)) < 10
                    ):
                        return el.get("text", "").strip()

            return None

        except Exception as e:
            logger.error(f"  Failed to extract timestamp text: {e}")
            return None

    async def _execute_launch_app(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Launch app step with smart state validation.

        - Checks if app is already on correct screen (skips launch)
        - If app is open but on wrong screen, force restarts
        - After launch, validates we reached expected activity
        """
        package = step.package
        if not package:
            logger.error("  launch_app step missing package name")
            return False

        # Get expected activity from step or recording context
        expected_activity = step.expected_activity or step.screen_activity

        # Check current state BEFORE launching
        try:
            current = await self.adb_bridge.get_current_activity(device_id)
            current_pkg = (
                current.split("/")[0] if current and "/" in current else current
            )

            logger.debug(f"  Current activity: {current}, Target package: {package}")

            # Already on correct screen (activity match)?
            activity_match = expected_activity and self._activity_matches(
                current, expected_activity
            )
            if activity_match:
                logger.info(f"  App already on correct screen: {expected_activity}")
                return True

            # Already on correct app (package match) - skip launch if no specific activity required
            if current_pkg == package and not expected_activity:
                logger.info(f"  App already in foreground: {package}")
                return True

            # If we expect a specific activity and aren't on it, force-stop before launch
            if expected_activity and not activity_match:
                logger.info(
                    f"  App not on expected screen ({current}), force stopping before launch..."
                )
                await self.adb_bridge.stop_app(device_id, package)
                await asyncio.sleep(0.5)

            # Different app in foreground? May need to force-stop target first for clean launch
            if current_pkg and current_pkg != package:
                logger.debug(
                    f"  Different app in foreground: {current_pkg}, will launch {package}"
                )
        except Exception as e:
            logger.debug(f"  Could not check current activity: {e}")

        # Launch app
        logger.debug(f"  Launching app: {package}")
        success = await self.adb_bridge.launch_app(device_id, package)

        if not success:
            logger.warning(f"  Failed to launch app: {package}")
            return False

        # Wait for app to launch
        await asyncio.sleep(2)

        # Validate we reached the target app/screen
        try:
            new_current = await self.adb_bridge.get_current_activity(device_id)
            new_pkg = (
                new_current.split("/")[0]
                if new_current and "/" in new_current
                else new_current
            )

            # Check activity match (if specified)
            if expected_activity:
                if not self._activity_matches(new_current, expected_activity):
                    logger.warning(
                        f"  Launched to {new_current} instead of {expected_activity} - waiting for expected screen"
                    )

                    # Poll for expected activity (up to 8 seconds with 500ms intervals)
                    poll_interval = 0.5
                    max_polls = 16
                    for poll in range(max_polls):
                        await asyncio.sleep(poll_interval)
                        new_current = await self.adb_bridge.get_current_activity(
                            device_id
                        )
                        if self._activity_matches(new_current, expected_activity):
                            logger.info(
                                f"  Expected screen appeared after {(poll + 1) * poll_interval:.1f}s"
                            )
                            return True

                    logger.warning(
                        "  Expected screen still not visible, attempting navigation"
                    )
                    navigation_success = await self._navigate_to_expected_screen(
                        device_id, package, new_current, expected_activity
                    )
                    if navigation_success:
                        logger.info(
                            f"  Reached expected screen after navigation: {expected_activity}"
                        )
                        return True

                    result.error_message = (
                        f"Launch failed: expected '{expected_activity}', but current is '{new_current}'. "
                        "Ensure the app opens to the correct screen or add navigation steps."
                    )
                    logger.error(
                        f"  Could not reach expected screen: {expected_activity}"
                    )
                    return False
                logger.debug(
                    f"  Successfully launched to expected screen: {expected_activity}"
                )
            # At minimum check package match
            elif new_pkg != package:
                logger.warning(
                    f"  Launch may have failed: foreground is {new_pkg} (expected {package})"
                )
            else:
                logger.debug(f"  Successfully launched app: {package}")
        except Exception as e:
            logger.debug(f"  Could not validate target activity: {e}")

        return True

    def _activity_matches(self, current: str, expected: str) -> bool:
        """
        Check if current activity matches expected.
        Supports partial matching (e.g., ".MainActivity" vs "com.app/.MainActivity")
        """
        if not current or not expected:
            return False
        if current == expected:
            return True
        # Try matching just the activity name part (after /)
        current_name = current.split("/")[-1] if "/" in current else current
        expected_name = expected.split("/")[-1] if "/" in expected else expected
        return current_name == expected_name

    async def _execute_wait(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Wait/delay step with optional activity polling or timestamp refresh detection.

        Modes:
        1. If validate_timestamp + timestamp_element: Poll for UI element text change
        2. If screen_activity: Poll for that activity to appear
        3. Otherwise: Simple sleep for duration
        """
        if not step.duration:
            logger.error("  wait step missing duration")
            return False

        duration_seconds = step.duration / 1000.0

        # Mode 1: Timestamp/UI refresh detection
        if step.validate_timestamp and step.timestamp_element:
            logger.info(
                f"  Wait with UI refresh detection (max {step.refresh_max_retries} checks)"
            )

            # Get initial element text
            initial_text = await self._extract_timestamp_text(
                device_id, step.timestamp_element
            )
            if initial_text:
                logger.debug(f"  Initial element text: '{initial_text}'")
            else:
                logger.warning(
                    f"  Could not find timestamp element - falling back to simple wait"
                )
                await asyncio.sleep(duration_seconds)
                return True

            # Poll for text change
            max_retries = step.refresh_max_retries or 3
            retry_delay = (
                step.refresh_retry_delay or 2000
            ) / 1000.0  # Convert to seconds

            for attempt in range(max_retries):
                # Wait before checking (give app time to update)
                await asyncio.sleep(retry_delay)

                # Check if text changed
                new_text = await self._extract_timestamp_text(
                    device_id, step.timestamp_element
                )
                logger.debug(f"  Check {attempt + 1}/{max_retries}: '{new_text}'")

                if new_text and new_text != initial_text:
                    logger.info(
                        f"  UI updated after {attempt + 1} check(s): '{initial_text}' -> '{new_text}'"
                    )
                    return True

                if attempt < max_retries - 1:
                    logger.debug(f"  Text unchanged, waiting for next check...")

            # Max retries reached - continue anyway (soft failure)
            logger.warning(
                f"  UI text unchanged after {max_retries} checks (continuing anyway)"
            )
            return True

        # Mode 2: Activity polling
        expected_activity = step.screen_activity or step.expected_activity
        if expected_activity:
            expected_name = (
                expected_activity.split("/")[-1]
                if "/" in expected_activity
                else expected_activity
            )
            logger.debug(f"  Waiting up to {duration_seconds:.1f}s for {expected_name}")

            poll_interval = 0.5  # Check every 500ms
            max_polls = int(duration_seconds / poll_interval) + 1
            max_polls = min(max_polls, 20)  # Cap at 10 seconds of polling

            for i in range(max_polls):
                try:
                    current = await self.adb_bridge.get_current_activity(device_id)
                    if current and self._activity_matches(current, expected_activity):
                        logger.info(
                            f"  Activity {expected_name} detected after {i * poll_interval:.1f}s"
                        )
                        return True
                except Exception:
                    pass
                await asyncio.sleep(poll_interval)

            # Activity not reached, log warning but don't fail
            logger.warning(
                f"  Activity {expected_name} not detected within {duration_seconds:.1f}s"
            )
            return True  # Continue flow, step may have been for timing only

        # Mode 3: Simple sleep
        logger.debug(f"  Waiting {duration_seconds:.1f}s")
        await asyncio.sleep(duration_seconds)
        return True

    async def _execute_tap(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Tap step with optional navigation verification.

        If step description suggests navigation (contains 'Navigate to'),
        verifies the screen changed after tap.
        """
        tap_x = step.x
        tap_y = step.y
        element_meta = getattr(step, "element", None)

        if element_meta:
            resource_id = element_meta.get("resource_id") or element_meta.get(
                "resource-id"
            )
            element_text = (
                element_meta.get("text")
                or element_meta.get("content_desc")
                or element_meta.get("content-desc")
            )
            element_class = element_meta.get("class") or element_meta.get("class_name")
            stored_bounds = element_meta.get("bounds")
            element_path = element_meta.get("path") or element_meta.get("element_path")
            parent_path = element_meta.get("parent_path")

            try:
                elements_response = await self.adb_bridge.get_ui_elements(
                    device_id, bounds_only=False
                )
                ui_elements = (
                    elements_response.get("elements", elements_response)
                    if isinstance(elements_response, dict)
                    else elements_response
                )
                match = self.element_finder.find_element(
                    ui_elements=ui_elements,
                    resource_id=resource_id,
                    element_text=element_text,
                    element_class=element_class,
                    stored_bounds=stored_bounds,
                    element_path=element_path,
                    parent_path=parent_path,
                )
                if match.found and match.bounds:
                    tap_x = int(match.bounds["x"] + (match.bounds["width"] / 2))
                    tap_y = int(match.bounds["y"] + (match.bounds["height"] / 2))
                    logger.info(
                        f"  [Tap] Resolved element via {match.method} "
                        f"(confidence={match.confidence:.2f}) -> ({tap_x}, {tap_y})"
                    )
            except Exception as e:
                logger.debug(f"  [Tap] Element resolution skipped: {e}")

        if tap_x is None or tap_y is None:
            logger.error("  tap step missing x/y coordinates")
            return False

        description = step.description or ""
        expected_activity = step.expected_activity
        is_navigation = (
            bool(expected_activity)
            or "navigate" in description.lower()
            or "nav to" in description.lower()
        )

        # Get current activity before tap (for navigation verification)
        activity_before = None
        if is_navigation:
            try:
                activity_before = await self.adb_bridge.get_current_activity(device_id)
            except Exception:
                pass

        # Execute tap
        logger.debug(f"  Tapping at ({tap_x}, {tap_y})")
        await self.adb_bridge.tap(device_id, tap_x, tap_y)

        # For navigation taps, verify screen changed or expected activity appears
        if is_navigation and activity_before:
            await asyncio.sleep(0.8)  # Wait for screen transition

            try:
                activity_after = await self.adb_bridge.get_current_activity(device_id)
                if expected_activity:
                    expected_name = (
                        expected_activity.split("/")[-1]
                        if "/" in expected_activity
                        else expected_activity
                    )
                    if self._activity_matches(activity_after, expected_activity):
                        logger.info(f"  Activity {expected_name} detected after tap")
                        return True
                elif activity_after and activity_after != activity_before:
                    logger.debug(
                        f"  Screen changed: {activity_before.split('/')[-1] if activity_before else '?'} -> "
                        f"{activity_after.split('/')[-1] if activity_after else '?'}"
                    )

                # Screen didn't change or expected activity not reached - retry tap once
                logger.warning("  Screen didn't change after tap, retrying...")
                await asyncio.sleep(0.3)
                await self.adb_bridge.tap(device_id, tap_x, tap_y)
                await asyncio.sleep(0.8)

                if expected_activity:
                    activity_after = await self.adb_bridge.get_current_activity(
                        device_id
                    )
                    if self._activity_matches(activity_after, expected_activity):
                        logger.info(
                            f"  Activity {expected_name} detected after retry tap"
                        )
                        return True

                # Navigation FAILED after retry - handle based on mode
                if expected_activity:
                    final_activity = await self.adb_bridge.get_current_activity(device_id)
                    final_name = final_activity.split('/')[-1] if final_activity and '/' in final_activity else final_activity

                    # Record the navigation failure
                    nav_failure = {
                        "step_description": step.description or f"Tap at ({tap_x}, {tap_y})",
                        "expected_activity": expected_activity,
                        "actual_activity": final_activity,
                        "tap_coordinates": {"x": tap_x, "y": tap_y},
                    }
                    result.navigation_failures.append(nav_failure)

                    if result.strict_mode:
                        logger.error(
                            f"  [Strict Mode] Navigation FAILED: Expected {expected_name}, "
                            f"still on {final_name or 'unknown'}"
                        )
                        return False

                    # Non-strict mode: warn but continue (original behavior)
                    logger.warning(
                        f"  Navigation failed but continuing (strict_mode=False): "
                        f"Expected {expected_name}, on {final_name or 'unknown'}"
                    )

            except Exception as e:
                logger.debug(f"  Could not verify navigation: {e}")

        return True

    async def _execute_swipe(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Swipe step"""
        if None in (step.start_x, step.start_y, step.end_x, step.end_y):
            logger.error("  swipe step missing coordinates")
            return False

        duration = step.duration or 300  # Default 300ms
        logger.debug(
            f"  Swiping from ({step.start_x}, {step.start_y}) to ({step.end_x}, {step.end_y})"
        )

        await self.adb_bridge.swipe(
            device_id, step.start_x, step.start_y, step.end_x, step.end_y, duration
        )
        return True

    async def _execute_text(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Text input step"""
        if not step.text:
            logger.error("  text step missing text content")
            return False

        logger.debug(f"  Typing text: {step.text[:50]}...")
        await self.adb_bridge.type_text(device_id, step.text)
        return True

    async def _execute_keyevent(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Keyevent step"""
        if not step.keycode:
            logger.error("  keyevent step missing keycode")
            return False

        logger.debug(f"  Sending keyevent: {step.keycode}")
        await self.adb_bridge.keyevent(device_id, step.keycode)
        return True

    async def _execute_action(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Execute a saved action by ID

        The step should have action_id field specifying which action to execute.
        Uses the action_executor to run the action.
        """
        if not step.action_id:
            logger.error("  execute_action step missing action_id")
            return False

        if not self.action_manager or not self.action_executor:
            logger.error("  execute_action requires action_manager and action_executor")
            return False

        logger.debug(f"  Executing action: {step.action_id}")

        try:
            # Execute the action using action_executor
            # Skip navigation since the flow already navigated to the correct screen
            action_result = await self.action_executor.execute_action_by_id(
                self.action_manager,
                device_id,
                step.action_id,
                skip_navigation=True,  # Flow handles navigation, action executes directly
            )

            # Store result details
            result.details[f"action_{step.action_id}"] = {
                "action_id": step.action_id,
                "success": action_result.success,
                "message": action_result.message,
                "execution_time_ms": action_result.execution_time,
            }

            if action_result.success:
                logger.debug(f"  Action {step.action_id} executed successfully")
                return True
            else:
                logger.error(
                    f"  Action {step.action_id} failed: {action_result.message}"
                )
                return False

        except Exception as e:
            logger.error(f"  Action execution error: {e}")
            result.details[f"action_{step.action_id}"] = {
                "action_id": step.action_id,
                "success": False,
                "error": str(e),
            }
            return False

    async def _execute_pull_refresh(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Pull-to-refresh gesture with optional timestamp validation"""
        logger.debug("  Executing pull-to-refresh")

        # Get device dimensions (use defaults if not available)
        width = 1080
        height = 1920

        # Pull-to-refresh: start near top (15%), drag to middle (55%)
        start_x = width // 2
        start_y = int(height * 0.15)
        end_x = start_x
        end_y = int(height * 0.55)
        duration = 350

        # Check if timestamp validation is enabled
        if step.validate_timestamp and step.timestamp_element:
            logger.debug("  Timestamp validation enabled")

            # Extract initial timestamp before refresh
            initial_timestamp = await self._extract_timestamp_text(
                device_id, step.timestamp_element
            )
            logger.debug(f"  Initial timestamp: {initial_timestamp}")

            # Attempt refresh with retries
            max_retries = step.refresh_max_retries or 3
            retry_delay = (
                step.refresh_retry_delay or 2000
            ) / 1000.0  # Convert to seconds

            for attempt in range(max_retries):
                logger.debug(f"  Refresh attempt {attempt + 1}/{max_retries}")

                # Execute pull-to-refresh gesture
                await self.adb_bridge.swipe(
                    device_id, start_x, start_y, end_x, end_y, duration
                )

                # Wait for refresh to complete
                await asyncio.sleep(retry_delay)

                # Extract new timestamp
                new_timestamp = await self._extract_timestamp_text(
                    device_id, step.timestamp_element
                )
                logger.debug(f"  New timestamp: {new_timestamp}")

                # Check if timestamp changed
                if new_timestamp and new_timestamp != initial_timestamp:
                    logger.info(f"  ✓ Timestamp changed after {attempt + 1} attempt(s)")
                    return True

                # Log retry if timestamp unchanged
                if attempt < max_retries - 1:
                    logger.warning(
                        f"  Timestamp unchanged, retrying refresh ({attempt + 2}/{max_retries})"
                    )

            # Max retries reached
            logger.warning(
                f"  Timestamp still unchanged after {max_retries} attempts (soft failure)"
            )
            return True  # Continue flow anyway (soft failure)

        else:
            # No timestamp validation - execute once
            await self.adb_bridge.swipe(
                device_id, start_x, start_y, end_x, end_y, duration
            )

            # Wait a moment for refresh to complete
            await asyncio.sleep(0.8)
            return True

    async def _execute_restart_app(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Restart app - force stop and relaunch using batch commands for speed
        With optional timestamp validation to ensure data actually updated

        Uses PersistentADBShell for 50-70% faster execution vs. individual commands
        """
        if not step.package:
            logger.error("  restart_app step missing package name")
            return False

        logger.debug(f"  Restarting app: {step.package} (batch mode)")

        # Check if timestamp validation is enabled
        if step.validate_timestamp and step.timestamp_element:
            logger.debug("  Timestamp validation enabled")

            # Extract initial timestamp before restart
            initial_timestamp = await self._extract_timestamp_text(
                device_id, step.timestamp_element
            )
            logger.debug(f"  Initial timestamp: {initial_timestamp}")

            # Attempt restart with retries
            max_retries = step.refresh_max_retries or 3
            retry_delay = (
                step.refresh_retry_delay or 2000
            ) / 1000.0  # Convert to seconds

            for attempt in range(max_retries):
                logger.debug(f"  Restart attempt {attempt + 1}/{max_retries}")

                try:
                    # Execute stop and launch in a single batch (50-70% faster)
                    commands = [
                        f"am force-stop {step.package}",  # Force stop the app
                        "sleep 0.5",  # Wait for stop to complete
                        f"monkey -p {step.package} -c android.intent.category.LAUNCHER 1",  # Relaunch
                    ]

                    results = await self.adb_bridge.execute_batch_commands(
                        device_id, commands
                    )

                    # Check if all commands succeeded
                    all_success = all(success for success, _ in results)

                    if not all_success:
                        # Log which command failed
                        for i, (success, output) in enumerate(results):
                            if not success:
                                logger.error(f"  Batch command {i} failed: {output}")
                        return False

                    # Wait for app to fully start
                    await asyncio.sleep(1.5)

                except Exception as e:
                    logger.error(
                        f"  Batch restart failed, falling back to sequential: {e}"
                    )

                    # Fallback to sequential execution
                    await self.adb_bridge.stop_app(device_id, step.package)
                    await asyncio.sleep(0.5)
                    success = await self.adb_bridge.launch_app(device_id, step.package)
                    if not success:
                        return False
                    await asyncio.sleep(1.5)

                # Wait for refresh to complete
                await asyncio.sleep(retry_delay)

                # Extract new timestamp
                new_timestamp = await self._extract_timestamp_text(
                    device_id, step.timestamp_element
                )
                logger.debug(f"  New timestamp: {new_timestamp}")

                # Check if timestamp changed
                if new_timestamp and new_timestamp != initial_timestamp:
                    logger.info(f"  ✓ Timestamp changed after {attempt + 1} attempt(s)")
                    return True

                # Log retry if timestamp unchanged
                if attempt < max_retries - 1:
                    logger.warning(
                        f"  Timestamp unchanged, retrying restart ({attempt + 2}/{max_retries})"
                    )

            # Max retries reached
            logger.warning(
                f"  Timestamp still unchanged after {max_retries} attempts (soft failure)"
            )
            return True  # Continue flow anyway (soft failure)

        else:
            # No timestamp validation - execute once
            try:
                # Execute stop and launch in a single batch (50-70% faster)
                commands = [
                    f"am force-stop {step.package}",  # Force stop the app
                    "sleep 0.5",  # Wait for stop to complete
                    f"monkey -p {step.package} -c android.intent.category.LAUNCHER 1",  # Relaunch
                ]

                results = await self.adb_bridge.execute_batch_commands(
                    device_id, commands
                )

                # Check if all commands succeeded
                all_success = all(success for success, _ in results)

                if not all_success:
                    # Log which command failed
                    for i, (success, output) in enumerate(results):
                        if not success:
                            logger.error(f"  Batch command {i} failed: {output}")
                    return False

                # Wait for app to fully start
                await asyncio.sleep(1.5)

                logger.debug(f"  App restart complete: {step.package}")
                return True

            except Exception as e:
                logger.error(f"  Batch restart failed, falling back to sequential: {e}")

                # Fallback to sequential execution
                await self.adb_bridge.stop_app(device_id, step.package)
                await asyncio.sleep(0.5)
                success = await self.adb_bridge.launch_app(device_id, step.package)
                await asyncio.sleep(1.5)

                return success

    async def _execute_capture_sensors(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Capture sensors at this step with smart element detection

        Process:
        1. Capture screenshot
        2. Get UI elements (full info for smart detection)
        3. For each sensor, use smart element finder to locate dynamically
        4. Extract value using found bounds
        5. Publish to MQTT immediately
        6. Store in result
        """
        if not step.sensor_ids:
            logger.warning("  capture_sensors step has no sensor_ids")
            return True

        # Check which sensors actually need updating based on their individual intervals
        sensors_to_capture = []
        sensors_skipped = []

        for sensor_id in step.sensor_ids:
            sensor = self.sensor_manager.get_sensor(device_id, sensor_id)
            if not sensor:
                # Try stable ID lookup
                sensor = self._find_sensor_by_stable_id(device_id, sensor_id)

            needs_update, seconds_until = self._sensor_needs_update(sensor, device_id)

            if needs_update:
                sensors_to_capture.append(sensor_id)
            else:
                sensors_skipped.append((sensor_id, sensor.friendly_name if sensor else sensor_id, seconds_until))

        # Log skipped sensors
        if sensors_skipped:
            skipped_names = [f"{name} ({int(secs)}s remaining)" for _, name, secs in sensors_skipped]
            logger.info(f"  [Interval] Skipping {len(sensors_skipped)} sensors (not due yet): {', '.join(skipped_names)}")

        # If ALL sensors can be skipped, return early (saves screenshot + UI dump time)
        if not sensors_to_capture:
            logger.info(f"  [Interval] All {len(step.sensor_ids)} sensors skipped - none due for update")
            return True  # Success - nothing to capture, but not a failure

        logger.debug(f"  Capturing {len(sensors_to_capture)}/{len(step.sensor_ids)} sensors (interval-based filtering)")

        try:
            # 0a. Quick check for NotificationShade/StatusBar - dismiss immediately if present
            current_activity = await self.adb_bridge.get_current_activity(device_id)
            if current_activity and (
                "NotificationShade" in current_activity
                or "StatusBar" in current_activity
            ):
                logger.info(
                    f"  [SensorCapture] NotificationShade detected, dismissing..."
                )
                # Use the fastest dismissal method first
                conn = self.adb_bridge.devices.get(device_id)
                if conn:
                    await conn.shell("cmd statusbar collapse")
                    await asyncio.sleep(0.3)
                    # If still showing, try HOME key
                    current_activity = await self.adb_bridge.get_current_activity(
                        device_id
                    )
                    if current_activity and "NotificationShade" in current_activity:
                        await conn.shell("input keyevent 3")  # HOME
                        await asyncio.sleep(0.3)
                logger.info(f"  [SensorCapture] NotificationShade dismissed")

            # 0b. Validate correct app AND screen is visible before capturing
            expected_package = step.screen_package
            expected_activity = step.screen_activity  # Activity when sensor was created

            if not expected_package and step.sensor_ids:
                # Try to get expected package from first sensor's source
                first_sensor = self.sensor_manager.get_sensor(
                    device_id, step.sensor_ids[0]
                )
                if (
                    first_sensor
                    and first_sensor.source
                    and first_sensor.source.element_resource_id
                ):
                    # Extract package from resource ID (e.g., "com.byd.bydautolink:id/tem_tv" -> "com.byd.bydautolink")
                    resource_id = first_sensor.source.element_resource_id
                    if ":id/" in resource_id:
                        expected_package = resource_id.split(":id/")[0]

            current_activity = await self.adb_bridge.get_current_activity(device_id)
            current_package = (
                current_activity.split("/")[0]
                if current_activity and "/" in current_activity
                else current_activity
            )
            current_activity_name = (
                current_activity.split("/")[-1]
                if current_activity and "/" in current_activity
                else current_activity
            )

            # Check if on correct ACTIVITY (specific screen within app)
            if expected_activity:
                expected_activity_name = (
                    expected_activity.split("/")[-1]
                    if "/" in expected_activity
                    else expected_activity
                )
                activity_match = self._activity_matches(
                    current_activity, expected_activity
                )

                if not activity_match:
                    # Screen mismatch - poll for expected activity (app may still be loading)
                    logger.warning(
                        f"Screen mismatch during sensor capture. "
                        f"Expected activity: '{expected_activity_name}', "
                        f"but the current activity is: '{current_activity_name}'. "
                        f"Full expected: '{expected_activity}', "
                        f"Full current: '{current_activity}'."
                    )
                    logger.info(
                        f"  Waiting for '{expected_activity_name}' to appear..."
                    )

                    # Poll for expected activity (up to 8 seconds with 500ms intervals)
                    poll_interval = 0.5
                    max_polls = 16  # 8 seconds total
                    activity_found = False

                    for poll in range(max_polls):
                        await asyncio.sleep(poll_interval)
                        current_activity = await self.adb_bridge.get_current_activity(
                            device_id
                        )
                        if self._activity_matches(current_activity, expected_activity):
                            logger.info(
                                f"  Activity {expected_activity_name} appeared after {(poll + 1) * poll_interval:.1f}s"
                            )
                            activity_found = True
                            break
                        # Log progress every 2 seconds
                        if (poll + 1) % 4 == 0:
                            curr_name = (
                                current_activity.split("/")[-1]
                                if current_activity and "/" in current_activity
                                else current_activity
                            )
                            logger.debug(
                                f"  Still waiting... Current: {curr_name} ({(poll + 1) * poll_interval:.1f}s)"
                            )

                    if not activity_found:
                        # Final attempt: check if it's NotificationShade blocking us
                        current_activity = await self.adb_bridge.get_current_activity(
                            device_id
                        )
                        current_package = (
                            current_activity.split("/")[0]
                            if current_activity and "/" in current_activity
                            else current_activity
                        )

                        # First, dismiss NotificationShade if that's what's blocking
                        if current_activity and "NotificationShade" in current_activity:
                            logger.info(
                                f"  NotificationShade blocking recovery, dismissing..."
                            )
                            conn = self.adb_bridge.devices.get(device_id)
                            if conn:
                                await conn.shell("cmd statusbar collapse")
                                await asyncio.sleep(0.3)
                                await conn.shell("input keyevent 3")  # HOME as backup
                                await asyncio.sleep(0.5)
                            current_activity = (
                                await self.adb_bridge.get_current_activity(device_id)
                            )
                            current_package = (
                                current_activity.split("/")[0]
                                if current_activity and "/" in current_activity
                                else current_activity
                            )
                            if self._activity_matches(
                                current_activity, expected_activity
                            ):
                                logger.info(
                                    f"  NotificationShade dismissed, now on correct screen"
                                )
                                activity_found = True

                        if (
                            not activity_found
                            and expected_package
                            and current_package != expected_package
                        ):
                            logger.info(
                                f"  Attempting recovery: launching {expected_package}"
                            )
                            success = await self.adb_bridge.launch_app(
                                device_id, expected_package
                            )
                            if success:
                                await asyncio.sleep(2)  # Reduced from 3s to 2s
                                new_activity = (
                                    await self.adb_bridge.get_current_activity(
                                        device_id
                                    )
                                )
                                if self._activity_matches(
                                    new_activity, expected_activity
                                ):
                                    logger.info(
                                        f"  Recovery successful: reached {expected_activity_name}"
                                    )
                                    activity_found = True

                        if not activity_found:
                            current_activity_name = (
                                current_activity.split("/")[-1]
                                if current_activity and "/" in current_activity
                                else current_activity
                            )
                            logger.error(
                                f"Timeout waiting for expected screen '{expected_activity_name}'. "
                                f"The current screen is still '{current_activity_name}'. "
                                f"Sensors may not be found. Please check the flow sequence. "
                                f"Hint: Ensure navigation steps (taps, swipes) correctly lead to this screen, "
                                f"or add a longer WAIT step."
                            )
                else:
                    logger.debug(f"  Correct screen: {current_activity_name}")

            # Check if on correct PACKAGE (app) - fallback if no activity specified
            elif expected_package:
                if current_package != expected_package:
                    logger.warning(
                        f"  Wrong app in foreground: {current_package} (expected: {expected_package})"
                    )

                    # Try to recover by launching the expected app
                    logger.info(
                        f"  Attempting recovery: launching {expected_package}..."
                    )

                    # Force stop and relaunch to get clean state
                    try:
                        await self.adb_bridge.stop_app(device_id, expected_package)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.debug(f"  Could not force-stop: {e}")

                    # Launch the app
                    success = await self.adb_bridge.launch_app(
                        device_id, expected_package
                    )
                    if success:
                        await asyncio.sleep(2)  # Wait for app to load
                        logger.info(f"  Recovery: Launched {expected_package}")

                        # Verify we're now on the correct app
                        new_activity = await self.adb_bridge.get_current_activity(
                            device_id
                        )
                        new_package = (
                            new_activity.split("/")[0]
                            if new_activity and "/" in new_activity
                            else new_activity
                        )
                        if new_package == expected_package:
                            logger.info(
                                f"  Recovery successful: now on {expected_package}"
                            )
                        else:
                            logger.warning(
                                f"  Recovery may have failed: still on {new_package}"
                            )
                    else:
                        logger.warning(
                            f"  Recovery failed: could not launch {expected_package}"
                        )
                else:
                    logger.debug(f"  Correct app in foreground: {current_package}")

            # 1. Capture screenshot
            screenshot_bytes = await self.adb_bridge.capture_screenshot(device_id)
            if not screenshot_bytes:
                logger.error("  Failed to capture screenshot")
                return False

            # Convert to PIL Image for text extraction
            screenshot_image = Image.open(io.BytesIO(screenshot_bytes))

            # 2. Get UI elements with FULL info for smart element detection
            # (not bounds_only - we need resource_id, text, class for smart matching)
            ui_elements = await self.adb_bridge.get_ui_elements(
                device_id, bounds_only=False
            )

            # 3. Extract each sensor and collect for batch publishing
            # Only process sensors that need updating (filtered by interval above)
            sensor_updates = []  # List of (sensor, value) tuples for batch publishing
            cached_count = 0
            interval_skipped_count = len(step.sensor_ids) - len(sensors_to_capture)
            for sensor_id in sensors_to_capture:
                # Check session cache first - avoid redundant captures
                if sensor_id in self._session_captured_sensors:
                    cached_value = self._session_captured_sensors[sensor_id]
                    result.captured_sensors[sensor_id] = cached_value
                    cached_count += 1
                    logger.debug(
                        f"  Sensor {sensor_id}: using cached value '{cached_value}'"
                    )
                    continue

                sensor = self.sensor_manager.get_sensor(device_id, sensor_id)
                if not sensor:
                    # Try to find sensor by stable_device_id (may be on different port)
                    sensor = self._find_sensor_by_stable_id(device_id, sensor_id)
                    if not sensor:
                        logger.warning(f"  Sensor {sensor_id} not found, skipping")
                        continue

                try:
                    # Smart element detection - find element dynamically
                    stored_bounds = None
                    if sensor.source.custom_bounds:
                        stored_bounds = {
                            "x": sensor.source.custom_bounds.x,
                            "y": sensor.source.custom_bounds.y,
                            "width": sensor.source.custom_bounds.width,
                            "height": sensor.source.custom_bounds.height,
                        }

                    match = self.element_finder.find_element(
                        ui_elements=ui_elements,
                        resource_id=sensor.source.element_resource_id,
                        element_text=sensor.source.element_text,
                        element_class=sensor.source.element_class,
                        stored_bounds=stored_bounds,
                    )

                    if not match.found:
                        logger.warning(
                            f"  Could not locate element for {sensor.friendly_name}: {match.message}"
                        )
                        continue

                    # Log detection method for debugging
                    if match.method != "stored_bounds":
                        logger.info(
                            f"  Smart detection for {sensor.friendly_name}: {match.method} (confidence: {match.confidence:.0%})"
                        )

                    # Use found bounds for extraction
                    extraction_bounds = match.bounds

                    # Extract value from element's text using extraction rule
                    raw_text = match.element.get("text", "") if match.element else ""
                    if raw_text:
                        value = self.text_extractor.extract(
                            raw_text, sensor.extraction_rule
                        )
                    else:
                        logger.warning(
                            f"  Element has no text for {sensor.friendly_name}"
                        )
                        value = (
                            sensor.extraction_rule.fallback_value
                            if sensor.extraction_rule
                            else None
                        )

                    # Store in result and session cache
                    result.captured_sensors[sensor_id] = value
                    self._session_captured_sensors[sensor_id] = value  # Cache for dedup

                    logger.debug(f"  Captured {sensor.friendly_name}: {value}")

                    # Collect for batch publishing (20-30% faster than individual)
                    sensor_updates.append((sensor, value))

                    # Check if element moved significantly from stored position
                    if (
                        match.method != "stored_bounds"
                        and stored_bounds
                        and match.bounds
                    ):
                        is_similar, distance = self.element_finder.compare_bounds(
                            stored_bounds, match.bounds
                        )
                        if not is_similar and distance > 10:  # Moved more than 10px
                            if result.repair_mode:
                                # Auto-repair: Update sensor bounds
                                logger.info(
                                    f"  [Repair Mode] Element moved {distance:.0f}px - auto-updating bounds"
                                )
                                try:
                                    # Update the sensor's element bounds
                                    old_bounds = sensor.element_bounds.copy() if sensor.element_bounds else None
                                    sensor.element_bounds = match.bounds
                                    self.sensor_manager.update_sensor(sensor)

                                    # Track the repair in result
                                    result.bounds_repaired.append({
                                        "sensor_id": sensor_id,
                                        "sensor_name": sensor.friendly_name,
                                        "old_bounds": old_bounds,
                                        "new_bounds": match.bounds,
                                        "drift_distance": distance,
                                        "detection_method": match.method,
                                    })
                                    logger.info(
                                        f"  [Repair Mode] Updated bounds for {sensor.friendly_name}"
                                    )
                                except Exception as repair_err:
                                    logger.warning(
                                        f"  [Repair Mode] Failed to update bounds: {repair_err}"
                                    )
                            else:
                                logger.info(
                                    f"  Element moved {distance:.0f}px - consider updating sensor bounds (use repair_mode=true to auto-fix)"
                                )

                except Exception as e:
                    logger.error(f"  Failed to extract sensor {sensor_id}: {e}")
                    # Continue with other sensors (don't fail entire step)

            # 4. Ensure MQTT discovery is published before state (auto-recreates deleted entities)
            if sensor_updates:
                for sensor, _ in sensor_updates:
                    try:
                        await self.mqtt_manager.publish_discovery(sensor)
                    except Exception as e:
                        logger.debug(f"  Discovery publish for {sensor.sensor_id}: {e}")

            # 5. Batch publish all sensor states at once (20-30% faster)
            if sensor_updates:
                batch_result = await self.mqtt_manager.publish_state_batch(
                    sensor_updates
                )
                logger.debug(
                    f"  Batch published {batch_result['success']}/{len(sensor_updates)} sensors to MQTT"
                )

                # 6. Persist captured sensor values to disk (fixes stale current_value issue)
                for sensor, value in sensor_updates:
                    sensor.current_value = str(value) if value is not None else None
                    sensor.last_updated = datetime.now()
                    self.sensor_manager.update_sensor(sensor)
                    logger.debug(f"  Persisted {sensor.friendly_name} = {value}")

            # Log capture results
            fresh_count = len(sensor_updates)
            total_sensors = len(step.sensor_ids)
            if fresh_count > 0:
                logger.info(f"  Sensors captured: {fresh_count}")
            if cached_count > 0:
                logger.info(
                    f"  Session cache: {cached_count}/{total_sensors} from cache, {fresh_count} freshly captured"
                )
            if interval_skipped_count > 0:
                logger.debug(
                    f"  Interval skip: {interval_skipped_count}/{total_sensors} skipped (not due for update)"
                )
            # Only fail if no sensors were captured AND none were skipped by interval
            # (interval-skipped sensors are intentional, not failures)
            if fresh_count == 0 and cached_count == 0 and interval_skipped_count == 0:
                logger.warning(f"  No sensors captured (0/{total_sensors})")
                return False

            return True

        except Exception as e:
            logger.error(f"  Sensor capture failed: {e}", exc_info=True)
            return False

    def _find_sensor_by_stable_id(self, current_device_id: str, sensor_id: str):
        """
        Try to find a sensor that may have been created on a different device port
        but belongs to the same physical device (matched by stable_device_id).
        """
        try:
            # Get stable_device_id for current device
            # This would need async but we'll do a simple lookup for now
            # Check all device sensors for matching sensor_id pattern
            device_list = self.sensor_manager.get_device_list()
            for device_id in device_list:
                sensors = self.sensor_manager.get_all_sensors(device_id)
                for sensor in sensors:
                    if sensor.sensor_id == sensor_id:
                        logger.info(
                            f"  Found sensor {sensor_id} on device {device_id} (current: {current_device_id})"
                        )
                        return sensor
            return None
        except Exception as e:
            logger.debug(f"  Error finding sensor by stable ID: {e}")
            return None

    async def _execute_validate_screen(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Validate screen by checking for expected UI element

        Args:
            validation_element should contain:
            {
                "text": "Expected Text",
                "class": "android.widget.TextView"  # optional
            }
        """
        if not step.validation_element:
            logger.error("  validate_screen step missing validation_element")
            return False

        logger.debug(f"  Validating screen for element: {step.validation_element}")

        try:
            # Get UI elements
            ui_elements = await self.adb_bridge.get_ui_elements(device_id)

            # Search for matching element
            expected_text = step.validation_element.get("text")
            expected_class = step.validation_element.get("class")

            for element in ui_elements:
                # Check text match
                if expected_text:
                    element_text = element.get("text", "")
                    if expected_text.lower() not in element_text.lower():
                        continue

                # Check class match (if specified)
                if expected_class:
                    element_class = element.get("class", "")
                    if expected_class != element_class:
                        continue

                # Found matching element
                logger.debug(f"  Screen validation passed: found element")
                return True

            logger.warning(f"  Screen validation failed: element not found")
            return False

        except Exception as e:
            logger.error(f"  Screen validation error: {e}", exc_info=True)
            return False

    async def _execute_go_home(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Go to home screen"""
        logger.debug("  Going to home screen")
        await self.adb_bridge.keyevent(device_id, "KEYCODE_HOME")
        return True

    async def _execute_go_back(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Press back button"""
        logger.debug("  Pressing back button")
        await self.adb_bridge.keyevent(device_id, "KEYCODE_BACK")
        return True

    # ========== Screen Power Control (Headless Mode) ==========

    async def _execute_wake_screen(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Wake the device screen"""
        logger.debug("  [Headless] Waking screen")
        return await self.adb_bridge.wake_screen(device_id)

    async def _execute_sleep_screen(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Put the device screen to sleep"""
        logger.debug("  [Headless] Sleeping screen")
        # Optional delay before sleep
        if step.duration:
            await asyncio.sleep(step.duration / 1000.0)
        return await self.adb_bridge.sleep_screen(device_id)

    async def _execute_ensure_screen_on(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Ensure screen is on before proceeding"""
        timeout = (
            step.duration or 3000
        )  # Use duration field for timeout, default 3000ms
        logger.debug(f"  [Headless] Ensuring screen is on (timeout: {timeout}ms)")
        success = await self.adb_bridge.ensure_screen_on(device_id, timeout_ms=timeout)
        if not success:
            result.error_message = f"Screen failed to wake after {timeout}ms"
            logger.warning(f"  [Headless] {result.error_message}")
        return success

    async def _execute_stitch_capture(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Capture and stitch multiple screenshots (for scrollable content)"""
        logger.debug("  Executing stitch capture")
        try:
            if self.screenshot_stitcher:
                # Use the screenshot stitcher for multi-screenshot capture
                stitched_result = await self.screenshot_stitcher.capture_stitched(
                    device_id,
                    max_scrolls=step.max_scrolls if hasattr(step, "max_scrolls") else 5,
                )
                if stitched_result:
                    result.captured_screenshots.append(
                        {
                            "type": "stitched",
                            "step_index": result.steps_completed,
                            "data": stitched_result,
                        }
                    )
                    return True
            else:
                logger.warning("  Screenshot stitcher not available")
                return False
        except Exception as e:
            logger.error(f"  Stitch capture failed: {e}")
            return False

    async def _execute_screenshot(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Capture a single screenshot at the current screen"""
        logger.debug("  Executing screenshot capture")
        try:
            # Capture screenshot
            screenshot_data = await self.adb_bridge.capture_screenshot(device_id)
            if screenshot_data:
                result.captured_screenshots.append(
                    {
                        "type": "screenshot",
                        "step_index": result.executed_steps,
                        "description": step.description or "Screenshot",
                        "expected_screen_id": getattr(step, "expected_screen_id", None),
                    }
                )
                logger.debug(f"  Screenshot captured successfully")
                return True
            else:
                logger.warning("  Screenshot capture returned no data")
                return False
        except Exception as e:
            logger.error(f"  Screenshot capture failed: {e}")
            return False

    async def _execute_conditional(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Conditional step (if/else branching)

        Condition types:
        - "element_exists:text=Hello" - Check if UI element with text exists
        - "element_exists:resource-id=button_ok" - Check by resource ID
        - "var:counter>5" - Compare variable value
        - "var:status==success" - String comparison
        - "screen_activity:MainActivity" - Check current activity
        """
        if not step.condition:
            logger.warning("  Conditional step missing condition")
            return False

        logger.debug(f"  Evaluating condition: {step.condition}")

        try:
            condition_met = await self._evaluate_condition(device_id, step.condition)
            logger.debug(f"  Condition result: {condition_met}")

            # Execute appropriate branch
            if condition_met and step.true_steps:
                logger.debug(f"  Executing true branch ({len(step.true_steps)} steps)")
                for nested_step in step.true_steps:
                    success = await self._execute_single_step(
                        device_id, nested_step, result
                    )
                    if not success and step.retry_on_failure:
                        return False
            elif not condition_met and step.false_steps:
                logger.debug(
                    f"  Executing false branch ({len(step.false_steps)} steps)"
                )
                for nested_step in step.false_steps:
                    success = await self._execute_single_step(
                        device_id, nested_step, result
                    )
                    if not success and step.retry_on_failure:
                        return False

            return True

        except Exception as e:
            logger.error(f"  Conditional evaluation failed: {e}")
            return False

    async def _evaluate_condition(self, device_id: str, condition: str) -> bool:
        """
        Evaluate a condition expression

        Supported formats:
        - element_exists:text=Hello
        - element_exists:resource-id=btn_ok
        - var:name==value
        - var:count>5
        - screen_activity:MainActivity
        """
        try:
            if condition.startswith("element_exists:"):
                # Check if UI element exists
                criteria = condition[15:]  # Remove prefix
                key, value = criteria.split("=", 1)
                ui_elements = await self.adb_bridge.get_ui_elements(device_id)

                for elem in ui_elements:
                    if key == "text" and elem.get("text") == value:
                        return True
                    elif key == "resource-id" and elem.get("resource-id") == value:
                        return True
                    elif key == "class" and elem.get("class") == value:
                        return True
                return False

            elif condition.startswith("var:"):
                # Variable comparison
                expr = condition[4:]  # Remove prefix
                return self._evaluate_variable_expression(expr)

            elif condition.startswith("screen_activity:"):
                # Check current activity
                expected = condition[16:]
                current = await self.adb_bridge.get_current_activity(device_id)
                return expected in current

            else:
                # Try as simple variable expression
                return self._evaluate_variable_expression(condition)

        except Exception as e:
            logger.error(f"  Condition evaluation error: {e}")
            return False

    def _evaluate_variable_expression(self, expr: str) -> bool:
        """Evaluate a simple variable expression like 'count>5' or 'status==done'"""
        import re

        # Parse comparison operators
        for op in ["==", "!=", ">=", "<=", ">", "<"]:
            if op in expr:
                parts = expr.split(op, 1)
                if len(parts) == 2:
                    var_name = parts[0].strip()
                    compare_value = parts[1].strip()

                    # Get variable value
                    var_value = self._variable_context.get(var_name)
                    if var_value is None:
                        return False

                    # Try numeric comparison
                    try:
                        var_num = float(var_value)
                        compare_num = float(compare_value)

                        if op == "==":
                            return var_num == compare_num
                        elif op == "!=":
                            return var_num != compare_num
                        elif op == ">=":
                            return var_num >= compare_num
                        elif op == "<=":
                            return var_num <= compare_num
                        elif op == ">":
                            return var_num > compare_num
                        elif op == "<":
                            return var_num < compare_num
                    except (ValueError, TypeError):
                        # Fall back to string comparison
                        var_str = str(var_value)
                        if op == "==":
                            return var_str == compare_value
                        elif op == "!=":
                            return var_str != compare_value

        # Check for truthy value of variable
        return bool(self._variable_context.get(expr))

    async def _execute_single_step(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Execute a single step using the step handlers.

        Used for nested steps in conditionals and loops.

        Args:
            device_id: Device ID
            step: FlowStep to execute
            result: FlowExecutionResult to update

        Returns:
            True if step succeeded, False otherwise
        """
        handler = self.step_handlers.get(step.step_type)
        if not handler:
            logger.error(f"  Unknown nested step type: {step.step_type}")
            return False

        try:
            return await handler(device_id, step, result)
        except Exception as e:
            logger.error(f"  Nested step {step.step_type} failed: {e}")
            return False

    # ============================================================================
    # State Validation Methods (Phase 8 - Hybrid XML + Activity + Screenshot)
    # ============================================================================

    async def _validate_state_and_recover(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Validate device state before executing step, with recovery on mismatch

        Hybrid validation strategy (in order of preference):
        1. XML UI Elements - Most reliable
        2. Activity Name - Fast and accurate
        3. Screenshot Similarity - Fallback only

        Args:
            device_id: Device ID
            step: Step with expected state info
            result: Execution result object

        Returns:
            True if state matches or was recovered, False otherwise
        """
        logger.debug(f"  [StateValidation] Checking state for {step.step_type}")

        # Attempt state validation
        state_valid, match_score = await self._validate_state_hybrid(device_id, step)

        if state_valid:
            logger.debug(f"  [StateValidation] State valid (score: {match_score:.2f})")
            return True

        # State mismatch detected
        logger.warning(
            f"  [StateValidation] State mismatch detected (score: {match_score:.2f}, threshold: {step.state_match_threshold:.2f})"
        )

        # Attempt recovery
        recovery_success = await self._recover_from_state_mismatch(device_id, step)

        if recovery_success:
            # Re-validate after recovery
            state_valid, match_score = await self._validate_state_hybrid(
                device_id, step
            )
            if state_valid:
                logger.info(
                    f"  [StateValidation] State recovered successfully (score: {match_score:.2f})"
                )
                return True
            else:
                logger.error(
                    f"  [StateValidation] State recovery failed (score: {match_score:.2f})"
                )
                return False
        else:
            logger.error(f"  [StateValidation] Recovery action failed")
            return False

    async def _validate_state_hybrid(
        self, device_id: str, step: FlowStep
    ) -> tuple[bool, float]:
        """
        Hybrid state validation using XML UI + Activity + Screenshot

        Returns:
            (is_valid, confidence_score)
        """
        confidence_scores = []

        # Strategy 1: XML UI Elements (Most reliable)
        if step.expected_ui_elements and len(step.expected_ui_elements) > 0:
            try:
                ui_elements = await self.adb_bridge.get_ui_elements(device_id)
                matched_count = 0

                for expected_elem in step.expected_ui_elements:
                    expected_text = expected_elem.get("text")
                    expected_class = expected_elem.get("class")
                    expected_resource_id = expected_elem.get("resource-id")

                    # Search for matching element
                    for elem in ui_elements:
                        if expected_text and elem.get("text") == expected_text:
                            matched_count += 1
                            break
                        if expected_class and elem.get("class") == expected_class:
                            if expected_resource_id:
                                if elem.get("resource-id") == expected_resource_id:
                                    matched_count += 1
                                    break
                            else:
                                matched_count += 1
                                break

                ui_match_score = matched_count / len(step.expected_ui_elements)
                confidence_scores.append(ui_match_score)

                logger.debug(
                    f"  [StateValidation] UI Elements: {matched_count}/{len(step.expected_ui_elements)} matched (score: {ui_match_score:.2f})"
                )

                # If UI element match is strong, we can skip other checks
                if matched_count >= step.ui_elements_required:
                    return (True, ui_match_score)

            except Exception as e:
                logger.debug(f"  [StateValidation] UI element check failed: {e}")

        # Strategy 2: Activity Name (Fast and accurate)
        # Check expected_activity (explicit) or screen_activity (from recording)
        expected_act = step.expected_activity or step.screen_activity
        if expected_act:
            try:
                # Retry up to 3 times if activity is empty (transient null during transitions)
                current_activity = ""
                for retry in range(3):
                    current_activity = await self.adb_bridge.get_current_activity(
                        device_id
                    )
                    if current_activity:
                        break
                    if retry < 2:
                        logger.debug(
                            f"  [StateValidation] Activity empty, retrying ({retry + 1}/3)..."
                        )
                        await asyncio.sleep(0.3)  # Brief delay for focus to settle

                # If still empty after retries, skip activity validation (don't fail)
                if not current_activity:
                    logger.debug(
                        f"  [StateValidation] Could not determine current activity, skipping activity check"
                    )
                    # Don't add score - let other validation methods decide
                else:
                    # Match can be exact or just the activity name part (after /)
                    activity_match = False
                    if current_activity == expected_act:
                        activity_match = True
                    else:
                        # Try matching just the activity name (e.g., ".MainActivity" vs "com.app/.MainActivity")
                        current_name = (
                            current_activity.split("/")[-1]
                            if "/" in current_activity
                            else current_activity
                        )
                        expected_name = (
                            expected_act.split("/")[-1]
                            if "/" in expected_act
                            else expected_act
                        )
                        if current_name == expected_name:
                            activity_match = True
                        # Also try matching full package/activity format
                        elif "/" in expected_act and "/" in current_activity:
                            # Compare just the activity class name
                            curr_class = current_activity.split("/")[-1].split(".")[-1]
                            exp_class = expected_act.split("/")[-1].split(".")[-1]
                            if curr_class == exp_class:
                                activity_match = True

                    activity_score = 1.0 if activity_match else 0.0
                    confidence_scores.append(activity_score)

                    logger.debug(
                        f"  [StateValidation] Activity: {current_activity} vs {expected_act} (match: {activity_match})"
                    )

                    if activity_match:
                        return (True, activity_score)

            except Exception as e:
                logger.debug(f"  [StateValidation] Activity check failed: {e}")

        # Strategy 3: Screenshot Similarity (Fallback)
        if step.expected_screenshot:
            try:
                screenshot_match_score = await self._compare_screenshots(
                    device_id, step.expected_screenshot
                )
                confidence_scores.append(screenshot_match_score)

                logger.debug(
                    f"  [StateValidation] Screenshot similarity: {screenshot_match_score:.2f}"
                )

            except Exception as e:
                logger.debug(f"  [StateValidation] Screenshot check failed: {e}")

        # Calculate overall confidence
        if len(confidence_scores) == 0:
            logger.warning(f"  [StateValidation] No validation criteria available")
            return (True, 1.0)  # No criteria = assume valid

        avg_score = sum(confidence_scores) / len(confidence_scores)
        is_valid = avg_score >= step.state_match_threshold

        return (is_valid, avg_score)

    async def _calculate_screenshot_similarity(
        self, device_id: str, expected_screenshot_b64: str
    ) -> float:
        """
        Calculate similarity score between current screen and expected screenshot.
        Uses OpenCV histogram comparison if available, falls back to PIL histogram.

        Args:
            device_id: Device ID
            expected_screenshot_b64: Base64 encoded expected screenshot

        Returns:
            Similarity score (0.0-1.0)
        """
        try:
            import base64
            import numpy as np
            from PIL import Image, ImageStat
            import io
            from services.feature_manager import get_feature_manager

            feature_manager = get_feature_manager()
            cv2_available = feature_manager.is_enabled("real_icons_enabled")

            # Capture current screenshot
            current_screenshot = await self.adb_bridge.capture_screenshot(device_id)

            # Decode expected screenshot
            expected_bytes = base64.b64decode(expected_screenshot_b64)
            expected_image = Image.open(io.BytesIO(expected_bytes))

            # Resize if dimensions don't match
            if current_screenshot.size != expected_image.size:
                expected_image = expected_image.resize(current_screenshot.size)

            if cv2_available:
                try:
                    import cv2

                    # Convert to OpenCV format (BGR)
                    current_np = cv2.cvtColor(
                        np.array(current_screenshot), cv2.COLOR_RGB2BGR
                    )
                    expected_np = cv2.cvtColor(
                        np.array(expected_image), cv2.COLOR_RGB2BGR
                    )

                    # Calculate histograms
                    current_hist = cv2.calcHist(
                        [current_np],
                        [0, 1, 2],
                        None,
                        [8, 8, 8],
                        [0, 256, 0, 256, 0, 256],
                    )
                    expected_hist = cv2.calcHist(
                        [expected_np],
                        [0, 1, 2],
                        None,
                        [8, 8, 8],
                        [0, 256, 0, 256, 0, 256],
                    )

                    # Normalize histograms
                    cv2.normalize(current_hist, current_hist)
                    cv2.normalize(expected_hist, expected_hist)

                    # Compare histograms using correlation method
                    similarity_score = cv2.compareHist(
                        current_hist, expected_hist, cv2.HISTCMP_CORREL
                    )

                    # Correlation returns -1 to 1, normalize to 0 to 1
                    normalized_score = (similarity_score + 1) / 2.0
                    return float(normalized_score)
                except Exception as e:
                    logger.warning(
                        f"  [StateValidation] OpenCV comparison failed, falling back to PIL: {e}"
                    )

            # PIL Fallback: Mean squared error of histograms
            # This is simpler but effective for basic "is it the same screen" checks
            h1 = current_screenshot.histogram()
            h2 = expected_image.histogram()

            # Root mean square error
            from math import sqrt

            rms = sqrt(sum((a - b) ** 2 for a, b in zip(h1, h2)) / len(h1))

            # Normalize to 0-1 (heuristic: 0 is identical, >30 is very different)
            # This is a rough approximation
            normalized_score = max(0.0, 1.0 - (rms / 1000.0))
            return float(normalized_score)

        except Exception as e:
            logger.error(f"  [StateValidation] Screenshot comparison failed: {e}")
            return 0.0

    async def _recover_from_state_mismatch(
        self, device_id: str, step: FlowStep
    ) -> bool:
        """
        Attempt to recover from state mismatch using smart navigation

        Recovery strategy (in order):
        1. Smart Navigation - Try to navigate from current screen using learned graph
        2. Restart + Navigate - Restart app and navigate from home screen
        3. Fallback - Use simple restart (goes to home only)

        Recovery actions:
        - force_restart_app: Try smart nav first, then restart and navigate
        - skip_step: Skip this step (return success)
        - fail: Fail immediately

        Args:
            device_id: Device ID
            step: Step with recovery action

        Returns:
            True if recovery succeeded, False otherwise
        """
        logger.info(f"  [StateValidation] Attempting recovery: {step.recovery_action}")

        try:
            if step.recovery_action == "force_restart_app":
                # Get package name from step context
                package = (
                    step.package
                    or step.screen_package
                    or getattr(step, "_package_context", None)
                )

                if not package:
                    logger.error(
                        "  [StateValidation] Cannot recover: no package name available"
                    )
                    return False

                # Phase 9: Smart Navigation Recovery
                # Strategy 1: Try to navigate from current screen if we know the target
                if step.expected_screen_id and step.navigation_required:
                    logger.info(
                        f"  [StateValidation] Trying smart navigation to {step.expected_screen_id[:8]}..."
                    )
                    nav_success = await self._navigate_to_screen(
                        device_id, step.expected_screen_id, package
                    )
                    if nav_success:
                        logger.info("  [StateValidation] Smart navigation succeeded")
                        return True
                    logger.warning(
                        "  [StateValidation] Smart navigation failed, trying restart + navigate"
                    )

                # Strategy 2: Restart app and navigate from home
                logger.debug(f"  [StateValidation] Force stopping {package}")
                await self.adb_bridge.stop_app(device_id, package)
                await asyncio.sleep(1)

                logger.debug(f"  [StateValidation] Relaunching {package}")
                await self.adb_bridge.launch_app(device_id, package)
                await asyncio.sleep(3)  # Wait for app to load

                # If we have a target screen, try to navigate from home
                if step.expected_screen_id:
                    graph = self.navigation_manager.get_graph(package)
                    if (
                        graph
                        and graph.home_screen_id
                        and graph.home_screen_id != step.expected_screen_id
                    ):
                        logger.info(
                            f"  [StateValidation] Navigating from home to target screen"
                        )
                        path = self.navigation_manager.find_path(
                            package, graph.home_screen_id, step.expected_screen_id
                        )
                        if path:
                            for transition in path.transitions:
                                success = await self._execute_transition_action(
                                    device_id, transition
                                )
                                if not success:
                                    logger.warning(
                                        "  [StateValidation] Navigation from home failed"
                                    )
                                    # Continue anyway - maybe close enough
                                    break
                                await asyncio.sleep(0.5)
                            logger.info(
                                "  [StateValidation] Navigation from home completed"
                            )

                return True

            elif step.recovery_action == "skip_step":
                logger.warning(
                    f"  [StateValidation] Skipping step due to state mismatch"
                )
                return True  # Treat as success (skip step)

            elif step.recovery_action == "fail":
                logger.error(f"  [StateValidation] Failing due to state mismatch")
                return False

            else:
                logger.warning(
                    f"  [StateValidation] Unknown recovery action: {step.recovery_action}"
                )
                return False

        except Exception as e:
            logger.error(f"  [StateValidation] Recovery failed: {e}", exc_info=True)
            return False

    # ============================================================================
    # Navigation Learning Integration (Phase 9)
    # ============================================================================

    async def _navigate_to_screen(
        self, device_id: str, target_screen_id: str, package: str
    ) -> bool:
        """
        Navigate from current screen to target screen using learned navigation graph

        Strategy:
        1. Identify current screen
        2. Find path in navigation graph
        3. Execute each transition action
        4. Verify we reached target screen
        5. If failed, restart app and try from home

        Args:
            device_id: Device ID
            target_screen_id: Target screen ID to navigate to
            package: App package name

        Returns:
            True if navigation succeeded
        """
        logger.info(f"[Navigation] Navigating to screen {target_screen_id[:8]}...")

        try:
            # Step 1: Identify current screen
            current_activity = await self.adb_bridge.get_current_activity(
                device_id, as_dict=True
            )
            if not current_activity:
                logger.warning("[Navigation] Could not get current activity")
                return False

            # Get UI elements for screen identification
            ui_elements = await self._get_screen_elements(device_id)
            landmarks = extract_ui_landmarks(ui_elements)
            current_screen_id = compute_screen_id(
                current_activity.get("activity", ""), landmarks
            )

            # Already on target screen?
            if current_screen_id == target_screen_id:
                logger.info("[Navigation] Already on target screen")
                return True

            # Step 2: Find path in navigation graph
            path = self.navigation_manager.find_path(
                package, current_screen_id, target_screen_id
            )

            if not path:
                logger.warning(
                    f"[Navigation] No path found from {current_screen_id[:8]}... to {target_screen_id[:8]}..."
                )
                # Try from home screen as fallback
                return await self._navigate_via_home(
                    device_id, target_screen_id, package
                )

            logger.info(f"[Navigation] Found path with {path.hop_count} steps")

            # Step 3: Execute each transition
            for i, transition in enumerate(path.transitions):
                logger.debug(
                    f"[Navigation] Executing transition {i+1}/{path.hop_count}"
                )

                success = await self._execute_transition_action(device_id, transition)
                if not success:
                    logger.warning(f"[Navigation] Transition {i+1} failed")
                    return False

                # Wait for screen transition
                await asyncio.sleep(0.5)

                # Update transition statistics
                self.navigation_manager.update_transition_stats(
                    package, transition.transition_id, success=True, time_ms=500
                )

            # Step 4: Verify we reached target
            final_activity = await self.adb_bridge.get_current_activity(
                device_id, as_dict=True
            )
            final_elements = await self._get_screen_elements(device_id)
            final_landmarks = extract_ui_landmarks(final_elements)
            final_screen_id = compute_screen_id(
                final_activity.get("activity", ""), final_landmarks
            )

            if final_screen_id == target_screen_id:
                logger.info("[Navigation] Successfully navigated to target screen")
                return True
            else:
                logger.warning(
                    f"[Navigation] Ended on wrong screen: {final_screen_id[:8]}... instead of {target_screen_id[:8]}..."
                )
                return False

        except Exception as e:
            logger.error(f"[Navigation] Navigation failed: {e}", exc_info=True)
            return False

    async def _navigate_via_home(
        self, device_id: str, target_screen_id: str, package: str
    ) -> bool:
        """
        Navigate to target by first going to home screen

        Args:
            device_id: Device ID
            target_screen_id: Target screen ID
            package: App package name

        Returns:
            True if navigation succeeded
        """
        logger.info("[Navigation] Attempting navigation via home screen...")

        graph = self.navigation_manager.get_graph(package)
        if not graph or not graph.home_screen_id:
            logger.warning("[Navigation] No home screen known for this app")
            return False

        # Restart app to get to home screen
        logger.debug(f"[Navigation] Restarting {package} to reach home screen")
        await self.adb_bridge.stop_app(device_id, package)
        await asyncio.sleep(1)
        await self.adb_bridge.launch_app(device_id, package)
        await asyncio.sleep(3)

        # Now try to navigate from home
        home_screen_id = graph.home_screen_id
        if home_screen_id == target_screen_id:
            logger.info("[Navigation] Target is home screen, already there")
            return True

        path = self.navigation_manager.find_path(
            package, home_screen_id, target_screen_id
        )
        if not path:
            logger.warning("[Navigation] No path found from home to target")
            return False

        # Execute path from home
        for transition in path.transitions:
            success = await self._execute_transition_action(device_id, transition)
            if not success:
                return False
            await asyncio.sleep(0.5)

        return True

    async def _execute_transition_action(self, device_id: str, transition) -> bool:
        """
        Execute a single transition action

        Args:
            device_id: Device ID
            transition: ScreenTransition with action details

        Returns:
            True if action executed successfully
        """
        action = transition.action

        try:
            if action.action_type == "tap":
                await self.adb_bridge.tap(device_id, action.x, action.y)

            elif action.action_type == "swipe":
                await self.adb_bridge.swipe(
                    device_id,
                    action.start_x,
                    action.start_y,
                    action.end_x,
                    action.end_y,
                    duration=300,
                )

            elif action.action_type == "go_back":
                await self.adb_bridge.keyevent(device_id, 4)  # KEYCODE_BACK

            elif action.action_type == "go_home":
                await self.adb_bridge.keyevent(device_id, 3)  # KEYCODE_HOME

            elif action.action_type == "keyevent" and action.keycode:
                await self.adb_bridge.keyevent(device_id, action.keycode)

            else:
                logger.warning(
                    f"[Navigation] Unknown action type: {action.action_type}"
                )
                return False

            return True

        except Exception as e:
            logger.error(f"[Navigation] Action execution failed: {e}")
            return False

    async def _get_screen_elements(self, device_id: str) -> list:
        """
        Get UI elements from current screen for identification

        Args:
            device_id: Device ID

        Returns:
            List of UI element dicts
        """
        try:
            result = await self.adb_bridge.get_ui_elements(device_id, bounds_only=False)
            if isinstance(result, dict):
                return result.get("elements", [])
            elif isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.warning(f"[Navigation] Failed to get screen elements: {e}")
            return []

    # ============================================================================
    # Known Starting Point - Ensures Consistent Flow Execution
    # ============================================================================

    def _get_target_package(self, flow: SensorCollectionFlow) -> Optional[str]:
        """
        Get the target package for a flow.
        Looks for LAUNCH_APP steps or screen_package in first step.

        Args:
            flow: Flow to analyze

        Returns:
            Package name or None
        """
        # Strategy 1: Find first LAUNCH_APP step
        for step in flow.steps:
            if step.step_type == FlowStepType.LAUNCH_APP and step.package:
                return step.package

        # Strategy 2: Check first step's screen_package
        if flow.steps and flow.steps[0].screen_package:
            return flow.steps[0].screen_package

        # Strategy 3: Check first step's package field
        if flow.steps and flow.steps[0].package:
            return flow.steps[0].package

        return None

    def _get_first_expected_activity(self, flow: SensorCollectionFlow) -> Optional[str]:
        """
        Get the expected activity for the first screen-dependent step.

        This finds the first step that requires being on a specific screen
        (e.g., capture_sensors, tap, swipe with screen_activity set).

        Args:
            flow: Flow to analyze

        Returns:
            Activity name or None
        """
        screen_dependent_types = {
            FlowStepType.CAPTURE_SENSORS,
            FlowStepType.TAP,
            FlowStepType.SWIPE,
            FlowStepType.TEXT,
            FlowStepType.VALIDATE_SCREEN,
        }

        for step in flow.steps:
            # Skip launch/wait steps - they don't require specific screens
            if step.step_type in {FlowStepType.LAUNCH_APP, FlowStepType.WAIT}:
                continue

            # Check if step has expected screen
            if step.step_type in screen_dependent_types:
                activity = step.screen_activity or step.expected_activity
                if activity:
                    logger.debug(f"[FlowExecutor] First expected activity: {activity}")
                    return activity

        return None

    async def _ensure_known_starting_point(
        self, device_id: str, package_name: str, expected_first_activity: str = None
    ) -> bool:
        """
        Ensure a known starting point for consistent flow execution.

        This method:
        1. Goes to home screen (clean slate)
        2. Waits briefly for home to settle
        3. Launches the target app fresh
        4. Waits for app to load
        5. If expected_first_activity is specified, navigates to it if needed

        This ensures every flow execution starts from the same state,
        preventing issues caused by the app being in an unexpected screen.

        Args:
            device_id: Device ID
            package_name: Package name to launch
            expected_first_activity: Optional specific activity the first step expects

        Returns:
            True if initialization succeeded
        """
        try:
            # Step 1: Go to home screen for clean slate
            logger.debug(f"  [Init] Going to home screen...")
            await self.adb_bridge.keyevent(device_id, "KEYCODE_HOME")
            await asyncio.sleep(0.8)  # Wait for home screen to settle

            # Step 2: Force stop to avoid resuming stale state
            try:
                await self.adb_bridge.stop_app(device_id, package_name)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.debug(f"  [Init] Could not force-stop {package_name}: {e}")

            # Step 3: Launch the app fresh
            logger.debug(f"  [Init] Launching {package_name}...")
            success = await self.adb_bridge.launch_app(device_id, package_name)

            if not success:
                logger.error(f"  [Init] Failed to launch {package_name}")
                return False

            await asyncio.sleep(2.5)  # Wait for app to fully load

            # Step 4: Verify we're in the right app
            current_activity = await self.adb_bridge.get_current_activity(device_id)
            current_package = (
                current_activity.split("/")[0]
                if current_activity and "/" in current_activity
                else current_activity
            )

            if current_package != package_name:
                logger.warning(
                    f"  [Init] Expected {package_name} but got {current_package}"
                )
                return False

            logger.info(
                f"  [Init] Successfully launched {package_name} (activity: {current_activity})"
            )

            # Step 5: If specific activity expected, check and navigate if needed
            if expected_first_activity:
                expected_name = (
                    expected_first_activity.split("/")[-1]
                    if "/" in expected_first_activity
                    else expected_first_activity
                )
                current_name = (
                    current_activity.split("/")[-1]
                    if "/" in current_activity
                    else current_activity
                )

                if not self._activity_matches(
                    current_activity, expected_first_activity
                ):
                    logger.warning(
                        f"  [Init] On {current_name}, need {expected_name} - attempting navigation"
                    )

                    navigation_success = await self._navigate_to_expected_screen(
                        device_id,
                        package_name,
                        current_activity,
                        expected_first_activity,
                    )

                    if navigation_success:
                        logger.info(
                            f"  [Init] Successfully navigated to {expected_name}"
                        )
                    else:
                        logger.warning(
                            f"  [Init] Could not navigate to {expected_name}, flow may fail"
                        )

            return True

        except Exception as e:
            logger.error(f"  [Init] Failed to ensure starting point: {e}")
            return False

    async def _reset_app_state(self, device_id: str, package_name: str) -> bool:
        """
        Reset app state without launching the app.
        Used before a launch_app step to ensure a clean start.
        """
        try:
            logger.debug("  [Init] Going to home screen...")
            await self.adb_bridge.keyevent(device_id, "KEYCODE_HOME")
            await asyncio.sleep(0.8)

            try:
                await self.adb_bridge.stop_app(device_id, package_name)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.debug(f"  [Init] Could not force-stop {package_name}: {e}")

            return True
        except Exception as e:
            logger.warning(f"  [Init] Failed to reset app state: {e}")
            return False

    async def _navigate_to_expected_screen(
        self,
        device_id: str,
        package_name: str,
        current_activity: str,
        expected_activity: str,
    ) -> bool:
        """
        Navigate from current screen to expected screen using multiple fallback strategies.

        Strategies (in order):
        1. Navigation graph path (if UI dump works)
        2. Activity-based path lookup (match by activity name)
        3. Common patterns (bottom nav, back button)
        4. Force restart with specific activity intent

        Args:
            device_id: Device ID
            package_name: App package name
            current_activity: Current activity (full or short name)
            expected_activity: Expected activity (full or short name)

        Returns:
            True if navigation succeeded
        """
        expected_name = (
            expected_activity.split("/")[-1]
            if "/" in expected_activity
            else expected_activity
        )
        current_name = (
            current_activity.split("/")[-1]
            if "/" in current_activity
            else current_activity
        )

        # Strategy 1: Navigation graph with UI-based screen ID
        logger.debug(f"  [Nav] Strategy 1: Navigation graph lookup")
        try:
            graph = self.navigation_manager.get_graph(package_name)
            if graph:
                # Find target and source screens by activity name
                target_screen_id = None
                source_screen_id = None

                for sid, screen in graph.screens.items():
                    if screen.activity:
                        if expected_name in screen.activity:
                            target_screen_id = sid
                        if current_name in screen.activity:
                            source_screen_id = sid

                if target_screen_id and source_screen_id:
                    # Direct path lookup by known screen IDs
                    path = self.navigation_manager.find_path(
                        package_name, source_screen_id, target_screen_id
                    )
                    if path and path.transitions:
                        logger.info(
                            f"  [Nav] Found path with {len(path.transitions)} steps"
                        )
                        for transition in path.transitions:
                            await self._execute_transition_action(device_id, transition)
                            await asyncio.sleep(0.8)

                        # Verify we reached the target
                        new_activity = await self.adb_bridge.get_current_activity(
                            device_id
                        )
                        if self._activity_matches(new_activity, expected_activity):
                            return True
                        logger.debug(
                            f"  [Nav] Strategy 1 incomplete: on {new_activity}"
                        )
        except Exception as e:
            logger.debug(f"  [Nav] Strategy 1 failed: {e}")

        # Strategy 2: Check if target is the home screen - try Home key or back navigation
        logger.debug(f"  [Nav] Strategy 2: Home/Back navigation")
        try:
            graph = self.navigation_manager.get_graph(package_name)
            is_target_home = False
            if graph and graph.home_screen_id:
                home_screen = graph.screens.get(graph.home_screen_id)
                if (
                    home_screen
                    and home_screen.activity
                    and expected_name in home_screen.activity
                ):
                    is_target_home = True

            if is_target_home:
                # Try pressing Back repeatedly to return to home (max 3 times)
                logger.info(f"  [Nav] Target is home screen, trying Back navigation")
                for i in range(3):
                    await self.adb_bridge.keyevent(device_id, "KEYCODE_BACK")
                    await asyncio.sleep(0.8)

                    new_activity = await self.adb_bridge.get_current_activity(device_id)
                    if self._activity_matches(new_activity, expected_activity):
                        return True

                    # Check if we're still in the same app
                    new_pkg = (
                        new_activity.split("/")[0]
                        if new_activity and "/" in new_activity
                        else new_activity
                    )
                    if new_pkg != package_name:
                        # Exited app, relaunch
                        await self.adb_bridge.launch_app(device_id, package_name)
                        await asyncio.sleep(1.5)
                        new_activity = await self.adb_bridge.get_current_activity(
                            device_id
                        )
                        if self._activity_matches(new_activity, expected_activity):
                            return True
                        break
        except Exception as e:
            logger.debug(f"  [Nav] Strategy 2 failed: {e}")

        # Strategy 3: Try common bottom navigation pattern (first tab = home)
        logger.debug(f"  [Nav] Strategy 3: Bottom navigation tap")
        try:
            # Get screen dimensions
            screen_info = await self.adb_bridge.get_screen_info(device_id)
            if screen_info:
                width = screen_info.get("width", 1080)
                height = screen_info.get("height", 2400)

                # Tap first bottom nav item (typically Home)
                # Bottom nav is usually in last 10% of screen height, first item at ~10% width
                tap_x = int(width * 0.1)
                tap_y = int(height * 0.95)

                logger.info(f"  [Nav] Tapping bottom nav at ({tap_x}, {tap_y})")
                await self.adb_bridge.tap(device_id, tap_x, tap_y)
                await asyncio.sleep(1.0)

                new_activity = await self.adb_bridge.get_current_activity(device_id)
                if self._activity_matches(new_activity, expected_activity):
                    return True
        except Exception as e:
            logger.debug(f"  [Nav] Strategy 3 failed: {e}")

        # Strategy 4: Force restart with specific activity intent
        logger.debug(f"  [Nav] Strategy 4: Launch specific activity")
        try:
            # Build activity intent command
            full_activity = expected_activity
            if "/" not in full_activity:
                full_activity = f"{package_name}/{expected_activity}"

            # Try starting specific activity
            result = await self.adb_bridge.execute_command(
                device_id, f"am start -n {full_activity}"
            )

            await asyncio.sleep(1.5)

            new_activity = await self.adb_bridge.get_current_activity(device_id)
            if self._activity_matches(new_activity, expected_activity):
                return True
        except Exception as e:
            logger.debug(f"  [Nav] Strategy 4 failed: {e}")

        # All strategies failed
        logger.warning(f"  [Nav] All navigation strategies failed")
        return False

    # ============================================================================
    # Utility Methods
    # ============================================================================

    async def execute_flow_on_demand(
        self, flow_id: str, device_id: str
    ) -> FlowExecutionResult:
        """
        Execute a flow on-demand (outside scheduler)

        Args:
            flow_id: Flow ID to execute
            device_id: Device ID

        Returns:
            FlowExecutionResult
        """
        flow = self.flow_manager.get_flow(device_id, flow_id)
        if not flow:
            raise ValueError(f"Flow {flow_id} not found")

        # Execute without scheduler lock (caller must ensure no conflicts)
        return await self.execute_flow(flow)

    def _get_sensor_name(self, device_id: str, sensor_id: str) -> str:
        """Get friendly name for a sensor ID"""
        try:
            sensor = self.sensor_manager.get_sensor(device_id, sensor_id)
            if sensor:
                return sensor.friendly_name
        except Exception:
            pass
        # Fallback to sensor ID
        return sensor_id

    def get_supported_step_types(self) -> list:
        """Get list of supported step types"""
        return list(self.step_handlers.keys())

    # ============================================================================
    # Phase 9: Advanced Flow Control (Loops, Variables)
    # ============================================================================

    async def _execute_loop(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Execute a loop step - repeat nested steps N times

        Supports:
        - Fixed iterations: iterations=5
        - Loop variable: loop_variable="i" sets ${i} to current iteration (0-indexed)
        - Break/continue via special return values
        """
        iterations = step.iterations or 1
        loop_steps = step.loop_steps or []

        if not loop_steps:
            logger.warning("  Loop step has no nested steps")
            return True

        logger.debug(
            f"  Executing loop: {iterations} iterations, {len(loop_steps)} steps each"
        )

        for i in range(iterations):
            # Set loop variable if specified
            if step.loop_variable:
                self._variable_context[step.loop_variable] = i
                logger.debug(
                    f"    Loop iteration {i + 1}/{iterations} (${step.loop_variable}={i})"
                )
            else:
                logger.debug(f"    Loop iteration {i + 1}/{iterations}")

            # Execute nested steps
            for nested_step in loop_steps:
                try:
                    success = await self._execute_single_step(
                        device_id, nested_step, result
                    )

                    # Check for break/continue signals
                    if nested_step.step_type == FlowStepType.BREAK_LOOP:
                        logger.debug(f"    Breaking out of loop at iteration {i + 1}")
                        return True

                    if nested_step.step_type == FlowStepType.CONTINUE_LOOP:
                        logger.debug(f"    Continuing to next iteration from {i + 1}")
                        break  # Break inner loop, continue outer

                    if not success:
                        if step.retry_on_failure:
                            logger.warning(f"    Loop step failed at iteration {i + 1}")
                            return False
                        # Otherwise continue to next step

                except LoopBreakException:
                    logger.debug(f"    Breaking out of loop at iteration {i + 1}")
                    return True
                except LoopContinueException:
                    logger.debug(f"    Continuing to next iteration from {i + 1}")
                    break

        logger.debug(f"  Loop completed all {iterations} iterations")
        return True

    async def _execute_set_variable(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """
        Set a variable in the execution context

        Supports:
        - Static value: variable_value="hello"
        - Variable reference: variable_value="${other_var}"
        - Captured sensor value: variable_value="${sensor:my_sensor}"
        - Last extracted text: variable_value="${last_extracted}"
        """
        if not step.variable_name:
            logger.warning("  set_variable step missing variable_name")
            return False

        value = step.variable_value or ""

        # Substitute variable references in the value
        resolved_value = self._substitute_variables(value, result)

        self._variable_context[step.variable_name] = resolved_value
        logger.debug(f"  Set variable: ${step.variable_name} = {resolved_value}")

        return True

    async def _execute_increment(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Increment a numeric variable by specified amount"""
        if not step.variable_name:
            logger.warning("  increment step missing variable_name")
            return False

        current = self._variable_context.get(step.variable_name, 0)
        increment_by = step.increment_by or 1

        try:
            new_value = float(current) + increment_by
            # Keep as int if possible
            if new_value == int(new_value):
                new_value = int(new_value)
            self._variable_context[step.variable_name] = new_value
            logger.debug(f"  Incremented: ${step.variable_name} = {new_value}")
            return True
        except (ValueError, TypeError):
            logger.error(
                f"  Cannot increment non-numeric variable: ${step.variable_name}"
            )
            return False

    async def _execute_break_loop(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Break out of current loop - handled by _execute_loop"""
        logger.debug("  Break loop signal")
        raise LoopBreakException()

    async def _execute_continue_loop(
        self, device_id: str, step: FlowStep, result: FlowExecutionResult
    ) -> bool:
        """Continue to next loop iteration - handled by _execute_loop"""
        logger.debug("  Continue loop signal")
        raise LoopContinueException()

    def _substitute_variables(self, text: str, result: FlowExecutionResult) -> str:
        """
        Substitute variable references in text

        Patterns:
        - ${var_name} - Get variable from context
        - ${sensor:sensor_id} - Get captured sensor value
        - ${last_extracted} - Last extracted text value
        """
        import re

        if not text or "${" not in text:
            return text

        def replace_var(match):
            var_ref = match.group(1)

            # Sensor reference
            if var_ref.startswith("sensor:"):
                sensor_id = var_ref[7:]
                return str(result.captured_sensors.get(sensor_id, ""))

            # Last extracted
            if var_ref == "last_extracted":
                return str(self._variable_context.get("_last_extracted", ""))

            # Regular variable
            return str(self._variable_context.get(var_ref, ""))

        return re.sub(r"\$\{([^}]+)\}", replace_var, text)

    def clear_variable_context(self):
        """Clear all variables (called at start of each flow)"""
        self._variable_context.clear()

    def get_variable(self, name: str) -> Any:
        """Get a variable value"""
        return self._variable_context.get(name)

    def set_variable(self, name: str, value: Any):
        """Set a variable value"""
        self._variable_context[name] = value


# Custom exceptions for loop control flow
class LoopBreakException(Exception):
    """Signal to break out of current loop"""

    pass


class LoopContinueException(Exception):
    """Signal to continue to next loop iteration"""

    pass
