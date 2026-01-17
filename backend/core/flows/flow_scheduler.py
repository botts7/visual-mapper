"""
Visual Mapper - Flow Scheduler (Phase 8)
Priority queue system with device-level locking for flow execution
"""

import logging
import asyncio
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

from .flow_models import SensorCollectionFlow
from services.device_identity import get_device_identity_resolver

logger = logging.getLogger(__name__)


class ExecutionRouter:
    """
    Routes flow execution to appropriate executor based on execution_method field

    Execution Methods:
    - "server": Execute via ADB on server (default, traditional method)
    - "android": Execute via MQTT command to Android companion app
    - "auto": Smart routing - try preferred_executor first, fallback if fails
    """

    def __init__(self, flow_executor, mqtt_manager=None):
        """
        Initialize execution router

        Args:
            flow_executor: FlowExecutor for server-side ADB execution
            mqtt_manager: MQTTManager for Android app communication (optional)
        """
        self.flow_executor = flow_executor
        self.mqtt_manager = mqtt_manager

        # Track Android execution results for fallback logic
        self._pending_android_executions: Dict[str, asyncio.Future] = {}
        self._android_timeout_seconds = 30  # Timeout for Android execution

        # Track execution history for reporting
        self._execution_history: Dict[str, List[Dict]] = (
            {}
        )  # device_id -> list of results
        self._max_history_per_device = 50

        # Track device capabilities from companion app
        self._device_capabilities: Dict[str, Dict] = (
            {}
        )  # device_id -> capabilities dict

        logger.info("[ExecutionRouter] Initialized")

    def set_mqtt_manager(self, mqtt_manager):
        """Set MQTT manager for Android execution and register result callback"""
        self.mqtt_manager = mqtt_manager

        # Register callbacks
        if mqtt_manager:
            mqtt_manager.set_flow_result_callback(self._handle_android_flow_result)
            mqtt_manager.set_companion_status_callback(self._handle_device_status)
            logger.info(
                "[ExecutionRouter] Registered flow result and status callbacks with MQTT manager"
            )

        logger.info("[ExecutionRouter] MQTT manager configured")

    def _handle_device_status(self, device_id: str, status_data: dict):
        """
        Handle device status update from Android companion app

        Caches capabilities for smart routing decisions.

        Args:
            device_id: Android device ID
            status_data: Status data including capabilities
        """
        logger.info(
            f"[ExecutionRouter] Received device status: {device_id} - capabilities={status_data.get('capabilities', [])}"
        )

        self._device_capabilities[device_id] = {
            "device_id": device_id,
            "platform": status_data.get("platform", "android"),
            "app_version": status_data.get("app_version", "unknown"),
            "accessibility_enabled": status_data.get("accessibility_enabled", False),
            "capabilities": status_data.get("capabilities", []),
            "timestamp": status_data.get("timestamp"),
            "last_updated": datetime.now().isoformat(),
        }

    def get_device_capabilities(self, device_id: str) -> Dict:
        """
        Get cached capabilities for a device

        Args:
            device_id: Device ID

        Returns:
            Capabilities dict or empty dict if not known
        """
        return self._device_capabilities.get(device_id, {})

    def is_android_capable(
        self, device_id: str, required_capabilities: List[str] = None
    ) -> bool:
        """
        Check if device has Android companion app with required capabilities

        Args:
            device_id: Device ID
            required_capabilities: List of required capability strings (e.g., ["flow_execution", "gestures"])

        Returns:
            True if device has companion app with all required capabilities
        """
        caps = self._device_capabilities.get(device_id, {})

        # No status received = no companion app
        if not caps:
            return False

        # Accessibility service must be running for most operations
        if not caps.get("accessibility_enabled", False):
            return False

        # Check specific capabilities if required
        if required_capabilities:
            device_caps = caps.get("capabilities", [])
            for req in required_capabilities:
                if req not in device_caps:
                    return False

        return True

    def _handle_android_flow_result(
        self, device_id: str, flow_id: str, result_data: dict
    ):
        """
        Handle flow execution result from Android companion app via MQTT

        Args:
            device_id: Android device ID
            flow_id: Flow ID that was executed
            result_data: Result data from Android app
        """
        logger.info(
            f"[ExecutionRouter] Received Android flow result: {device_id}/{flow_id} - success={result_data.get('success')}"
        )

        # Store in execution history
        if device_id not in self._execution_history:
            self._execution_history[device_id] = []

        history_entry = {
            "flow_id": flow_id,
            "device_id": device_id,
            "success": result_data.get("success", False),
            "error": result_data.get("error"),
            "duration_ms": result_data.get("duration", 0),
            "timestamp": result_data.get("timestamp", datetime.now().isoformat()),
            "executor": "android",
        }
        self._execution_history[device_id].append(history_entry)

        # Trim history to max size
        if len(self._execution_history[device_id]) > self._max_history_per_device:
            self._execution_history[device_id] = self._execution_history[device_id][
                -self._max_history_per_device :
            ]

        # Resolve pending future if waiting for this result
        execution_key = f"{device_id}/{flow_id}"
        if execution_key in self._pending_android_executions:
            future = self._pending_android_executions.pop(execution_key)
            if not future.done():
                future.set_result(result_data)
                logger.debug(
                    f"[ExecutionRouter] Resolved pending execution: {execution_key}"
                )

    def get_execution_history(self, device_id: str, limit: int = 20) -> List[Dict]:
        """
        Get recent execution history for a device

        Args:
            device_id: Device ID
            limit: Maximum number of entries to return

        Returns:
            List of execution history entries (most recent first)
        """
        history = self._execution_history.get(device_id, [])
        return list(reversed(history[-limit:]))

    async def execute_flow(
        self, flow: SensorCollectionFlow, device_lock: asyncio.Lock = None
    ) -> "ExecutionResult":
        """
        Execute flow using appropriate method based on execution_method field

        Args:
            flow: Flow to execute
            device_lock: Optional lock for ADB operations

        Returns:
            ExecutionResult with success status and data
        """
        execution_method = getattr(flow, "execution_method", "server")

        logger.info(
            f"[ExecutionRouter] Routing flow {flow.flow_id} via {execution_method}"
        )

        if execution_method == "server":
            return await self._execute_on_server(flow, device_lock)
        elif execution_method == "android":
            return await self._execute_on_android(flow)
        elif execution_method == "auto":
            return await self._execute_auto(flow, device_lock)
        else:
            logger.warning(
                f"[ExecutionRouter] Unknown execution_method '{execution_method}', defaulting to server"
            )
            return await self._execute_on_server(flow, device_lock)

    async def _execute_on_server(
        self, flow: SensorCollectionFlow, device_lock: asyncio.Lock = None
    ):
        """Execute flow via server ADB"""
        logger.debug(f"[ExecutionRouter] Executing flow {flow.flow_id} on server (ADB)")
        return await self.flow_executor.execute_flow(flow, device_lock=device_lock)

    async def _execute_on_android(self, flow: SensorCollectionFlow):
        """Execute flow via MQTT command to Android companion app"""
        if not self.mqtt_manager:
            logger.error(
                "[ExecutionRouter] MQTT manager not configured for Android execution"
            )
            return ExecutionResult(success=False, error_message="MQTT not configured")

        if not self.mqtt_manager.is_connected():
            logger.error("[ExecutionRouter] MQTT not connected for Android execution")
            return ExecutionResult(success=False, error_message="MQTT not connected")

        logger.debug(
            f"[ExecutionRouter] Executing flow {flow.flow_id} on Android via MQTT"
        )

        try:
            # Create execution request
            payload = {
                "command": "execute_flow",
                "flow_id": flow.flow_id,
                "flow_name": flow.name,
                "sensors": [
                    {
                        "sensor_id": sensor.sensor_id,
                        "name": sensor.name,
                        "source_type": sensor.source.source_type,
                        "source_config": (
                            sensor.source.model_dump()
                            if hasattr(sensor.source, "model_dump")
                            else {}
                        ),
                    }
                    for sensor in flow.sensors
                ],
                "timestamp": datetime.now().isoformat(),
            }

            # Send MQTT command
            success = await self.mqtt_manager.publish_flow_command(
                device_id=flow.device_id, flow_id=flow.flow_id, payload=payload
            )

            if success:
                logger.info(
                    f"[ExecutionRouter] Sent flow execution command to Android: {flow.flow_id}"
                )
                # Note: Actual result comes back via MQTT callback - this just confirms command sent
                return ExecutionResult(success=True, execution_method="android")
            else:
                logger.error(
                    f"[ExecutionRouter] Failed to send flow command to Android: {flow.flow_id}"
                )
                return ExecutionResult(
                    success=False, error_message="Failed to publish MQTT command"
                )

        except Exception as e:
            logger.error(
                f"[ExecutionRouter] Android execution error: {e}", exc_info=True
            )
            return ExecutionResult(success=False, error_message=str(e))

    async def _execute_auto(
        self, flow: SensorCollectionFlow, device_lock: asyncio.Lock = None
    ):
        """
        Smart execution with fallback and capability awareness

        Process:
        1. Check if Android companion app is available with required capabilities
        2. If available and preferred=android, try Android first
        3. If not available or failed, use fallback
        4. Track which method was used for logging/metrics
        """
        preferred = getattr(flow, "preferred_executor", "android")
        fallback = getattr(flow, "fallback_executor", "server")

        # Check Android capability
        android_capable = self.is_android_capable(
            flow.device_id, required_capabilities=["flow_execution", "accessibility"]
        )

        logger.info(
            f"[ExecutionRouter] Auto mode: preferred={preferred}, fallback={fallback}, android_capable={android_capable}"
        )

        # Smart routing: if preferred is android but not capable, start with server
        actual_preferred = preferred
        if preferred == "android" and not android_capable:
            logger.info(
                f"[ExecutionRouter] Device not Android-capable, starting with server"
            )
            actual_preferred = "server"
        elif preferred == "server" and fallback == "android" and not android_capable:
            # If fallback is android but not capable, warn (will still try server first)
            logger.debug(
                f"[ExecutionRouter] Fallback android not available, will stick with server"
            )

        # Try preferred executor
        if actual_preferred == "android":
            result = await self._execute_on_android(flow)
            result.execution_method = "android"
        else:
            result = await self._execute_on_server(flow, device_lock)
            result.execution_method = "server"

        # If failed, try fallback
        if not result.success:
            actual_fallback = fallback

            # Don't try android fallback if not capable
            if fallback == "android" and not android_capable:
                logger.warning(
                    f"[ExecutionRouter] Fallback android requested but device not capable, skipping"
                )
                actual_fallback = None

            if actual_fallback and actual_fallback != actual_preferred:
                logger.warning(
                    f"[ExecutionRouter] Preferred executor '{actual_preferred}' failed, trying fallback '{actual_fallback}'"
                )

                if actual_fallback == "android":
                    result = await self._execute_on_android(flow)
                    result.execution_method = "android"
                elif actual_fallback == "server":
                    result = await self._execute_on_server(flow, device_lock)
                    result.execution_method = "server"

                if result.success:
                    result.used_fallback = True
                    logger.info(
                        f"[ExecutionRouter] Fallback executor '{actual_fallback}' succeeded"
                    )

        return result


