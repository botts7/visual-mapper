"""
Subprocess-based ADB Connection.
Required for Android 11+ wireless debugging that uses TLS.
Adapted from v3 with improvements: inherits from BaseADBConnection, uses centralized config.
"""

import logging
import subprocess
from typing import Tuple

from .base_connection import BaseADBConnection
from .config import config

_LOGGER = logging.getLogger(__name__)


class SubprocessADBConnection(BaseADBConnection):
    """Manage ADB connection using subprocess (for TLS wireless debugging).

    This connection type is required for:
    - Android 11+ wireless debugging with TLS
    - High-port connections (e.g., 45441)
    - Any scenario where Python adb-shell library doesn't support the protocol
    """

    def __init__(self, hass, device_id: str):
        """Initialize subprocess ADB connection.

        Args:
            hass: Home Assistant instance or None for standalone mode
            device_id: Device identifier (e.g., "192.168.1.2:45441")
        """
        super().__init__(hass, device_id)

    async def connect(self) -> bool:
        """Test ADB connection to device.

        Connection sequence:
        1. Check if device is already connected
        2. If not, run adb connect {device_id}
        3. Verify device appears in adb devices

        Returns:
            True if connected successfully, False otherwise
        """
        try:
            _LOGGER.info(f"Testing subprocess ADB connection to {self.device_id}...")

            # Check if device is already connected
            def _check_devices():
                result = subprocess.run(
                    ["adb", "devices"], capture_output=True, text=True, timeout=5
                )
                return result.returncode == 0, result.stdout

            success, output = await self._run_in_executor(_check_devices)

            if success and self.device_id in output:
                _LOGGER.info(f"✅ Device {self.device_id} already connected")
                self._connected = True
                return True

            # Try connecting
            _LOGGER.info(f"Connecting to {self.device_id}...")

            def _connect():
                result = subprocess.run(
                    ["adb", "connect", self.device_id],
                    capture_output=True,
                    text=True,
                    timeout=config.CONNECTION_TIMEOUT,
                )
                return result.returncode == 0, result.stdout

            success, output = await self._run_in_executor(_connect)

            # Check for success indicators
            if success and (
                "connected" in output.lower() or "already connected" in output.lower()
            ):
                _LOGGER.info(f"✅ Connected to {self.device_id}")
                self._connected = True
                return True
            else:
                _LOGGER.error(f"Connection failed: {output}")
                return False

        except FileNotFoundError:
            _LOGGER.error(
                "ADB binary not found. Install android-tools to use subprocess ADB."
            )
            return False
        except subprocess.TimeoutExpired:
            _LOGGER.error(f"Connection timeout after {config.CONNECTION_TIMEOUT}s")
            return False
        except Exception as e:
            _LOGGER.error(f"ADB connection error: {e}")
            return False

    async def shell(self, command: str):
        """Execute shell command on device.

        Args:
            command: Shell command to execute

        Returns:
            Command output as bytes or string (str for text commands, bytes for binary like screencap)

        Raises:
            ConnectionError: If not connected to device
        """
        if not self._connected:
            raise ConnectionError(f"Not connected to device {self.device_id}")

        try:
            _LOGGER.debug(f"Executing: adb -s {self.device_id} shell {command}")

            def _run_shell():
                result = subprocess.run(
                    ["adb", "-s", self.device_id, "shell", command],
                    capture_output=True,
                    timeout=config.SHELL_TIMEOUT,
                )
                return result.stdout

            response = await self._run_in_executor(_run_shell)

            # For screencap -p, return raw bytes (PNG data)
            if command.startswith("screencap") and "-p" in command:
                return response if response else b""

            # For other commands, decode as UTF-8 text
            try:
                return response.decode("utf-8").strip() if response else ""
            except UnicodeDecodeError:
                # If decoding fails, return as bytes
                return response

        except subprocess.TimeoutExpired:
            _LOGGER.error(f"Shell command timeout after {config.SHELL_TIMEOUT}s")
            raise TimeoutError(f"Command timeout: {command}")
        except Exception as e:
            _LOGGER.error(f"Shell command failed: {e}")
            raise

    async def pull(self, remote_path: str, local_path: str) -> bool:
        """Pull file from device.

        Args:
            remote_path: Path on device
            local_path: Local path to save file

        Returns:
            True if successful, False otherwise

        Raises:
            ConnectionError: If not connected to device
        """
        if not self._connected:
            raise ConnectionError(f"Not connected to device {self.device_id}")

        try:
            _LOGGER.debug(f"Pulling {remote_path} to {local_path}")

            def _pull():
                result = subprocess.run(
                    ["adb", "-s", self.device_id, "pull", remote_path, local_path],
                    capture_output=True,
                    text=True,
                    timeout=config.PULL_TIMEOUT,
                )
                return result.returncode == 0

            success = await self._run_in_executor(_pull)

            if success:
                _LOGGER.debug("✅ File pulled successfully")
                return True
            else:
                _LOGGER.error("Pull failed")
                return False

        except subprocess.TimeoutExpired:
            _LOGGER.error(f"Pull timeout after {config.PULL_TIMEOUT}s")
            return False
        except Exception as e:
            _LOGGER.error(f"Pull failed: {e}")
            return False

    async def push(self, local_path: str, remote_path: str) -> bool:
        """Push file to device.

        Args:
            local_path: Local file path
            remote_path: Path on device

        Returns:
            True if successful, False otherwise

        Raises:
            ConnectionError: If not connected to device
        """
        if not self._connected:
            raise ConnectionError(f"Not connected to device {self.device_id}")

        try:
            _LOGGER.debug(f"Pushing {local_path} to {remote_path}")

            def _push():
                result = subprocess.run(
                    ["adb", "-s", self.device_id, "push", local_path, remote_path],
                    capture_output=True,
                    text=True,
                    timeout=config.PUSH_TIMEOUT,
                )
                return result.returncode == 0

            success = await self._run_in_executor(_push)

            if success:
                _LOGGER.debug("✅ File pushed successfully")
                return True
            else:
                _LOGGER.error("Push failed")
                return False

        except subprocess.TimeoutExpired:
            _LOGGER.error(f"Push timeout after {config.PUSH_TIMEOUT}s")
            return False
        except Exception as e:
            _LOGGER.error(f"Push failed: {e}")
            return False

    async def close(self):
        """Close ADB connection (disconnect from device)."""
        if not self._connected:
            return

        try:
            _LOGGER.info(f"Disconnecting from {self.device_id}...")

            def _disconnect():
                subprocess.run(
                    ["adb", "disconnect", self.device_id],
                    capture_output=True,
                    timeout=5,
                )

            await self._run_in_executor(_disconnect)
            _LOGGER.info(f"Disconnected from {self.device_id}")

        except Exception as e:
            _LOGGER.debug(f"Error disconnecting: {e}")
        finally:
            self._connected = False
