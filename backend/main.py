"""
Visual Mapper - FastAPI Server
Version: 0.0.4 (Phase 3 - Sensor Creation)
"""

import logging
import base64
import time
import os
import io
import asyncio
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError
import uvicorn
from pathlib import Path
from PIL import Image

from utils.version import APP_VERSION
from core.adb.adb_bridge import ADBBridge
from core.sensors.sensor_manager import SensorManager
from core.sensors.sensor_models import SensorDefinition, TextExtractionRule
from core.sensors.text_extractor import TextExtractor, ElementTextExtractor
from core.mqtt.mqtt_manager import MQTTManager
from core.sensors.sensor_updater import SensorUpdater
from core.mqtt.ha_device_classes import (
    validate_unit_for_device_class,
    can_use_state_class,
    get_device_class_info,
    export_to_json as export_device_classes,
)
from utils.action_manager import ActionManager
from utils.action_executor import ActionExecutor
from utils.action_models import (
    ActionCreateRequest,
    ActionUpdateRequest,
    ActionExecutionRequest,
    ActionListResponse,
)
from utils.error_handler import handle_api_error
from utils.device_migrator import DeviceMigrator
from utils.connection_monitor import ConnectionMonitor
from utils.device_security import DeviceSecurityManager

# Phase 8: Flow System
from core.flows import FlowManager, FlowExecutor, FlowScheduler, FlowExecutionHistory
from core.performance_monitor import PerformanceMonitor
from core.screenshot_stitcher import ScreenshotStitcher
from ml_components.app_icon_extractor import AppIconExtractor
from ml_components.playstore_icon_scraper import PlayStoreIconScraper
from ml_components.device_icon_scraper import DeviceIconScraper
from ml_components.icon_background_fetcher import IconBackgroundFetcher
from ml_components.app_name_background_fetcher import AppNameBackgroundFetcher
from core.stream_manager import StreamManager, get_stream_manager
from core.adb.adb_helpers import ADBMaintenance, PersistentShellPool, PersistentADBShell
from core.navigation_manager import NavigationManager
from core.navigation_mqtt_handler import NavigationMqttHandler
from services.feature_manager import get_feature_manager

# Route modules (modular architecture)
from routes import RouteDependencies, set_dependencies
from routes import (
    meta,
    health,
    adb_info,
    cache,
    performance,
    shell,
    maintenance,
    adb_connection,
    adb_control,
    adb_screenshot,
    adb_apps,
    suggestions,
    sensors,
    mqtt,
    actions,
    flows,
    streaming,
    migration,
    device_security,
    device_registration,
    navigation,
    companion,
    services,
    deduplication,
    settings,
    ml,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


# === WebSocket Log Handler for Real-Time Log Viewer ===


class WebSocketLogHandler(logging.Handler):
    """
    Custom logging handler that broadcasts log messages to WebSocket clients.
    Maintains a circular buffer of recent logs for new connections.
    """

    def __init__(self, max_buffer: int = 200):
        super().__init__()
        self.clients: set = set()
        self.log_buffer: list = []
        self.max_buffer = max_buffer
        self._lock = asyncio.Lock()

    def emit(self, record):
        """Handle a log record by broadcasting to all connected clients"""
        try:
            log_entry = {
                "timestamp": (
                    self.formatter.formatTime(record)
                    if self.formatter
                    else record.created
                ),
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
                "module": record.module,
            }

            # Add to buffer (thread-safe)
            self.log_buffer.append(log_entry)
            if len(self.log_buffer) > self.max_buffer:
                self.log_buffer.pop(0)

            # Broadcast to all connected clients (async-safe)
            if self.clients:
                import json

                message = json.dumps({"type": "log", "data": log_entry})
                # Schedule broadcast in event loop
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self._broadcast(message))
                except RuntimeError:
                    pass  # No event loop available

        except Exception:
            self.handleError(record)

    async def _broadcast(self, message: str):
        """Broadcast message to all connected WebSocket clients"""
        disconnected = set()
        for client in self.clients.copy():
            try:
                await client.send_text(message)
            except Exception:
                disconnected.add(client)

        # Remove disconnected clients
        self.clients -= disconnected

    def add_client(self, websocket):
        """Add a WebSocket client"""
        self.clients.add(websocket)

    def remove_client(self, websocket):
        """Remove a WebSocket client"""
        self.clients.discard(websocket)

    def get_recent_logs(self, count: int = 50) -> list:
        """Get recent log entries from buffer"""
        return self.log_buffer[-count:]


# Create global log handler instance
ws_log_handler = WebSocketLogHandler()
ws_log_handler.setLevel(logging.DEBUG)
ws_log_handler.setFormatter(
    logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", "%H:%M:%S")
)

# Add to root logger to capture all logs
logging.getLogger().addHandler(ws_log_handler)

# Create FastAPI app
app = FastAPI(
    title="Visual Mapper API",
    version=APP_VERSION,
    description="Android Device Monitoring & Automation for Home Assistant",
)

# Track devices with active wizard sessions (prevents auto-sleep during flow editing)
wizard_active_devices: set = set()

# Configure CORS to expose custom headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (localhost development)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Icon-Source"],  # Expose custom header to frontend
)


# Add validation error handler to log detailed errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Log and return detailed validation errors"""
    logger.error("=" * 80)
    logger.error("[VALIDATION ERROR] Request validation failed")
    logger.error(f"[VALIDATION ERROR] URL: {request.url}")
    logger.error(f"[VALIDATION ERROR] Method: {request.method}")

    # Log request body
    try:
        body = await request.body()
        logger.error(f"[VALIDATION ERROR] Request Body: {body.decode('utf-8')}")
    except Exception as e:
        logger.error(f"[VALIDATION ERROR] Could not read request body: {e}")

    # Log detailed validation errors
    logger.error(f"[VALIDATION ERROR] Errors: {exc.errors()}")
    logger.error("=" * 80)

    return JSONResponse(
        status_code=422,
        content={"success": False, "detail": exc.errors(), "body": exc.body},
    )


