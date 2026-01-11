"""
Route Dependencies - Centralized dependency injection for route modules

This module provides a dependency injection pattern to avoid circular imports
and make route modules testable. All manager instances are injected at startup.
"""

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    # Type hints only - avoid runtime circular imports
    from core.adb.adb_bridge import ADBBridge
    from utils.device_migrator import DeviceMigrator
    from core.sensors.sensor_manager import SensorManager
    from core.sensors.text_extractor import TextExtractor
    from utils.action_manager import ActionManager
    from utils.action_executor import ActionExecutor
    from core.mqtt.mqtt_manager import MQTTManager
    from core.sensors.sensor_updater import SensorUpdater
    from core.flows import FlowManager, FlowExecutor, FlowScheduler
    from core.performance_monitor import PerformanceMonitor
    from core.screenshot_stitcher import ScreenshotStitcher
    from ml_components.app_icon_extractor import AppIconExtractor
    from ml_components.playstore_icon_scraper import PlayStoreIconScraper
    from ml_components.device_icon_scraper import DeviceIconScraper
    from ml_components.icon_background_fetcher import IconBackgroundFetcher
    from ml_components.app_name_background_fetcher import AppNameBackgroundFetcher
    from core.stream_manager import StreamManager
    from core.adb.adb_helpers import ADBMaintenance
    from core.adb.adb_subprocess import PersistentShellPool
    from utils.connection_monitor import ConnectionMonitor
    from utils.device_security import DeviceSecurityManager
    from core.navigation_manager import NavigationManager


@dataclass
class RouteDependencies:
    """
    Container for all dependencies needed by route modules

    All manager instances are injected here at startup to avoid:
    - Circular imports between modules
    - Global variable access in route handlers
    - Tight coupling between routes and server.py

    Usage in route modules:
        from routes import get_deps

        @router.get("/endpoint")
        async def handler():
            deps = get_deps()
            result = await deps.adb_bridge.some_method()
            return result
    """

    # =========================================================================
    # CORE MANAGERS (Always initialized)
    # =========================================================================
    adb_bridge: "ADBBridge"
    device_migrator: "DeviceMigrator"
    sensor_manager: "SensorManager"
    text_extractor: "TextExtractor"
    action_manager: "ActionManager"
    action_executor: "ActionExecutor"

    # =========================================================================
    # OPTIONAL MANAGERS (Initialized at startup if enabled)
    # =========================================================================
    mqtt_manager: Optional["MQTTManager"] = None
    sensor_updater: Optional["SensorUpdater"] = None
    flow_manager: Optional["FlowManager"] = None
    flow_executor: Optional["FlowExecutor"] = None
    flow_scheduler: Optional["FlowScheduler"] = None
    performance_monitor: Optional["PerformanceMonitor"] = None
    screenshot_stitcher: Optional["ScreenshotStitcher"] = None
    app_icon_extractor: Optional["AppIconExtractor"] = None
    playstore_icon_scraper: Optional["PlayStoreIconScraper"] = None
    device_icon_scraper: Optional["DeviceIconScraper"] = None
    icon_background_fetcher: Optional["IconBackgroundFetcher"] = None
    app_name_background_fetcher: Optional["AppNameBackgroundFetcher"] = None
    stream_manager: Optional["StreamManager"] = None
    adb_maintenance: Optional["ADBMaintenance"] = None
    shell_pool: Optional["PersistentShellPool"] = None
    connection_monitor: Optional["ConnectionMonitor"] = None
    device_security_manager: Optional["DeviceSecurityManager"] = None
    navigation_manager: Optional["NavigationManager"] = None
    feature_manager: Optional[object] = None  # FeatureManager instance
    data_dir: Optional[str] = "data"

    # =========================================================================
    # UTILITIES
    # =========================================================================
    ws_log_handler: Optional[object] = None  # WebSocketLogHandler instance
    element_text_extractor: Optional[object] = None  # ElementTextExtractor instance


# Global dependencies instance (set once at startup)
_deps: Optional[RouteDependencies] = None


def set_dependencies(deps: RouteDependencies) -> None:
    """
    Set global dependencies (called once at server startup)

    Args:
        deps: RouteDependencies instance with all managers initialized

    Example:
        # In server.py startup:
        deps = RouteDependencies(
            adb_bridge=adb_bridge,
            sensor_manager=sensor_manager,
            ...
        )
        set_dependencies(deps)
    """
    global _deps
    _deps = deps


def get_deps() -> RouteDependencies:
    """
    Get dependencies for route handlers

    Returns:
        RouteDependencies instance with all managers

    Raises:
        RuntimeError: If dependencies not initialized (call set_dependencies first)

    Example:
        @router.get("/health")
        async def health_check():
            deps = get_deps()
            mqtt_status = "connected" if deps.mqtt_manager else "disconnected"
            return {"status": "ok", "mqtt_status": mqtt_status}
    """
    if _deps is None:
        raise RuntimeError(
            "Dependencies not initialized. "
            "Call set_dependencies() in server startup before registering routes."
        )
    return _deps


# Export public API
__all__ = [
    "RouteDependencies",
    "set_dependencies",
    "get_deps",
]
