"""
ADB Connection Configuration.
Centralized configuration for all ADB connection types.
"""
from dataclasses import dataclass


@dataclass
class ADBConfig:
    """Configuration for ADB connections."""

    # Retry settings
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 2  # seconds
    CONNECTION_TIMEOUT: int = 10  # seconds

    # ADB server settings
    ADB_SERVER_HOST: str = "127.0.0.1"
    ADB_SERVER_PORT: int = 5037

    # Default ports
    DEFAULT_ADB_PORT: int = 5555

    # Key locations
    ADB_KEY_DIR: str = "~/.android"
    ADB_KEY_NAME: str = "adbkey"

    # Timeouts
    SHELL_TIMEOUT: int = 30  # seconds
    AUTH_TIMEOUT: float = 10.0  # seconds
    TRANSPORT_TIMEOUT: float = 9.0  # seconds
    PAIRING_TIMEOUT: int = 10  # seconds

    # File transfer
    PULL_TIMEOUT: int = 30  # seconds
    PUSH_TIMEOUT: int = 30  # seconds


# Global configuration instance
config = ADBConfig()