# Data Directory Configuration (HA Add-on Compatibility)
# Standalone: ./data (relative to CWD)
# HA Add-on: /config/visual_mapper (persistent storage mapped from Home Assistant)
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
logger.info(f"[Server] Data directory: {DATA_DIR.absolute()}")

# Initialize ADB Bridge
adb_bridge = ADBBridge()

# Initialize Device Migrator (handles IP/port changes)
device_migrator = DeviceMigrator(data_dir=str(DATA_DIR), config_dir=str(DATA_DIR))

# Initialize Sensor Manager and Text Extractor
sensor_manager = SensorManager(data_dir=str(DATA_DIR))
text_extractor = TextExtractor()
element_text_extractor = ElementTextExtractor(text_extractor)

# Initialize Action Manager and Executor
action_manager = ActionManager(data_dir=str(DATA_DIR))
action_executor = ActionExecutor(adb_bridge)

# Initialize Device Security Manager
device_security_manager = DeviceSecurityManager(data_dir=str(DATA_DIR))

# Initialize Navigation Manager (learns app navigation hierarchy)
navigation_manager = NavigationManager(config_dir=str(DATA_DIR / "navigation"))

# Initialize MQTT Manager (will be configured on startup)
mqtt_manager: Optional[MQTTManager] = None
sensor_updater: Optional[SensorUpdater] = None

# Phase 8: Flow System (will be configured on startup)
flow_manager: Optional[FlowManager] = None
flow_executor: Optional[FlowExecutor] = None
flow_scheduler: Optional[FlowScheduler] = None
performance_monitor: Optional[PerformanceMonitor] = None
screenshot_stitcher: Optional[ScreenshotStitcher] = None
app_icon_extractor: Optional[AppIconExtractor] = None
playstore_icon_scraper: Optional[PlayStoreIconScraper] = None
device_icon_scraper: Optional[DeviceIconScraper] = None
icon_background_fetcher: Optional["IconBackgroundFetcher"] = None
app_name_background_fetcher: Optional["AppNameBackgroundFetcher"] = None
stream_manager: Optional["StreamManager"] = None
adb_maintenance: Optional["ADBMaintenance"] = None
shell_pool: Optional["PersistentShellPool"] = None
connection_monitor: Optional["ConnectionMonitor"] = None

# MQTT Configuration (loaded from environment or config)
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_DISCOVERY_PREFIX = os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant")
AUTO_START_UPDATES = os.getenv("AUTO_START_UPDATES", "true").lower() == "true"
MQTT_USE_SSL = os.getenv("MQTT_USE_SSL", "false").lower() == "true"
MQTT_TLS_INSECURE = os.getenv("MQTT_TLS_INSECURE", "false").lower() == "true"
MQTT_CA_CERT = os.getenv("MQTT_CA_CERT", "")

# App Icon Configuration (Phase 8 Enhancement)
# Set to "true" to extract real icons from device (requires ADB access)
# Set to "false" to use SVG letter icons (faster, no caching needed)
ENABLE_REAL_ICONS = os.getenv("ENABLE_REAL_ICONS", "true").lower() == "true"

# HTML/CSS/JS Cache Control (Development Mode)
# Set DISABLE_HTML_CACHE=false in production to enable browser caching
DISABLE_HTML_CACHE = os.getenv("DISABLE_HTML_CACHE", "true").lower() == "true"


# Request/Response Models
class ConnectDeviceRequest(BaseModel):
    host: str
    port: int = 5555


class DisconnectDeviceRequest(BaseModel):
    device_id: str


class ScreenshotRequest(BaseModel):
    device_id: str
    quick: bool = False  # Quick mode: skip UI elements for faster preview


class ScreenshotStitchRequest(BaseModel):
    device_id: str
    max_scrolls: Optional[int] = 20
    scroll_ratio: Optional[float] = 0.75
    overlap_ratio: Optional[float] = 0.25
    stitcher_version: Optional[str] = "v2"
    debug: Optional[bool] = False


class SuggestSensorsRequest(BaseModel):
    device_id: str


class SuggestActionsRequest(BaseModel):
    device_id: str


class TapRequest(BaseModel):
    device_id: str
    x: int
    y: int


class SwipeRequest(BaseModel):
    device_id: str
    x1: int
    y1: int
    x2: int
    y2: int
    duration: int = 300


class TextInputRequest(BaseModel):
    device_id: str
    text: str


class KeyEventRequest(BaseModel):
    device_id: str
    keycode: int


class PairingRequest(BaseModel):
    pairing_host: str
    pairing_port: int
    pairing_code: str
    connection_port: int  # The actual ADB port to connect to after pairing


class ShellExecuteRequest(BaseModel):
    command: str


class ShellBatchRequest(BaseModel):
    commands: list


