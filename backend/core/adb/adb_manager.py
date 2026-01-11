"""
ADB Manager with hybrid approach.
Priority:
1. ADB Server Add-on (best - supports TLS, managed by HA)
2. Python ADB library (good - works for USB and port 5555)
3. Subprocess ADB (fallback - if system ADB available, supports TLS)

Adapted from v3 with improvements: uses BaseADBConnection types, centralized config.
"""

import asyncio
import logging
import socket
from typing import Tuple

from .adb_connection import PythonADBConnection
from .adb_subprocess import SubprocessADBConnection
from .adb_network import NetworkADBConnection
from .base_connection import BaseADBConnection
from .config import config

_LOGGER = logging.getLogger(__name__)


class ADBManager:
    """Manages ADB connections using hybrid approach with auto-detection."""

    def __init__(self, hass, allow_download: bool = True):
        """Initialize ADB manager.

        Args:
            hass: Home Assistant instance or None for standalone mode
            allow_download: Unused (kept for compatibility with v3)
        """
        self.hass = hass
        self._connection = None

    async def _run_in_executor(self, func):
        """Run a sync function in executor.

        Args:
            func: Synchronous function to run

        Returns:
            Result from function
        """
        # Check if hass has the async_add_executor_job method (HA instance)
        if hasattr(self.hass, "async_add_executor_job"):
            return await self.hass.async_add_executor_job(func)
        else:
            # Running as standalone addon - use asyncio
            return await asyncio.to_thread(func)

    async def _check_adb_server(self) -> bool:
        """Check if ADB Server add-on is running.

        Returns:
            True if ADB server is reachable on localhost:5037
        """
        try:

            def _test():
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                # Try localhost (add-on uses host_network: true)
                result = sock.connect_ex(
                    (config.ADB_SERVER_HOST, config.ADB_SERVER_PORT)
                )
                sock.close()
                return result == 0

            return await self._run_in_executor(_test)
        except Exception as e:
            _LOGGER.debug(f"ADB server check failed: {e}")
            return False

    async def ensure_adb_available(self) -> Tuple[bool, str]:
        """Ensure ADB is available.

        Checks for (in priority order):
        1. ADB Server add-on (port 5037)
        2. Python ADB library (always available)
        3. System ADB binary (fallback)

        Returns:
            Tuple of (success: bool, message: str)
        """
        # Check for ADB Server add-on (best option)
        if await self._check_adb_server():
            _LOGGER.info("✅ ADB Server add-on detected (TLS support enabled)")
            return True, "adb_server_addon"

        _LOGGER.info("🐍 Python ADB library available (adb-shell)")

        # Check if system ADB binary is also available (fallback)
        try:
            import subprocess

            def _check_adb():
                result = subprocess.run(
                    ["adb", "version"], capture_output=True, timeout=2
                )
                return result.returncode == 0

            is_available = await self._run_in_executor(_check_adb)
            if is_available:
                _LOGGER.info(
                    "✅ System ADB binary also available (fallback TLS support)"
                )
                return True, "hybrid_adb"
            else:
                _LOGGER.info("ℹ️  Install ADB Server add-on for TLS support")
                return True, "python_adb_only"
        except Exception as e:
            _LOGGER.info(f"ℹ️  System ADB not available - install add-on for TLS: {e}")
            return True, "python_adb_only"

    async def get_connection(self, host: str, port: int = None) -> BaseADBConnection:
        """Get ADB connection instance using optimal strategy.

        Priority:
        1. ADB Server add-on (if available on port 5037)
        2. Python ADB (port 5555 or USB)
        3. Subprocess ADB (high ports with TLS)

        Args:
            host: Device IP address
            port: ADB port (default from config: 5555)

        Returns:
            BaseADBConnection instance
        """
        if port is None:
            port = config.DEFAULT_ADB_PORT

        device_id = f"{host}:{port}"

        # Check if ADB Server add-on is available
        if await self._check_adb_server():
            _LOGGER.info(f"Using ADB Server add-on for {device_id}")
            return NetworkADBConnection(self.hass, device_id)

        # Android 11+ wireless debugging uses TLS on high ports (e.g., 45441)
        # Python ADB library doesn't support TLS, so use subprocess for these
        if port != config.DEFAULT_ADB_PORT:
            _LOGGER.info(f"Port {port} detected - using subprocess ADB (TLS support)")
            return SubprocessADBConnection(self.hass, device_id)
        else:
            _LOGGER.info(f"Port {port} detected - using Python ADB library")
            return PythonADBConnection(self.hass, host, port)

    async def test_adb(self, host: str, port: int = None) -> bool:
        """Test ADB connection to device.

        Args:
            host: Device IP address
            port: ADB port (default from config: 5555)

        Returns:
            True if connection successful, False otherwise
        """
        if port is None:
            port = config.DEFAULT_ADB_PORT

        conn = await self.get_connection(host, port)
        try:
            connected = await conn.connect()
            if connected:
                # Try a simple command
                result = await conn.shell("echo test")
                await conn.close()
                return result == "test"
            return False
        except Exception as e:
            _LOGGER.error(f"ADB test failed: {e}")
            return False
