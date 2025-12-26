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

from flow_models import SensorCollectionFlow

logger = logging.getLogger(__name__)


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

    def __init__(self, flow_executor, flow_manager):
        """
        Initialize flow scheduler

        Args:
            flow_executor: FlowExecutor instance for executing flows
            flow_manager: FlowManager instance for loading flows
        """
        self.flow_executor = flow_executor
        self.flow_manager = flow_manager

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

        # Scheduler state
        self._running = False

        logger.info("[FlowScheduler] Initialized")

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
        self,
        flow: SensorCollectionFlow,
        priority: int = 10,
        reason: str = "periodic"
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

        # Create queue and lock if needed
        if device_id not in self._queues:
            self._queues[device_id] = asyncio.PriorityQueue()
            self._device_locks[device_id] = asyncio.Lock()
            self._queue_depths[device_id] = 0
            self._total_executions[device_id] = 0

        # Create queued flow item
        queued = QueuedFlow(
            priority=priority,
            timestamp=time.time(),
            flow=flow,
            reason=reason
        )

        # Add to queue
        await self._queues[device_id].put(queued)

        # Update metrics
        self._queue_depths[device_id] = self._queues[device_id].qsize()

        logger.debug(f"[FlowScheduler] Queued flow {flow.flow_id} (priority={priority}, reason={reason}, queue_depth={self._queue_depths[device_id]})")

        # Start scheduler task if not running
        if device_id not in self._scheduler_tasks or self._scheduler_tasks[device_id].done():
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

                # 2. Check if flow still enabled
                if not queued.flow.enabled:
                    logger.info(f"[FlowScheduler] Skipping disabled flow: {queued.flow.flow_id}")
                    queue.task_done()
                    continue

                # 3. Acquire device lock
                async with lock:
                    logger.info(f"[FlowScheduler] Executing flow {queued.flow.flow_id} (priority={queued.priority}, reason={queued.reason})")

                    try:
                        # 4. Execute flow
                        result = await self.flow_executor.execute_flow(queued.flow, device_lock=lock)

                        # 5. Update metrics
                        self._last_execution[device_id] = datetime.now()
                        self._total_executions[device_id] = self._total_executions.get(device_id, 0) + 1

                        if result.success:
                            logger.debug(f"[FlowScheduler] Flow {queued.flow.flow_id} completed successfully")
                        else:
                            logger.warning(f"[FlowScheduler] Flow {queued.flow.flow_id} failed: {result.error_message}")

                    except Exception as e:
                        logger.error(f"[FlowScheduler] Flow execution error: {e}", exc_info=True)

                # 6. Update queue depth
                self._queue_depths[device_id] = queue.qsize()
                queue.task_done()

            except asyncio.CancelledError:
                logger.info(f"[FlowScheduler] Device scheduler cancelled for {device_id}")
                break
            except Exception as e:
                logger.error(f"[FlowScheduler] Scheduler error for {device_id}: {e}", exc_info=True)
                await asyncio.sleep(1)  # Prevent tight loop on errors

        logger.info(f"[FlowScheduler] Device scheduler stopped for {device_id}")

    async def _start_periodic_scheduling(self):
        """
        Start periodic scheduling tasks for all enabled flows

        Creates a background task for each enabled flow that schedules it
        at the configured update_interval_seconds
        """
        # Get all devices
        devices = list(set(
            flow.device_id
            for flows in [self.flow_manager.get_device_flows(d) for d in self._get_all_device_ids()]
            for flow in flows
        ))

        total_flows = 0

        for device_id in devices:
            flows = self.flow_manager.get_enabled_flows(device_id)

            for flow in flows:
                # Create periodic task for this flow
                task = asyncio.create_task(self._run_periodic_flow(flow))
                self._periodic_tasks[flow.flow_id] = task
                total_flows += 1

        logger.info(f"[FlowScheduler] Started periodic scheduling for {total_flows} flows across {len(devices)} devices")

    async def _run_periodic_flow(self, flow: SensorCollectionFlow):
        """
        Background task that periodically schedules a flow

        Args:
            flow: Flow to schedule periodically
        """
        logger.debug(f"[FlowScheduler] Starting periodic scheduling for {flow.flow_id} (interval={flow.update_interval_seconds}s)")

        while self._running:
            try:
                # Calculate priority based on update interval
                # Faster intervals = higher priority
                if flow.update_interval_seconds < 30:
                    priority = 5  # High priority
                elif flow.update_interval_seconds < 300:
                    priority = 10  # Normal priority
                else:
                    priority = 15  # Low priority

                # Schedule flow
                await self.schedule_flow(flow, priority=priority, reason="periodic")

                # Wait for next interval
                await asyncio.sleep(flow.update_interval_seconds)

            except asyncio.CancelledError:
                logger.debug(f"[FlowScheduler] Periodic scheduling cancelled for {flow.flow_id}")
                break
            except Exception as e:
                logger.error(f"[FlowScheduler] Periodic scheduling error for {flow.flow_id}: {e}", exc_info=True)
                await asyncio.sleep(flow.update_interval_seconds)  # Continue on error

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

        # Restart periodic scheduling for enabled flows
        enabled_flows = self.flow_manager.get_enabled_flows(device_id)
        for flow in enabled_flows:
            task = asyncio.create_task(self._run_periodic_flow(flow))
            self._periodic_tasks[flow.flow_id] = task

        logger.info(f"[FlowScheduler] Reloaded {len(enabled_flows)} flows for {device_id}")

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
            "scheduler_running": device_id in self._scheduler_tasks and not self._scheduler_tasks[device_id].done()
        }

    def get_all_metrics(self) -> Dict[str, Dict]:
        """Get scheduler metrics for all devices"""
        return {
            device_id: self.get_metrics(device_id)
            for device_id in self._queues.keys()
        }