# Startup and Shutdown Events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize MQTT connection on startup"""
    global mqtt_manager, sensor_updater, flow_manager, flow_executor, flow_scheduler, performance_monitor, screenshot_stitcher, app_icon_extractor, playstore_icon_scraper, device_icon_scraper, icon_background_fetcher, app_name_background_fetcher, stream_manager, adb_maintenance, shell_pool, connection_monitor

    logger.info(f"[Server] Starting Visual Mapper v{APP_VERSION}")
    logger.info(f"[Server] MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")
    if MQTT_USE_SSL:
        logger.info(f"[Server] MQTT SSL Enabled (Insecure: {MQTT_TLS_INSECURE})")

    # Prepare TLS config
    mqtt_tls_config = None
    if MQTT_USE_SSL:
        mqtt_tls_config = {
            "insecure": MQTT_TLS_INSECURE,
            "ca_cert": MQTT_CA_CERT if MQTT_CA_CERT else None,
        }

    # Initialize MQTT Manager
    mqtt_manager = MQTTManager(
        broker=MQTT_BROKER,
        port=MQTT_PORT,
        username=MQTT_USERNAME if MQTT_USERNAME else None,
        password=MQTT_PASSWORD if MQTT_PASSWORD else None,
        discovery_prefix=MQTT_DISCOVERY_PREFIX,
        data_dir=str(DATA_DIR),
        tls_config=mqtt_tls_config,
    )
    # Link sensor_manager for stable_device_id lookup in availability publishing
    mqtt_manager.sensor_manager = sensor_manager

    # Initialize Screenshot Stitcher (independent of MQTT)
    screenshot_stitcher = ScreenshotStitcher(adb_bridge)
    logger.info("[Server] ✅ Screenshot Stitcher initialized")

    # Initialize App Icon Extractor (independent of MQTT)
    app_icon_extractor = AppIconExtractor(
        cache_dir=str(DATA_DIR / "app-icons"), enable_extraction=ENABLE_REAL_ICONS
    )
    logger.info(
        f"[Server] {'✅' if ENABLE_REAL_ICONS else '⚪'} App Icon Extractor initialized (real icons: {ENABLE_REAL_ICONS})"
    )

    # Initialize Play Store Icon Scraper (independent of MQTT)
    playstore_icon_scraper = PlayStoreIconScraper(
        cache_dir=str(DATA_DIR / "app-icons-playstore")
    )
    logger.info(f"[Server] ✅ Play Store Icon Scraper initialized")

    # Initialize Device Icon Scraper (independent of MQTT)
    device_icon_scraper = DeviceIconScraper(
        adb_bridge=adb_bridge, cache_dir=str(DATA_DIR / "device-icons")
    )
    logger.info(f"[Server] ✅ Device Icon Scraper initialized (device-specific icons)")

    # Initialize Background Icon Fetcher (independent of MQTT)
    icon_background_fetcher = IconBackgroundFetcher(
        playstore_scraper=playstore_icon_scraper, apk_extractor=app_icon_extractor
    )
    logger.info(f"[Server] ✅ Background Icon Fetcher initialized (async icon loading)")

    # Initialize Background App Name Fetcher (independent of MQTT)
    app_name_background_fetcher = AppNameBackgroundFetcher(
        playstore_scraper=playstore_icon_scraper
    )
    logger.info(
        f"[Server] ✅ Background App Name Fetcher initialized (async name loading)"
    )

    # Initialize Stream Manager (enhanced capture with adbutils)
    stream_manager = get_stream_manager(adb_bridge)
    logger.info("[Server] ✅ Stream Manager initialized (enhanced capture)")

    # Initialize ADB Maintenance utilities
    adb_maintenance = ADBMaintenance(adb_bridge)
    logger.info("[Server] ✅ ADB Maintenance utilities initialized")

    # Initialize Persistent Shell Pool for batch command optimization
    shell_pool = PersistentShellPool(max_sessions_per_device=2)
    logger.info("[Server] ✅ Persistent Shell Pool initialized")

    # Phase 8: Initialize Flow System (independent of MQTT)
    logger.info("[Server] Initializing Flow System (Phase 8)")

    # Initialize components - use DATA_DIR for persistent storage
    flow_manager = FlowManager(
        storage_dir=str(DATA_DIR / "flows"),
        template_dir=str(DATA_DIR / "flow_templates"),
        data_dir=str(DATA_DIR),
    )
    execution_history = FlowExecutionHistory()  # Track detailed flow execution logs

    flow_executor = FlowExecutor(
        adb_bridge=adb_bridge,
        sensor_manager=sensor_manager,
        text_extractor=text_extractor,
        mqtt_manager=mqtt_manager,
        flow_manager=flow_manager,
        screenshot_stitcher=screenshot_stitcher,
        execution_history=execution_history,
        navigation_manager=navigation_manager,  # Phase 9: Smart navigation recovery
        action_manager=action_manager,
        action_executor=action_executor,
    )

    flow_scheduler = FlowScheduler(flow_executor, flow_manager)
    performance_monitor = PerformanceMonitor(flow_scheduler, mqtt_manager)

    # Update flow_executor with performance_monitor
    flow_executor.performance_monitor = performance_monitor

    # Start scheduler
    await flow_scheduler.start()
    logger.info("[Server] ✅ Flow System initialized and scheduler started")

    # Initialize Connection Monitor (handles device health checks and auto-recovery)
    connection_monitor = ConnectionMonitor(
        adb_bridge=adb_bridge,
        device_migrator=device_migrator,
        mqtt_manager=mqtt_manager,
        check_interval=30,  # Check every 30 seconds
    )
    logger.info("[Server] ✅ Connection Monitor initialized")

    # Connect to MQTT broker
    connected = await mqtt_manager.connect()
    if connected:
        logger.info("[Server] ✅ Connected to MQTT broker")

        # Initialize Sensor Updater (requires MQTT)
        # Pass flow_manager so SensorUpdater can skip devices with enabled flows
        # (FlowScheduler handles sensor updates for those devices)
        sensor_updater = SensorUpdater(adb_bridge, sensor_manager, mqtt_manager, flow_manager)

        # Initialize Navigation MQTT Handler for passive navigation learning
        navigation_mqtt_handler = NavigationMqttHandler(navigation_manager)
        mqtt_manager.set_navigation_learn_callback(
            navigation_mqtt_handler.handle_learn_transition
        )
        logger.info(
            "[Server] ✅ Navigation MQTT handler initialized for passive learning"
        )

        # Subscribe to device announcements (MQTT-based device discovery)
        async def on_device_announced(announcement: dict):
            """Handle device announcement from Android companion app"""
            try:
                ip = announcement.get("ip")
                adb_port = announcement.get("adb_port")
                model = announcement.get("model", "Unknown")
                already_paired = announcement.get("already_paired", True)
                device_serial = announcement.get(
                    "device_id"
                )  # Stable serial from companion
                source = announcement.get("source", "VMC")  # Source indicator
                current_app = announcement.get("current_app")  # Current foreground app

                logger.info(
                    f"[Server] 📱 Device announced: {model} at {ip}:{adb_port} (paired={already_paired}, app={current_app})"
                )

                # Store announcement for API access
                if not hasattr(mqtt_manager, "_announced_devices"):
                    mqtt_manager._announced_devices = {}
                mqtt_manager._announced_devices[f"{ip}:{adb_port}"] = announcement

                # Cache device info for friendly MQTT names (from companion app)
                # Use stable device serial if provided, otherwise use IP:port
                device_id_for_cache = device_serial or f"{ip}:{adb_port}"
                if model and model != "Unknown":
                    # Add source indicator for companion-sourced info
                    model_with_source = f"{model} ({source})" if source else model
                    # Include app name if available
                    app_name = None
                    if current_app:
                        # Extract app name from package (e.g., com.byd.bydautolink -> BYD)
                        app_name = (
                            current_app.split(".")[-1]
                            if "." in current_app
                            else current_app
                        )
                    mqtt_manager.set_device_info(
                        device_id_for_cache, model=model_with_source, app_name=app_name
                    )
                    logger.info(
                        f"[Server] Cached device info from {source}: {model_with_source} (app: {app_name}) for {device_id_for_cache}"
                    )

                # Auto-connect if already paired
                if already_paired and ip and adb_port:
                    # Check if not already connected
                    device_id = f"{ip}:{adb_port}"
                    existing_devices = await adb_bridge.get_connected_devices()
                    if not any(d.get("id") == device_id for d in existing_devices):
                        logger.info(
                            f"[Server] 🔗 Auto-connecting to announced device: {device_id}"
                        )
                        try:
                            await adb_bridge.connect_device(ip, adb_port)
                            logger.info(f"[Server] ✅ Auto-connected to {device_id}")
                        except Exception as e:
                            logger.warning(
                                f"[Server] Failed to auto-connect to {device_id}: {e}"
                            )

            except Exception as e:
                logger.error(f"[Server] Error handling device announcement: {e}")

        await mqtt_manager.subscribe_device_announcements(on_device_announced)
        logger.info("[Server] ✅ Subscribed to device announcements (MQTT discovery)")

        # Subscribe to generated flows from Android companion app
        async def on_generated_flow(flow_data: dict):
            """Handle flow generated by Android companion app exploration"""
            try:
                flow_id = flow_data.get("flow_id", "unknown")
                device_id = flow_data.get("device_id")
                name = flow_data.get("name", "Auto-generated flow")

                logger.info(f"[Server] 📥 Received generated flow: {name} ({flow_id})")

                if not device_id:
                    logger.error("[Server] Generated flow missing device_id, skipping")
                    return

                # Save the flow using flow_manager
                if flow_manager:
                    try:
                        # Ensure required fields
                        if "steps" not in flow_data:
                            flow_data["steps"] = []
                        if "enabled" not in flow_data:
                            flow_data["enabled"] = (
                                False  # Disabled by default for review
                            )

                        saved_flow = flow_manager.create_flow(device_id, flow_data)
                        logger.info(
                            f"[Server] ✅ Saved generated flow: {flow_id} for device {device_id}"
                        )
                    except Exception as e:
                        logger.error(f"[Server] Failed to save generated flow: {e}")
                else:
                    logger.warning(
                        "[Server] Flow manager not available, cannot save generated flow"
                    )

            except Exception as e:
                logger.error(f"[Server] Error processing generated flow: {e}")

        await mqtt_manager.subscribe_to_generated_flows()
        mqtt_manager.set_generated_flow_callback(on_generated_flow)
        logger.info("[Server] ✅ Subscribed to generated flows (Android exploration)")

        # Track devices that have had discovery published to prevent duplicates
        devices_with_discovery_published = set()

        # Register callback to publish MQTT discovery when devices are discovered
        async def on_device_discovered(device_id: str, model: str = None):
            """Callback triggered when ADB bridge auto-imports a device"""
            try:
                # Set device model info in MQTT manager for friendly names
                if model and mqtt_manager:
                    mqtt_manager.set_device_info(device_id, model=model)
                    logger.info(f"[Server] Set device model for {device_id}: {model}")
                # Check for device IP/port changes and auto-migrate
                try:
                    stable_device_id = await adb_bridge.get_device_serial(device_id)
                    if stable_device_id:
                        # Check if this is a known device with a new address
                        migration_result = device_migrator.check_and_migrate(
                            device_id, stable_device_id
                        )
                        if migration_result:
                            logger.info(
                                f"[Server] 🔄 Device {device_id} migrated from previous address"
                            )
                            logger.info(
                                f"[Server] Migrated: {migration_result['sensors']} sensors, {migration_result['actions']} actions, {migration_result['flows']} flows"
                            )
                            # Reload managers to pick up migrated configurations
                            sensor_manager._load_all_sensors()  # Reload sensor definitions
                            flow_manager._load_all_flows()  # Reload flows
                except Exception as e:
                    logger.warning(
                        f"[Server] Device migration check failed for {device_id}: {e}"
                    )

                # Publish sensor discoveries (skip if already published for this device)
                if device_id in devices_with_discovery_published:
                    logger.info(
                        f"[Server] Device {device_id} already had discovery published, skipping callback"
                    )
                else:
                    sensors = sensor_manager.get_all_sensors(device_id)
                    if sensors:
                        logger.info(
                            f"[Server] Device discovered: {device_id} - Publishing MQTT discovery for {len(sensors)} sensors"
                        )
                        for sensor in sensors:
                            try:
                                # Publish discovery config
                                await mqtt_manager.publish_discovery(sensor)
                                logger.debug(
                                    f"[Server] Published discovery for {sensor.sensor_id}"
                                )

                                # Publish initial state if sensor has current_value
                                if sensor.current_value:
                                    await mqtt_manager.publish_state(
                                        sensor, sensor.current_value
                                    )
                                    logger.info(
                                        f"[Server] Published initial state for {sensor.sensor_id}: {sensor.current_value}"
                                    )
                            except Exception as e:
                                logger.error(
                                    f"[Server] Failed to publish discovery for {sensor.sensor_id}: {e}"
                                )
                        # Mark device as having discovery published
                        devices_with_discovery_published.add(device_id)
                    else:
                        logger.debug(
                            f"[Server] Device discovered: {device_id} - No sensors configured yet"
                        )

                # Publish action discoveries
                actions = action_manager.list_actions(device_id)
                if actions:
                    logger.info(
                        f"[Server] Device discovered: {device_id} - Publishing MQTT discovery for {len(actions)} actions"
                    )
                    for action_def in actions:
                        try:
                            await mqtt_manager.publish_action_discovery(action_def)
                            logger.debug(
                                f"[Server] Published action discovery for {action_def.id}"
                            )
                        except Exception as e:
                            logger.error(
                                f"[Server] Failed to publish action discovery for {action_def.id}: {e}"
                            )
                else:
                    logger.debug(
                        f"[Server] Device discovered: {device_id} - No actions configured yet"
                    )

                # Add device to connection monitor for health checks
                try:
                    stable_device_id = await adb_bridge.get_device_serial(device_id)
                    await connection_monitor.add_device(device_id, stable_device_id)
                except Exception as e:
                    logger.warning(
                        f"[Server] Failed to add device {device_id} to connection monitor: {e}"
                    )

                # Publish device availability (so HA sensors show as "available")
                try:
                    stable_device_id = await adb_bridge.get_device_serial(device_id)
                    await mqtt_manager.publish_availability(
                        device_id, online=True, stable_device_id=stable_device_id
                    )
                    logger.info(
                        f"[Server] Published availability for {device_id}: online"
                    )
                except Exception as e:
                    logger.warning(
                        f"[Server] Failed to publish availability for {device_id}: {e}"
                    )

            except Exception as e:
                logger.error(
                    f"[Server] Failed to publish discoveries for {device_id}: {e}"
                )

        adb_bridge.register_device_discovered_callback(on_device_discovered)

        # Auto-reconnect to previously connected devices
        async def auto_reconnect_devices():
            """Attempt to reconnect to previously connected devices on startup"""
            await asyncio.sleep(2)  # Wait for server to fully initialize
            try:
                import glob
                import json
                import subprocess

                # Find all sensor files in data directory
                sensor_files = glob.glob(str(DATA_DIR / "sensors_*.json"))
                device_ids = set()

                for file_path in sensor_files:
                    try:
                        with open(file_path, "r") as f:
                            data = json.load(f)
                            device_id = data.get("device_id")
                            if device_id:
                                device_ids.add(device_id)
                    except Exception as e:
                        logger.debug(f"[Server] Failed to read {file_path}: {e}")

                if device_ids:
                    logger.info(
                        f"[Server] Auto-reconnecting to {len(device_ids)} previously connected devices..."
                    )
                    reconnected_count = 0

                    for device_id in device_ids:
                        try:
                            # Try to connect via adb
                            result = subprocess.run(
                                ["adb", "connect", device_id],
                                capture_output=True,
                                text=True,
                                timeout=10,
                            )
                            if (
                                "connected" in result.stdout.lower()
                                or "already connected" in result.stdout.lower()
                            ):
                                logger.info(
                                    f"[Server] ✅ Auto-reconnected to {device_id}"
                                )
                                reconnected_count += 1
                            else:
                                logger.debug(
                                    f"[Server] Could not reconnect to {device_id}: {result.stdout.strip()}"
                                )
                        except Exception as e:
                            logger.debug(
                                f"[Server] Failed to auto-reconnect to {device_id}: {e}"
                            )

                    # If we couldn't reconnect to any devices, trigger a network scan
                    # This will find devices with changed IP/port and auto-migrate them
                    if reconnected_count == 0 and device_migrator.device_map:
                        logger.info(
                            "[Server] No devices reconnected via direct connection - scanning network for known devices..."
                        )
                        await asyncio.sleep(1)
                        # Trigger device discovery which will handle migration
                        await adb_bridge.discover_devices()
                else:
                    logger.debug("[Server] No previously connected devices found")
            except Exception as e:
                logger.error(f"[Server] Auto-reconnect failed: {e}")

        asyncio.create_task(auto_reconnect_devices())

        # Start connection monitor
        async def start_connection_monitor():
            """Start connection monitor after initial reconnection attempts"""
            await asyncio.sleep(10)  # Wait for initial reconnections
            await connection_monitor.start()
            logger.info(
                "[Server] ✅ Connection Monitor started - will check device health every 30s"
            )

        asyncio.create_task(start_connection_monitor())

        # Background task to publish discovery for already-connected devices
        async def publish_existing_devices():
            """Wait for device discovery to complete, then publish MQTT for existing devices"""
            await asyncio.sleep(35)  # Wait for device discovery timeout (30s) + buffer
            try:
                devices = await adb_bridge.get_devices()
                for device in devices:
                    device_id = device["id"]

                    # Skip if already published via on_device_discovered callback
                    if device_id in devices_with_discovery_published:
                        logger.info(
                            f"[Server] Device {device_id} already had discovery published, skipping delayed"
                        )
                        continue

                    # Publish sensor discoveries
                    sensors = sensor_manager.get_all_sensors(device_id)
                    if sensors:
                        logger.info(
                            f"[Server] Publishing delayed discovery for existing device: {device_id} ({len(sensors)} sensors)"
                        )
                        for sensor in sensors:
                            try:
                                # Publish discovery config
                                await mqtt_manager.publish_discovery(sensor)
                                logger.debug(
                                    f"[Server] Published delayed discovery for {sensor.sensor_id}"
                                )

                                # Publish initial state if sensor has current_value
                                if sensor.current_value:
                                    await mqtt_manager.publish_state(
                                        sensor, sensor.current_value
                                    )
                                    logger.info(
                                        f"[Server] Published delayed state for {sensor.sensor_id}: {sensor.current_value}"
                                    )
                            except Exception as e:
                                logger.error(
                                    f"[Server] Failed delayed discovery for {sensor.sensor_id}: {e}"
                                )
                        # Mark as published
                        devices_with_discovery_published.add(device_id)

                    # Publish action discoveries
                    actions = action_manager.list_actions(device_id)
                    if actions:
                        logger.info(
                            f"[Server] Publishing delayed discovery for existing device: {device_id} ({len(actions)} actions)"
                        )
                        for action_def in actions:
                            try:
                                await mqtt_manager.publish_action_discovery(action_def)
                                logger.debug(
                                    f"[Server] Published delayed action discovery for {action_def.id}"
                                )
                            except Exception as e:
                                logger.error(
                                    f"[Server] Failed delayed action discovery for {action_def.id}: {e}"
                                )
            except Exception as e:
                logger.error(f"[Server] Failed to publish delayed discoveries: {e}")

        asyncio.create_task(publish_existing_devices())

        # Register action command callback to handle MQTT button presses from HA
        async def on_action_command(device_id: str, action_id: str):
            """Callback triggered when HA sends action execution command via MQTT"""
            try:
                logger.info(
                    f"[Server] MQTT action command received: {device_id}/{action_id}"
                )
                result = await action_executor.execute_action_by_id(
                    action_manager, device_id, action_id
                )
                if result.success:
                    logger.info(f"[Server] Action executed successfully: {action_id}")
                else:
                    logger.error(f"[Server] Action execution failed: {result.message}")
            except Exception as e:
                logger.error(f"[Server] Failed to execute action {action_id}: {e}")

        mqtt_manager.set_action_command_callback(on_action_command)
        logger.info("[Server] ✅ Registered MQTT action command callback")

        # Auto-start updates for all devices if configured
        if AUTO_START_UPDATES:
            try:
                devices = await adb_bridge.get_devices()
                for device in devices:
                    device_id = device["id"]
                    sensors = sensor_manager.get_all_sensors(device_id)
                    if sensors:
                        logger.info(f"[Server] Auto-starting updates for {device_id}")
                        await sensor_updater.start_device_updates(device_id)
            except Exception as e:
                logger.error(f"[Server] Failed to auto-start updates: {e}")
    else:
        logger.warning(
            "[Server] ⚠️ Failed to connect to MQTT broker - sensor updates disabled"
        )

    # Initialize route dependencies (modular architecture)
    _init_route_dependencies()

    # ML Training Server (optional - based on config)
    ml_training_thread = None
    ml_training_mode = os.getenv("ML_TRAINING_MODE", "disabled").lower()

    # Check if ML server should auto-start from saved settings
    # This allows the server to remember its state across restarts
    if ml_training_mode == "disabled":
        try:
            import json

            settings_path = DATA_DIR / "settings.json"
            logger.info(f"[Server] Checking ML auto-start at: {settings_path}")

            if settings_path.exists():
                with open(settings_path) as f:
                    settings = json.load(f)

                if settings.get("ml_server_auto_start", False):
                    ml_training_mode = "local"
                    logger.info(
                        "[Server] ML Training auto-start enabled from saved settings"
                    )
                else:
                    logger.info(
                        f"[Server] ML auto-start not enabled (value={settings.get('ml_server_auto_start', 'not set')})"
                    )
            else:
                logger.info(f"[Server] Settings file not found at {settings_path}")
        except Exception as e:
            logger.warning(f"[Server] Could not load ML auto-start setting: {e}")

    if ml_training_mode == "local":
        try:
            from ml_components.ml_training_server import MLTrainingServer

            ml_server = MLTrainingServer(
                broker=MQTT_BROKER,
                port=MQTT_PORT,
                username=MQTT_USERNAME if MQTT_USERNAME else None,
                password=MQTT_PASSWORD if MQTT_PASSWORD else None,
                data_dir=str(DATA_DIR),
            )

            import threading

            ml_training_thread = threading.Thread(target=ml_server.start, daemon=True)
            ml_training_thread.start()
            logger.info("[Server] ✅ ML Training Server started (local mode)")
        except ImportError as e:
            logger.warning(f"[Server] ⚠️ ML Training dependencies not available: {e}")
        except Exception as e:
            logger.error(f"[Server] Failed to start ML Training Server: {e}")
    elif ml_training_mode == "remote":
        ml_remote_host = os.getenv("ML_REMOTE_HOST", "")
        if ml_remote_host:
            logger.info(
                f"[Server] ✅ ML Training delegated to remote server: {ml_remote_host}"
            )
        else:
            logger.warning(
                "[Server] ⚠️ ML Training mode is 'remote' but ML_REMOTE_HOST not set"
            )
    else:
        logger.info("[Server] ML Training disabled")

    yield

    logger.info("[Server] Shutting down Visual Mapper...")

    # Stop all sensor updates
    if sensor_updater:
        await sensor_updater.stop_all_updates()

    # Stop connection monitor
    if connection_monitor:
        await connection_monitor.stop()

    # Disconnect from MQTT
    if mqtt_manager:
        await mqtt_manager.disconnect()

    logger.info("[Server] Shutdown complete")


