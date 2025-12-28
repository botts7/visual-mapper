"""
Visual Mapper - Flow Executor (Phase 8)
Unified execution engine for sensor collection flows
"""

import logging
import asyncio
import time
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
from PIL import Image
import io

from flow_models import (
    SensorCollectionFlow,
    FlowStep,
    FlowExecutionResult,
    FlowStepType
)
from utils.element_finder import SmartElementFinder, ElementMatch
from utils.device_security import DeviceSecurityManager, LockStrategy
from flow_execution_history import FlowExecutionHistory, FlowExecutionLog, FlowStepLog

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
        execution_history=None
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
        self.security_manager = DeviceSecurityManager()

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
            # Screen power control (headless mode)
            FlowStepType.WAKE_SCREEN: self._execute_wake_screen,
            FlowStepType.SLEEP_SCREEN: self._execute_sleep_screen,
            FlowStepType.ENSURE_SCREEN_ON: self._execute_ensure_screen_on,
        }

        # Note: execute_action will be added when action system is integrated

        logger.info("[FlowExecutor] Initialized")

    async def execute_flow(
        self,
        flow: SensorCollectionFlow,
        device_lock: Optional[asyncio.Lock] = None
    ) -> FlowExecutionResult:
        """
        Execute complete flow

        Args:
            flow: Flow to execute
            device_lock: Optional device lock (from scheduler)

        Returns:
            FlowExecutionResult with success/failure details

        Process:
        1. Execute each step sequentially
        2. Retry failed steps if retry_on_failure=True
        3. Stop on error if stop_on_error=True
        4. Capture sensors at designated steps
        5. Publish to MQTT in real-time
        6. Update flow metrics
        """
        start_time = time.time()
        result = FlowExecutionResult(
            flow_id=flow.flow_id,
            success=False,
            executed_steps=0,
            captured_sensors={},
            execution_time_ms=0
        )

        # Create execution log for history tracking
        execution_log = FlowExecutionLog(
            execution_id=str(uuid.uuid4()),
            flow_id=flow.flow_id,
            device_id=flow.device_id,
            started_at=datetime.now().isoformat(),
            triggered_by="scheduler",  # TODO: Pass this as parameter when called from API/manual
            total_steps=len(flow.steps),
            steps=[]
        )

        logger.info(f"[FlowExecutor] Starting flow {flow.flow_id} ({flow.name})")

        try:
            # Auto-wake screen if headless mode enabled
            if flow.auto_wake_before:
                logger.info(f"  [Headless] Auto-waking screen before flow")
                wake_success = await self.adb_bridge.ensure_screen_on(
                    flow.device_id,
                    timeout_ms=flow.wake_timeout_ms
                )
                if not wake_success:
                    if flow.verify_screen_on:
                        result.error_message = "Failed to wake screen for headless execution"
                        logger.error(f"  [Headless] {result.error_message}")
                        result.execution_time_ms = int((time.time() - start_time) * 1000)
                        return result
                    else:
                        logger.warning(f"  [Headless] Screen wake failed, continuing anyway (verify_screen_on=False)")

            # Auto-unlock if device has auto_unlock strategy configured
            security_config = self.security_manager.get_lock_config(flow.device_id)
            if security_config and security_config.get('strategy') == LockStrategy.AUTO_UNLOCK.value:
                logger.info(f"  [Security] Auto-unlock enabled for device")
                passcode = self.security_manager.get_passcode(flow.device_id)
                if passcode:
                    try:
                        unlock_success = await self.adb_bridge.unlock_device(flow.device_id, passcode)
                        if unlock_success:
                            logger.info(f"  [Security] Device unlocked successfully")
                        else:
                            logger.warning(f"  [Security] Device unlock failed (check passcode)")
                    except Exception as e:
                        logger.error(f"  [Security] Error during unlock: {e}")
                else:
                    logger.warning(f"  [Security] Auto-unlock configured but no passcode found")
            elif security_config and security_config.get('strategy') == LockStrategy.MANUAL_ONLY.value:
                logger.info(f"  [Security] Manual unlock strategy - user must unlock device manually")

            # Wait briefly for lock screen to stabilize after wake
            # (screen wakes first, then lock screen appears ~500ms later)
            await asyncio.sleep(0.5)

            # CRITICAL: Verify device is actually unlocked before executing flow
            is_locked = await self.adb_bridge.is_locked(flow.device_id)
            if is_locked:
                result.error_message = "Device is locked - cannot execute flow. Configure auto-unlock in device security settings."
                logger.error(f"  [Security] {result.error_message}")
                result.execution_time_ms = int((time.time() - start_time) * 1000)

                # Log failed execution to history
                execution_log.completed_at = datetime.now().isoformat()
                execution_log.duration_ms = result.execution_time_ms
                execution_log.success = False
                execution_log.error = result.error_message
                execution_log.executed_steps = 0
                try:
                    self.execution_history.add_execution(execution_log)
                except Exception as e:
                    logger.error(f"[FlowExecutor] Failed to save execution history: {e}")

                return result

            # Execute steps sequentially
            for i, step in enumerate(flow.steps):
                # Timeout check
                elapsed = time.time() - start_time
                if elapsed > flow.flow_timeout:
                    result.error_message = f"Flow timeout after {elapsed:.1f}s (limit: {flow.flow_timeout}s)"
                    result.failed_step = i
                    logger.warning(f"  {result.error_message}")
                    break

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
                    success=False
                )

                # Execute step with retry
                try:
                    success = await self._execute_step_with_retry(
                        flow.device_id,
                        step,
                        result
                    )

                    step_log.success = success
                    if not success:
                        step_log.error = f"Step failed: {step.step_type}"
                        result.failed_step = i
                        logger.warning(f"  Step {i+1} failed: {step.step_type}")

                        if flow.stop_on_error:
                            logger.info(f"  Stopping flow (stop_on_error=True)")
                            # Complete step log
                            step_log.completed_at = datetime.now().isoformat()
                            step_log.duration_ms = int((time.time() - step_start) * 1000)
                            execution_log.steps.append(step_log)
                            break

                    result.executed_steps += 1

                except Exception as step_error:
                    step_log.success = False
                    step_log.error = str(step_error)
                    logger.error(f"  Step {i+1} error: {step_error}")

                finally:
                    # Complete step log
                    step_log.completed_at = datetime.now().isoformat()
                    step_log.duration_ms = int((time.time() - step_start) * 1000)
                    execution_log.steps.append(step_log)

            # Mark success if all steps executed
            result.success = (result.executed_steps == len(flow.steps))

            # Update flow metadata
            flow.last_executed = datetime.now()
            flow.execution_count += 1

            if result.success:
                flow.success_count += 1
                flow.last_success = True
                flow.last_error = None
                logger.info(f"[FlowExecutor] Flow {flow.flow_id} completed successfully")
            else:
                flow.failure_count += 1
                flow.last_success = False
                flow.last_error = result.error_message
                logger.error(f"[FlowExecutor] Flow {flow.flow_id} failed: {result.error_message}")

            # Save updated flow state
            self.flow_manager.update_flow(flow)

        except Exception as e:
            result.success = False
            result.error_message = f"Flow execution error: {str(e)}"
            logger.error(f"[FlowExecutor] Flow {flow.flow_id} error: {e}", exc_info=True)

        finally:
            # Auto-sleep screen ONLY if flow was successful (don't sleep if failed - user might be using it!)
            if flow.auto_sleep_after and result.success:
                try:
                    logger.info(f"  [Headless] Auto-sleeping screen after successful flow")
                    await self.adb_bridge.sleep_screen(flow.device_id)
                except Exception as sleep_error:
                    logger.warning(f"  [Headless] Failed to sleep screen: {sleep_error}")

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

        logger.info(f"[FlowExecutor] Flow {flow.flow_id} finished in {result.execution_time_ms}ms")
        logger.info(f"  Steps executed: {result.executed_steps}/{len(flow.steps)}")
        logger.info(f"  Sensors captured: {len(result.captured_sensors)}")

        # Record execution metrics (if performance monitor enabled)
        if self.performance_monitor:
            try:
                await self.performance_monitor.record_execution(flow, result)
            except Exception as e:
                logger.error(f"[FlowExecutor] Failed to record metrics: {e}")

        return result

    async def _execute_step_with_retry(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
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
                if step.validate_state and step.expected_screenshot:
                    logger.debug(f"  Validating state before {step.step_type}")
                    state_valid = await self._validate_state_and_recover(device_id, step, result)
                    if not state_valid:
                        logger.warning(f"  State validation failed for {step.step_type}")
                        if attempt < max_attempts - 1:
                            logger.info(f"  Retrying step after state recovery (attempt {attempt+2}/{max_attempts})")
                            await asyncio.sleep(1)
                            continue
                        else:
                            result.error_message = "State validation failed after recovery attempts"
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
                    logger.info(f"  Retrying step {step.step_type} (attempt {attempt+2}/{max_attempts})")
                    await asyncio.sleep(1)  # Brief delay before retry

            except Exception as e:
                logger.error(f"  Step execution error: {e}", exc_info=True)
                if attempt == max_attempts - 1:
                    result.error_message = str(e)
                    return False
                else:
                    logger.info(f"  Retrying after error (attempt {attempt+2}/{max_attempts})")
                    await asyncio.sleep(1)

        return False

    # ============================================================================
    # Step Handlers
    # ============================================================================

    async def _extract_timestamp_text(
        self,
        device_id: str,
        timestamp_element: Dict[str, Any]
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
            if not elements_response or 'elements' not in elements_response:
                return None

            elements = elements_response['elements']

            # Find element by matching resource-id (most reliable) or bounds
            for el in elements:
                # Match by resource-id (most reliable)
                if timestamp_element.get('resource-id'):
                    if el.get('resource-id') == timestamp_element.get('resource-id'):
                        return el.get('text', '').strip()

                # Match by bounds (if resource-id not available)
                if timestamp_element.get('bounds'):
                    ts_bounds = timestamp_element['bounds']
                    el_bounds = el.get('bounds', {})

                    # Check if bounds match (with small tolerance of ±10px)
                    if (abs(el_bounds.get('x', 0) - ts_bounds.get('x', 0)) < 10 and
                        abs(el_bounds.get('y', 0) - ts_bounds.get('y', 0)) < 10):
                        return el.get('text', '').strip()

            return None

        except Exception as e:
            logger.error(f"  Failed to extract timestamp text: {e}")
            return None

    async def _execute_launch_app(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Launch app step"""
        if not step.package:
            logger.error("  launch_app step missing package name")
            return False

        logger.debug(f"  Launching app: {step.package}")
        success = await self.adb_bridge.launch_app(device_id, step.package)

        if not success:
            logger.warning(f"  Failed to launch app: {step.package}")

        return success

    async def _execute_wait(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Wait/delay step"""
        if not step.duration:
            logger.error("  wait step missing duration")
            return False

        duration_seconds = step.duration / 1000.0
        logger.debug(f"  Waiting {duration_seconds:.1f}s")
        await asyncio.sleep(duration_seconds)
        return True

    async def _execute_tap(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Tap step"""
        if step.x is None or step.y is None:
            logger.error("  tap step missing x/y coordinates")
            return False

        logger.debug(f"  Tapping at ({step.x}, {step.y})")
        await self.adb_bridge.tap(device_id, step.x, step.y)
        return True

    async def _execute_swipe(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Swipe step"""
        if None in (step.start_x, step.start_y, step.end_x, step.end_y):
            logger.error("  swipe step missing coordinates")
            return False

        duration = step.duration or 300  # Default 300ms
        logger.debug(f"  Swiping from ({step.start_x}, {step.start_y}) to ({step.end_x}, {step.end_y})")

        await self.adb_bridge.swipe(
            device_id,
            step.start_x, step.start_y,
            step.end_x, step.end_y,
            duration
        )
        return True

    async def _execute_text(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Text input step"""
        if not step.text:
            logger.error("  text step missing text content")
            return False

        logger.debug(f"  Typing text: {step.text[:50]}...")
        await self.adb_bridge.type_text(device_id, step.text)
        return True

    async def _execute_keyevent(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Keyevent step"""
        if not step.keycode:
            logger.error("  keyevent step missing keycode")
            return False

        logger.debug(f"  Sending keyevent: {step.keycode}")
        await self.adb_bridge.keyevent(device_id, step.keycode)
        return True

    async def _execute_pull_refresh(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
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
            initial_timestamp = await self._extract_timestamp_text(device_id, step.timestamp_element)
            logger.debug(f"  Initial timestamp: {initial_timestamp}")

            # Attempt refresh with retries
            max_retries = step.refresh_max_retries or 3
            retry_delay = (step.refresh_retry_delay or 2000) / 1000.0  # Convert to seconds

            for attempt in range(max_retries):
                logger.debug(f"  Refresh attempt {attempt + 1}/{max_retries}")

                # Execute pull-to-refresh gesture
                await self.adb_bridge.swipe(device_id, start_x, start_y, end_x, end_y, duration)

                # Wait for refresh to complete
                await asyncio.sleep(retry_delay)

                # Extract new timestamp
                new_timestamp = await self._extract_timestamp_text(device_id, step.timestamp_element)
                logger.debug(f"  New timestamp: {new_timestamp}")

                # Check if timestamp changed
                if new_timestamp and new_timestamp != initial_timestamp:
                    logger.info(f"  ✓ Timestamp changed after {attempt + 1} attempt(s)")
                    return True

                # Log retry if timestamp unchanged
                if attempt < max_retries - 1:
                    logger.warning(f"  Timestamp unchanged, retrying refresh ({attempt + 2}/{max_retries})")

            # Max retries reached
            logger.warning(f"  Timestamp still unchanged after {max_retries} attempts (soft failure)")
            return True  # Continue flow anyway (soft failure)

        else:
            # No timestamp validation - execute once
            await self.adb_bridge.swipe(device_id, start_x, start_y, end_x, end_y, duration)

            # Wait a moment for refresh to complete
            await asyncio.sleep(0.8)
            return True

    async def _execute_restart_app(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
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
            initial_timestamp = await self._extract_timestamp_text(device_id, step.timestamp_element)
            logger.debug(f"  Initial timestamp: {initial_timestamp}")

            # Attempt restart with retries
            max_retries = step.refresh_max_retries or 3
            retry_delay = (step.refresh_retry_delay or 2000) / 1000.0  # Convert to seconds

            for attempt in range(max_retries):
                logger.debug(f"  Restart attempt {attempt + 1}/{max_retries}")

                try:
                    # Execute stop and launch in a single batch (50-70% faster)
                    commands = [
                        f"am force-stop {step.package}",  # Force stop the app
                        "sleep 0.5",  # Wait for stop to complete
                        f"monkey -p {step.package} -c android.intent.category.LAUNCHER 1",  # Relaunch
                    ]

                    results = await self.adb_bridge.execute_batch_commands(device_id, commands)

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
                    logger.error(f"  Batch restart failed, falling back to sequential: {e}")

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
                new_timestamp = await self._extract_timestamp_text(device_id, step.timestamp_element)
                logger.debug(f"  New timestamp: {new_timestamp}")

                # Check if timestamp changed
                if new_timestamp and new_timestamp != initial_timestamp:
                    logger.info(f"  ✓ Timestamp changed after {attempt + 1} attempt(s)")
                    return True

                # Log retry if timestamp unchanged
                if attempt < max_retries - 1:
                    logger.warning(f"  Timestamp unchanged, retrying restart ({attempt + 2}/{max_retries})")

            # Max retries reached
            logger.warning(f"  Timestamp still unchanged after {max_retries} attempts (soft failure)")
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

                results = await self.adb_bridge.execute_batch_commands(device_id, commands)

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
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
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

        logger.debug(f"  Capturing {len(step.sensor_ids)} sensors")

        try:
            # 1. Capture screenshot
            screenshot_bytes = await self.adb_bridge.capture_screenshot(device_id)
            if not screenshot_bytes:
                logger.error("  Failed to capture screenshot")
                return False

            # Convert to PIL Image for text extraction
            screenshot_image = Image.open(io.BytesIO(screenshot_bytes))

            # 2. Get UI elements with FULL info for smart element detection
            # (not bounds_only - we need resource_id, text, class for smart matching)
            ui_elements = await self.adb_bridge.get_ui_elements(device_id, bounds_only=False)

            # 3. Extract each sensor and collect for batch publishing
            sensor_updates = []  # List of (sensor, value) tuples for batch publishing
            for sensor_id in step.sensor_ids:
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
                            'x': sensor.source.custom_bounds.x,
                            'y': sensor.source.custom_bounds.y,
                            'width': sensor.source.custom_bounds.width,
                            'height': sensor.source.custom_bounds.height
                        }

                    match = self.element_finder.find_element(
                        ui_elements=ui_elements,
                        resource_id=sensor.source.element_resource_id,
                        element_text=sensor.source.element_text,
                        element_class=sensor.source.element_class,
                        stored_bounds=stored_bounds
                    )

                    if not match.found:
                        logger.warning(f"  Could not locate element for {sensor.friendly_name}: {match.message}")
                        continue

                    # Log detection method for debugging
                    if match.method != "stored_bounds":
                        logger.info(f"  Smart detection for {sensor.friendly_name}: {match.method} (confidence: {match.confidence:.0%})")

                    # Use found bounds for extraction
                    extraction_bounds = match.bounds

                    # Extract value using text extractor with dynamically found bounds
                    value = await self.text_extractor.extract_from_image(
                        screenshot_image,
                        extraction_bounds,
                        sensor.extraction_rule
                    )

                    # Store in result
                    result.captured_sensors[sensor_id] = value

                    logger.debug(f"  Captured {sensor.friendly_name}: {value}")

                    # Collect for batch publishing (20-30% faster than individual)
                    sensor_updates.append((sensor, value))

                    # Optionally update stored bounds if element moved significantly
                    if match.method != "stored_bounds" and stored_bounds and match.bounds:
                        is_similar, distance = self.element_finder.compare_bounds(stored_bounds, match.bounds)
                        if not is_similar and distance > 10:  # Moved more than 10px
                            logger.info(f"  Element moved {distance:.0f}px - consider updating sensor bounds")

                except Exception as e:
                    logger.error(f"  Failed to extract sensor {sensor_id}: {e}")
                    # Continue with other sensors (don't fail entire step)

            # 4. Batch publish all sensor states at once (20-30% faster)
            if sensor_updates:
                batch_result = await self.mqtt_manager.publish_state_batch(sensor_updates)
                logger.debug(f"  Batch published {batch_result['success']}/{len(sensor_updates)} sensors to MQTT")

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
                        logger.info(f"  Found sensor {sensor_id} on device {device_id} (current: {current_device_id})")
                        return sensor
            return None
        except Exception as e:
            logger.debug(f"  Error finding sensor by stable ID: {e}")
            return None

    async def _execute_validate_screen(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
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
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Go to home screen"""
        logger.debug("  Going to home screen")
        await self.adb_bridge.keyevent(device_id, "KEYCODE_HOME")
        return True

    async def _execute_go_back(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Press back button"""
        logger.debug("  Pressing back button")
        await self.adb_bridge.keyevent(device_id, "KEYCODE_BACK")
        return True

    # ========== Screen Power Control (Headless Mode) ==========

    async def _execute_wake_screen(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Wake the device screen"""
        logger.debug("  [Headless] Waking screen")
        return await self.adb_bridge.wake_screen(device_id)

    async def _execute_sleep_screen(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Put the device screen to sleep"""
        logger.debug("  [Headless] Sleeping screen")
        # Optional delay before sleep
        if step.duration:
            await asyncio.sleep(step.duration / 1000.0)
        return await self.adb_bridge.sleep_screen(device_id)

    async def _execute_ensure_screen_on(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Ensure screen is on before proceeding"""
        timeout = step.duration or 3000  # Use duration field for timeout, default 3000ms
        logger.debug(f"  [Headless] Ensuring screen is on (timeout: {timeout}ms)")
        success = await self.adb_bridge.ensure_screen_on(device_id, timeout_ms=timeout)
        if not success:
            result.error_message = f"Screen failed to wake after {timeout}ms"
            logger.warning(f"  [Headless] {result.error_message}")
        return success

    async def _execute_stitch_capture(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Capture and stitch multiple screenshots (for scrollable content)"""
        logger.debug("  Executing stitch capture")
        try:
            if self.screenshot_stitcher:
                # Use the screenshot stitcher for multi-screenshot capture
                stitched_result = await self.screenshot_stitcher.capture_stitched(
                    device_id,
                    max_scrolls=step.max_scrolls if hasattr(step, 'max_scrolls') else 5
                )
                if stitched_result:
                    result.captured_screenshots.append({
                        'type': 'stitched',
                        'step_index': result.steps_completed,
                        'data': stitched_result
                    })
                    return True
            else:
                logger.warning("  Screenshot stitcher not available")
                return False
        except Exception as e:
            logger.error(f"  Stitch capture failed: {e}")
            return False

    async def _execute_conditional(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """
        Conditional step (if/else branching)

        Note: This is a placeholder for future implementation.
        Full conditional logic requires expression evaluation.
        """
        logger.warning("  Conditional steps not yet implemented")
        return False

    # ============================================================================
    # State Validation Methods (Phase 8 - Hybrid XML + Activity + Screenshot)
    # ============================================================================

    async def _validate_state_and_recover(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
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
        logger.warning(f"  [StateValidation] State mismatch detected (score: {match_score:.2f}, threshold: {step.state_match_threshold:.2f})")

        # Attempt recovery
        recovery_success = await self._recover_from_state_mismatch(device_id, step)

        if recovery_success:
            # Re-validate after recovery
            state_valid, match_score = await self._validate_state_hybrid(device_id, step)
            if state_valid:
                logger.info(f"  [StateValidation] State recovered successfully (score: {match_score:.2f})")
                return True
            else:
                logger.error(f"  [StateValidation] State recovery failed (score: {match_score:.2f})")
                return False
        else:
            logger.error(f"  [StateValidation] Recovery action failed")
            return False

    async def _validate_state_hybrid(
        self,
        device_id: str,
        step: FlowStep
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

                logger.debug(f"  [StateValidation] UI Elements: {matched_count}/{len(step.expected_ui_elements)} matched (score: {ui_match_score:.2f})")

                # If UI element match is strong, we can skip other checks
                if matched_count >= step.ui_elements_required:
                    return (True, ui_match_score)

            except Exception as e:
                logger.debug(f"  [StateValidation] UI element check failed: {e}")

        # Strategy 2: Activity Name (Fast and accurate)
        if step.expected_activity:
            try:
                current_activity = await self.adb_bridge.get_current_activity(device_id)
                activity_match = (current_activity == step.expected_activity)
                activity_score = 1.0 if activity_match else 0.0
                confidence_scores.append(activity_score)

                logger.debug(f"  [StateValidation] Activity: {current_activity} vs {step.expected_activity} (match: {activity_match})")

                if activity_match:
                    return (True, activity_score)

            except Exception as e:
                logger.debug(f"  [StateValidation] Activity check failed: {e}")

        # Strategy 3: Screenshot Similarity (Fallback)
        if step.expected_screenshot:
            try:
                screenshot_match_score = await self._compare_screenshots(device_id, step.expected_screenshot)
                confidence_scores.append(screenshot_match_score)

                logger.debug(f"  [StateValidation] Screenshot similarity: {screenshot_match_score:.2f}")

            except Exception as e:
                logger.debug(f"  [StateValidation] Screenshot check failed: {e}")

        # Calculate overall confidence
        if len(confidence_scores) == 0:
            logger.warning(f"  [StateValidation] No validation criteria available")
            return (True, 1.0)  # No criteria = assume valid

        avg_score = sum(confidence_scores) / len(confidence_scores)
        is_valid = avg_score >= step.state_match_threshold

        return (is_valid, avg_score)

    async def _compare_screenshots(
        self,
        device_id: str,
        expected_screenshot_b64: str
    ) -> float:
        """
        Compare current screenshot with expected screenshot using histogram comparison

        Args:
            device_id: Device ID
            expected_screenshot_b64: Base64 encoded expected screenshot

        Returns:
            Similarity score (0.0-1.0)
        """
        try:
            import base64
            import numpy as np
            import cv2

            # Capture current screenshot
            current_screenshot = await self.adb_bridge.screenshot(device_id)

            # Decode expected screenshot
            expected_bytes = base64.b64decode(expected_screenshot_b64)
            expected_image = Image.open(io.BytesIO(expected_bytes))

            # Resize if dimensions don't match
            if current_screenshot.size != expected_image.size:
                expected_image = expected_image.resize(current_screenshot.size)

            # Convert to OpenCV format (BGR)
            current_np = cv2.cvtColor(np.array(current_screenshot), cv2.COLOR_RGB2BGR)
            expected_np = cv2.cvtColor(np.array(expected_image), cv2.COLOR_RGB2BGR)

            # Calculate histograms
            current_hist = cv2.calcHist([current_np], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
            expected_hist = cv2.calcHist([expected_np], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])

            # Normalize histograms
            cv2.normalize(current_hist, current_hist)
            cv2.normalize(expected_hist, expected_hist)

            # Compare histograms using correlation method
            similarity_score = cv2.compareHist(current_hist, expected_hist, cv2.HISTCMP_CORREL)

            # Correlation returns -1 to 1, normalize to 0 to 1
            normalized_score = (similarity_score + 1) / 2.0

            return float(normalized_score)

        except Exception as e:
            logger.error(f"  [StateValidation] Screenshot comparison failed: {e}")
            return 0.0

    async def _recover_from_state_mismatch(
        self,
        device_id: str,
        step: FlowStep
    ) -> bool:
        """
        Attempt to recover from state mismatch

        Recovery actions:
        - force_restart_app: Kill and relaunch app
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
                # Get package name from step or from launch_app step
                package = step.package or getattr(step, '_package_context', None)

                if not package:
                    logger.error("  [StateValidation] Cannot force restart: no package name available")
                    return False

                # Force stop app
                logger.debug(f"  [StateValidation] Force stopping {package}")
                await self.adb_bridge.shell(device_id, f"am force-stop {package}")
                await asyncio.sleep(1)

                # Relaunch app
                logger.debug(f"  [StateValidation] Relaunching {package}")
                await self.adb_bridge.launch_app(device_id, package)
                await asyncio.sleep(3)  # Wait for app to load

                return True

            elif step.recovery_action == "skip_step":
                logger.warning(f"  [StateValidation] Skipping step due to state mismatch")
                return True  # Treat as success (skip step)

            elif step.recovery_action == "fail":
                logger.error(f"  [StateValidation] Failing due to state mismatch")
                return False

            else:
                logger.warning(f"  [StateValidation] Unknown recovery action: {step.recovery_action}")
                return False

        except Exception as e:
            logger.error(f"  [StateValidation] Recovery failed: {e}", exc_info=True)
            return False

    # ============================================================================
    # Utility Methods
    # ============================================================================

    async def execute_flow_on_demand(
        self,
        flow_id: str,
        device_id: str
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

    def get_supported_step_types(self) -> list:
        """Get list of supported step types"""
        return list(self.step_handlers.keys())
