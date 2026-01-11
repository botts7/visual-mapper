"""
Network ADB Bridge.
Connects to ADB server running on network (e.g., Windows PC or ADB Server addon).
This allows HA container to use ADB via network without installing it locally.
Adapted from v3 with improvements: inherits from BaseADBConnection, uses centralized config.
"""

import asyncio
import logging
import socket
import subprocess
from typing import Tuple

from .base_connection import BaseADBConnection
from .config import config

_LOGGER = logging.getLogger(__name__)


class NetworkADBConnection(BaseADBConnection):
    """Connect to remote ADB server via network.

    This connection type is best when:
    - ADB Server addon is installed and running
    - ADB server is available on localhost:5037
    - Want to leverage existing ADB infrastructure
    """

    def __init__(
        self, hass, device_id: str, adb_host: str = None, adb_port: int = None
    ):
        """Initialize network ADB connection.

        Args:
            hass: Home Assistant instance or None for standalone mode
            device_id: Device identifier (e.g., "192.168.1.2:45441")
            adb_host: ADB server hostname/IP (default from config: 127.0.0.1)
            adb_port: ADB server port (default from config: 5037)
        """
        super().__init__(hass, device_id)
        self.adb_host = adb_host or config.ADB_SERVER_HOST
        self.adb_port = adb_port or config.ADB_SERVER_PORT

    async def _verify_adb_server(self) -> Tuple[bool, str]:
        """Verify ADB server is running and accessible.

        Returns:
            Tuple of (success: bool, error_message: str)
        """

        # Step 1: Check if ADB binary exists
        def _check_adb_binary():
            try:
                result = subprocess.run(
                    ["which", "adb"], capture_output=True, text=True, timeout=5
                )
                return result.returncode == 0, result.stdout.strip()
            except Exception as e:
                return False, str(e)

        has_adb, adb_path = await self._run_in_executor(_check_adb_binary)
        if not has_adb:
            return False, "ADB binary not found"

        _LOGGER.info(f"✅ ADB binary found: {adb_path}")

        # Step 2: Check if ADB server port is open
        def _test_port():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex((self.adb_host, self.adb_port))
                sock.close()
                return result == 0
            except Exception as e:
                _LOGGER.debug(f"Port test failed: {e}")
                return False

        port_open = await self._run_in_executor(_test_port)
        if not port_open:
            return False, f"ADB server not running on {self.adb_host}:{self.adb_port}"

        _LOGGER.info(f"✅ ADB server port {self.adb_port} is open")
        return True, ""

    async def connect(self) -> bool:
        """Connect to ADB server and device with retry logic.

        Connection sequence:
        1. Verify ADB server is running
        2. Run adb connect {device_id}
        3. Wait for connection to establish
        4. Verify device appears in adb devices
        5. Retry if failed (up to MAX_RETRIES)

        Returns:
            True if connected successfully, False otherwise
        """
        _LOGGER.info(
            f"Connecting to device {self.device_id} via ADB server at {self.adb_host}:{self.adb_port}"
        )

        # Step 1: Verify ADB server is running
        server_ok, server_error = await self._verify_adb_server()
        if not server_ok:
            _LOGGER.error(f"ADB server check failed: {server_error}")
            return False

        # Step 2-5: Try to connect with retries
        last_error = ""
        for attempt in range(1, config.MAX_RETRIES + 1):
            _LOGGER.info(f"Connection attempt {attempt}/{config.MAX_RETRIES}")

            try:
                # Run adb connect
                connect_success, connect_output = await self._run_adb_connect()

                if not connect_success:
                    last_error = connect_output
                    _LOGGER.warning(f"adb connect failed: {connect_output}")
                    if attempt < config.MAX_RETRIES:
                        _LOGGER.info(f"Retrying in {config.RETRY_DELAY} seconds...")
                        await asyncio.sleep(config.RETRY_DELAY)
                        continue
                    else:
                        break

                # Wait for connection to establish
                _LOGGER.info(
                    f"Waiting {config.RETRY_DELAY}s for connection to establish..."
                )
                await asyncio.sleep(config.RETRY_DELAY)

                # Verify device is in the list
                devices = await self._send_adb_command("host:devices")
                _LOGGER.info(f"ADB devices: {devices}")

                # Check for device status
                if self.device_id in devices:
                    # Check if device is online (not offline)
                    if f"{self.device_id}\toffline" in devices:
                        last_error = "Device connected but offline"
                        _LOGGER.warning(last_error)
                        if attempt < config.MAX_RETRIES:
                            await asyncio.sleep(config.RETRY_DELAY)
                            continue
                    else:
                        _LOGGER.info(
                            f"✅ Device {self.device_id} connected and online!"
                        )
                        self._connected = True
                        return True
                else:
                    last_error = f"Device {self.device_id} not found in devices list"
                    _LOGGER.warning(last_error)
                    if attempt < config.MAX_RETRIES:
                        await asyncio.sleep(config.RETRY_DELAY)
                        continue

            except Exception as e:
                last_error = str(e)
                _LOGGER.error(f"Connection attempt failed: {e}")
                if attempt < config.MAX_RETRIES:
                    await asyncio.sleep(config.RETRY_DELAY)
                    continue

        _LOGGER.error(
            f"Failed to connect after {config.MAX_RETRIES} attempts. Last error: {last_error}"
        )
        return False

    async def _run_adb_connect(self) -> Tuple[bool, str]:
        """Run adb connect command.

        Returns:
            Tuple of (success: bool, output_message: str)
        """

        def _connect():
            try:
                result = subprocess.run(
                    ["adb", "connect", self.device_id],
                    capture_output=True,
                    text=True,
                    timeout=config.CONNECTION_TIMEOUT,
                )
                output = result.stdout + result.stderr
                output = output.strip()

                # Check various success conditions
                if "connected to" in output.lower():
                    return True, output
                elif "already connected" in output.lower():
                    return True, output
                elif "failed" in output.lower():
                    return False, output
                elif "refused" in output.lower():
                    return False, f"Connection refused: {output}"
                elif "unable to connect" in output.lower():
                    return False, output
                else:
                    # Ambiguous - check return code
                    return result.returncode == 0, output
            except subprocess.TimeoutExpired:
                return False, "Connection timeout"
            except Exception as e:
                return False, str(e)

        return await self._run_in_executor(_connect)

    async def _send_adb_command(self, command: str) -> str:
        """Send command to ADB server.

        Args:
            command: ADB protocol command

        Returns:
            Response from ADB server
        """

        def _send():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((self.adb_host, self.adb_port))

            # Send command length + command
            msg = f"{len(command):04x}{command}".encode()
            sock.sendall(msg)

            # Read response status
            status = sock.recv(4).decode()
            if status != "OKAY":
                error = sock.recv(1024).decode()
                sock.close()
                raise Exception(f"ADB command failed: {error}")

            # Read response data
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk

            sock.close()
            return response.decode()

        return await self._run_in_executor(_send)

    async def shell(self, command: str) -> str:
        """Execute shell command on device via ADB server.

        Args:
            command: Shell command to execute

        Returns:
            Command output as string

        Raises:
            ConnectionError: If not connected to device
        """
        if not self._connected:
            raise ConnectionError(f"Not connected to device {self.device_id}")

        try:
            _LOGGER.debug(f"Executing: {command}")

            def _shell():
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(30)
                sock.connect((self.adb_host, self.adb_port))

                # Switch to device transport
                transport_cmd = f"host:transport:{self.device_id}"
                msg = f"{len(transport_cmd):04x}{transport_cmd}".encode()
                sock.sendall(msg)

                status = sock.recv(4).decode()
                if status != "OKAY":
                    error = sock.recv(1024).decode()
                    sock.close()
                    raise Exception(f"Transport failed: {error}")

                # Send shell command
                shell_cmd = f"shell:{command}"
                msg = f"{len(shell_cmd):04x}{shell_cmd}".encode()
                sock.sendall(msg)

                status = sock.recv(4).decode()
                if status != "OKAY":
                    error = sock.recv(1024).decode()
                    sock.close()
                    raise Exception(f"Shell command failed: {error}")

                # Read response
                response = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk

                sock.close()
                return response

            result = await self._run_in_executor(_shell)

            # For screencap -p, return raw bytes (PNG data)
            if command.startswith("screencap") and "-p" in command:
                return result if result else b""

            # For other commands, decode as UTF-8 text
            try:
                return result.decode("utf-8").strip() if result else ""
            except UnicodeDecodeError:
                # If decoding fails, return as bytes
                return result

        except Exception as e:
            _LOGGER.error(f"Shell command failed: {e}")
            raise

    async def pull(self, remote_path: str, local_path: str) -> bool:
        """Pull file from device using subprocess adb pull.

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
                return result.returncode == 0, result.stdout + result.stderr

            success, output = await self._run_in_executor(_pull)

            if success:
                _LOGGER.debug("✅ File pulled successfully")
                return True
            else:
                _LOGGER.error(f"Pull failed: {output}")
                return False

        except Exception as e:
            _LOGGER.error(f"File pull failed: {e}")
            return False

    async def push(self, local_path: str, remote_path: str) -> bool:
        """Push file to device using subprocess adb push.

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
                return result.returncode == 0, result.stdout + result.stderr

            success, output = await self._run_in_executor(_push)

            if success:
                _LOGGER.debug("✅ File pushed successfully")
                return True
            else:
                _LOGGER.error(f"Push failed: {output}")
                return False

        except Exception as e:
            _LOGGER.error(f"File push failed: {e}")
            return False

    async def close(self):
        """Close ADB connection."""
        self._connected = False
        _LOGGER.info(f"Disconnected from ADB server")