# Register lifespan
app.router.lifespan_context = lifespan


# ============================================================================
# ROUTE REGISTRATION - Modular Architecture
# ============================================================================

# NOTE: This is server_new.py - refactored version with modular routes
# Original server.py remains untouched for comparison/rollback


# Initialize dependency injection (after startup completes managers initialization)
# This will be called at the end of startup event
def _init_route_dependencies():
    """Initialize route dependencies after all managers are created"""
    # Note: These module-level variables are read here, not assigned
    # No 'global' declarations needed for read-only access
    feature_manager = get_feature_manager()

    deps = RouteDependencies(
        adb_bridge=adb_bridge,
        device_migrator=device_migrator,
        sensor_manager=sensor_manager,
        text_extractor=text_extractor,
        element_text_extractor=element_text_extractor,
        action_manager=action_manager,
        action_executor=action_executor,
        mqtt_manager=mqtt_manager,
        sensor_updater=sensor_updater,
        flow_manager=flow_manager,
        flow_executor=flow_executor,
        flow_scheduler=flow_scheduler,
        performance_monitor=performance_monitor,
        screenshot_stitcher=screenshot_stitcher,
        app_icon_extractor=app_icon_extractor,
        playstore_icon_scraper=playstore_icon_scraper,
        device_icon_scraper=device_icon_scraper,
        icon_background_fetcher=icon_background_fetcher,
        app_name_background_fetcher=app_name_background_fetcher,
        stream_manager=stream_manager,
        adb_maintenance=adb_maintenance,
        shell_pool=shell_pool,
        connection_monitor=connection_monitor,
        device_security_manager=device_security_manager,
        navigation_manager=navigation_manager,
        ws_log_handler=ws_log_handler,
        feature_manager=feature_manager,
        data_dir=str(DATA_DIR),
    )
    set_dependencies(deps)

    # Set navigation manager for navigation routes
    navigation.set_navigation_manager(navigation_manager)
    logger.info("[Server] Route dependencies initialized")


