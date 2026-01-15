"""
Visual Mapper - Default Configuration Constants

Centralized configuration for the entire application.
Values can be overridden via environment variables.

Usage:
    from config.defaults import Defaults
    timeout = Defaults.API_TIMEOUT
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AppDefaults:
    """Application-wide default configuration."""

    # ==========================================================================
    # Server Settings
    # ==========================================================================
    SERVER_PORT: int = 8082
    SERVER_HOST: str = "0.0.0.0"

    # ==========================================================================
    # MQTT Settings
    # ==========================================================================
    MQTT_BROKER: str = "localhost"
    MQTT_PORT: int = 1883
    MQTT_DISCOVERY_PREFIX: str = "homeassistant"
    MQTT_KEEPALIVE: int = 60
    MQTT_QOS: int = 0  # Quality of Service level

    # ==========================================================================
    # API Timeouts (seconds)
    # ==========================================================================
    API_TIMEOUT: int = 30
    SCREENSHOT_TIMEOUT: int = 15
    ELEMENT_DUMP_TIMEOUT: int = 10
    STREAMING_TIMEOUT: int = 5

    # ==========================================================================
    # Sensor Settings
    # ==========================================================================
    SENSOR_UPDATE_INTERVAL: int = 30  # Default sensor update interval (seconds)
    SENSOR_MIN_INTERVAL: int = 5  # Minimum allowed interval
    SENSOR_MAX_INTERVAL: int = 3600  # Maximum allowed interval (1 hour)

    # ==========================================================================
    # Flow Settings
    # ==========================================================================
    FLOW_EXECUTION_TIMEOUT: int = 300  # 5 minutes max flow execution
    FLOW_STEP_TIMEOUT: int = 30  # Per-step timeout
    FLOW_RETRY_DELAY: int = 2  # Delay between retries

    # ==========================================================================
    # Connection Monitor Settings
    # ==========================================================================
    CONNECTION_CHECK_INTERVAL: int = 30  # Device health check interval
    CONNECTION_RETRY_DELAY: int = 10  # Initial retry delay
    CONNECTION_MAX_RETRY_DELAY: int = 300  # Maximum retry delay (5 minutes)

    # ==========================================================================
    # Streaming Settings
    # ==========================================================================
    STREAM_FPS_HIGH: int = 5
    STREAM_FPS_MEDIUM: int = 12
    STREAM_FPS_LOW: int = 18
    STREAM_FPS_FAST: int = 25
    STREAM_FPS_ULTRAFAST: int = 30

    # ==========================================================================
    # Icon/Asset Settings
    # ==========================================================================
    ICON_CACHE_MAX_AGE: int = 86400 * 7  # 7 days
    ICON_FETCH_TIMEOUT: int = 10
    ICON_QUEUE_MAX_SIZE: int = 100

    # ==========================================================================
    # ML Training Settings
    # ==========================================================================
    ML_BATCH_SIZE: int = 64
    ML_SAVE_INTERVAL: int = 60  # seconds

    @classmethod
    def from_env(cls) -> "AppDefaults":
        """Create config from environment variables with defaults."""
        return cls(
            SERVER_PORT=int(os.getenv("SERVER_PORT", cls.SERVER_PORT)),
            MQTT_BROKER=os.getenv("MQTT_BROKER", cls.MQTT_BROKER),
            MQTT_PORT=int(os.getenv("MQTT_PORT", cls.MQTT_PORT)),
            MQTT_DISCOVERY_PREFIX=os.getenv("MQTT_DISCOVERY_PREFIX", cls.MQTT_DISCOVERY_PREFIX),
            SENSOR_UPDATE_INTERVAL=int(os.getenv("SENSOR_UPDATE_INTERVAL", cls.SENSOR_UPDATE_INTERVAL)),
            CONNECTION_CHECK_INTERVAL=int(os.getenv("CONNECTION_CHECK_INTERVAL", cls.CONNECTION_CHECK_INTERVAL)),
        )


# Global defaults instance - can be overridden at runtime
Defaults = AppDefaults()


def load_defaults_from_env():
    """Reload defaults from environment variables."""
    global Defaults
    Defaults = AppDefaults.from_env()
