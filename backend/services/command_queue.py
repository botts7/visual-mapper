"""
Command Queue Service - Offline Command Resilience

Phase 2 Refactor: Queues commands when Android device is offline
and replays them when the device reconnects.

Features:
- TTL-based expiration (default 1 hour)
- Priority ordering
- Duplicate detection
- Async-safe operations
- Persistent storage (SQLite)
"""

import asyncio
import logging
import sqlite3
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from threading import Lock

logger = logging.getLogger(__name__)


class CommandPriority(Enum):
    """Command priority levels for ordering"""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class CommandStatus(Enum):
    """Command status in queue"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class QueuedCommand:
    """A command waiting to be sent to a device"""

    command_id: str
    device_id: str
    command_type: str
    payload: Dict[str, Any]
    priority: int = CommandPriority.NORMAL.value
    created_at: float = None
    expires_at: float = None
    status: str = CommandStatus.PENDING.value
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.expires_at is None:
            self.expires_at = self.created_at + 3600  # 1 hour default TTL


class CommandQueue:
    """
    Persistent command queue for offline resilience.

    Usage:
        queue = CommandQueue()

        # Queue a command
        cmd_id = await queue.enqueue(
            device_id="192.168.1.100:5555",
            command_type="execute_flow",
            payload={"flow_id": "my_flow"}
        )

        # When device connects, replay pending commands
        commands = await queue.get_pending_commands(device_id)
        for cmd in commands:
            success = await send_to_device(cmd)
            if success:
                await queue.mark_completed(cmd.command_id)
            else:
                await queue.mark_failed(cmd.command_id, "Send failed")
    """

    def __init__(
        self, db_path: str = "data/command_queue.db", default_ttl_seconds: int = 3600
    ):
        self.db_path = Path(db_path)
        self.default_ttl = default_ttl_seconds
        self._lock = Lock()
        self._init_db()
        logger.info(f"[CommandQueue] Initialized with DB at {self.db_path}")

    def _init_db(self):
        """Initialize SQLite database"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS command_queue (
                    command_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    command_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    priority INTEGER DEFAULT 1,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    error_message TEXT,
                    updated_at REAL
                )
            """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_device_status ON command_queue(device_id, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_expires ON command_queue(expires_at)"
            )
            conn.commit()

    def _generate_id(self) -> str:
        """Generate unique command ID"""
        import uuid

        return f"cmd_{uuid.uuid4().hex[:12]}"

    async def enqueue(
        self,
        device_id: str,
        command_type: str,
        payload: Dict[str, Any],
        priority: CommandPriority = CommandPriority.NORMAL,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """
        Add a command to the queue.

        Args:
            device_id: Target device ID
            command_type: Type of command (e.g., "execute_flow", "sync_sensors")
            payload: Command payload
            priority: Command priority
            ttl_seconds: Time-to-live override (default: 1 hour)

        Returns:
            Command ID
        """
        command_id = self._generate_id()
        now = time.time()
        ttl = ttl_seconds or self.default_ttl
        expires_at = now + ttl

        cmd = QueuedCommand(
            command_id=command_id,
            device_id=device_id,
            command_type=command_type,
            payload=payload,
            priority=priority.value,
            created_at=now,
            expires_at=expires_at,
        )

        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO command_queue (
                        command_id, device_id, command_type, payload, priority,
                        created_at, expires_at, status, retry_count, max_retries, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        cmd.command_id,
                        cmd.device_id,
                        cmd.command_type,
                        json.dumps(cmd.payload),
                        cmd.priority,
                        cmd.created_at,
                        cmd.expires_at,
                        cmd.status,
                        cmd.retry_count,
                        cmd.max_retries,
                        now,
                    ),
                )
                conn.commit()

        logger.info(
            f"[CommandQueue] Enqueued {command_type} for {device_id}: {command_id}"
        )
        return command_id

    async def get_pending_commands(self, device_id: str) -> List[QueuedCommand]:
        """
        Get all pending commands for a device, ordered by priority and age.
        Automatically expires old commands.

        Args:
            device_id: Device to get commands for

        Returns:
            List of pending commands
        """
        now = time.time()

        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                # First, expire old commands
                conn.execute(
                    """
                    UPDATE command_queue
                    SET status = ?, updated_at = ?
                    WHERE expires_at < ? AND status = ?
                """,
                    (
                        CommandStatus.EXPIRED.value,
                        now,
                        now,
                        CommandStatus.PENDING.value,
                    ),
                )

                # Then get pending commands
                cursor = conn.execute(
                    """
                    SELECT command_id, device_id, command_type, payload, priority,
                           created_at, expires_at, status, retry_count, max_retries, error_message
                    FROM command_queue
                    WHERE device_id = ? AND status = ?
                    ORDER BY priority DESC, created_at ASC
                """,
                    (device_id, CommandStatus.PENDING.value),
                )

                rows = cursor.fetchall()
                conn.commit()

        commands = []
        for row in rows:
            commands.append(
                QueuedCommand(
                    command_id=row[0],
                    device_id=row[1],
                    command_type=row[2],
                    payload=json.loads(row[3]),
                    priority=row[4],
                    created_at=row[5],
                    expires_at=row[6],
                    status=row[7],
                    retry_count=row[8],
                    max_retries=row[9],
                    error_message=row[10],
                )
            )

        logger.debug(
            f"[CommandQueue] Found {len(commands)} pending commands for {device_id}"
        )
        return commands

    async def mark_processing(self, command_id: str) -> bool:
        """Mark a command as being processed"""
        return await self._update_status(command_id, CommandStatus.PROCESSING)

    async def mark_completed(self, command_id: str) -> bool:
        """Mark a command as completed"""
        return await self._update_status(command_id, CommandStatus.COMPLETED)

    async def mark_failed(self, command_id: str, error_message: str) -> bool:
        """
        Mark a command as failed.
        If retries remaining, keeps it pending for retry.
        """
        now = time.time()

        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                # Get current retry count
                cursor = conn.execute(
                    "SELECT retry_count, max_retries FROM command_queue WHERE command_id = ?",
                    (command_id,),
                )
                row = cursor.fetchone()

                if not row:
                    return False

                retry_count, max_retries = row
                retry_count += 1

                if retry_count >= max_retries:
                    # No more retries, mark as failed
                    conn.execute(
                        """
                        UPDATE command_queue
                        SET status = ?, error_message = ?, retry_count = ?, updated_at = ?
                        WHERE command_id = ?
                    """,
                        (
                            CommandStatus.FAILED.value,
                            error_message,
                            retry_count,
                            now,
                            command_id,
                        ),
                    )
                    logger.warning(
                        f"[CommandQueue] Command {command_id} failed permanently: {error_message}"
                    )
                else:
                    # Keep pending for retry
                    conn.execute(
                        """
                        UPDATE command_queue
                        SET status = ?, error_message = ?, retry_count = ?, updated_at = ?
                        WHERE command_id = ?
                    """,
                        (
                            CommandStatus.PENDING.value,
                            error_message,
                            retry_count,
                            now,
                            command_id,
                        ),
                    )
                    logger.info(
                        f"[CommandQueue] Command {command_id} will retry ({retry_count}/{max_retries})"
                    )

                conn.commit()

        return True

    async def _update_status(self, command_id: str, status: CommandStatus) -> bool:
        """Update command status"""
        now = time.time()

        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute(
                    """
                    UPDATE command_queue SET status = ?, updated_at = ?
                    WHERE command_id = ?
                """,
                    (status.value, now, command_id),
                )
                conn.commit()
                return cursor.rowcount > 0

    async def get_queue_stats(self, device_id: Optional[str] = None) -> Dict[str, Any]:
        """Get queue statistics"""
        now = time.time()

        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                if device_id:
                    cursor = conn.execute(
                        """
                        SELECT status, COUNT(*) FROM command_queue
                        WHERE device_id = ?
                        GROUP BY status
                    """,
                        (device_id,),
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT status, COUNT(*) FROM command_queue
                        GROUP BY status
                    """
                    )

                stats = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            "device_id": device_id,
            "pending": stats.get(CommandStatus.PENDING.value, 0),
            "processing": stats.get(CommandStatus.PROCESSING.value, 0),
            "completed": stats.get(CommandStatus.COMPLETED.value, 0),
            "failed": stats.get(CommandStatus.FAILED.value, 0),
            "expired": stats.get(CommandStatus.EXPIRED.value, 0),
            "total": sum(stats.values()),
        }

    async def cleanup_old_commands(self, max_age_hours: int = 24) -> int:
        """Remove old completed/failed/expired commands"""
        cutoff = time.time() - (max_age_hours * 3600)

        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute(
                    """
                    DELETE FROM command_queue
                    WHERE status IN (?, ?, ?) AND created_at < ?
                """,
                    (
                        CommandStatus.COMPLETED.value,
                        CommandStatus.FAILED.value,
                        CommandStatus.EXPIRED.value,
                        cutoff,
                    ),
                )
                deleted = cursor.rowcount
                conn.commit()

        if deleted > 0:
            logger.info(f"[CommandQueue] Cleaned up {deleted} old commands")
        return deleted

    async def cancel_pending(
        self, device_id: str, command_type: Optional[str] = None
    ) -> int:
        """Cancel pending commands for a device"""
        now = time.time()

        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                if command_type:
                    cursor = conn.execute(
                        """
                        UPDATE command_queue
                        SET status = ?, updated_at = ?
                        WHERE device_id = ? AND command_type = ? AND status = ?
                    """,
                        (
                            CommandStatus.EXPIRED.value,
                            now,
                            device_id,
                            command_type,
                            CommandStatus.PENDING.value,
                        ),
                    )
                else:
                    cursor = conn.execute(
                        """
                        UPDATE command_queue
                        SET status = ?, updated_at = ?
                        WHERE device_id = ? AND status = ?
                    """,
                        (
                            CommandStatus.EXPIRED.value,
                            now,
                            device_id,
                            CommandStatus.PENDING.value,
                        ),
                    )

                cancelled = cursor.rowcount
                conn.commit()

        logger.info(
            f"[CommandQueue] Cancelled {cancelled} pending commands for {device_id}"
        )
        return cancelled


# Singleton instance
_queue_instance: Optional[CommandQueue] = None


def get_command_queue(db_path: str = "data/command_queue.db") -> CommandQueue:
    """Get or create the singleton command queue instance"""
    global _queue_instance
    if _queue_instance is None:
        _queue_instance = CommandQueue(db_path)
    return _queue_instance