# Register route modules
app.include_router(meta.router)
logger.info("[Server] Registered route module: meta (2 endpoints)")
app.include_router(health.router)
logger.info("[Server] Registered route module: health (1 endpoint)")
app.include_router(adb_info.router)
logger.info("[Server] Registered route module: adb_info (6 endpoints)")
app.include_router(cache.router)
logger.info("[Server] Registered route module: cache (6 endpoints)")
app.include_router(performance.router)
logger.info(
    "[Server] Registered route module: performance (8 endpoints: 4 performance + 4 diagnostics)"
)
app.include_router(shell.router)
logger.info(
    "[Server] Registered route module: shell (5 endpoints: stats + execute + batch + benchmark + close)"
)
app.include_router(maintenance.router)
logger.info(
    "[Server] Registered route module: maintenance (12 endpoints: 2 server + 6 device optimization + 2 background limit + 2 metrics)"
)
app.include_router(adb_connection.router)
logger.info(
    f"[Server] Registered route module: adb_connection ({len(adb_connection.router.routes)} endpoints)"
)
app.include_router(adb_control.router)
logger.info(
    "[Server] Registered route module: adb_control (6 endpoints: tap + swipe + text + keyevent + back + home)"
)
app.include_router(adb_screenshot.router)
logger.info(
    "[Server] Registered route module: adb_screenshot (3 endpoints: screenshot + elements + stitch)"
)
app.include_router(adb_apps.router)
logger.info(
    "[Server] Registered route module: adb_apps (4 endpoints: apps + app-icon + launch + stop-app)"
)
app.include_router(suggestions.router)
logger.info(
    "[Server] Registered route module: suggestions (2 endpoints: suggest-sensors + suggest-actions)"
)
app.include_router(sensors.router)
logger.info(
    "[Server] Registered route module: sensors (7 endpoints: CRUD + test-extract + migrate-stable-ids)"
)
app.include_router(mqtt.router)
logger.info(
    "[Server] Registered route module: mqtt (7 endpoints: start/stop/restart + status + discovery management)"
)
app.include_router(actions.router)
logger.info(
    "[Server] Registered route module: actions (8 endpoints: CRUD + execute + export/import)"
)
app.include_router(flows.router)
logger.info(
    "[Server] Registered route module: flows (16 endpoints: CRUD + execute + metrics + alerts + scheduler)"
)
app.include_router(streaming.router)
logger.info(
    "[Server] Registered route module: streaming (4 endpoints: 2 HTTP stats + 2 WebSocket streams)"
)
app.include_router(migration.router)
logger.info(
    "[Server] Registered route module: migration (1 endpoint: global stable ID migration)"
)
app.include_router(device_security.router)
logger.info(
    "[Server] Registered route module: device_security (3 endpoints: lock screen config + unlock test)"
)
app.include_router(device_registration.router)
logger.info(
    "[Server] Registered route module: device_registration (5 endpoints: register + heartbeat + list + get + unregister)"
)
app.include_router(navigation.router)
logger.info(
    "[Server] Registered route module: navigation (11 endpoints: graph CRUD + screens + transitions + pathfinding + learning)"
)
app.include_router(companion.router)
logger.info(
    "[Server] Registered route module: companion (5 endpoints: ui-tree + status + devices + discover-screens + select-elements)"
)
app.include_router(services.router)
logger.info(
    "[Server] Registered route module: services (6 endpoints: status + mqtt + ml start/stop/restart)"
)
app.include_router(deduplication.router)
logger.info(
    "[Server] Registered route module: deduplication (5 endpoints: sensor/action/flow similarity + optimize)"
)
app.include_router(settings.router)
logger.info(
    "[Server] Registered route module: settings (8 endpoints: preferences + saved devices CRUD)"
)
app.include_router(ml.router)
logger.info(
    "[Server] Registered route module: ml (6 endpoints: status + stats + export + reset + import)"
)