@dataclass
class ExecutionResult:
    """Result of flow execution"""

    success: bool
    error_message: str = ""
    execution_method: str = "server"
    used_fallback: bool = False
    sensor_values: Dict = None

    def __post_init__(self):
        if self.sensor_values is None:
            self.sensor_values = {}


@dataclass
class QueuedFlow:
    """Represents a flow in the execution queue"""

    priority: int
    timestamp: float
    flow: SensorCollectionFlow
    reason: str

    def __lt__(self, other):
        """Compare for priority queue ordering (lower priority number = higher priority)"""
        if self.priority != other.priority:
            return self.priority < other.priority
        # If same priority, FIFO (earlier timestamp first)
        return self.timestamp < other.timestamp


class FlowScheduler:
    """
    Manages flow execution scheduling with priority queue and device locking

    Features:
    - Priority queue system (on-demand > periodic)
    - Device-level locking (prevent ADB conflicts)
    - Independent scheduling per device
    - Queue depth tracking for backlog detection
    - Periodic flow auto-scheduling

    Priority Levels:
    - 0-4: On-demand (user triggered, Home Assistant automation)
    - 5-9: High priority periodic (fast update intervals <30s)
    - 10-14: Normal priority periodic (standard intervals 30-300s)
    - 15-19: Low priority periodic (slow update intervals >300s)
    """

    def __init__(self, flow_executor, flow_manager, mqtt_manager=None):
        """
        Initialize flow scheduler

        Args:
            flow_executor: FlowExecutor instance for executing flows
            flow_manager: FlowManager instance for loading flows
            mqtt_manager: MQTTManager instance for Android execution (optional)
        """
        self.flow_executor = flow_executor
        self.flow_manager = flow_manager
        self.mqtt_manager = mqtt_manager

        # Create execution router for smart execution method routing
        self.execution_router = ExecutionRouter(flow_executor, mqtt_manager)

        # Device locks (prevent concurrent ADB operations)
        self._device_locks: Dict[str, asyncio.Lock] = {}

        # Priority queues per device
        self._queues: Dict[str, asyncio.PriorityQueue] = {}

        # Background scheduler tasks per device
        self._scheduler_tasks: Dict[str, asyncio.Task] = {}

        # Periodic update tasks per flow
        self._periodic_tasks: Dict[str, asyncio.Task] = {}

        # Metrics
        self._queue_depths: Dict[str, int] = {}
        self._last_execution: Dict[str, datetime] = {}
        self._total_executions: Dict[str, int] = {}

        # Track which flow_ids are currently queued per device (prevents duplicate queueing)
        self._queued_flow_ids: Dict[str, set] = {}

        # Unlock debounce tracking - prevents rapid unlock attempts
        self._last_unlock_attempt: Dict[str, float] = {}
        self._unlock_debounce_seconds: int = 5  # Reduced for faster retry

        # Scheduler state
        self._running = False
        self._paused = False  # Pause state for periodic scheduling

        # Activity log for UI visibility (circular buffer, max 100 entries)
        from collections import deque
        self._activity_log: deque = deque(maxlen=100)

        logger.info("[FlowScheduler] Initialized")

    def _log_activity(self, event_type: str, flow_id: str = None, device_id: str = None,
                      message: str = None, success: bool = None, details: dict = None):
        """Log scheduler activity for UI visibility"""
        from datetime import datetime
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,  # queued, executing, completed, failed, unlock_attempt, unlock_failed, skipped
            "flow_id": flow_id,
            "device_id": device_id,
            "message": message,
            "success": success,
            "details": details or {}
        }
        self._activity_log.append(entry)

    def get_activity_log(self, limit: int = 50) -> list:
        """Get recent scheduler activity for UI display"""
        return list(self._activity_log)[-limit:]

    def set_mqtt_manager(self, mqtt_manager):
        """
        Set MQTT manager for Android execution routing

        Allows setting MQTT manager after scheduler initialization,
        which is useful when scheduler is created before MQTT is connected.
        """
        self.mqtt_manager = mqtt_manager
        self.execution_router.set_mqtt_manager(mqtt_manager)
        logger.info("[FlowScheduler] MQTT manager configured for execution routing")

    def resolve_device_id(self, flow: SensorCollectionFlow) -> Optional[str]:
        """
        Resolve a flow's device_id to the currently connected device.

        Uses device_identity resolver to find the current connection_id,
        which may have changed if the device reconnected with a different port.

        Args:
            flow: Flow to resolve device for

        Returns:
            Current connection_id if device is connected, None if not found
        """
        try:
            resolver = get_device_identity_resolver()

            # Try to resolve using stable_device_id if available
            device_id_to_resolve = flow.stable_device_id or flow.device_id

            # Use centralized resolution
            current_conn = resolver.resolve_to_connection_id(device_id_to_resolve)

            if current_conn and current_conn != flow.device_id:
                logger.info(
                    f"[FlowScheduler] Resolved device {device_id_to_resolve}: "
                    f"{flow.device_id} -> {current_conn}"
                )
                return current_conn
            elif current_conn:
                return current_conn

            # Fall back to original device_id
            return flow.device_id

        except Exception as e:
            logger.warning(f"[FlowScheduler] Error resolving device ID: {e}")
            return flow.device_id

    async def start(self):
        """Start the scheduler"""
        if self._running:
            logger.warning("[FlowScheduler] Already running")
            return

        self._running = True
        logger.info("[FlowScheduler] Starting scheduler")

        # Start periodic scheduling for all enabled flows
        await self._start_periodic_scheduling()

        logger.info("[FlowScheduler] Scheduler started")

    async def stop(self):
        """Stop the scheduler"""
        if not self._running:
            return

        self._running = False
        logger.info("[FlowScheduler] Stopping scheduler")

        # Cancel all periodic tasks
        for flow_id, task in list(self._periodic_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._periodic_tasks.clear()

        # Cancel all scheduler tasks
        for device_id, task in list(self._scheduler_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._scheduler_tasks.clear()

        logger.info("[FlowScheduler] Scheduler stopped")

    async def schedule_flow(
        self, flow: SensorCollectionFlow, priority: int = 10, reason: str = "periodic"
    ):
        """
        Add flow to execution queue

        Args:
            flow: Flow to execute
            priority: Priority level (0=highest, 19=lowest)
            reason: Reason for scheduling (for logging)

        Priority Guidelines:
        - 0-4: On-demand (user triggered)
        - 5-9: High priority periodic
        - 10-14: Normal priority periodic (default)
        - 15-19: Low priority periodic
        """
        device_id = flow.device_id
        flow_id = flow.flow_id

        # Create queue and lock if needed
        if device_id not in self._queues:
            self._queues[device_id] = asyncio.PriorityQueue()
            self._device_locks[device_id] = asyncio.Lock()
            self._queue_depths[device_id] = 0
            self._total_executions[device_id] = 0
            self._queued_flow_ids[device_id] = set()

        # Initialize queued flow tracking if needed
        if device_id not in self._queued_flow_ids:
            self._queued_flow_ids[device_id] = set()

        # SMART QUEUE: Skip if flow already queued (unless on-demand)
        # On-demand (priority < 5) always allowed - user explicitly wants it
        if reason == "periodic" and flow_id in self._queued_flow_ids[device_id]:
            logger.info(
                f"[FlowScheduler] Skipping {flow_id} - already queued (queue_depth={self._queue_depths.get(device_id, 0)})"
            )
            self._log_activity("skipped", flow_id, device_id,
                               f"Already queued (depth={self._queue_depths.get(device_id, 0)})")
            return

        # Create queued flow item
        queued = QueuedFlow(
            priority=priority, timestamp=time.time(), flow=flow, reason=reason
        )

        # Track that this flow is now queued
        self._queued_flow_ids[device_id].add(flow_id)

        # Add to queue
        await self._queues[device_id].put(queued)

        # Update metrics
        self._queue_depths[device_id] = self._queues[device_id].qsize()

        logger.debug(
            f"[FlowScheduler] Queued flow {flow_id} (priority={priority}, reason={reason}, queue_depth={self._queue_depths[device_id]})"
        )
        self._log_activity("queued", flow_id, device_id,
                           f"Priority {priority}, reason: {reason}",
                           details={"queue_depth": self._queue_depths[device_id], "reason": reason})

        # Start scheduler task if not running
        if (
            device_id not in self._scheduler_tasks
            or self._scheduler_tasks[device_id].done()
        ):
            task = asyncio.create_task(self._run_device_scheduler(device_id))
            self._scheduler_tasks[device_id] = task
            logger.info(f"[FlowScheduler] Started scheduler task for {device_id}")

    async def schedule_flow_on_demand(self, flow: SensorCollectionFlow):
        """
        Schedule a flow for immediate execution (highest priority)

        Args:
            flow: Flow to execute
        """
        await self.schedule_flow(flow, priority=0, reason="on-demand")

    async def _run_device_scheduler(self, device_id: str):
        """
        Background task that processes queue for a device

        Process:
        1. Wait for flow in queue (blocks)
        2. Acquire device lock
        3. Execute flow via FlowExecutor
        4. Release lock
        5. Update metrics
        6. Repeat
        """
        queue = self._queues[device_id]
        lock = self._device_locks[device_id]

        logger.info(f"[FlowScheduler] Device scheduler started for {device_id}")

        while self._running:
            try:
                # 1. Wait for flow (blocks until available)
                queued = await queue.get()

                # Remove from queued tracking (flow is now being processed)
                flow_id = queued.flow.flow_id
                if device_id in self._queued_flow_ids:
                    self._queued_flow_ids[device_id].discard(flow_id)

                # 2. Check if flow still enabled
                if not queued.flow.enabled:
                    logger.info(
                        f"[FlowScheduler] Skipping disabled flow: {queued.flow.flow_id}"
                    )
                    queue.task_done()
                    continue

                # 2b. Check if wizard is active on this device - skip flow execution
                # NOTE: Device may have multiple IDs (USB serial vs WiFi IP) - check all
                try:
                    from main import wizard_active_devices

                    wizard_active = device_id in wizard_active_devices

                    # Also check alternative IDs (WiFi IP vs USB serial mismatch)
                    if not wizard_active:
                        try:
                            connected = (
                                await self.flow_executor.adb_bridge.get_connected_devices()
                            )
                            for dev in connected:
                                dev_id = dev.get("id", "")
                                wifi_ip = dev.get("wifi_ip", "")
                                if dev_id == device_id or wifi_ip == device_id:
                                    if (
                                        dev_id in wizard_active_devices
                                        or wifi_ip in wizard_active_devices
                                    ):
                                        wizard_active = True
                                        logger.info(
                                            f"[FlowScheduler] Device {device_id} matched wizard via {dev_id}/{wifi_ip}"
                                        )
                                        break
                        except Exception:
                            pass

                    if wizard_active:
                        logger.info(
                            f"[FlowScheduler] Skipping flow {queued.flow.flow_id} - wizard active on {device_id}"
                        )
                        queue.task_done()
                        continue
                except ImportError:
                    pass

                # 3. Resolve device ID (handle port changes when device reconnects)
                resolved_device_id = self.resolve_device_id(queued.flow)
                if resolved_device_id and resolved_device_id != device_id:
                    # Update flow's device_id in memory for this execution
                    queued.flow.device_id = resolved_device_id
                    logger.info(
                        f"[FlowScheduler] Updated flow {queued.flow.flow_id} device: {device_id} -> {resolved_device_id}"
                    )

                # 4. Acquire device lock (only needed for server/ADB execution)
                async with lock:
                    logger.info(
                        f"[FlowScheduler] Executing flow {queued.flow.flow_id} (priority={queued.priority}, reason={queued.reason}, method={getattr(queued.flow, 'execution_method', 'server')})"
                    )

                    try:
                        # Use resolved device_id for unlock check
                        exec_device_id = queued.flow.device_id

                        # ============================================
                        # AUTO-UNLOCK: Before flow execution
                        # ============================================
                        self._log_activity("executing", queued.flow.flow_id, exec_device_id,
                                           f"Starting execution ({queued.flow.name})")
                        unlocked = await self._auto_unlock_if_needed(exec_device_id)
                        if not unlocked:
                            # Re-queue instead of skipping - device may unlock soon
                            logger.warning(
                                f"[FlowScheduler] Flow {queued.flow.flow_id} deferred - device locked, re-queuing in 10s"
                            )
                            self._log_activity("deferred", queued.flow.flow_id, exec_device_id,
                                               "Device locked, re-queuing in 10s", success=False)
                            queue.task_done()

                            # Re-queue with slight delay (don't block the queue)
                            async def requeue_after_delay():
                                await asyncio.sleep(10)
                                # Only requeue if scheduler still running
                                if self._running and queued.flow.enabled:
                                    # Lower priority (higher number) for retries to let other flows go first
                                    retry_priority = min(queued.priority + 5, 20)
                                    await self.schedule_flow(
                                        queued.flow,
                                        priority=retry_priority,
                                        reason="retry_after_locked",
                                    )
                                    logger.info(
                                        f"[FlowScheduler] Re-queued flow {queued.flow.flow_id} after device lock"
                                    )

                            asyncio.create_task(requeue_after_delay())
                            continue

                        # 4. Execute flow via execution router (handles server/android/auto routing)
                        result = await self.execution_router.execute_flow(
                            queued.flow, device_lock=lock
                        )

                        # 5. Update metrics
                        self._last_execution[device_id] = datetime.now()
                        self._total_executions[device_id] = (
                            self._total_executions.get(device_id, 0) + 1
                        )

                        if result.success:
                            method = getattr(result, "execution_method", "server")
                            fallback = getattr(result, "used_fallback", False)
                            fallback_msg = " (fallback)" if fallback else ""
                            logger.debug(
                                f"[FlowScheduler] Flow {queued.flow.flow_id} completed successfully via {method}{fallback_msg}"
                            )
                            self._log_activity("completed", queued.flow.flow_id, device_id,
                                               f"Completed successfully via {method}{fallback_msg}",
                                               success=True,
                                               details={"steps": result.executed_steps, "method": method})

                            # ============================================
                            # AUTO-LOCK: After successful flow execution
                            # ============================================
                            if await self.should_lock_device(device_id):
                                try:
                                    await self.flow_executor.adb_bridge.sleep_screen(
                                        device_id
                                    )
                                    logger.info(
                                        f"[FlowScheduler] Locked device {device_id} (no flow scheduled soon)"
                                    )
                                except Exception as lock_error:
                                    logger.warning(
                                        f"[FlowScheduler] Failed to lock device: {lock_error}"
                                    )
                        else:
                            error_msg = result.error_message or "Unknown error"
                            self._log_activity("failed", queued.flow.flow_id, device_id,
                                               f"Failed: {error_msg[:100]}",
                                               success=False,
                                               details={"error": error_msg, "failed_step": result.failed_step})
                            logger.warning(
                                f"[FlowScheduler] Flow {queued.flow.flow_id} failed: {result.error_message}"
                            )
                            # Don't lock on failure - user may need to intervene

                    except Exception as e:
                        logger.error(
                            f"[FlowScheduler] Flow execution error: {e}", exc_info=True
                        )

                # 6. Update queue depth
                self._queue_depths[device_id] = queue.qsize()
                queue.task_done()

            except asyncio.CancelledError:
                logger.info(
                    f"[FlowScheduler] Device scheduler cancelled for {device_id}"
                )
                break
            except Exception as e:
                logger.error(
                    f"[FlowScheduler] Scheduler error for {device_id}: {e}",
                    exc_info=True,
                )
                await asyncio.sleep(1)  # Prevent tight loop on errors

        logger.info(f"[FlowScheduler] Device scheduler stopped for {device_id}")

    async def _start_periodic_scheduling(self):
        """
        Start periodic scheduling tasks for all enabled flows

        Creates a background task for each enabled flow that schedules it
        at the configured update_interval_seconds
        """
        # Get all devices
        devices = list(
            set(
                flow.device_id
                for flows in [
                    self.flow_manager.get_device_flows(d)
                    for d in self._get_all_device_ids()
                ]
                for flow in flows
            )
        )

        total_flows = 0

        for device_id in devices:
            flows = self.flow_manager.get_enabled_flows(device_id)

            for flow in flows:
                # Create periodic task for this flow
                task = asyncio.create_task(self._run_periodic_flow(flow))
                self._periodic_tasks[flow.flow_id] = task
                total_flows += 1

        logger.info(
            f"[FlowScheduler] Started periodic scheduling for {total_flows} flows across {len(devices)} devices"
        )

    async def _run_periodic_flow(self, flow: SensorCollectionFlow):
        """
        Background task that periodically schedules a flow

        Re-reads flow from disk each iteration to pick up enabled/disabled changes.

        Args:
            flow: Flow to schedule periodically (used for initial flow_id/device_id)
        """
        import time

        # Store IDs - we'll re-read flow from disk each iteration
        flow_id = flow.flow_id
        device_id = flow.device_id
        initial_interval = flow.update_interval_seconds

        logger.debug(
            f"[FlowScheduler] Starting periodic scheduling for {flow_id} (interval={initial_interval}s)"
        )

        while self._running:
            try:
                # RE-READ flow from disk to get current enabled state
                current_flow = self.flow_manager.get_flow(device_id, flow_id)

                # Check if flow still exists and is enabled
                if not current_flow:
                    logger.info(
                        f"[FlowScheduler] Flow {flow_id} no longer exists, stopping periodic task"
                    )
                    break

                if not current_flow.enabled:
                    logger.info(
                        f"[FlowScheduler] Flow {flow_id} is disabled, stopping periodic task"
                    )
                    break

                # Track execution start time to account for execution duration
                execution_start = time.time()

                # Calculate priority based on update interval
                # Faster intervals = higher priority
                interval = current_flow.update_interval_seconds
                if interval < 30:
                    priority = 5  # High priority
                elif interval < 300:
                    priority = 10  # Normal priority
                else:
                    priority = 15  # Low priority

                # Schedule flow (use current_flow, not stale reference)
                await self.schedule_flow(
                    current_flow, priority=priority, reason="periodic"
                )

                # Calculate sleep duration, accounting for execution time
                execution_duration = time.time() - execution_start
                sleep_duration = max(5, interval - execution_duration)

                logger.debug(
                    f"[FlowScheduler] Flow {flow_id} scheduled (took {execution_duration:.1f}s, sleeping {sleep_duration:.1f}s)"
                )

                # Wait for adjusted interval
                await asyncio.sleep(sleep_duration)

            except asyncio.CancelledError:
                logger.debug(
                    f"[FlowScheduler] Periodic scheduling cancelled for {flow_id}"
                )
                break
            except Exception as e:
                logger.error(
                    f"[FlowScheduler] Periodic scheduling error for {flow_id}: {e}",
                    exc_info=True,
                )
                await asyncio.sleep(initial_interval)  # Continue on error

    def _get_all_device_ids(self) -> List[str]:
        """
        Get list of all device IDs that have flows

        Uses get_all_flows() to properly scan storage directory
        instead of relying on potentially empty in-memory cache.
        """
        # Get all flows from storage (not just in-memory cache)
        all_flows = self.flow_manager.get_all_flows()

        # Extract unique device IDs
        device_ids = set(flow.device_id for flow in all_flows)

        logger.debug(f"[FlowScheduler] Found {len(device_ids)} devices with flows")
        return list(device_ids)

    async def reload_flows(self, device_id: str):
        """
        Reload flows for a device and restart periodic scheduling

        Args:
            device_id: Device to reload flows for
        """
        logger.info(f"[FlowScheduler] Reloading flows for {device_id}")

        # Cancel existing periodic tasks for this device
        flows = self.flow_manager.get_device_flows(device_id)
        for flow in flows:
            if flow.flow_id in self._periodic_tasks:
                self._periodic_tasks[flow.flow_id].cancel()
                try:
                    await self._periodic_tasks[flow.flow_id]
                except asyncio.CancelledError:
                    pass
                del self._periodic_tasks[flow.flow_id]

        # Only restart periodic scheduling if not paused
        if self._paused:
            logger.info(
                f"[FlowScheduler] Scheduler is paused - skipping periodic task creation for {device_id}"
            )
            return

        # Restart periodic scheduling for enabled flows
        enabled_flows = self.flow_manager.get_enabled_flows(device_id)
        for flow in enabled_flows:
            task = asyncio.create_task(self._run_periodic_flow(flow))
            self._periodic_tasks[flow.flow_id] = task

        logger.info(
            f"[FlowScheduler] Reloaded {len(enabled_flows)} flows for {device_id}"
        )

    def get_queue_depth(self, device_id: str) -> int:
        """Get current queue depth for a device"""
        return self._queue_depths.get(device_id, 0)

    def get_last_execution(self, device_id: str) -> Optional[datetime]:
        """Get timestamp of last execution for a device"""
        return self._last_execution.get(device_id)

    def get_metrics(self, device_id: str) -> Dict:
        """
        Get scheduler metrics for a device

        Returns:
            Dictionary with queue depth, last execution, total executions
        """
        return {
            "queue_depth": self.get_queue_depth(device_id),
            "last_execution": self.get_last_execution(device_id),
            "total_executions": self._total_executions.get(device_id, 0),
            "scheduler_running": device_id in self._scheduler_tasks
            and not self._scheduler_tasks[device_id].done(),
        }

    def get_all_metrics(self) -> Dict[str, Dict]:
        """Get scheduler metrics for all devices"""
        return {
            device_id: self.get_metrics(device_id) for device_id in self._queues.keys()
        }

    async def pause(self):
        """
        Pause periodic scheduling (stops adding new flows to queue)
        Note: Currently executing flows will complete
        """
        if self._paused:
            logger.warning("[FlowScheduler] Already paused")
            return

        self._paused = True
        logger.info("[FlowScheduler] Pausing periodic scheduling")

        # Cancel all periodic tasks
        for flow_id, task in list(self._periodic_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._periodic_tasks.clear()
        logger.info("[FlowScheduler] Periodic scheduling paused")

    async def resume(self):
        """
        Resume periodic scheduling

        Always restarts periodic scheduling if tasks are empty, even if not
        officially "paused". This handles edge cases where tasks were cancelled
        but _paused flag wasn't properly set (e.g., race conditions with wizard).
        """
        if not self._paused and len(self._periodic_tasks) > 0:
            logger.warning("[FlowScheduler] Not paused")
            return

        # Reset paused flag
        was_paused = self._paused
        self._paused = False

        if was_paused:
            logger.info("[FlowScheduler] Resuming periodic scheduling")
        else:
            logger.info(
                "[FlowScheduler] Force-resuming periodic scheduling (tasks were empty)"
            )

        # Restart periodic scheduling
        await self._start_periodic_scheduling()
        logger.info("[FlowScheduler] Periodic scheduling resumed")

    def get_status(self) -> Dict:
        """
        Get overall scheduler status

        Returns:
            Dictionary with scheduler state and per-device info
        """
        device_status = {}
        for device_id in self._queues.keys():
            device_status[device_id] = {
                "queue_depth": self.get_queue_depth(device_id),
                "scheduler_active": device_id in self._scheduler_tasks
                and not self._scheduler_tasks[device_id].done(),
                "last_execution": (
                    self.get_last_execution(device_id).isoformat()
                    if self.get_last_execution(device_id)
                    else None
                ),
                "total_executions": self._total_executions.get(device_id, 0),
            }

        return {
            "running": self._running,
            "paused": self._paused,
            "total_periodic_tasks": len(self._periodic_tasks),
            "devices": device_status,
        }

    def get_queued_flows(self, device_id: str) -> List[Dict]:
        """
        Get list of pending flows in queue for a device

        Note: This returns a snapshot of the queue contents.
        Due to asyncio.PriorityQueue implementation, we cannot peek without
        consuming, so we return basic info from available metrics.

        Args:
            device_id: Device ID to check

        Returns:
            List of queued flow info dictionaries
        """
        if device_id not in self._queues:
            return []

        queue_depth = self._queue_depths.get(device_id, 0)

        # Since PriorityQueue doesn't allow peeking, return summary info
        # For detailed queue contents, we'd need to track separately
        return [
            {
                "device_id": device_id,
                "queue_depth": queue_depth,
                "message": f"{queue_depth} flow(s) queued for execution",
            }
        ]

    async def cancel_queued_flows_for_device(self, device_id: str) -> int:
        """
        Cancel all pending flows for a device.

        Used when Flow Wizard opens to prevent queued flows from executing
        and locking the device during wizard operation.

        Args:
            device_id: Device ID to cancel flows for

        Returns:
            Number of flows cancelled
        """
        if device_id not in self._queues:
            logger.debug(f"[FlowScheduler] No queue for device {device_id}")
            return 0

        # Drain the existing queue (DON'T replace with new queue - that breaks
        # the scheduler task's reference to the queue object!)
        queue = self._queues[device_id]
        cancelled = 0
        while not queue.empty():
            try:
                queue.get_nowait()
                queue.task_done()  # Mark task as done to prevent blocking
                cancelled += 1
            except asyncio.QueueEmpty:
                break

        self._queue_depths[device_id] = 0

        # Clear queued flow tracking
        if device_id in self._queued_flow_ids:
            self._queued_flow_ids[device_id].clear()

        if cancelled > 0:
            logger.info(
                f"[FlowScheduler] Cancelled {cancelled} queued flows for {device_id} (wizard opened)"
            )
        else:
            logger.debug(f"[FlowScheduler] No queued flows to cancel for {device_id}")

        return cancelled

    def is_paused(self) -> bool:
        """Check if scheduler is paused"""
        return self._paused

    def is_running(self) -> bool:
        """Check if scheduler is running"""
        return self._running

    # ============================================================================
    # Smart Lock Management (AUTO_UNLOCK strategy)
    # ============================================================================

    async def _auto_unlock_if_needed(self, device_id: str) -> bool:
        """
        Ensure device is unlocked before flow execution.

        Scheduler-specific wrapper that adds debounce protection before
        delegating to FlowExecutor's unified unlock method.

        Returns True if device is ready (unlocked or successfully unlocked).
        Returns False if device is locked and couldn't be unlocked.
        """
        import time

        # Scheduler-specific debounce check - prevent rapid unlock attempts
        # when multiple flows are scheduled close together
        last_attempt = self._last_unlock_attempt.get(device_id, 0)
        time_since_last = time.time() - last_attempt
        if time_since_last < self._unlock_debounce_seconds:
            remaining = int(self._unlock_debounce_seconds - time_since_last)
            logger.warning(
                f"[FlowScheduler] Unlock debounce blocking {device_id} ({remaining}s remaining) - skipping unlock"
            )
            self._log_activity("unlock_debounced", None, device_id,
                               f"Debounce active ({remaining}s remaining)", success=False)
            return False

        # Record unlock attempt time for debounce
        self._last_unlock_attempt[device_id] = time.time()

        # Delegate to unified unlock method in FlowExecutor
        # (has retry logic, cooldown check, swipe + PIN support)
        # FlowExecutor returns dict with "success" key - extract it for bool return
        self._log_activity("unlock_attempt", None, device_id, "Attempting device unlock")
        result = await self.flow_executor.auto_unlock_if_needed(device_id)
        success = result.get("success", False)
        if success:
            self._log_activity("unlock_success", None, device_id, "Device unlocked", success=True)
        else:
            error_msg = result.get("error", "Unknown unlock error")
            self._log_activity("unlock_failed", None, device_id, error_msg, success=False,
                               details={"reason": result.get("reason", "unknown")})
        return success

    def get_time_until_next_flow(self, device_id: str) -> Optional[float]:
        """
        Calculate seconds until next flow execution for a device.

        Checks:
        1. Queue depth (if queue has pending flows, return 0)
        2. Periodic flow timings

        Returns:
            Seconds until next flow, or None if no enabled flows
        """
        # If queue has pending flows, next execution is imminent
        if self._queue_depths.get(device_id, 0) > 0:
            return 0.0

        # Get all enabled flows for this device
        flows = self.flow_manager.get_enabled_flows(device_id)
        if not flows:
            return None

        # Calculate time until next execution for each flow
        now = datetime.now()
        min_time = float("inf")

        for flow in flows:
            # Get last execution time
            last_exec = flow.last_executed
            if not last_exec:
                # Never executed - will run soon
                return 0.0

            # Calculate next execution time
            next_exec_time = last_exec.timestamp() + flow.update_interval_seconds
            time_until = next_exec_time - now.timestamp()

            if time_until < min_time:
                min_time = time_until

        return min_time if min_time != float("inf") else None

    async def should_lock_device(self, device_id: str) -> bool:
        """
        Check if device should be locked after flow execution.

        Returns True if ALL conditions met:
        - Device has AUTO_UNLOCK strategy configured (system manages lock/unlock)
        - No flow scheduled within grace period (from device config, default 5 min)
        - Wizard is not active on device
        - Streaming is not active on device

        Args:
            device_id: Device to check

        Returns:
            True if device should be locked
        """
        # Check if device has AUTO_UNLOCK configured
        # Only devices with AUTO_UNLOCK should be auto-locked by the system
        from utils.device_security import LockStrategy

        security_config = self.flow_executor.security_manager.get_lock_config(device_id)
        if not security_config:
            logger.debug(
                f"[FlowScheduler] No security config for {device_id} - skip lock"
            )
            return False

        if security_config.get("strategy") != LockStrategy.AUTO_UNLOCK.value:
            logger.debug(
                f"[FlowScheduler] Device {device_id} strategy is {security_config.get('strategy')} - skip lock"
            )
            return False

        # Get configurable grace period (default 300s = 5 min)
        grace_period_seconds = security_config.get("sleep_grace_period", 300)

        # Check if wizard is active (skip lock if user is working)
        # Use ADB to properly resolve USB vs WiFi device ID mismatches
        try:
            from main import wizard_active_devices

            # Debug log to help diagnose wizard active issues
            if wizard_active_devices:
                logger.debug(
                    f"[FlowScheduler] should_lock_device({device_id}): wizard_active_devices={wizard_active_devices}"
                )

            if device_id in wizard_active_devices:
                logger.debug(
                    f"[FlowScheduler] Skipping lock - wizard active on {device_id}"
                )
                return False

            # Check if any active wizard device matches this device (handle WiFi vs USB ID mismatch)
            if wizard_active_devices:
                try:
                    connected = (
                        await self.flow_executor.adb_bridge.get_connected_devices()
                    )
                    for dev in connected:
                        dev_id = dev.get("id", "")
                        wifi_ip = dev.get("wifi_ip", "")
                        # Check if this connected device matches our device_id
                        if dev_id == device_id or wifi_ip == device_id:
                            # Now check if either ID is in wizard_active
                            if (
                                dev_id in wizard_active_devices
                                or wifi_ip in wizard_active_devices
                            ):
                                logger.debug(
                                    f"[FlowScheduler] Skipping lock - wizard active (USB/WiFi match: {dev_id}/{wifi_ip})"
                                )
                                return False
                except Exception as e:
                    logger.debug(
                        f"[FlowScheduler] Error checking device IDs for wizard: {e}"
                    )
        except ImportError:
            pass

        # Check if streaming is active - don't lock during live view
        if self.flow_executor.adb_bridge.is_streaming(device_id):
            logger.info(
                f"[FlowScheduler] Skipping lock - streaming active on {device_id}"
            )
            return False

        # Check time until next flow
        time_until_next = self.get_time_until_next_flow(device_id)

        if time_until_next is None:
            # No enabled flows - lock the device
            logger.debug(
                f"[FlowScheduler] No enabled flows for {device_id} - will lock"
            )
            return True

        if time_until_next <= grace_period_seconds:
            # Flow coming soon - don't lock
            logger.debug(
                f"[FlowScheduler] Next flow in {time_until_next:.0f}s (< {grace_period_seconds}s grace) - skip lock"
            )
            return False

        # No flow soon - lock the device
        logger.debug(
            f"[FlowScheduler] Next flow in {time_until_next:.0f}s (> {grace_period_seconds}s grace) - will lock"
        )
        return True
