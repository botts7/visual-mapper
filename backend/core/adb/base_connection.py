"""
Base ADB Connection - Abstract interface for all connection types.
This eliminates code duplication from v3 reference implementation.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Any

_LOGGER = logging.getLogger(__name__)


class BaseADBConnection(ABC):
    """Abstract base class for all ADB connection types.

    All connection types (PythonADB, SubprocessADB, NetworkADB) inherit from this
    to ensure consistent interface and eliminate duplicate code.
    """

    def __init__(self, hass: Optional[Any], device_id: str):
        """Initialize base connection.

        Args:
            hass: Home Assistant instance or None for standalone mode
            device_id: Device identifier (e.g., "192.168.1.100:5555")
        """
        self.hass = hass
        self.device_id = device_id
        self._connected = False

    async def _run_in_executor(self, func, *args):
        """Run sync function in executor (shared implementation).

        This method handles both Home Assistant integration mode and standalone mode.

        Args:
            func: Synchronous function to run
            *args: Arguments to pass to function

        Returns:
            Result from function execution
        """
        if hasattr(self.hass, "async_add_executor_job"):
            # Home Assistant integration mode
            return await self.hass.async_add_executor_job(func, *args)
        else:
            # Standalone addon mode
            return await asyncio.to_thread(func, *args)

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to device.

        Must be implemented by subclasses.

        Returns:
            True if connected successfully, False otherwise
        """
        pass

    @abstractmethod
    async def shell(self, command: str) -> str:
        """Execute shell command on device.

        Must be implemented by subclasses.

        Args:
            command: Shell command to execute

        Returns:
            Command output as string

        Raises:
            ConnectionError: If not connected to device
        """
        pass

    @abstractmethod
    async def pull(self, remote_path: str, local_path: str) -> bool:
        """Pull file from device.

        Must be implemented by subclasses.

        Args:
            remote_path: Path on device
            local_path: Local path to save file

        Returns:
            True if successful, False otherwise

        Raises:
            ConnectionError: If not connected to device
        """
        pass

    @abstractmethod
    async def push(self, local_path: str, remote_path: str) -> bool:
        """Push file to device.

        Must be implemented by subclasses.

        Args:
            local_path: Local file path
            remote_path: Path on device

        Returns:
            True if successful, False otherwise

        Raises:
            ConnectionError: If not connected to device
        """
        pass

    @abstractmethod
    async def close(self):
        """Close connection.

        Must be implemented by subclasses.
        """
        pass

    @property
    def available(self) -> bool:
        """Check if connection is available.

        Returns:
            True if connected, False otherwise
        """
        return self._connected