# ============================================================================
# All API endpoints have been migrated to routes/ modules
# See routes/__init__.py for the full list of route modules
# ============================================================================


# === Device Identity Test Endpoint ===
@app.get("/api/test/device-identity")
async def test_device_identity():
    """Test endpoint for device identity"""
    from services.device_identity import get_device_identity_resolver

    resolver = get_device_identity_resolver(str(DATA_DIR))
    return {"devices": resolver.get_all_devices(), "status": "ok"}


# === Real-Time Log Viewer ===


@app.get("/api/logs/recent")
async def get_recent_logs(count: int = 50):
    """Get recent log entries from buffer"""
    return {
        "success": True,
        "logs": ws_log_handler.get_recent_logs(count),
        "connected_clients": len(ws_log_handler.clients),
    }


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """
    WebSocket endpoint for real-time log streaming.

    Clients receive:
    - Initial batch of recent logs on connect
    - Real-time log messages as they occur

    Message format:
    {
        "type": "log" | "history",
        "data": { timestamp, level, message, logger, module } | [logs...]
    }
    """
    await websocket.accept()
    logger.info("[WS-Logs] Client connected")

    # Register client
    ws_log_handler.add_client(websocket)

    try:
        # Send recent log history on connect
        recent_logs = ws_log_handler.get_recent_logs(100)
        await websocket.send_json({"type": "history", "data": recent_logs})

        # Keep connection alive and handle client messages
        while True:
            try:
                # Wait for client messages (ping/pong, filter requests, etc.)
                message = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                # Handle filter commands
                if message.startswith("filter:"):
                    # Future: implement log filtering
                    pass
                elif message == "ping":
                    await websocket.send_json({"type": "pong"})

            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break

    except WebSocketDisconnect:
        logger.info("[WS-Logs] Client disconnected")
    except Exception as e:
        logger.error(f"[WS-Logs] Error: {e}")
    finally:
        ws_log_handler.remove_client(websocket)


