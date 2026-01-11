"""
Visual Mapper - Performance Monitor (Phase 8 Week 2)
Tracks flow execution metrics and generates actionable alerts
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass
from collections import deque

from core.flows import SensorCollectionFlow, FlowExecutionResult

logger = logging.getLogger(__name__)


@dataclass
class PerformanceAlert:
    """
    Performance alert with severity and recommendations

    Severity Levels:
    - info: Informational (FYI)
    - warning: Potential issue (action recommended)
    - error: Confirmed issue (action required)
    - critical: Severe issue (immediate action required)
    """

    device_id: str
    severity: str  # info, warning, error, critical
    message: str
    recommendations: List[str]
    timestamp: datetime
    flow_id: Optional[str] = None
    metric_name: Optional[str] = None
    metric_value: Optional[Any] = None

    def dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            "device_id": self.device_id,
            "severity": self.severity,
            "message": self.message,
            "recommendations": self.recommendations,
            "timestamp": self.timestamp.isoformat(),
            "flow_id": self.flow_id,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
        }


class PerformanceMonitor:
    """
    Monitors flow execution performance and generates alerts

    Features:
    - Queue depth monitoring (backlog detection)
    - Execution time tracking
    - Success/failure rate tracking
    - Slow step identification
    - Actionable alert generation
    - Historical metrics storage (last 100 per device)

    Thresholds:
    - QUEUE_DEPTH_WARNING: 5 flows queued
    - QUEUE_DEPTH_CRITICAL: 10 flows queued
    - BACKLOG_RATIO: 0.5 (execution time > 50% of update interval)
    - FAILURE_RATE_WARNING: 0.2 (20% failure rate)
    - FAILURE_RATE_CRITICAL: 0.5 (50% failure rate)
    """

    def __init__(self, flow_scheduler, mqtt_manager=None):
        """
        Initialize performance monitor

        Args:
            flow_scheduler: FlowScheduler instance for queue depth checks
            mqtt_manager: Optional MQTTManager for alert publishing
        """
        self.scheduler = flow_scheduler
        self.mqtt_manager = mqtt_manager

        # Metrics storage (per device, last 100 executions)
        self._execution_history: Dict[str, deque] = {}

        # Alerts (per device, last 50 alerts)
        self._alerts: Dict[str, deque] = {}

        # Alert thresholds
        self.QUEUE_DEPTH_WARNING = 5
        self.QUEUE_DEPTH_CRITICAL = 10
        self.BACKLOG_RATIO = 0.5  # Execution time > 50% of interval
        self.FAILURE_RATE_WARNING = 0.2  # 20% failure rate
        self.FAILURE_RATE_CRITICAL = 0.5  # 50% failure rate

        # Alert cooldown (seconds) - prevent spam
        self._last_alert_time: Dict[str, datetime] = {}
        self.ALERT_COOLDOWN_SECONDS = 300  # 5 minutes

        logger.info("[PerformanceMonitor] Initialized")

    async def record_execution(
        self, flow: SensorCollectionFlow, result: FlowExecutionResult
    ):
        """
        Record execution result and check for performance issues

        Args:
            flow: Flow that was executed
            result: Execution result with metrics
        """
        device_id = flow.device_id

        # 1. Store execution result
        if device_id not in self._execution_history:
            self._execution_history[device_id] = deque(maxlen=100)

        self._execution_history[device_id].append(
            {
                "flow_id": result.flow_id,
                "success": result.success,
                "execution_time_ms": result.execution_time_ms,
                "executed_steps": result.executed_steps,
                "timestamp": datetime.now(),
                "error_message": result.error_message,
            }
        )

        # 2. Check queue depth
        await self._check_queue_depth(device_id)

        # 3. Check for backlog (execution time too long)
        await self._check_backlog(device_id, flow, result)

        # 4. Check failure rate
        await self._check_failure_rate(device_id)

        logger.debug(
            f"[PerformanceMonitor] Recorded execution for {flow.flow_id}: "
            f"success={result.success}, time={result.execution_time_ms}ms"
        )

    async def _check_queue_depth(self, device_id: str):
        """
        Check if queue depth exceeds thresholds

        Args:
            device_id: Device to check
        """
        queue_depth = self.scheduler.get_queue_depth(device_id)

        if queue_depth >= self.QUEUE_DEPTH_CRITICAL:
            await self._create_alert(
                device_id=device_id,
                severity="critical",
                message=f"Queue backlog: {queue_depth} flows waiting",
                recommendations=[
                    "Increase update intervals for low-priority flows",
                    "Disable unused flows",
                    "Consider splitting sensors across multiple devices",
                    f"Current queue: {queue_depth} flows (critical threshold: {self.QUEUE_DEPTH_CRITICAL})",
                ],
                metric_name="queue_depth",
                metric_value=queue_depth,
            )
        elif queue_depth >= self.QUEUE_DEPTH_WARNING:
            await self._create_alert(
                device_id=device_id,
                severity="warning",
                message=f"Queue depth: {queue_depth} flows waiting",
                recommendations=[
                    "Review flow update intervals",
                    "Consider disabling low-priority flows",
                    f"Current queue: {queue_depth} flows (warning threshold: {self.QUEUE_DEPTH_WARNING})",
                ],
                metric_name="queue_depth",
                metric_value=queue_depth,
            )

    async def _check_backlog(
        self, device_id: str, flow: SensorCollectionFlow, result: FlowExecutionResult
    ):
        """
        Check if flow execution time is too long relative to update interval

        Args:
            device_id: Device ID
            flow: Flow that was executed
            result: Execution result
        """
        if not result.success:
            return  # Don't check backlog for failed flows

        execution_time_s = result.execution_time_ms / 1000
        interval_s = flow.update_interval_seconds
        ratio = execution_time_s / interval_s

        if ratio > self.BACKLOG_RATIO:
            await self._create_alert(
                device_id=device_id,
                severity="warning",
                message=f"Slow flow: {flow.name} takes {execution_time_s:.1f}s but updates every {interval_s}s",
                recommendations=[
                    f"Increase update interval to {int(execution_time_s * 2.5)}s or more",
                    "Optimize flow steps (reduce waits, remove unnecessary steps)",
                    "Consider splitting into multiple faster flows",
                    f"Current ratio: {ratio:.1%} (threshold: {self.BACKLOG_RATIO:.0%})",
                ],
                flow_id=flow.flow_id,
                metric_name="execution_time_ratio",
                metric_value=ratio,
            )

    async def _check_failure_rate(self, device_id: str):
        """
        Check if failure rate exceeds thresholds

        Args:
            device_id: Device to check
        """
        history = self._execution_history.get(device_id, [])
        if len(history) < 10:
            return  # Need at least 10 executions for meaningful rate

        # Calculate failure rate over last 20 executions
        recent = list(history)[-20:]
        failure_rate = sum(1 for r in recent if not r["success"]) / len(recent)

        if failure_rate >= self.FAILURE_RATE_CRITICAL:
            await self._create_alert(
                device_id=device_id,
                severity="error",
                message=f"High failure rate: {failure_rate:.0%} of recent flows failed",
                recommendations=[
                    "Check device connection (ADB may be unstable)",
                    "Review flow validation steps",
                    "Check for app crashes or permission issues",
                    "Review recent error messages in flow history",
                    f"Recent failures: {int(failure_rate * len(recent))}/{len(recent)}",
                ],
                metric_name="failure_rate",
                metric_value=failure_rate,
            )
        elif failure_rate >= self.FAILURE_RATE_WARNING:
            await self._create_alert(
                device_id=device_id,
                severity="warning",
                message=f"Elevated failure rate: {failure_rate:.0%}",
                recommendations=[
                    "Monitor device connection stability",
                    "Review flow validation logic",
                    f"Recent failures: {int(failure_rate * len(recent))}/{len(recent)}",
                ],
                metric_name="failure_rate",
                metric_value=failure_rate,
            )

    async def _create_alert(
        self,
        device_id: str,
        severity: str,
        message: str,
        recommendations: List[str],
        flow_id: Optional[str] = None,
        metric_name: Optional[str] = None,
        metric_value: Optional[Any] = None,
    ):
        """
        Create performance alert with cooldown to prevent spam

        Args:
            device_id: Device ID
            severity: Alert severity (info, warning, error, critical)
            message: Alert message
            recommendations: List of actionable recommendations
            flow_id: Optional flow ID
            metric_name: Optional metric name
            metric_value: Optional metric value
        """
        # Check cooldown
        alert_key = f"{device_id}:{metric_name or 'general'}"
        now = datetime.now()

        if alert_key in self._last_alert_time:
            time_since_last = (now - self._last_alert_time[alert_key]).total_seconds()
            if time_since_last < self.ALERT_COOLDOWN_SECONDS:
                logger.debug(
                    f"[PerformanceMonitor] Alert cooldown active for {alert_key} "
                    f"({time_since_last:.0f}s / {self.ALERT_COOLDOWN_SECONDS}s)"
                )
                return

        # Create alert
        alert = PerformanceAlert(
            device_id=device_id,
            severity=severity,
            message=message,
            recommendations=recommendations,
            timestamp=now,
            flow_id=flow_id,
            metric_name=metric_name,
            metric_value=metric_value,
        )

        # Store alert
        if device_id not in self._alerts:
            self._alerts[device_id] = deque(maxlen=50)

        self._alerts[device_id].append(alert)

        # Update cooldown timer
        self._last_alert_time[alert_key] = now

        # Publish to MQTT for Home Assistant notification
        if self.mqtt_manager and severity in ["error", "critical"]:
            try:
                await self.mqtt_manager.publish_alert(alert)
            except Exception as e:
                logger.error(
                    f"[PerformanceMonitor] Failed to publish alert to MQTT: {e}"
                )

        # Log alert
        log_level = {
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL,
        }.get(severity, logging.WARNING)

        logger.log(log_level, f"[PerformanceMonitor] {severity.upper()}: {message}")

    def get_metrics(self, device_id: str) -> Dict[str, Any]:
        """
        Get performance metrics for a device

        Args:
            device_id: Device ID

        Returns:
            Dictionary with performance metrics
        """
        history = self._execution_history.get(device_id, deque())

        if not history:
            return {
                "device_id": device_id,
                "no_data": True,
                "message": "No execution history available",
            }

        # Convert deque to list for easier processing
        history_list = list(history)
        recent = history_list[-10:] if len(history_list) >= 10 else history_list

        # Calculate metrics
        total_executions = len(history_list)
        successful_executions = sum(1 for r in history_list if r["success"])
        success_rate = (
            successful_executions / total_executions if total_executions > 0 else 0
        )

        avg_execution_time = int(
            sum(r["execution_time_ms"] for r in history_list) / total_executions
        )

        recent_success_rate = (
            sum(1 for r in recent if r["success"]) / len(recent) if recent else 0
        )

        # Get slowest flows
        slowest_flows = self._get_slowest_flows(device_id, limit=5)

        # Get recent alerts
        alerts = self._alerts.get(device_id, deque())
        recent_alerts = [a.dict() for a in list(alerts)[-5:]]

        return {
            "device_id": device_id,
            "queue_depth": self.scheduler.get_queue_depth(device_id),
            "total_executions": total_executions,
            "successful_executions": successful_executions,
            "success_rate": success_rate,
            "recent_success_rate": recent_success_rate,
            "avg_execution_time_ms": avg_execution_time,
            "recent_alerts": recent_alerts,
            "slowest_flows": slowest_flows,
            "last_execution": (
                history_list[-1]["timestamp"].isoformat() if history_list else None
            ),
        }

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """
        Get metrics for all devices

        Returns:
            Dictionary mapping device_id to metrics
        """
        all_device_ids = set(self._execution_history.keys()) | set(
            self.scheduler._queues.keys()
        )

        return {device_id: self.get_metrics(device_id) for device_id in all_device_ids}

    def _get_slowest_flows(
        self, device_id: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get slowest flows for a device

        Args:
            device_id: Device ID
            limit: Maximum number of flows to return

        Returns:
            List of slowest flows with execution times
        """
        history = self._execution_history.get(device_id, deque())
        if not history:
            return []

        # Group by flow_id and calculate average time
        flow_times: Dict[str, List[int]] = {}

        for record in history:
            flow_id = record["flow_id"]
            if flow_id not in flow_times:
                flow_times[flow_id] = []
            flow_times[flow_id].append(record["execution_time_ms"])

        # Calculate averages and sort
        flow_averages = [
            {
                "flow_id": flow_id,
                "avg_time_ms": int(sum(times) / len(times)),
                "execution_count": len(times),
            }
            for flow_id, times in flow_times.items()
        ]

        # Sort by average time (descending)
        flow_averages.sort(key=lambda x: x["avg_time_ms"], reverse=True)

        return flow_averages[:limit]

    def get_recent_alerts(
        self, device_id: Optional[str] = None, limit: int = 10
    ) -> List[Dict]:
        """
        Get recent alerts

        Args:
            device_id: Optional device ID filter
            limit: Maximum number of alerts to return

        Returns:
            List of recent alerts (most recent first)
        """
        if device_id:
            alerts = self._alerts.get(device_id, deque())
            return [a.dict() for a in list(alerts)[-limit:]][::-1]
        else:
            # Get alerts from all devices
            all_alerts = []
            for device_alerts in self._alerts.values():
                all_alerts.extend(list(device_alerts))

            # Sort by timestamp (most recent first)
            all_alerts.sort(key=lambda a: a.timestamp, reverse=True)

            return [a.dict() for a in all_alerts[:limit]]

    def clear_alerts(self, device_id: Optional[str] = None):
        """
        Clear alerts for a device or all devices

        Args:
            device_id: Optional device ID (if None, clears all)
        """
        if device_id:
            if device_id in self._alerts:
                self._alerts[device_id].clear()
                logger.info(f"[PerformanceMonitor] Cleared alerts for {device_id}")
        else:
            self._alerts.clear()
            logger.info("[PerformanceMonitor] Cleared all alerts")
