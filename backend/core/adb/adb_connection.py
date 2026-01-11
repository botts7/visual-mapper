"""
Pure Python ADB Connection Manager.
Uses adb-shell library - no binary dependencies required.
Adapted from v3 with improvements: inherits from BaseADBConnection, uses centralized config.
"""

import asyncio
import logging
import os
import subprocess
from typing import Optional

from adb_shell.adb_device_async import AdbDeviceTcpAsync
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
from adb_shell.auth.keygen import keygen

from .base_connection import BaseADBConnection
from .config import config

_LOGGER = logging.getLogger(__name__)


class PythonADBConnection(BaseADBConnection):
    """Manage ADB connection using pure Python implementation.

    Supports:
    - TCP/IP connections on port 5555 (legacy, non-TLS)
    - Wireless pairing for Android 11+ (uses subprocess for pairing)
    - RSA key generation and management
    - TLS connection attempts with fallback
    """

    def __init__(self, hass, host: str, port: int = 5555):
        """Initialize ADB connection.

        Args:
            hass: Home Assistant instance or None for standalone mode
            host: Device IP address
            port: ADB port (default 5555)
        """
        super().__init__(hass, f"{host}:{port}")
        self.host = host
        self.port = port
        self._device: Optional[AdbDeviceTcpAsync] = None
        self._lock = asyncio.Lock()
        self._signer: Optional[PythonRSASigner] = None

    async def _setup_keys(self) -> PythonRSASigner:
        """Generate and load ADB authentication keys.

        Returns:
            PythonRSASigner instance with loaded keys

        Raises:
            Exception: If key generation or loading fails
        """
        # Use config for key directory
        adb_dir = os.path.expanduser(config.ADB_KEY_DIR)

        if hasattr(self.hass, "config"):
            # Home Assistant integration mode
            adbkey_path = self.hass.config.path(".storage", "visual_mapper_adbkey")
        else:
            # Standalone addon mode - use standard location
            os.makedirs(adb_dir, exist_ok=True)
            adbkey_path = os.path.join(adb_dir, config.ADB_KEY_NAME)

        # Generate new keys if they don't exist
        if not os.path.isfile(adbkey_path):
            _LOGGER.info("Generating new ADB authentication keys...")
            await self._run_in_executor(keygen, adbkey_path)
            _LOGGER.info(f"✅ Keys generated at: {adbkey_path}")

        # Load private and public keys asynchronously
        try:

            def _read_keys():
                with open(adbkey_path) as f:
                    priv = f.read()
                with open(adbkey_path + ".pub") as f:
                    pub = f.read()
                return priv, pub

            priv, pub = await self._run_in_executor(_read_keys)
            signer = PythonRSASigner(pub, priv)
            _LOGGER.debug("ADB keys loaded successfully")
            return signer

        except Exception as e:
            _LOGGER.error(f"Failed to load ADB keys: {e}")
            raise

    async def pair_with_code(
        self, pairing_host: str, pairing_port: int, pairing_code: str
    ) -> bool:
        """Pair with device using pairing code (for wireless ADB).

        This uses system ADB binary for pairing since adb-shell doesn't support it.

        Args:
            pairing_host: Device IP for pairing
            pairing_port: Pairing port (shown on device, e.g., 40543)
            pairing_code: 6-digit pairing code (shown on device)

        Returns:
            True if pairing successful, False otherwise
        """
        try:
            _LOGGER.info(f"Attempting to pair with {pairing_host}:{pairing_port}...")

            # Try to find system ADB binary
            def _check_adb(path):
                """Check if ADB binary exists at path."""
                try:
                    result = subprocess.run(
                        [path, "version"], capture_output=True, timeout=2, text=True
                    )
                    return result.returncode == 0
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    return False

            adb_binary = None
            for path in ["/usr/bin/adb", "/usr/local/bin/adb", "adb"]:
                try:
                    if await self._run_in_executor(_check_adb, path):
                        adb_binary = path
                        _LOGGER.debug(f"Found ADB binary at: {path}")
                        break
                except Exception as e:
                    _LOGGER.debug(f"Error checking ADB at {path}: {e}")
                    continue

            if not adb_binary:
                _LOGGER.error("System ADB not found. Cannot perform wireless pairing.")
                _LOGGER.error("Install ADB binary to enable wireless pairing support.")
                return False

            # Run pairing command with code as input
            def _run_pair():
                proc = subprocess.Popen(
                    [adb_binary, "pair", f"{pairing_host}:{pairing_port}"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                output, _ = proc.communicate(
                    input=f"{pairing_code}\n", timeout=config.PAIRING_TIMEOUT
                )
                return proc.returncode, output

            returncode, output = await self._run_in_executor(_run_pair)

            _LOGGER.debug(f"Pairing output: {output}")

            # Check for success indicators
            if returncode == 0 and (
                "Successfully paired" in output or "success" in output.lower()
            ):
                _LOGGER.info(f"✅ Successfully paired with {pairing_host}")
                return True
            else:
                _LOGGER.error(f"Pairing failed: {output}")
                return False

        except subprocess.TimeoutExpired:
            _LOGGER.error(f"Pairing timeout after {config.PAIRING_TIMEOUT}s")
            return False
        except Exception as e:
            _LOGGER.error(f"Pairing error: {e}")
            return False

    async def connect(self) -> bool:
        """Establish ADB connection to device.

        Attempts TLS connection first (for Android 11+ wireless),
        falls back to non-TLS if that fails.

        Returns:
            True if connected successfully, False otherwise
        """
        async with self._lock:
            try:
                # Setup authentication
                if not self._signer:
                    self._signer = await self._setup_keys()

                # Create device instance
                _LOGGER.info(f"Connecting to {self.host}:{self.port} via Python ADB...")
                self._device = AdbDeviceTcpAsync(
                    host=self.host,
                    port=self.port,
                    default_transport_timeout_s=config.TRANSPORT_TIMEOUT,
                )

                # Try connecting with TLS first (for Android 11+ wireless debugging)
                try:
                    _LOGGER.debug("Attempting TLS connection...")
                    await self._device.connect(
                        rsa_keys=[self._signer],
                        auth_timeout_s=config.AUTH_TIMEOUT,
                        transport_timeout_s=config.TRANSPORT_TIMEOUT,
                    )
                    _LOGGER.debug("✅ TLS connection established")
                except Exception as tls_error:
                    # If TLS fails, try without TLS (legacy connection)
                    _LOGGER.debug(f"TLS connection failed: {tls_error}")
                    _LOGGER.debug("Retrying with non-TLS connection...")

                    await self._device.close()
                    self._device = AdbDeviceTcpAsync(
                        host=self.host,
                        port=self.port,
                        default_transport_timeout_s=config.TRANSPORT_TIMEOUT,
                    )
                    await self._device.connect(
                        rsa_keys=[self._signer], auth_timeout_s=config.AUTH_TIMEOUT
                    )
                    _LOGGER.debug("✅ Non-TLS connection established")

                if self._device.available:
                    _LOGGER.info(f"✅ Connected to {self.host}:{self.port}")
                    self._connected = True
                    return True
                else:
                    _LOGGER.error(f"Failed to connect to {self.host}:{self.port}")
                    return False

            except ConnectionRefusedError:
                _LOGGER.error(f"Connection refused by {self.host}:{self.port}")
                return False
            except TimeoutError:
                _LOGGER.error(f"Connection timeout to {self.host}:{self.port}")
                return False
            except Exception as e:
                _LOGGER.error(f"ADB connection error: {e}")
                return False

    async def shell(self, command: str) -> str:
        """Execute shell command on device.

        Args:
            command: Shell command to execute

        Returns:
            Command output as string

        Raises:
            ConnectionError: If not connected to device
        """
        if not self._device or not self._device.available:
            raise ConnectionError(f"Not connected to device {self.device_id}")

        async with self._lock:
            try:
                _LOGGER.debug(f"Executing: {command}")
                response = await self._device.shell(command)
                return response.strip() if response else ""
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
        if not self._device or not self._device.available:
            raise ConnectionError(f"Not connected to device {self.device_id}")

        async with self._lock:
            try:
                _LOGGER.debug(f"Pulling {remote_path} to {local_path}")
                await self._device.pull(remote_path, local_path)
                _LOGGER.debug(f"✅ File pulled successfully")
                return True
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
        if not self._device or not self._device.available:
            raise ConnectionError(f"Not connected to device {self.device_id}")

        async with self._lock:
            try:
                _LOGGER.debug(f"Pushing {local_path} to {remote_path}")
                await self._device.push(local_path, remote_path)
                _LOGGER.debug(f"✅ File pushed successfully")
                return True
            except Exception as e:
                _LOGGER.error(f"Push failed: {e}")
                return False

    async def close(self):
        """Close ADB connection."""
        if self._device:
            try:
                await self._device.close()
                _LOGGER.info(f"Disconnected from {self.host}:{self.port}")
            except Exception as e:
                _LOGGER.debug(f"Error closing connection: {e}")
            finally:
                self._device = None
                self._connected = False

    @property
    def available(self) -> bool:
        """Check if connection is available.

        Returns:
            True if connected, False otherwise
        """
        return self._device is not None and self._device.available