# =============================================================================
# CUSTOM STATIC FILES - No ETags in Development Mode
# =============================================================================


class NoCacheStaticFiles(StaticFiles):
    """
    Custom StaticFiles that disables ETags and caching headers in development mode.

    When DISABLE_HTML_CACHE is True, this prevents 304 Not Modified responses
    by not generating ETags or Last-Modified headers on FileResponse objects.
    """

    async def get_response(self, path: str, scope):
        """Override to customize FileResponse headers"""
        response = await super().get_response(path, scope)

        if DISABLE_HTML_CACHE and hasattr(response, "headers"):
            # Remove cache validation headers to force fresh downloads
            if "etag" in response.headers:
                del response.headers["etag"]
            if "last-modified" in response.headers:
                del response.headers["last-modified"]

            # Add no-cache headers for HTML/JS/CSS
            content_type = response.headers.get("content-type", "")
            if any(
                ct in content_type for ct in ["text/html", "javascript", "text/css"]
            ):
                response.headers["Cache-Control"] = (
                    "no-cache, no-store, must-revalidate"
                )
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"

        return response


# Mount static files LAST (catch-all route)
# Prefer explicit env override or mounted frontend directory in Docker.
static_dir_env = os.getenv("STATIC_DIR")
STATIC_DIR = None

if static_dir_env:
    candidate = Path(static_dir_env)
    if candidate.exists():
        STATIC_DIR = candidate

if STATIC_DIR is None:
    docker_frontend = Path("/app/frontend/www")
    if docker_frontend.exists():
        STATIC_DIR = docker_frontend
    else:
        STATIC_DIR = Path(__file__).parent.parent / "frontend" / "www"
        if not STATIC_DIR.exists():
            STATIC_DIR = Path("/frontend/www")

logger.info(f"[Server] Static files directory: {STATIC_DIR.absolute()}")
app.mount("/", NoCacheStaticFiles(directory=str(STATIC_DIR), html=True), name="www")

if __name__ == "__main__":
    # Default to port 8080 (better firewall compatibility), can be overridden by environment variable
    port = int(os.getenv("PORT", 8080))

    logger.info(f"Starting Visual Mapper v0.0.4 (Phase 3 - Sensor Creation)")
    logger.info(f"Server: http://localhost:{port}")
    logger.info(f"API: http://localhost:{port}/api")
    logger.info(
        f"HTML Cache: {'DISABLED (development mode)' if DISABLE_HTML_CACHE else 'ENABLED (production mode)'}"
    )

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
