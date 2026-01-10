"""
Device Security Manager

Handles lock screen configuration and encrypted passcode storage for Android devices.

Security Features:
- Per-device encryption keys derived from stable_device_id
- PBKDF2 (100,000 iterations) + Fernet cipher
- Keys never stored on disk (regenerated from device ID each time)
- Passcodes encrypted at rest in JSON files
- File permissions: 600 (owner read/write only)

Lock Strategies:
1. NO_LOCK - No lock screen (convenience)
2. SMART_LOCK - Android Trusted Places (recommended)
3. AUTO_UNLOCK - Store encrypted passcode (moderate security)
4. MANUAL_ONLY - User unlocks manually (most secure)
"""

import json
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


class LockStrategy(str, Enum):
    """Lock screen strategies for device security"""

    NO_LOCK = "no_lock"  # No lock screen
    SMART_LOCK = "smart_lock"  # Android Trusted Places (recommended)
    AUTO_UNLOCK = "auto_unlock"  # Encrypted passcode stored
    MANUAL_ONLY = "manual_only"  # User unlocks manually


class DeviceSecurityManager:
    """Manages device lock screen configuration and encrypted passcode storage"""

    def __init__(self, data_dir: str = "data"):
        """
        Initialize security manager.

        Args:
            data_dir: Base directory for data storage
        """
        self.data_dir = Path(data_dir)
        self.security_dir = self.data_dir / "security"
        self.security_dir.mkdir(parents=True, exist_ok=True)

        # Set restrictive permissions on security directory (Unix-like systems)
        if hasattr(os, "chmod"):
            try:
                os.chmod(self.security_dir, 0o700)  # Owner read/write/execute only
            except Exception as e:
                logger.warning(f"Could not set directory permissions: {e}")

        # Static salt for key derivation (in production, should be per-installation)
        # This is combined with device_id for per-device encryption keys
        self.salt = b"visual_mapper_device_security_v1"

    def _derive_encryption_key(self, device_id: str) -> bytes:
        """
        Derive encryption key from device ID using PBKDF2.

        Args:
            device_id: Device identifier (stable_device_id)

        Returns:
            32-byte encryption key
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.salt,
            iterations=100000,  # OWASP recommendation
        )
        key = kdf.derive(device_id.encode("utf-8"))
        return key

    def _get_fernet(self, device_id: str) -> Fernet:
        """
        Get Fernet cipher for device.

        Args:
            device_id: Device identifier

        Returns:
            Fernet cipher instance
        """
        key = self._derive_encryption_key(device_id)
        # Fernet requires base64-encoded key
        import base64

        b64_key = base64.urlsafe_b64encode(key)
        return Fernet(b64_key)

    def encrypt_passcode(self, device_id: str, passcode: str) -> str:
        """
        Encrypt passcode for device.

        Args:
            device_id: Device identifier
            passcode: Plain text passcode

        Returns:
            Base64-encoded encrypted passcode
        """
        try:
            fernet = self._get_fernet(device_id)
            encrypted = fernet.encrypt(passcode.encode("utf-8"))
            return encrypted.decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to encrypt passcode for {device_id}: {e}")
            raise

    def decrypt_passcode(self, device_id: str, encrypted_passcode: str) -> str:
        """
        Decrypt passcode for device.

        Args:
            device_id: Device identifier
            encrypted_passcode: Base64-encoded encrypted passcode

        Returns:
            Plain text passcode
        """
        try:
            fernet = self._get_fernet(device_id)
            decrypted = fernet.decrypt(encrypted_passcode.encode("utf-8"))
            return decrypted.decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to decrypt passcode for {device_id}: {e}")
            raise

    def _get_config_path(self, device_id: str) -> Path:
        """
        Get path to device security config file.

        Args:
            device_id: Device identifier

        Returns:
            Path to config file
        """
        # Sanitize device_id for filename (replace colons with underscores)
        safe_id = device_id.replace(":", "_").replace("/", "_")
        return self.security_dir / f"{safe_id}_security.json"

    def save_lock_config(
        self,
        device_id: str,
        strategy: LockStrategy,
        passcode: Optional[str] = None,
        notes: Optional[str] = None,
        sleep_grace_period: int = 300,
    ) -> bool:
        """
        Save lock screen configuration for device.

        Args:
            device_id: Device identifier
            strategy: Lock strategy to use
            passcode: Passcode (required for AUTO_UNLOCK strategy)
            notes: Optional notes about configuration
            sleep_grace_period: Seconds to wait before sleeping if another flow is due (default 300 = 5 min)

        Returns:
            True if saved successfully

        Raises:
            ValueError: If AUTO_UNLOCK strategy without passcode
        """
        if strategy == LockStrategy.AUTO_UNLOCK and not passcode:
            raise ValueError("AUTO_UNLOCK strategy requires passcode")

        config = {
            "device_id": device_id,
            "strategy": strategy.value,
            "notes": notes or "",
            "sleep_grace_period": sleep_grace_period,
        }

        # Encrypt passcode if provided
        if passcode:
            try:
                config["encrypted_passcode"] = self.encrypt_passcode(device_id, passcode)
            except Exception as e:
                logger.error(f"Failed to encrypt passcode: {e}")
                return False

        # Save to JSON file
        config_path = self._get_config_path(device_id)
        try:
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)

            # Set restrictive permissions (Unix-like systems)
            if hasattr(os, "chmod"):
                try:
                    os.chmod(config_path, 0o600)  # Owner read/write only
                except Exception as e:
                    logger.warning(f"Could not set file permissions: {e}")

            logger.info(
                f"Saved lock configuration for {device_id}: strategy={strategy.value}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to save lock configuration for {device_id}: {e}")
            return False

    def get_lock_config(self, device_id: str) -> Optional[Dict]:
        """
        Get lock screen configuration for device.

        Args:
            device_id: Device identifier

        Returns:
            Config dict with keys:
                - device_id: str
                - strategy: str (LockStrategy value)
                - notes: str
                - has_passcode: bool
                - sleep_grace_period: int (seconds, default 300)
            Returns None if no config exists
        """
        config_path = self._get_config_path(device_id)

        if not config_path.exists():
            return None

        try:
            with open(config_path, "r") as f:
                config = json.load(f)

            # Return sanitized config (don't expose encrypted passcode)
            return {
                "device_id": config.get("device_id", device_id),
                "strategy": config.get("strategy", LockStrategy.MANUAL_ONLY.value),
                "notes": config.get("notes", ""),
                "has_passcode": "encrypted_passcode" in config,
                "sleep_grace_period": config.get("sleep_grace_period", 300),
            }

        except Exception as e:
            logger.error(f"Failed to load lock configuration for {device_id}: {e}")
            return None

    def get_passcode(self, device_id: str) -> Optional[str]:
        """
        Get decrypted passcode for device.

        Args:
            device_id: Device identifier

        Returns:
            Decrypted passcode, or None if not available

        Security Note:
            Passcode is only returned if strategy is AUTO_UNLOCK.
            Caller is responsible for clearing passcode from memory after use.
        """
        config_path = self._get_config_path(device_id)

        if not config_path.exists():
            return None

        try:
            with open(config_path, "r") as f:
                config = json.load(f)

            # Only return passcode if AUTO_UNLOCK strategy
            if config.get("strategy") != LockStrategy.AUTO_UNLOCK.value:
                return None

            encrypted = config.get("encrypted_passcode")
            if not encrypted:
                return None

            # Decrypt and return
            return self.decrypt_passcode(device_id, encrypted)

        except Exception as e:
            logger.error(f"Failed to get passcode for {device_id}: {e}")
            return None

    def delete_lock_config(self, device_id: str) -> bool:
        """
        Delete lock screen configuration for device.

        Args:
            device_id: Device identifier

        Returns:
            True if deleted successfully or file didn't exist
        """
        config_path = self._get_config_path(device_id)

        if not config_path.exists():
            return True

        try:
            config_path.unlink()
            logger.info(f"Deleted lock configuration for {device_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete lock configuration for {device_id}: {e}")
            return False

    def list_configured_devices(self) -> list[str]:
        """
        List all devices with lock configurations.

        Returns:
            List of device IDs
        """
        devices = []
        try:
            for config_file in self.security_dir.glob("*_security.json"):
                try:
                    with open(config_file, "r") as f:
                        config = json.load(f)
                        device_id = config.get("device_id")
                        if device_id:
                            devices.append(device_id)
                except Exception as e:
                    logger.warning(f"Could not read config file {config_file}: {e}")
        except Exception as e:
            logger.error(f"Failed to list configured devices: {e}")

        return devices
