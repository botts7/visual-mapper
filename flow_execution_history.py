"""
Flow Execution History - Track detailed logs for each flow run

This module provides persistent storage for flow execution history:
- Tracks each execution attempt with detailed step-by-step logs
- Stores success/failure status, timestamps, errors
- Provides queryable history for UI display
- Helps debug flow failures and track performance over time
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class FlowStepLog:
    """Log entry for a single step execution"""
    step_index: int
    step_type: str
    description: Optional[str]
    started_at: str  # ISO format
    completed_at: Optional[str] = None
    success: bool = False
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    details: Optional[Dict[str, Any]] = None  # Additional context (e.g., captured sensor values)


@dataclass
class FlowExecutionLog:
    """Complete log for a single flow execution"""
    execution_id: str  # UUID for this execution
    flow_id: str
    device_id: str
    started_at: str  # ISO format
    completed_at: Optional[str] = None
    success: bool = False
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    triggered_by: str = "scheduler"  # scheduler, manual, api, test
    steps: List[FlowStepLog] = None  # Step-by-step logs
    total_steps: int = 0
    executed_steps: int = 0

    def __post_init__(self):
        if self.steps is None:
            self.steps = []


class FlowExecutionHistory:
    """
    Manages persistent storage and retrieval of flow execution history

    Storage Strategy:
    - In-memory cache for recent executions (last 100 per flow)
    - JSON file storage for persistence
    - Automatic cleanup of old logs (keep last 1000 per flow)
    """

    def __init__(self, storage_dir: str = "data/flow-history"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache: flow_id -> deque of FlowExecutionLog
        self._cache: Dict[str, deque] = {}
        self._cache_size = 100  # Keep last 100 executions per flow in memory

        # Load existing history from disk
        self._load_all_history()

        logger.info(f"[FlowExecutionHistory] Initialized with storage: {self.storage_dir}")

    def _get_history_file(self, flow_id: str) -> Path:
        """Get path to history file for a flow"""
        # Use flow_id as filename (safe for filesystem)
        safe_flow_id = flow_id.replace(':', '_').replace('/', '_')
        return self.storage_dir / f"{safe_flow_id}.json"

    def _load_all_history(self):
        """Load all existing flow history files into cache"""
        for history_file in self.storage_dir.glob("*.json"):
            try:
                flow_id = history_file.stem.replace('_', ':')  # Reverse sanitization
                self._load_history(flow_id)
            except Exception as e:
                logger.warning(f"[FlowExecutionHistory] Failed to load {history_file}: {e}")

    def _load_history(self, flow_id: str):
        """Load history for a specific flow from disk"""
        history_file = self._get_history_file(flow_id)
        if not history_file.exists():
            self._cache[flow_id] = deque(maxlen=self._cache_size)
            return

        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                executions = [self._dict_to_log(log_dict) for log_dict in data]
                # Keep only recent executions in cache
                self._cache[flow_id] = deque(executions[-self._cache_size:], maxlen=self._cache_size)
                logger.debug(f"[FlowExecutionHistory] Loaded {len(executions)} executions for {flow_id}")
        except Exception as e:
            logger.error(f"[FlowExecutionHistory] Failed to load history for {flow_id}: {e}")
            self._cache[flow_id] = deque(maxlen=self._cache_size)

    def _dict_to_log(self, log_dict: Dict) -> FlowExecutionLog:
        """Convert dict to FlowExecutionLog"""
        # Convert step dicts to FlowStepLog objects
        steps = []
        if 'steps' in log_dict and log_dict['steps']:
            steps = [FlowStepLog(**step) for step in log_dict['steps']]

        log_dict['steps'] = steps
        return FlowExecutionLog(**log_dict)

    def _log_to_dict(self, log: FlowExecutionLog) -> Dict:
        """Convert FlowExecutionLog to dict"""
        log_dict = asdict(log)
        return log_dict

    def _save_history(self, flow_id: str):
        """Save history for a specific flow to disk"""
        if flow_id not in self._cache:
            return

        history_file = self._get_history_file(flow_id)
        try:
            # Convert all logs to dicts
            logs = [self._log_to_dict(log) for log in self._cache[flow_id]]

            # Keep only last 1000 executions in file storage
            logs = logs[-1000:]

            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(logs, f, indent=2)

            logger.debug(f"[FlowExecutionHistory] Saved {len(logs)} executions for {flow_id}")
        except Exception as e:
            logger.error(f"[FlowExecutionHistory] Failed to save history for {flow_id}: {e}")

    def add_execution(self, log: FlowExecutionLog):
        """Add a new execution log"""
        flow_id = log.flow_id

        # Initialize cache if needed
        if flow_id not in self._cache:
            self._cache[flow_id] = deque(maxlen=self._cache_size)

        # Add to cache
        self._cache[flow_id].append(log)

        # Save to disk
        self._save_history(flow_id)

        logger.info(
            f"[FlowExecutionHistory] Logged execution {log.execution_id}: "
            f"{'SUCCESS' if log.success else 'FAILED'} ({log.executed_steps}/{log.total_steps} steps, {log.duration_ms}ms)"
        )

    def get_history(self, flow_id: str, limit: int = 50) -> List[FlowExecutionLog]:
        """Get execution history for a flow"""
        if flow_id not in self._cache:
            self._load_history(flow_id)

        if flow_id not in self._cache:
            return []

        # Return most recent executions
        logs = list(self._cache[flow_id])
        return logs[-limit:]

    def get_latest_execution(self, flow_id: str) -> Optional[FlowExecutionLog]:
        """Get the most recent execution log for a flow"""
        if flow_id not in self._cache:
            self._load_history(flow_id)

        if flow_id not in self._cache or not self._cache[flow_id]:
            return None

        return self._cache[flow_id][-1]

    def get_execution(self, flow_id: str, execution_id: str) -> Optional[FlowExecutionLog]:
        """Get a specific execution by ID"""
        history = self.get_history(flow_id, limit=1000)
        for log in history:
            if log.execution_id == execution_id:
                return log
        return None

    def get_stats(self, flow_id: str) -> Dict[str, Any]:
        """Get statistics for a flow"""
        history = self.get_history(flow_id, limit=1000)
        if not history:
            return {
                "total_executions": 0,
                "success_count": 0,
                "failure_count": 0,
                "success_rate": 0.0,
                "avg_duration_ms": 0,
                "last_execution": None
            }

        success_count = sum(1 for log in history if log.success)
        failure_count = len(history) - success_count
        success_rate = (success_count / len(history)) * 100 if history else 0.0

        # Calculate average duration (only for completed executions)
        completed = [log for log in history if log.duration_ms is not None]
        avg_duration = sum(log.duration_ms for log in completed) / len(completed) if completed else 0

        latest = history[-1]

        return {
            "total_executions": len(history),
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": round(success_rate, 1),
            "avg_duration_ms": round(avg_duration),
            "last_execution": {
                "execution_id": latest.execution_id,
                "started_at": latest.started_at,
                "success": latest.success,
                "error": latest.error,
                "duration_ms": latest.duration_ms
            }
        }

    def cleanup_old_logs(self, days: int = 30):
        """Delete execution logs older than specified days"""
        from datetime import timedelta

        cutoff_date = datetime.now() - timedelta(days=days)
        deleted_count = 0

        for flow_id in list(self._cache.keys()):
            history = list(self._cache[flow_id])
            # Filter logs newer than cutoff
            kept_logs = [
                log for log in history
                if datetime.fromisoformat(log.started_at) > cutoff_date
            ]

            deleted = len(history) - len(kept_logs)
            if deleted > 0:
                self._cache[flow_id] = deque(kept_logs, maxlen=self._cache_size)
                self._save_history(flow_id)
                deleted_count += deleted

        logger.info(f"[FlowExecutionHistory] Cleaned up {deleted_count} old execution logs")
        return deleted_count
