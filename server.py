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
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError
import uvicorn
from pathlib import Path
from PIL import Image

from adb_bridge import ADBBridge
from sensor_manager import SensorManager
from sensor_models import SensorDefinition, TextExtractionRule
from text_extractor import TextExtractor, ElementTextExtractor
from mqtt_manager import MQTTManager
from sensor_updater import SensorUpdater
from ha_device_classes import (
    validate_unit_for_device_class,
    can_use_state_class,
    get_device_class_info,
    export_to_json as export_device_classes
)
from utils.action_manager import ActionManager
from utils.action_executor import ActionExecutor
from utils.action_models import (
    ActionCreateRequest,
    ActionUpdateRequest,
    ActionExecutionRequest,
    ActionListResponse
)
from utils.error_handler import handle_api_error

# Phase 8: Flow System
from flow_manager import FlowManager
from flow_executor import FlowExecutor
from flow_scheduler import FlowScheduler
from performance_monitor import PerformanceMonitor
from screenshot_stitcher import ScreenshotStitcher
from app_icon_extractor import AppIconExtractor
from playstore_icon_scraper import PlayStoreIconScraper
from device_icon_scraper import DeviceIconScraper
from icon_background_fetcher import IconBackgroundFetcher
from app_name_background_fetcher import AppNameBackgroundFetcher
from stream_manager import StreamManager, get_stream_manager
from adb_helpers import ADBMaintenance, PersistentShellPool, PersistentADBShell

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
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
                "timestamp": self.formatter.formatTime(record) if self.formatter else record.created,
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
                "module": record.module
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
ws_log_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s', '%H:%M:%S'))

# Add to root logger to capture all logs
logging.getLogger().addHandler(ws_log_handler)

# Create FastAPI app
app = FastAPI(
    title="Visual Mapper API",
    version="0.0.5",
    description="Android Device Monitoring & Automation for Home Assistant"
)

# Configure CORS to expose custom headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (localhost development)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Icon-Source"]  # Expose custom header to frontend
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
        content={
            "success": False,
            "detail": exc.errors(),
            "body": exc.body
        }
    )

# Initialize ADB Bridge
adb_bridge = ADBBridge()

# Initialize Sensor Manager and Text Extractor
sensor_manager = SensorManager()
text_extractor = TextExtractor()
element_text_extractor = ElementTextExtractor(text_extractor)

# Initialize Action Manager and Executor
action_manager = ActionManager()
action_executor = ActionExecutor(adb_bridge)

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
icon_background_fetcher: Optional['IconBackgroundFetcher'] = None
app_name_background_fetcher: Optional['AppNameBackgroundFetcher'] = None
stream_manager: Optional['StreamManager'] = None
adb_maintenance: Optional['ADBMaintenance'] = None
shell_pool: Optional['PersistentShellPool'] = None

# MQTT Configuration (loaded from environment or config)
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_DISCOVERY_PREFIX = os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant")
AUTO_START_UPDATES = os.getenv("AUTO_START_UPDATES", "true").lower() == "true"

# App Icon Configuration (Phase 8 Enhancement)
# Set to "true" to extract real icons from device (requires ADB access)
# Set to "false" to use SVG letter icons (faster, no caching needed)
ENABLE_REAL_ICONS = os.getenv("ENABLE_REAL_ICONS", "true").lower() == "true"


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
@app.on_event("startup")
async def startup_event():
    """Initialize MQTT connection on startup"""
    global mqtt_manager, sensor_updater, flow_manager, flow_executor, flow_scheduler, performance_monitor, screenshot_stitcher, app_icon_extractor, playstore_icon_scraper, device_icon_scraper, icon_background_fetcher, app_name_background_fetcher, stream_manager, adb_maintenance, shell_pool

    logger.info("[Server] Starting Visual Mapper v0.0.5")
    logger.info(f"[Server] MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")

    # Initialize MQTT Manager
    mqtt_manager = MQTTManager(
        broker=MQTT_BROKER,
        port=MQTT_PORT,
        username=MQTT_USERNAME if MQTT_USERNAME else None,
        password=MQTT_PASSWORD if MQTT_PASSWORD else None,
        discovery_prefix=MQTT_DISCOVERY_PREFIX
    )

    # Initialize Screenshot Stitcher (independent of MQTT)
    screenshot_stitcher = ScreenshotStitcher(adb_bridge)
    logger.info("[Server] ✅ Screenshot Stitcher initialized")

    # Initialize App Icon Extractor (independent of MQTT)
    app_icon_extractor = AppIconExtractor(
        cache_dir="data/app-icons",
        enable_extraction=ENABLE_REAL_ICONS
    )
    logger.info(f"[Server] {'✅' if ENABLE_REAL_ICONS else '⚪'} App Icon Extractor initialized (real icons: {ENABLE_REAL_ICONS})")

    # Initialize Play Store Icon Scraper (independent of MQTT)
    playstore_icon_scraper = PlayStoreIconScraper(
        cache_dir="data/app-icons-playstore"
    )
    logger.info(f"[Server] ✅ Play Store Icon Scraper initialized")

    # Initialize Device Icon Scraper (independent of MQTT)
    device_icon_scraper = DeviceIconScraper(
        adb_bridge=adb_bridge,
        cache_dir="data/device-icons"
    )
    logger.info(f"[Server] ✅ Device Icon Scraper initialized (device-specific icons)")

    # Initialize Background Icon Fetcher (independent of MQTT)
    icon_background_fetcher = IconBackgroundFetcher(
        playstore_scraper=playstore_icon_scraper,
        apk_extractor=app_icon_extractor
    )
    logger.info(f"[Server] ✅ Background Icon Fetcher initialized (async icon loading)")

    # Initialize Background App Name Fetcher (independent of MQTT)
    app_name_background_fetcher = AppNameBackgroundFetcher(
        playstore_scraper=playstore_icon_scraper
    )
    logger.info(f"[Server] ✅ Background App Name Fetcher initialized (async name loading)")

    # Initialize Stream Manager (enhanced capture with adbutils)
    stream_manager = get_stream_manager(adb_bridge)
    logger.info("[Server] ✅ Stream Manager initialized (enhanced capture)")

    # Initialize ADB Maintenance utilities
    adb_maintenance = ADBMaintenance(adb_bridge)
    logger.info("[Server] ✅ ADB Maintenance utilities initialized")

    # Initialize Persistent Shell Pool for batch command optimization
    shell_pool = PersistentShellPool(max_sessions_per_device=2)
    logger.info("[Server] ✅ Persistent Shell Pool initialized")

    # Connect to MQTT broker
    connected = await mqtt_manager.connect()
    if connected:
        logger.info("[Server] ✅ Connected to MQTT broker")

        # Initialize Sensor Updater
        sensor_updater = SensorUpdater(adb_bridge, sensor_manager, mqtt_manager)

        # Phase 8: Initialize Flow System
        logger.info("[Server] Initializing Flow System (Phase 8)")

        # Initialize components
        flow_manager = FlowManager()

        flow_executor = FlowExecutor(
            adb_bridge=adb_bridge,
            sensor_manager=sensor_manager,
            text_extractor=text_extractor,
            mqtt_manager=mqtt_manager,
            flow_manager=flow_manager,
            screenshot_stitcher=screenshot_stitcher
        )

        flow_scheduler = FlowScheduler(flow_executor, flow_manager)
        performance_monitor = PerformanceMonitor(flow_scheduler, mqtt_manager)

        # Update flow_executor with performance_monitor
        flow_executor.performance_monitor = performance_monitor

        # Start scheduler
        await flow_scheduler.start()
        logger.info("[Server] ✅ Flow System initialized and scheduler started")

        # Register callback to publish MQTT discovery when devices are discovered
        async def on_device_discovered(device_id: str):
            """Callback triggered when ADB bridge auto-imports a device"""
            try:
                # Publish sensor discoveries
                sensors = sensor_manager.get_all_sensors(device_id)
                if sensors:
                    logger.info(f"[Server] Device discovered: {device_id} - Publishing MQTT discovery for {len(sensors)} sensors")
                    for sensor in sensors:
                        try:
                            # Publish discovery config
                            await mqtt_manager.publish_discovery(sensor)
                            logger.debug(f"[Server] Published discovery for {sensor.sensor_id}")

                            # Publish initial state if sensor has current_value
                            if sensor.current_value:
                                await mqtt_manager.publish_state(sensor, sensor.current_value)
                                logger.info(f"[Server] Published initial state for {sensor.sensor_id}: {sensor.current_value}")
                        except Exception as e:
                            logger.error(f"[Server] Failed to publish discovery for {sensor.sensor_id}: {e}")
                else:
                    logger.debug(f"[Server] Device discovered: {device_id} - No sensors configured yet")

                # Publish action discoveries
                actions = action_manager.list_actions(device_id)
                if actions:
                    logger.info(f"[Server] Device discovered: {device_id} - Publishing MQTT discovery for {len(actions)} actions")
                    for action_def in actions:
                        try:
                            await mqtt_manager.publish_action_discovery(action_def)
                            logger.debug(f"[Server] Published action discovery for {action_def.id}")
                        except Exception as e:
                            logger.error(f"[Server] Failed to publish action discovery for {action_def.id}: {e}")
                else:
                    logger.debug(f"[Server] Device discovered: {device_id} - No actions configured yet")
            except Exception as e:
                logger.error(f"[Server] Failed to publish discoveries for {device_id}: {e}")

        adb_bridge.register_device_discovered_callback(on_device_discovered)

        # Background task to publish discovery for already-connected devices
        async def publish_existing_devices():
            """Wait for device discovery to complete, then publish MQTT for existing devices"""
            await asyncio.sleep(35)  # Wait for device discovery timeout (30s) + buffer
            try:
                devices = await adb_bridge.get_devices()
                for device in devices:
                    device_id = device["id"]

                    # Publish sensor discoveries
                    sensors = sensor_manager.get_all_sensors(device_id)
                    if sensors:
                        logger.info(f"[Server] Publishing delayed discovery for existing device: {device_id} ({len(sensors)} sensors)")
                        for sensor in sensors:
                            try:
                                # Publish discovery config
                                await mqtt_manager.publish_discovery(sensor)
                                logger.debug(f"[Server] Published delayed discovery for {sensor.sensor_id}")

                                # Publish initial state if sensor has current_value
                                if sensor.current_value:
                                    await mqtt_manager.publish_state(sensor, sensor.current_value)
                                    logger.info(f"[Server] Published delayed state for {sensor.sensor_id}: {sensor.current_value}")
                            except Exception as e:
                                logger.error(f"[Server] Failed delayed discovery for {sensor.sensor_id}: {e}")

                    # Publish action discoveries
                    actions = action_manager.list_actions(device_id)
                    if actions:
                        logger.info(f"[Server] Publishing delayed discovery for existing device: {device_id} ({len(actions)} actions)")
                        for action_def in actions:
                            try:
                                await mqtt_manager.publish_action_discovery(action_def)
                                logger.debug(f"[Server] Published delayed action discovery for {action_def.id}")
                            except Exception as e:
                                logger.error(f"[Server] Failed delayed action discovery for {action_def.id}: {e}")
            except Exception as e:
                logger.error(f"[Server] Failed to publish delayed discoveries: {e}")

        asyncio.create_task(publish_existing_devices())

        # Register action command callback to handle MQTT button presses from HA
        async def on_action_command(device_id: str, action_id: str):
            """Callback triggered when HA sends action execution command via MQTT"""
            try:
                logger.info(f"[Server] MQTT action command received: {device_id}/{action_id}")
                result = await action_executor.execute_action_by_id(action_manager, device_id, action_id)
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
        logger.warning("[Server] ⚠️ Failed to connect to MQTT broker - sensor updates disabled")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("[Server] Shutting down Visual Mapper...")

    # Stop all sensor updates
    if sensor_updater:
        await sensor_updater.stop_all_updates()

    # Disconnect from MQTT
    if mqtt_manager:
        await mqtt_manager.disconnect()

    logger.info("[Server] Shutdown complete")


# Health check endpoint (must be defined BEFORE static files mount)
@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    mqtt_status = "connected" if (mqtt_manager and mqtt_manager.is_connected) else "disconnected"

    return {
        "status": "ok",
        "version": "0.0.5",
        "message": "Visual Mapper is running",
        "mqtt_status": mqtt_status
    }

# =============================================================================
# PERFORMANCE METRICS ENDPOINTS
# =============================================================================

@app.get("/api/performance/metrics")
async def get_performance_metrics():
    """
    Get comprehensive performance metrics for monitoring and optimization.

    Returns aggregated metrics from all subsystems:
    - Screenshot cache hit rate
    - ADB connection pool status
    - Performance monitor statistics
    - MQTT publishing stats
    """
    metrics = {
        "timestamp": time.time(),
        "version": "0.0.5",
    }

    # Screenshot cache statistics
    if adb_bridge:
        cache_stats = adb_bridge.get_cache_stats()
        metrics["screenshot_cache"] = cache_stats

    # ADB connection pool stats (if available)
    if adb_bridge:
        try:
            # Get connected devices count
            devices = await adb_bridge.list_devices()
            metrics["adb_connections"] = {
                "total_devices": len(devices),
                "connected_devices": len([d for d in devices if d.get("connected", False)]),
                "device_ids": [d["id"] for d in devices]
            }
        except Exception as e:
            logger.error(f"[API] Failed to get ADB stats: {e}")
            metrics["adb_connections"] = {"error": str(e)}

    # Performance monitor stats (if available)
    if performance_monitor:
        try:
            perf_stats = await performance_monitor.get_stats()
            metrics["performance"] = perf_stats
        except Exception as e:
            logger.error(f"[API] Failed to get performance stats: {e}")
            metrics["performance"] = {"error": str(e)}

    # MQTT stats
    if mqtt_manager:
        metrics["mqtt"] = {
            "connected": mqtt_manager.is_connected,
            "broker": mqtt_manager.broker_host if hasattr(mqtt_manager, 'broker_host') else "unknown"
        }

    return metrics


@app.get("/api/performance/cache")
async def get_cache_stats():
    """
    Get detailed screenshot cache statistics.

    Useful for tuning cache TTL and monitoring cache effectiveness.
    High hit rate (>80%) indicates effective caching.
    """
    if not adb_bridge:
        raise HTTPException(status_code=503, detail="ADB bridge not initialized")

    return adb_bridge.get_cache_stats()


@app.post("/api/performance/cache/clear")
async def clear_cache():
    """
    Clear screenshot cache for all devices.

    Useful for testing or forcing fresh captures.
    """
    if not adb_bridge:
        raise HTTPException(status_code=503, detail="ADB bridge not initialized")

    try:
        # Clear the cache
        adb_bridge._screenshot_cache.clear()
        adb_bridge._screenshot_cache_hits = 0
        adb_bridge._screenshot_cache_misses = 0

        return {
            "success": True,
            "message": "Screenshot cache cleared",
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[API] Failed to clear cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/performance/adb")
async def get_adb_performance():
    """
    Get ADB subsystem performance metrics.

    Includes connection health, response times, and optimization status.
    """
    if not adb_bridge:
        raise HTTPException(status_code=503, detail="ADB bridge not initialized")

    try:
        devices = await adb_bridge.list_devices()

        return {
            "timestamp": time.time(),
            "devices": {
                "total": len(devices),
                "connected": len([d for d in devices if d.get("connected", False)]),
                "models": [d.get("model", "Unknown") for d in devices]
            },
            "cache": adb_bridge.get_cache_stats(),
            "optimizations": {
                "screenshot_cache_enabled": adb_bridge._screenshot_cache_enabled,
                "cache_ttl_ms": adb_bridge._screenshot_cache_ttl_ms,
                "bounds_only_mode": "Available",
                "batch_commands": "Available",
                "persistent_shell_pool": "Initialized"
            }
        }
    except Exception as e:
        logger.error(f"[API] Failed to get ADB performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DIAGNOSTICS ENDPOINTS
# =============================================================================

@app.get("/api/diagnostics/adb/{device_id}")
async def get_adb_diagnostics(device_id: str, samples: int = 5):
    """
    Run ADB diagnostic tests and return comprehensive timing info.
    Helps debug performance issues by benchmarking capture speed.

    Args:
        device_id: The ADB device ID
        samples: Number of screenshot samples to take (1-10, default 5)
    """
    import time
    import subprocess

    # Clamp samples to reasonable range
    samples = max(1, min(10, samples))

    results = {
        "device_id": device_id,
        "timestamp": time.time(),
        "connection_type": "unknown",
        "adb_version": None,
        "device_info": {},
        "screenshot_benchmark": {
            "samples_ms": [],
            "min_ms": None,
            "max_ms": None,
            "avg_ms": None,
            "success_count": 0,
            "failure_count": 0
        },
        "ui_dump_timing": {
            "time_ms": None,
            "element_count": 0
        },
        "errors": []
    }

    # Get ADB version
    try:
        adb_version = subprocess.run(["adb", "version"], capture_output=True, text=True, timeout=5)
        if adb_version.returncode == 0:
            results["adb_version"] = adb_version.stdout.strip().split('\n')[0]
    except Exception as e:
        results["errors"].append(f"ADB version check failed: {e}")

    # Check connection type (USB vs WiFi)
    try:
        if ':' in device_id and not device_id.startswith('emulator'):
            results["connection_type"] = "wifi"
        else:
            results["connection_type"] = "usb"
    except:
        pass

    # Get device info
    try:
        device_info = await adb_bridge.get_device_info(device_id)
        results["device_info"] = device_info
    except Exception as e:
        results["errors"].append(f"Device info failed: {e}")

    # Screenshot benchmark (configurable samples)
    logger.info(f"[Diagnostics] Running screenshot benchmark for {device_id} ({samples} samples)")
    sample_times = []
    for i in range(samples):
        try:
            start = time.time()
            screenshot = await adb_bridge.capture_screenshot(device_id)
            elapsed = (time.time() - start) * 1000  # ms

            if screenshot and len(screenshot) > 1000:
                sample_times.append(elapsed)
                results["screenshot_benchmark"]["success_count"] += 1
            else:
                results["screenshot_benchmark"]["failure_count"] += 1
                results["errors"].append(f"Sample {i+1}: Empty screenshot")
        except Exception as e:
            results["screenshot_benchmark"]["failure_count"] += 1
            results["errors"].append(f"Sample {i+1}: {e}")

    if sample_times:
        results["screenshot_benchmark"]["samples_ms"] = [round(s, 1) for s in sample_times]
        results["screenshot_benchmark"]["min_ms"] = round(min(sample_times), 1)
        results["screenshot_benchmark"]["max_ms"] = round(max(sample_times), 1)
        results["screenshot_benchmark"]["avg_ms"] = round(sum(sample_times) / len(sample_times), 1)

    # UI dump timing
    try:
        start = time.time()
        elements = await adb_bridge.get_ui_elements(device_id)
        elapsed = (time.time() - start) * 1000
        results["ui_dump_timing"]["time_ms"] = round(elapsed, 1)
        results["ui_dump_timing"]["element_count"] = len(elements) if elements else 0
    except Exception as e:
        results["errors"].append(f"UI dump failed: {e}")

    logger.info(f"[Diagnostics] Benchmark complete: avg={results['screenshot_benchmark']['avg_ms']}ms")
    return results


# Global streaming metrics (updated by streaming endpoints)
streaming_metrics = {}

@app.get("/api/diagnostics/streaming/{device_id}")
async def get_streaming_diagnostics(device_id: str):
    """Get current streaming performance metrics for a device."""
    # First try stream_manager metrics (enhanced)
    if stream_manager:
        sm_metrics = stream_manager.get_metrics(device_id)
        if sm_metrics:
            return {
                "active": True,
                "mode": "enhanced",
                "source": "stream_manager",
                **sm_metrics
            }

    # Fall back to global streaming_metrics
    metrics = streaming_metrics.get(device_id, {
        "active": False,
        "mode": None,
        "current_fps": 0,
        "avg_capture_time_ms": 0,
        "frames_sent": 0,
        "frames_dropped": 0,
        "last_frame_time": None,
        "connection_duration_s": 0
    })
    return metrics


@app.get("/api/diagnostics/benchmark/{device_id}")
async def benchmark_capture(device_id: str, iterations: int = 5):
    """
    Benchmark capture performance across different backends.

    Compares adbutils vs adb_bridge capture speeds.
    """
    if not stream_manager:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    if device_id not in adb_bridge.devices:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    logger.info(f"[Diagnostics] Running capture benchmark for {device_id} ({iterations} iterations)")
    results = await stream_manager.benchmark_capture(device_id, iterations)
    logger.info(f"[Diagnostics] Benchmark complete: recommended={results.get('recommended_backend')}")
    return results


@app.get("/api/diagnostics/system")
async def get_system_diagnostics():
    """Get overall system diagnostics - CPU, memory, connected devices."""
    import platform

    result = {
        "platform": platform.system(),
        "python_version": platform.python_version(),
        "cpu_percent": 0.0,
        "memory_used_mb": 0,
        "memory_total_mb": 0,
        "connected_devices": len(adb_bridge.devices),
        "active_streams": len([d for d, m in streaming_metrics.items() if m.get("active")]),
        "mqtt_connected": mqtt_manager.is_connected if mqtt_manager else False,
        "uptime_seconds": 0,
        # Flow scheduler status
        "flow_scheduler": {
            "running": flow_scheduler.is_running if flow_scheduler else False,
            "paused": flow_scheduler.is_paused if flow_scheduler else False,
            "active_flows": len(flow_scheduler.device_tasks) if flow_scheduler else 0
        } if flow_scheduler else None
    }

    # Try to get psutil metrics (optional dependency)
    try:
        import psutil
        result["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        result["memory_used_mb"] = round(mem.used / (1024 * 1024))
        result["memory_total_mb"] = round(mem.total / (1024 * 1024))

        # Get process uptime
        import os
        process = psutil.Process(os.getpid())
        result["uptime_seconds"] = int(time.time() - process.create_time())
    except ImportError:
        logger.warning("[Diagnostics] psutil not installed - system metrics unavailable")
    except Exception as e:
        logger.error(f"[Diagnostics] Error getting system metrics: {e}")

    return result


# === ADB Maintenance Endpoints ===

@app.post("/api/maintenance/server/restart")
async def restart_adb_server():
    """Restart ADB server to fix zombie processes and connection issues"""
    if not adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await adb_maintenance.restart_adb_server()


@app.get("/api/maintenance/server/status")
async def get_adb_server_status():
    """Get ADB server status and connected devices"""
    if not adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await adb_maintenance.get_server_status()


@app.post("/api/maintenance/{device_id}/trim-cache")
async def trim_device_cache(device_id: str):
    """Clear all app caches on device to free storage and improve performance"""
    if not adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await adb_maintenance.trim_cache(device_id)


@app.post("/api/maintenance/{device_id}/compile-apps")
async def compile_device_apps(device_id: str, mode: str = "speed-profile"):
    """Force ART compilation for faster app launches (takes 5-15 minutes)

    Modes: speed-profile (recommended), speed, verify, quicken
    """
    if not adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await adb_maintenance.compile_apps(device_id, mode)


@app.post("/api/maintenance/{device_id}/optimize-ui")
async def optimize_device_ui(device_id: str):
    """Disable visual effects for faster UI operations"""
    if not adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await adb_maintenance.optimize_ui(device_id)


@app.post("/api/maintenance/{device_id}/reset-ui")
async def reset_device_ui(device_id: str):
    """Reset UI animations and effects to defaults"""
    if not adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await adb_maintenance.reset_ui_optimizations(device_id)


@app.post("/api/maintenance/{device_id}/full-optimize")
async def full_device_optimize(device_id: str):
    """Run full optimization suite (cache + UI)"""
    if not adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await adb_maintenance.full_optimize(device_id)


@app.post("/api/maintenance/{device_id}/reset-display")
async def reset_device_display(device_id: str):
    """Emergency reset of display size and density"""
    if not adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await adb_maintenance.reset_display(device_id)


@app.get("/api/maintenance/{device_id}/background-limit")
async def get_background_limit(device_id: str):
    """Get current background process limit"""
    if not adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await adb_maintenance.get_background_limit(device_id)


@app.post("/api/maintenance/{device_id}/background-limit")
async def set_background_limit(device_id: str, limit: int = 4):
    """Set background process limit (0-4, -1 for default)"""
    if not adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return await adb_maintenance.set_background_limit(device_id, limit)


@app.get("/api/maintenance/metrics")
async def get_all_connection_metrics():
    """Get connection health metrics for all devices"""
    if not adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    return {"success": True, "metrics": adb_maintenance.get_all_metrics()}


@app.get("/api/maintenance/{device_id}/metrics")
async def get_device_connection_metrics(device_id: str):
    """Get connection health metrics for a specific device"""
    if not adb_maintenance:
        raise HTTPException(status_code=503, detail="ADB Maintenance not initialized")
    metrics = adb_maintenance.get_connection_metrics(device_id)
    if not metrics:
        return {"success": True, "metrics": None, "message": "No metrics yet for this device"}
    return {"success": True, "metrics": metrics}


# === UI Hierarchy Cache Endpoints ===

@app.get("/api/cache/ui/stats")
async def get_ui_cache_stats():
    """Get UI hierarchy cache statistics"""
    if not adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    return {"success": True, "cache": adb_bridge.get_ui_cache_stats()}


@app.post("/api/cache/ui/clear")
async def clear_ui_cache(device_id: str = None):
    """Clear UI hierarchy cache for a device or all devices"""
    if not adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    adb_bridge.clear_ui_cache(device_id)
    return {
        "success": True,
        "message": f"UI cache cleared for {device_id}" if device_id else "UI cache cleared for all devices"
    }


@app.post("/api/cache/ui/settings")
async def update_ui_cache_settings(enabled: bool = None, ttl_ms: float = None):
    """Update UI hierarchy cache settings"""
    if not adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")

    if enabled is not None:
        adb_bridge.set_ui_cache_enabled(enabled)
    if ttl_ms is not None:
        adb_bridge.set_ui_cache_ttl(ttl_ms)

    return {"success": True, "cache": adb_bridge.get_ui_cache_stats()}


# === Screenshot Cache Endpoints ===

@app.get("/api/cache/screenshot/stats")
async def get_screenshot_cache_stats():
    """Get screenshot cache statistics"""
    if not adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    return {"success": True, "cache": adb_bridge.get_screenshot_cache_stats()}


@app.post("/api/cache/screenshot/settings")
async def update_screenshot_cache_settings(enabled: bool = None, ttl_ms: float = None):
    """Update screenshot cache settings"""
    if not adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")

    if enabled is not None:
        adb_bridge.set_screenshot_cache_enabled(enabled)
    if ttl_ms is not None:
        adb_bridge.set_screenshot_cache_ttl(ttl_ms)

    return {"success": True, "cache": adb_bridge.get_screenshot_cache_stats()}


@app.get("/api/cache/all/stats")
async def get_all_cache_stats():
    """Get all cache statistics (UI + Screenshot)"""
    if not adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    return {
        "success": True,
        "ui_cache": adb_bridge.get_ui_cache_stats(),
        "screenshot_cache": adb_bridge.get_screenshot_cache_stats()
    }


# === Stream Isolation Stats ===

@app.get("/api/stream/stats")
async def get_stream_isolation_stats():
    """Get streaming isolation statistics (separate from screenshots)"""
    if not adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    return {"success": True, "stream": adb_bridge.get_stream_stats()}


@app.get("/api/stream/{device_id}/stats")
async def get_device_stream_stats(device_id: str):
    """Get streaming stats for a specific device"""
    if not adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")
    return {"success": True, "stream": adb_bridge.get_stream_stats(device_id)}


# === Persistent Shell Pool Endpoints ===

@app.get("/api/shell/stats")
async def get_shell_pool_stats():
    """Get persistent shell pool statistics"""
    if not shell_pool:
        raise HTTPException(status_code=503, detail="Shell pool not initialized")
    return {"success": True, "stats": shell_pool.get_stats()}


@app.post("/api/shell/{device_id}/execute")
async def execute_shell_command(device_id: str, request: ShellExecuteRequest):
    """Execute a command using persistent shell session (faster than individual adb shell calls)"""
    if not shell_pool:
        raise HTTPException(status_code=503, detail="Shell pool not initialized")

    try:
        shell = await shell_pool.get_shell(device_id)
        success, output = await shell.execute(request.command)
        return {
            "success": success,
            "output": output,
            "session": shell.stats
        }
    except Exception as e:
        logger.error(f"[Shell] Execute error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/shell/{device_id}/batch")
async def execute_shell_batch(device_id: str, request: ShellBatchRequest):
    """Execute multiple commands in a persistent shell session"""
    if not shell_pool:
        raise HTTPException(status_code=503, detail="Shell pool not initialized")

    try:
        shell = await shell_pool.get_shell(device_id)
        results = await shell.execute_batch(request.commands)
        return {
            "success": True,
            "results": [{"success": r[0], "output": r[1]} for r in results],
            "session": shell.stats
        }
    except Exception as e:
        logger.error(f"[Shell] Batch execute error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/shell/{device_id}/benchmark")
async def benchmark_shell_session(device_id: str, iterations: int = 10):
    """Benchmark persistent shell vs regular adb shell performance"""
    if not shell_pool:
        raise HTTPException(status_code=503, detail="Shell pool not initialized")
    if not adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")

    test_command = "echo test"
    results = {
        "persistent_shell": {"times_ms": [], "avg_ms": 0},
        "regular_adb": {"times_ms": [], "avg_ms": 0},
        "improvement_percent": 0
    }

    # Benchmark persistent shell
    try:
        shell = await shell_pool.get_shell(device_id)
        for _ in range(iterations):
            start = time.time()
            await shell.execute(test_command)
            elapsed = (time.time() - start) * 1000
            results["persistent_shell"]["times_ms"].append(round(elapsed, 1))
    except Exception as e:
        logger.error(f"[Shell] Benchmark persistent shell error: {e}")
        results["persistent_shell"]["error"] = str(e)

    # Benchmark regular adb shell (spawning new process each time)
    try:
        for _ in range(iterations):
            start = time.time()
            proc = await asyncio.create_subprocess_exec(
                'adb', '-s', device_id, 'shell', test_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            elapsed = (time.time() - start) * 1000
            results["regular_adb"]["times_ms"].append(round(elapsed, 1))
    except Exception as e:
        logger.error(f"[Shell] Benchmark regular adb error: {e}")
        results["regular_adb"]["error"] = str(e)

    # Calculate averages
    if results["persistent_shell"]["times_ms"]:
        results["persistent_shell"]["avg_ms"] = round(
            sum(results["persistent_shell"]["times_ms"]) / len(results["persistent_shell"]["times_ms"]), 1
        )
    if results["regular_adb"]["times_ms"]:
        results["regular_adb"]["avg_ms"] = round(
            sum(results["regular_adb"]["times_ms"]) / len(results["regular_adb"]["times_ms"]), 1
        )

    # Calculate improvement
    if results["regular_adb"]["avg_ms"] > 0 and results["persistent_shell"]["avg_ms"] > 0:
        improvement = (
            (results["regular_adb"]["avg_ms"] - results["persistent_shell"]["avg_ms"])
            / results["regular_adb"]["avg_ms"]
        ) * 100
        results["improvement_percent"] = round(improvement, 1)

    return {"success": True, "benchmark": results, "iterations": iterations}


@app.delete("/api/shell/{device_id}")
async def close_device_shells(device_id: str):
    """Close all persistent shell sessions for a device"""
    if not shell_pool:
        raise HTTPException(status_code=503, detail="Shell pool not initialized")

    await shell_pool.close_device_sessions(device_id)
    return {"success": True, "message": f"Closed all shell sessions for {device_id}"}


# Root API info
@app.get("/api/")
async def api_root():
    """API root endpoint"""
    return {
        "name": "Visual Mapper API",
        "version": "0.0.5",
        "endpoints": {
            "health": "/api/health",
            "diagnostics_adb": "/api/diagnostics/adb/{device_id}",
            "diagnostics_streaming": "/api/diagnostics/streaming/{device_id}",
            "diagnostics_benchmark": "/api/diagnostics/benchmark/{device_id}",
            "diagnostics_system": "/api/diagnostics/system",
            "connect": "/api/adb/connect",
            "pair": "/api/adb/pair",
            "disconnect": "/api/adb/disconnect",
            "devices": "/api/adb/devices",
            "screenshot": "/api/adb/screenshot",
            "sensors": "/api/sensors",
            "sensors_by_device": "/api/sensors/{device_id}",
            "sensor_detail": "/api/sensors/{device_id}/{sensor_id}",
            "device_classes": "/api/device-classes",
            "shell_stats": "/api/shell/stats",
            "shell_execute": "/api/shell/{device_id}/execute",
            "shell_batch": "/api/shell/{device_id}/batch",
            "shell_benchmark": "/api/shell/{device_id}/benchmark",
            "maintenance_server_restart": "/api/maintenance/server/restart",
            "maintenance_metrics": "/api/maintenance/metrics"
        }
    }


@app.get("/api/device-classes")
async def get_device_classes():
    """
    Get comprehensive Home Assistant device class reference.
    Includes all sensor types, units, icons, and validation rules.

    This is a local reference file, not pulled from Home Assistant.
    Works in both standalone and add-on modes.
    """
    try:
        return export_device_classes()
    except Exception as e:
        logger.error(f"[API] Failed to export device classes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Device Management Endpoints
@app.post("/api/adb/connect")
async def connect_device(request: ConnectDeviceRequest):
    """Connect to Android device via TCP/IP"""
    try:
        logger.info(f"[API] Connecting to {request.host}:{request.port}")
        device_id = await adb_bridge.connect_device(request.host, request.port)
        return {
            "device_id": device_id,
            "connected": True,
            "message": f"Connected to {device_id}"
        }
    except Exception as e:
        logger.error(f"[API] Connection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/adb/pair")
async def pair_device(request: PairingRequest):
    """Pair with Android 11+ device using wireless pairing

    Android 11+ wireless debugging uses TWO ports:
    - Pairing port (e.g., 37899) - for initial pairing with code
    - Connection port (e.g., 45441) - for actual ADB connection after pairing
    """
    try:
        logger.info(f"[API] Pairing with {request.pairing_host}:{request.pairing_port}")

        # Step 1: Pair with pairing port using code
        success = await adb_bridge.pair_device(
            request.pairing_host,
            request.pairing_port,
            request.pairing_code
        )

        if not success:
            raise HTTPException(status_code=500, detail="Pairing failed - check code and port")

        # Step 2: Connect on connection port (NOT 5555!) after successful pairing
        logger.info(f"[API] Pairing successful, connecting on port {request.connection_port}")
        device_id = await adb_bridge.connect_device(request.pairing_host, request.connection_port)

        return {
            "success": True,
            "device_id": device_id,
            "message": f"Paired and connected to {device_id}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Pairing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/adb/disconnect")
async def disconnect_device(request: DisconnectDeviceRequest):
    """Disconnect from Android device"""
    try:
        logger.info(f"[API] Disconnecting from {request.device_id}")
        await adb_bridge.disconnect_device(request.device_id)
        return {
            "device_id": request.device_id,
            "disconnected": True,
            "message": f"Disconnected from {request.device_id}"
        }
    except Exception as e:
        logger.error(f"[API] Disconnection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/adb/devices")
async def get_devices():
    """Get list of connected devices"""
    try:
        devices = await adb_bridge.get_devices()
        return {"devices": devices}
    except Exception as e:
        logger.error(f"[API] Failed to get devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Screenshot Capture Endpoint
@app.post("/api/adb/screenshot")
async def capture_screenshot(request: ScreenshotRequest):
    """Capture screenshot and UI elements from device

    Quick mode (quick=true): Only captures screenshot image, skips UI element extraction
    Normal mode (quick=false): Captures both screenshot and UI elements
    """
    try:
        mode = "quick" if request.quick else "full"
        logger.info(f"[API] Capturing {mode} screenshot from {request.device_id}")

        # Capture PNG screenshot
        screenshot_bytes = await adb_bridge.capture_screenshot(request.device_id)

        # Extract UI elements (skip if quick mode)
        if request.quick:
            elements = []
            logger.info(f"[API] Quick screenshot captured: {len(screenshot_bytes)} bytes (UI elements skipped)")
        else:
            elements = await adb_bridge.get_ui_elements(request.device_id)
            logger.info(f"[API] Full screenshot captured: {len(screenshot_bytes)} bytes, {len(elements)} UI elements")

        # Encode screenshot to base64
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        return {
            "screenshot": screenshot_base64,
            "elements": elements,
            "timestamp": datetime.now().isoformat(),
            "quick": request.quick
        }
    except ValueError as e:
        logger.error(f"[API] Screenshot failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Screenshot failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Fast Elements-Only Endpoint (for streaming mode)
@app.get("/api/adb/elements/{device_id}")
async def get_elements_only(device_id: str):
    """Get UI elements without capturing screenshot (faster for streaming mode)"""
    try:
        logger.info(f"[API] Getting elements only from {device_id}")
        elements = await adb_bridge.get_ui_elements(device_id)
        logger.info(f"[API] Got {len(elements)} elements")

        # Note: Device dimensions are provided by MJPEG config when streaming starts.
        # This endpoint returns elements-only for speed. If dimensions are needed,
        # they should come from the stream config or a separate dimensions endpoint.

        return {
            "success": True,
            "elements": elements,
            "count": len(elements),
            "timestamp": datetime.now().isoformat()
        }
    except ValueError as e:
        logger.warning(f"[API] Elements request failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Elements failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Screenshot Stitching Endpoint
@app.post("/api/adb/screenshot/stitch")
async def capture_stitched_screenshot(request: ScreenshotStitchRequest):
    """Capture full scrollable page by stitching multiple screenshots"""
    try:
        logger.info(f"[API] Capturing stitched screenshot from {request.device_id}")
        logger.debug(f"  max_scrolls={request.max_scrolls}, scroll_ratio={request.scroll_ratio}, overlap_ratio={request.overlap_ratio}")

        if screenshot_stitcher is None:
            logger.error(f"[API] ScreenshotStitcher not initialized")
            raise HTTPException(status_code=500, detail="Screenshot stitcher not available")

        # Capture scrolling screenshot using new modular implementation
        result = await screenshot_stitcher.capture_scrolling_screenshot(
            request.device_id,
            max_scrolls=request.max_scrolls,
            scroll_ratio=request.scroll_ratio,
            overlap_ratio=request.overlap_ratio
        )

        # Convert PIL Image to base64
        img_buffer = io.BytesIO()
        result['image'].save(img_buffer, format='PNG')
        img_buffer.seek(0)
        screenshot_base64 = base64.b64encode(img_buffer.read()).decode('utf-8')

        logger.info(f"[API] Stitched screenshot captured: {result['metadata']}")
        logger.info(f"[API] Combined elements: {len(result.get('elements', []))}")

        return {
            "screenshot": screenshot_base64,
            "elements": result.get('elements', []),
            "metadata": result['metadata'],
            "debug_screenshots": result.get('debug_screenshots', []),
            "timestamp": datetime.now().isoformat()
        }
    except ValueError as e:
        logger.error(f"[API] Stitched screenshot failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Stitched screenshot failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))



# Device Control Endpoints
@app.post("/api/adb/tap")
async def tap_device(request: TapRequest):
    """Simulate tap at coordinates on device"""
    try:
        logger.info(f"[API] Tap at ({request.x}, {request.y}) on {request.device_id}")
        await adb_bridge.tap(request.device_id, request.x, request.y)
        return {
            "success": True,
            "device_id": request.device_id,
            "x": request.x,
            "y": request.y,
            "message": f"Tapped at ({request.x}, {request.y})"
        }
    except Exception as e:
        logger.error(f"[API] Tap failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/adb/swipe")
async def swipe_device(request: SwipeRequest):
    """Simulate swipe gesture on device"""
    try:
        logger.info(f"[API] Swipe ({request.x1},{request.y1}) -> ({request.x2},{request.y2}) on {request.device_id}")
        await adb_bridge.swipe(
            request.device_id,
            request.x1, request.y1,
            request.x2, request.y2,
            request.duration
        )
        return {
            "success": True,
            "device_id": request.device_id,
            "from": {"x": request.x1, "y": request.y1},
            "to": {"x": request.x2, "y": request.y2},
            "duration": request.duration,
            "message": f"Swiped from ({request.x1},{request.y1}) to ({request.x2},{request.y2})"
        }
    except Exception as e:
        logger.error(f"[API] Swipe failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/adb/text")
async def input_text(request: TextInputRequest):
    """Type text on device"""
    try:
        logger.info(f"[API] Type text on {request.device_id}: {request.text[:20]}...")
        await adb_bridge.type_text(request.device_id, request.text)
        return {
            "success": True,
            "device_id": request.device_id,
            "text": request.text,
            "message": f"Typed {len(request.text)} characters"
        }
    except Exception as e:
        logger.error(f"[API] Text input failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/adb/keyevent")
async def send_keyevent(request: KeyEventRequest):
    """Send hardware key event to device"""
    try:
        logger.info(f"[API] Key event {request.keycode} on {request.device_id}")
        await adb_bridge.keyevent(request.device_id, request.keycode)
        return {
            "success": True,
            "device_id": request.device_id,
            "keycode": request.keycode,
            "message": f"Sent key event: {request.keycode}"
        }
    except Exception as e:
        logger.error(f"[API] Key event failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/adb/back")
async def send_back_key(request: dict):
    """Send BACK key event to device (convenience endpoint)"""
    try:
        device_id = request.get("device_id")
        if not device_id:
            raise HTTPException(status_code=400, detail="device_id required")
        logger.info(f"[API] Back key on {device_id}")
        await adb_bridge.keyevent(device_id, "KEYCODE_BACK")
        return {"success": True, "device_id": device_id, "message": "Back key sent"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Back key failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/adb/home")
async def send_home_key(request: dict):
    """Send HOME key event to device (convenience endpoint)"""
    try:
        device_id = request.get("device_id")
        if not device_id:
            raise HTTPException(status_code=400, detail="device_id required")
        logger.info(f"[API] Home key on {device_id}")
        await adb_bridge.keyevent(device_id, "KEYCODE_HOME")
        return {"success": True, "device_id": device_id, "message": "Home key sent"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Home key failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/adb/activity/{device_id}")
async def get_current_activity(device_id: str):
    """Get current focused activity/window on device"""
    try:
        logger.info(f"[API] Getting current activity for {device_id}")
        activity = await adb_bridge.get_current_activity(device_id)
        return {
            "success": True,
            "device_id": device_id,
            "activity": activity,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[API] Get activity failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/screen/current/{device_id}")
async def get_current_screen(device_id: str):
    """
    Get current screen info (activity with package/activity breakdown).
    Used for screen awareness in Flow Wizard.

    Returns:
        activity: {package, activity, full_name}
        element_count: Number of UI elements on screen
        timestamp: Current time
    """
    try:
        logger.info(f"[API] Getting current screen info for {device_id}")

        # Get activity info as dict (with package breakdown)
        activity_info = await adb_bridge.get_current_activity(device_id, as_dict=True)

        return {
            "success": True,
            "device_id": device_id,
            "activity": activity_info,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[API] Get screen info failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/adb/apps/{device_id}")
async def get_installed_apps(device_id: str):
    """Get list of installed apps on device"""
    try:
        logger.info(f"[API] Getting installed apps for {device_id}")
        apps = await adb_bridge.get_installed_apps(device_id)
        return {
            "success": True,
            "device_id": device_id,
            "apps": apps,
            "count": len(apps),
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[API] Get apps failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/adb/app-icon/{device_id}/{package_name}")
async def get_app_icon(device_id: str, package_name: str, skip_extraction: bool = False):
    """
    Get app icon - multi-tier approach for optimal performance

    Multi-Tier Loading Strategy:
    0. Device-specific cache (scraped from device) - INSTANT ✅ 🏆 BEST QUALITY
    1. Play Store cache (pre-populated/scraped) - INSTANT ✅
    2. APK extraction cache (previously extracted) - INSTANT ✅
    3. If skip_extraction=true: Return SVG immediately - INSTANT ✅
    4. Play Store scrape (on-demand) - 1-2 seconds ⏱️
    5. APK extraction (for system/OEM apps) - 10-30 seconds ⏱️⏱️
    6. SVG fallback - INSTANT ✅

    Args:
        device_id: ADB device ID
        package_name: App package name
        skip_extraction: If true, skip slow methods (scraping/extraction) and return SVG

    Returns:
        Icon image data (PNG/WebP/SVG)
    """
    from fastapi.responses import Response

    # Tier 0: Check device-specific cache (INSTANT + BEST QUALITY)
    # This is scraped from the actual device app drawer, so it respects:
    # - User's launcher theme
    # - Adaptive icons (rendered correctly)
    # - Custom icon packs
    # - OEM customizations
    if device_icon_scraper:
        icon_data = device_icon_scraper.get_icon(device_id, package_name)
        if icon_data:
            logger.debug(f"[API] 🏆 Tier 0: Device-specific cache hit for {package_name}")
            return Response(content=icon_data, media_type="image/png", headers={"X-Icon-Source": "device-scraper"})

    # Tier 1: Check Play Store cache (INSTANT)
    if playstore_icon_scraper:
        from pathlib import Path
        playstore_cache = Path(f"data/app-icons-playstore/{package_name}.png")
        if playstore_cache.exists():
            icon_data = playstore_cache.read_bytes()
            logger.debug(f"[API] ✅ Tier 1: Play Store cache hit for {package_name}")
            return Response(content=icon_data, media_type="image/png", headers={"X-Icon-Source": "playstore"})

    # Tier 2: Check APK extraction cache (INSTANT)
    if app_icon_extractor:
        from pathlib import Path
        import glob
        apk_cache_pattern = f"data/app-icons/{package_name}_*.png"
        apk_caches = glob.glob(apk_cache_pattern)
        if apk_caches:
            icon_data = Path(apk_caches[0]).read_bytes()
            logger.debug(f"[API] ✅ Tier 2: APK cache hit for {package_name}")
            return Response(content=icon_data, media_type="image/png", headers={"X-Icon-Source": "apk-extraction"})

    # Tier 3: Not in cache - Trigger background fetch and return SVG immediately
    # Background fetch will populate cache for next request (smart progressive loading)
    if icon_background_fetcher and not skip_extraction:
        icon_background_fetcher.request_icon(device_id, package_name)
        logger.debug(f"[API] 🔄 Tier 3: Background fetch requested for {package_name}")

    # Tier 4: SVG fallback (INSTANT - return immediately while background fetch happens)
    first_letter = package_name.split('.')[-1][0].upper() if package_name else 'A'
    hash_val = hash(package_name) % 360
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
        <rect width="48" height="48" fill="hsl({hash_val}, 70%, 60%)" rx="8"/>
        <text x="24" y="32" font-family="Arial, sans-serif" font-size="24" font-weight="bold"
              fill="white" text-anchor="middle">{first_letter}</text>
    </svg>'''
    logger.debug(f"[API] ⚪ Tier 4: SVG fallback for {package_name} (background fetch in progress)")
    return Response(content=svg, media_type="image/svg+xml", headers={"X-Icon-Source": "svg-placeholder"})


@app.post("/api/adb/prefetch-icons/{device_id}")
async def prefetch_app_icons(device_id: str, max_apps: Optional[int] = None):
    """
    Prefetch app icons in background (Play Store + APK extraction)

    This triggers background fetching for all apps on the device.
    Icons load instantly from cache on subsequent requests.

    Args:
        device_id: ADB device ID
        max_apps: Maximum number of apps to prefetch (None = all)

    Returns:
        {
            "success": true,
            "apps_queued": 375,
            "queue_stats": {...}
        }
    """
    try:
        if not icon_background_fetcher:
            raise HTTPException(status_code=500, detail="Background icon fetcher not initialized")

        logger.info(f"[API] Starting background icon prefetch for {device_id}")

        # Get list of installed apps
        apps = await adb_bridge.get_installed_apps(device_id)
        packages = [app['package'] for app in apps]

        # Queue all apps for background fetch
        await icon_background_fetcher.prefetch_all_apps(device_id, packages, max_apps)

        queue_stats = icon_background_fetcher.get_queue_stats()

        logger.info(f"[API] ✅ Queued {len(packages[:max_apps] if max_apps else packages)} apps for prefetch")

        return {
            "success": True,
            "apps_queued": len(packages[:max_apps] if max_apps else packages),
            "total_apps": len(packages),
            "queue_stats": queue_stats
        }

    except Exception as e:
        logger.error(f"[API] Icon prefetch failed: {e}")
        raise HTTPException(status_code=500, detail=f"Icon prefetch failed: {str(e)}")


@app.get("/api/adb/icon-queue-stats")
async def get_icon_queue_stats():
    """
    Get background icon fetching queue statistics

    Returns:
        {
            "queue_size": 45,
            "processing_count": 1,
            "is_running": true
        }
    """
    try:
        if not icon_background_fetcher:
            raise HTTPException(status_code=500, detail="Background icon fetcher not initialized")

        stats = icon_background_fetcher.get_queue_stats()
        return stats

    except Exception as e:
        logger.error(f"[API] Failed to get queue stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get queue stats: {str(e)}")


@app.get("/api/adb/app-name-queue-stats")
async def get_app_name_queue_stats():
    """
    Get background app name fetching queue statistics

    Returns:
        {
            "queue_size": 45,
            "processing_count": 1,
            "completed_count": 120,
            "failed_count": 5,
            "total_requested": 165,
            "progress_percentage": 75.8,
            "is_running": true
        }
    """
    try:
        if not app_name_background_fetcher:
            raise HTTPException(status_code=500, detail="Background app name fetcher not initialized")

        stats = app_name_background_fetcher.get_queue_stats()
        return stats

    except Exception as e:
        logger.error(f"[API] Failed to get app name queue stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get app name queue stats: {str(e)}")


@app.post("/api/adb/prefetch-app-names/{device_id}")
async def prefetch_app_names(device_id: str, max_apps: Optional[int] = None):
    """
    Prefetch real app names from Google Play Store (background job)

    This should be triggered when device is selected in Flow Wizard to populate
    the app name cache silently in the background.

    Strategy:
    - Returns immediately (non-blocking)
    - Fetches names in background over ~5-10 minutes
    - Names appear in cache for next session
    - Progress visible in dev mode via /api/adb/app-name-queue-stats

    Args:
        device_id: ADB device ID
        max_apps: Maximum number of apps to prefetch (None = all)

    Returns:
        {
            "success": true,
            "queued_count": 165,
            "stats": {...}
        }
    """
    try:
        if not app_name_background_fetcher:
            raise HTTPException(status_code=500, detail="Background app name fetcher not initialized")

        logger.info(f"[API] Starting app name prefetch for {device_id}")

        # Get list of installed apps (returns list of dicts with 'package' key)
        apps = await adb_bridge.get_installed_apps(device_id)
        packages = [app['package'] for app in apps]

        # Queue app name prefetch (non-blocking)
        await app_name_background_fetcher.prefetch_all_apps(packages, max_apps)

        # Get stats
        stats = app_name_background_fetcher.get_queue_stats()

        logger.info(f"[API] ✅ Queued {stats['total_requested']} apps for name prefetch")

        return {
            "success": True,
            "queued_count": stats['total_requested'],
            "stats": stats
        }

    except Exception as e:
        logger.error(f"[API] App name prefetch failed: {e}")
        raise HTTPException(status_code=500, detail=f"App name prefetch failed: {str(e)}")


@app.post("/api/adb/scrape-device-icons/{device_id}")
async def scrape_device_icons(device_id: str, max_apps: Optional[int] = None):
    """
    Scrape app icons from device app drawer (device onboarding)

    This should be triggered:
    1. During device onboarding (first time setup)
    2. When new apps are detected on the device
    3. Manually by user if icons need refresh

    Args:
        device_id: ADB device ID
        max_apps: Maximum number of apps to scrape (None = all)

    Returns:
        {
            "success": true,
            "icons_scraped": 42,
            "total_apps": 120,
            "cache_stats": {...}
        }
    """
    try:
        if not device_icon_scraper:
            raise HTTPException(status_code=500, detail="Device icon scraper not initialized")

        logger.info(f"[API] Starting device icon scraping for {device_id}")

        # Scrape icons from device
        icons_scraped = await device_icon_scraper.scrape_device_icons(device_id, max_apps)

        # Get cache stats
        cache_stats = device_icon_scraper.get_cache_stats(device_id)

        logger.info(f"[API] ✅ Scraped {icons_scraped} icons from {device_id}")

        return {
            "success": True,
            "icons_scraped": icons_scraped,
            "cache_stats": cache_stats
        }
    except Exception as e:
        logger.error(f"[API] Device icon scraping failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/adb/check-icon-cache/{device_id}")
async def check_icon_cache(device_id: str):
    """
    Check if device icon cache needs updating (new apps detected)

    Returns:
        {
            "needs_update": true/false,
            "cache_stats": {...},
            "new_apps_count": 5
        }
    """
    try:
        if not device_icon_scraper:
            raise HTTPException(status_code=500, detail="Device icon scraper not initialized")

        # Get installed apps
        apps = await adb_bridge.get_installed_apps(device_id)
        app_packages = [app['package'] for app in apps]

        # Check if update needed
        needs_update = device_icon_scraper.should_update(device_id, app_packages)

        # Get cache stats
        cache_stats = device_icon_scraper.get_cache_stats(device_id)

        # Calculate new apps count
        from pathlib import Path
        safe_device_id = device_id.replace(':', '_')
        device_cache_dir = Path(f"data/device-icons/{safe_device_id}")
        cached_packages = {f.stem for f in device_cache_dir.glob("*.png")} if device_cache_dir.exists() else set()
        new_apps_count = len(set(app_packages) - cached_packages)

        return {
            "needs_update": needs_update,
            "cache_stats": cache_stats,
            "new_apps_count": new_apps_count,
            "total_apps": len(app_packages)
        }
    except Exception as e:
        logger.error(f"[API] Check icon cache failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/adb/icon-cache-stats")
async def get_icon_cache_stats(device_id: Optional[str] = None):
    """
    Get icon cache statistics for all scrapers

    Args:
        device_id: Optional device ID for device-specific stats

    Returns:
        {
            "device_scraper": {...},
            "playstore_scraper": {...},
            "apk_extractor": {...}
        }
    """
    try:
        stats = {}

        # Device scraper stats
        if device_icon_scraper:
            stats["device_scraper"] = device_icon_scraper.get_cache_stats(device_id)

        # Play Store scraper stats
        if playstore_icon_scraper:
            stats["playstore_scraper"] = playstore_icon_scraper.get_cache_stats()

        # APK extractor stats
        if app_icon_extractor:
            stats["apk_extractor"] = app_icon_extractor.get_cache_stats()

        return stats
    except Exception as e:
        logger.error(f"[API] Get icon cache stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/adb/launch")
async def launch_app(request: Request):
    """Launch an app by package name"""
    try:
        data = await request.json()
        device_id = data.get("device_id")
        package = data.get("package")

        if not device_id or not package:
            raise HTTPException(status_code=400, detail="device_id and package required")

        logger.info(f"[API] Launching {package} on {device_id}")
        success = await adb_bridge.launch_app(device_id, package)

        return {
            "success": success,
            "device_id": device_id,
            "package": package,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[API] Launch app failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/adb/stop-app")
async def stop_app(request: Request):
    """Force stop an app by package name"""
    try:
        data = await request.json()
        device_id = data.get("device_id")
        package = data.get("package")

        if not device_id or not package:
            raise HTTPException(status_code=400, detail="device_id and package required")

        logger.info(f"[API] Force stopping {package} on {device_id}")
        success = await adb_bridge.stop_app(device_id, package)

        return {
            "success": success,
            "device_id": device_id,
            "package": package,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"[API] Stop app failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Sensor Management Endpoints
@app.post("/api/sensors")
async def create_sensor(sensor: SensorDefinition):
    """Create a new sensor"""
    try:
        logger.info(f"[API] Creating sensor for device {sensor.device_id}")
        created_sensor = sensor_manager.create_sensor(sensor)

        # Publish MQTT discovery for the new sensor
        if mqtt_manager:
            try:
                success = await mqtt_manager.publish_discovery(created_sensor)
                if success:
                    logger.info(f"[API] Published MQTT discovery for new sensor {created_sensor.sensor_id}")
                    # Also publish initial state if available
                    if created_sensor.current_value:
                        await mqtt_manager.publish_state(created_sensor, created_sensor.current_value)
                else:
                    logger.warning(f"[API] Failed to publish MQTT discovery for {created_sensor.sensor_id}")
            except Exception as e:
                logger.error(f"[API] MQTT discovery failed for {created_sensor.sensor_id}: {e}")

        return {
            "success": True,
            "sensor": created_sensor.model_dump(mode='json')
        }
    except ValueError as e:
        logger.error(f"[API] Sensor creation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Sensor creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/test/extract")
async def test_extraction(request: dict):
    """Test text extraction with a rule (for preview in sensor creation UI)

    Request body:
    {
        "text": "Battery: 94%",
        "extraction_rule": {
            "method": "numeric",
            "extract_numeric": true,
            ...
        }
    }

    Response:
    {
        "success": true,
        "extracted_value": "94",
        "original_text": "Battery: 94%"
    }
    """
    try:
        text = request.get("text", "")
        rule_data = request.get("extraction_rule", {})

        # Create TextExtractionRule from dict
        extraction_rule = TextExtractionRule(**rule_data)

        # Create text extractor and extract
        extractor = TextExtractor()
        result = extractor.extract(text, extraction_rule)

        return {
            "success": True,
            "extracted_value": result,
            "original_text": text,
            "method_used": extraction_rule.method
        }
    except Exception as e:
        logger.error(f"[API] Test extraction failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "extracted_value": request.get("extraction_rule", {}).get("fallback_value", ""),
            "original_text": request.get("text", "")
        }


@app.get("/api/sensors/{device_id}")
async def get_sensors(device_id: str):
    """Get all sensors for a device"""
    try:
        logger.info(f"[API] Getting sensors for device {device_id}")
        sensors = sensor_manager.get_all_sensors(device_id)
        return {
            "success": True,
            "device_id": device_id,
            "sensors": [s.model_dump(mode='json') for s in sensors],
            "count": len(sensors)
        }
    except Exception as e:
        logger.error(f"[API] Get sensors failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sensors/{device_id}/{sensor_id}")
async def get_sensor(device_id: str, sensor_id: str):
    """Get a specific sensor"""
    try:
        logger.info(f"[API] Getting sensor {sensor_id} for device {device_id}")
        sensor = sensor_manager.get_sensor(device_id, sensor_id)
        if not sensor:
            raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")
        return {
            "success": True,
            "sensor": sensor.model_dump(mode='json')
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Get sensor failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def validate_sensor_config(sensor: SensorDefinition) -> Optional[str]:
    """
    Validate sensor configuration for Home Assistant compatibility.
    Uses ha_device_classes.py for comprehensive validation.
    Returns error message if invalid, None if valid.
    """
    # Rule 1: Friendly name should not be empty
    if not sensor.friendly_name or sensor.friendly_name.strip() == "":
        return "Friendly name cannot be empty"

    # Rule 2: Binary sensors should NOT have state_class
    if sensor.sensor_type == "binary_sensor":
        if sensor.state_class and sensor.state_class != "none":
            return "Binary sensors cannot have state_class. Remove state_class or change sensor_type to 'sensor'."

    # Rule 3: Check if state_class is allowed for this device class
    if sensor.state_class and sensor.state_class != "none":
        if not can_use_state_class(sensor.device_class, sensor.sensor_type):
            device_info = get_device_class_info(sensor.device_class, sensor.sensor_type)
            if device_info:
                return f"Device class '{sensor.device_class}' ({device_info.description}) does not support state_class. Set state_class to 'none'."
            else:
                return f"Device class '{sensor.device_class}' does not support state_class. Set state_class to 'none'."

    # Rule 4: Sensors with state_class='measurement' MUST have unit_of_measurement
    if sensor.state_class == "measurement":
        if not sensor.unit_of_measurement:
            return "Sensors with state_class='measurement' must have a unit_of_measurement (e.g. %, °C, W). Either add a unit or change state_class to 'none'."

    # Rule 5: Validate unit matches device class expectations
    if sensor.device_class and sensor.device_class != "none" and sensor.unit_of_measurement:
        if not validate_unit_for_device_class(sensor.device_class, sensor.unit_of_measurement, sensor.sensor_type):
            device_info = get_device_class_info(sensor.device_class, sensor.sensor_type)
            if device_info and device_info.valid_units:
                expected_units = ", ".join(device_info.valid_units) if device_info.valid_units else "no unit"
                return f"Device class '{sensor.device_class}' expects units: {expected_units}. Got: '{sensor.unit_of_measurement}'"

    return None  # Valid


@app.put("/api/sensors")
async def update_sensor(sensor: SensorDefinition):
    """Update an existing sensor"""
    try:
        logger.info(f"[API] Updating sensor {sensor.sensor_id}")

        # Validate sensor configuration
        validation_error = validate_sensor_config(sensor)
        if validation_error:
            raise HTTPException(status_code=400, detail=validation_error)

        updated_sensor = sensor_manager.update_sensor(sensor)

        # Republish MQTT discovery to update Home Assistant (if MQTT enabled)
        mqtt_updated = False
        if mqtt_manager and mqtt_manager.is_connected:
            try:
                mqtt_updated = await mqtt_manager.publish_discovery(updated_sensor)
                if mqtt_updated:
                    logger.info(f"[API] Republished MQTT discovery for {sensor.sensor_id}")
                    # Also publish current state if available
                    if updated_sensor.current_value:
                        await mqtt_manager.publish_state(updated_sensor, updated_sensor.current_value)
                else:
                    logger.warning(f"[API] Failed to republish MQTT discovery for {sensor.sensor_id}")
            except Exception as e:
                logger.error(f"[API] MQTT republish failed for {sensor.sensor_id}: {e}")

        return {
            "success": True,
            "sensor": updated_sensor.model_dump(mode='json'),
            "mqtt_updated": mqtt_updated
        }
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"[API] Sensor update failed: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Sensor update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/sensors/{device_id}/{sensor_id}")
async def delete_sensor(device_id: str, sensor_id: str):
    """Delete a sensor and remove from Home Assistant"""
    try:
        logger.info(f"[API] Deleting sensor {sensor_id} for device {device_id}")

        # Get sensor before deleting (need it for MQTT removal)
        sensor = sensor_manager.get_sensor(device_id, sensor_id)
        if not sensor:
            raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")

        # Remove from Home Assistant via MQTT (if MQTT is enabled)
        mqtt_removed = False
        if mqtt_manager and mqtt_manager.is_connected:
            try:
                mqtt_removed = await mqtt_manager.remove_discovery(sensor)
                if mqtt_removed:
                    logger.info(f"[API] Removed sensor {sensor_id} from Home Assistant")
                else:
                    logger.warning(f"[API] Failed to remove sensor {sensor_id} from Home Assistant")
            except Exception as e:
                logger.error(f"[API] MQTT removal failed for {sensor_id}: {e}")

        # Delete from local storage
        success = sensor_manager.delete_sensor(device_id, sensor_id)
        if not success:
            raise HTTPException(status_code=500, detail=f"Failed to delete sensor {sensor_id}")

        return {
            "success": True,
            "mqtt_removed": mqtt_removed,
            "message": f"Sensor {sensor_id} deleted" + (" and removed from Home Assistant" if mqtt_removed else "")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Delete sensor failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# MQTT Control Endpoints
@app.post("/api/mqtt/start/{device_id}")
async def start_sensor_updates(device_id: str):
    """Start sensor update loop for device"""
    if not sensor_updater:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        logger.info(f"[API] Starting sensor updates for {device_id}")
        success = await sensor_updater.start_device_updates(device_id)
        return {
            "success": success,
            "device_id": device_id,
            "message": "Sensor updates started" if success else "Failed to start updates"
        }
    except Exception as e:
        logger.error(f"[API] Start updates failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mqtt/stop/{device_id}")
async def stop_sensor_updates(device_id: str):
    """Stop sensor update loop for device"""
    if not sensor_updater:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        logger.info(f"[API] Stopping sensor updates for {device_id}")
        success = await sensor_updater.stop_device_updates(device_id)
        return {
            "success": success,
            "device_id": device_id,
            "message": "Sensor updates stopped" if success else "Failed to stop updates"
        }
    except Exception as e:
        logger.error(f"[API] Stop updates failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mqtt/restart/{device_id}")
async def restart_sensor_updates(device_id: str):
    """Restart sensor update loop for device"""
    if not sensor_updater:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        logger.info(f"[API] Restarting sensor updates for {device_id}")
        success = await sensor_updater.restart_device_updates(device_id)
        return {
            "success": success,
            "device_id": device_id,
            "message": "Sensor updates restarted" if success else "Failed to restart updates"
        }
    except Exception as e:
        logger.error(f"[API] Restart updates failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mqtt/status")
async def mqtt_status():
    """Get MQTT connection status and running devices"""
    if not mqtt_manager or not sensor_updater:
        return {
            "connected": False,
            "broker": MQTT_BROKER,
            "port": MQTT_PORT,
            "running_devices": [],
            "message": "MQTT not initialized"
        }

    return {
        "connected": mqtt_manager.is_connected,
        "broker": MQTT_BROKER,
        "port": MQTT_PORT,
        "discovery_prefix": MQTT_DISCOVERY_PREFIX,
        "running_devices": list(sensor_updater.get_running_devices()),
        "message": "MQTT connected" if mqtt_manager.is_connected else "MQTT disconnected"
    }


@app.post("/api/mqtt/publish-discovery/{device_id}/{sensor_id}")
async def publish_sensor_discovery(device_id: str, sensor_id: str):
    """Manually publish MQTT discovery for a sensor"""
    if not mqtt_manager:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        logger.info(f"[API] Publishing discovery for {device_id}/{sensor_id}")
        sensor = sensor_manager.get_sensor(device_id, sensor_id)
        if not sensor:
            raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")

        success = await mqtt_manager.publish_discovery(sensor)
        return {
            "success": success,
            "device_id": device_id,
            "sensor_id": sensor_id,
            "message": "Discovery published" if success else "Failed to publish discovery"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Publish discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/mqtt/remove-discovery/{device_id}/{sensor_id}")
async def remove_sensor_discovery(device_id: str, sensor_id: str):
    """Remove MQTT discovery for a sensor (unpublish from HA)"""
    if not mqtt_manager:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        logger.info(f"[API] Removing discovery for {device_id}/{sensor_id}")
        sensor = sensor_manager.get_sensor(device_id, sensor_id)
        if not sensor:
            raise HTTPException(status_code=404, detail=f"Sensor {sensor_id} not found")

        success = await mqtt_manager.remove_discovery(sensor)
        return {
            "success": success,
            "device_id": device_id,
            "sensor_id": sensor_id,
            "message": "Discovery removed" if success else "Failed to remove discovery"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Remove discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/mqtt/publish-discovery-all/{device_id}")
async def publish_all_sensor_discoveries(device_id: str):
    """Publish MQTT discovery for ALL sensors on a device"""
    if not mqtt_manager:
        raise HTTPException(status_code=503, detail="MQTT not initialized")

    try:
        logger.info(f"[API] Publishing discovery for all sensors on {device_id}")
        sensors = sensor_manager.get_all_sensors(device_id)

        if not sensors:
            return {
                "success": True,
                "device_id": device_id,
                "published_count": 0,
                "message": "No sensors found for device"
            }

        published_count = 0
        failed_sensors = []

        for sensor in sensors:
            try:
                success = await mqtt_manager.publish_discovery(sensor)
                if success:
                    published_count += 1
                    logger.info(f"[API] Published discovery for {sensor.sensor_id}")
                else:
                    failed_sensors.append(sensor.sensor_id)
            except Exception as e:
                logger.error(f"[API] Failed to publish discovery for {sensor.sensor_id}: {e}")
                failed_sensors.append(sensor.sensor_id)

        return {
            "success": True,
            "device_id": device_id,
            "total_sensors": len(sensors),
            "published_count": published_count,
            "failed_sensors": failed_sensors,
            "message": f"Published {published_count}/{len(sensors)} sensor discoveries"
        }
    except Exception as e:
        logger.error(f"[API] Bulk publish discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== ACTION ENDPOINTS =====

@app.post("/api/actions")
async def create_action(request: ActionCreateRequest, device_id: str):
    """
    Create a new action for a device

    Args:
        request: ActionCreateRequest with action configuration and tags
        device_id: Target device ID (query parameter)

    Returns:
        Created ActionDefinition
    """
    try:
        logger.info(f"[API] Creating {request.action.action_type} action for {device_id}")
        action_def = action_manager.create_action(
            device_id=device_id,
            action=request.action,
            tags=request.tags
        )

        # Publish MQTT discovery to Home Assistant (if MQTT enabled)
        mqtt_published = False
        if mqtt_manager and mqtt_manager.is_connected:
            try:
                mqtt_published = await mqtt_manager.publish_action_discovery(action_def)
                if mqtt_published:
                    logger.info(f"[API] Published MQTT discovery for action {action_def.id}")
                else:
                    logger.warning(f"[API] Failed to publish MQTT discovery for action {action_def.id}")
            except Exception as e:
                logger.error(f"[API] MQTT action discovery failed for {action_def.id}: {e}")

        return {
            "success": True,
            "action": action_def.dict(),
            "mqtt_published": mqtt_published
        }
    except Exception as e:
        logger.error(f"[API] Create action failed: {e}")
        return handle_api_error(e)


@app.get("/api/actions/{device_id}")
async def list_actions(device_id: str):
    """
    List all actions for a device

    Args:
        device_id: Device ID

    Returns:
        ActionListResponse with all actions
    """
    try:
        actions = action_manager.list_actions(device_id)
        return ActionListResponse(
            actions=actions,
            total=len(actions),
            device_id=device_id
        )
    except Exception as e:
        logger.error(f"[API] List actions failed: {e}")
        return handle_api_error(e)


@app.get("/api/actions/{device_id}/{action_id}")
async def get_action(device_id: str, action_id: str):
    """
    Get a specific action

    Args:
        device_id: Device ID
        action_id: Action ID

    Returns:
        ActionDefinition
    """
    try:
        action_def = action_manager.get_action(device_id, action_id)
        return {
            "success": True,
            "action": action_def.dict()
        }
    except Exception as e:
        logger.error(f"[API] Get action failed: {e}")
        return handle_api_error(e)


@app.put("/api/actions/{device_id}/{action_id}")
async def update_action(device_id: str, action_id: str, request: ActionUpdateRequest):
    """
    Update an existing action

    Args:
        device_id: Device ID
        action_id: Action ID
        request: ActionUpdateRequest with updates

    Returns:
        Updated ActionDefinition
    """
    try:
        logger.info(f"[API] Updating action {action_id} for {device_id}")
        action_def = action_manager.update_action(
            device_id=device_id,
            action_id=action_id,
            action=request.action,
            enabled=request.enabled,
            tags=request.tags
        )
        return {
            "success": True,
            "action": action_def.dict()
        }
    except Exception as e:
        logger.error(f"[API] Update action failed: {e}")
        return handle_api_error(e)


@app.delete("/api/actions/{device_id}/{action_id}")
async def delete_action(device_id: str, action_id: str):
    """
    Delete an action

    Args:
        device_id: Device ID
        action_id: Action ID

    Returns:
        Success message
    """
    try:
        logger.info(f"[API] Deleting action {action_id} for {device_id}")

        # Get action before deleting (need it for MQTT removal)
        action_def = action_manager.get_action(device_id, action_id)
        if not action_def:
            raise HTTPException(status_code=404, detail=f"Action {action_id} not found")

        # Remove from Home Assistant via MQTT (if MQTT is enabled)
        mqtt_removed = False
        if mqtt_manager and mqtt_manager.is_connected:
            try:
                mqtt_removed = await mqtt_manager.remove_action_discovery(action_def)
                if mqtt_removed:
                    logger.info(f"[API] Removed action {action_id} from Home Assistant")
                else:
                    logger.warning(f"[API] Failed to remove action {action_id} from Home Assistant")
            except Exception as e:
                logger.error(f"[API] MQTT action removal failed for {action_id}: {e}")

        # Delete from local storage
        action_manager.delete_action(device_id, action_id)

        return {
            "success": True,
            "message": f"Action {action_id} deleted" + (" and removed from Home Assistant" if mqtt_removed else ""),
            "mqtt_removed": mqtt_removed
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Delete action failed: {e}")
        return handle_api_error(e)


@app.post("/api/actions/execute")
async def execute_action_endpoint(request: ActionExecutionRequest, device_id: str):
    """
    Execute an action (saved or inline)

    Args:
        request: ActionExecutionRequest with action_id OR inline action
        device_id: Target device ID (query parameter)

    Returns:
        ActionExecutionResult
    """
    try:
        if request.action_id:
            # Execute saved action
            logger.info(f"[API] Executing saved action {request.action_id} for {device_id}")
            result = await action_executor.execute_action_by_id(
                action_manager,
                device_id,
                request.action_id
            )
        else:
            # Execute inline action
            logger.info(f"[API] Executing inline action for {device_id}")
            result = await action_executor.execute_action(request.action)

        return result.dict()

    except Exception as e:
        logger.error(f"[API] Execute action failed: {e}")
        return handle_api_error(e)


@app.get("/api/actions/export/{device_id}")
async def export_actions(device_id: str):
    """
    Export all actions for a device as JSON

    Args:
        device_id: Device ID

    Returns:
        JSON string of actions
    """
    try:
        actions_json = action_manager.export_actions(device_id)
        return {
            "success": True,
            "device_id": device_id,
            "actions_json": actions_json
        }
    except Exception as e:
        logger.error(f"[API] Export actions failed: {e}")
        return handle_api_error(e)


@app.post("/api/actions/import/{device_id}")
async def import_actions(device_id: str, actions_json: str):
    """
    Import actions from JSON string

    Args:
        device_id: Target device ID
        actions_json: JSON string of actions

    Returns:
        Import result with count
    """
    try:
        logger.info(f"[API] Importing actions for {device_id}")
        count = action_manager.import_actions(device_id, actions_json)
        return {
            "success": True,
            "device_id": device_id,
            "imported_count": count,
            "message": f"Imported {count} actions"
        }
    except Exception as e:
        logger.error(f"[API] Import actions failed: {e}")
        return handle_api_error(e)


################################################################################
#                         PHASE 8: FLOW SYSTEM API ENDPOINTS                  #
################################################################################

# ============================================================================
# Flow CRUD Endpoints
# ============================================================================

@app.post("/api/flows")
async def create_flow(flow_data: dict):
    """
    Create a new flow

    Body:
        flow_data: Flow definition (SensorCollectionFlow dict)

    Returns:
        Created flow with generated flow_id
    """
    try:
        if not flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        # Import here to avoid circular dependency
        from flow_models import SensorCollectionFlow

        # Create flow from dict
        flow = SensorCollectionFlow(**flow_data)

        # Save flow
        success = flow_manager.create_flow(flow)
        if not success:
            raise HTTPException(status_code=400, detail="Flow already exists")

        logger.info(f"[API] Created flow {flow.flow_id} for device {flow.device_id}")
        return flow.dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to create flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/flows")
async def list_flows(device_id: Optional[str] = None):
    """
    List all flows (optionally filtered by device)

    Args:
        device_id: Optional device ID filter

    Returns:
        List of flows
    """
    try:
        if not flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        if device_id:
            flows = flow_manager.get_device_flows(device_id)
        else:
            flows = flow_manager.get_all_flows()

        return {"flows": [f.dict() for f in flows]}

    except Exception as e:
        logger.error(f"[API] Failed to list flows: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/flows/{device_id}/{flow_id}")
async def get_flow(device_id: str, flow_id: str):
    """
    Get a specific flow

    Args:
        device_id: Device ID
        flow_id: Flow ID

    Returns:
        Flow definition
    """
    try:
        if not flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        flow = flow_manager.get_flow(device_id, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        return flow.dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to get flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/flows/{device_id}/{flow_id}")
async def update_flow(device_id: str, flow_id: str, flow_data: dict):
    """
    Update an existing flow

    Args:
        device_id: Device ID
        flow_id: Flow ID
        flow_data: Updated flow definition

    Returns:
        Updated flow
    """
    try:
        if not flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        # Import here to avoid circular dependency
        from flow_models import SensorCollectionFlow

        # Create flow from dict
        flow = SensorCollectionFlow(**flow_data)

        # Ensure IDs match
        if flow.device_id != device_id or flow.flow_id != flow_id:
            raise HTTPException(status_code=400, detail="Flow ID mismatch")

        # Update flow
        success = flow_manager.update_flow(flow)
        if not success:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        logger.info(f"[API] Updated flow {flow_id} for device {device_id}")
        return flow.dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to update flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/flows/{device_id}/{flow_id}")
async def delete_flow(device_id: str, flow_id: str):
    """
    Delete a flow

    Args:
        device_id: Device ID
        flow_id: Flow ID

    Returns:
        Success message
    """
    try:
        if not flow_manager:
            raise HTTPException(status_code=503, detail="Flow manager not initialized")

        success = flow_manager.delete_flow(device_id, flow_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        logger.info(f"[API] Deleted flow {flow_id} for device {device_id}")
        return {"success": True, "message": f"Flow {flow_id} deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to delete flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Flow Execution Endpoints
# ============================================================================

@app.post("/api/flows/{device_id}/{flow_id}/execute")
async def execute_flow_on_demand(device_id: str, flow_id: str):
    """
    Execute a flow on-demand (outside the scheduler)

    Args:
        device_id: Device ID
        flow_id: Flow ID

    Returns:
        Execution result
    """
    try:
        if not flow_scheduler:
            raise HTTPException(status_code=503, detail="Flow scheduler not initialized")

        # Get flow
        flow = flow_manager.get_flow(device_id, flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        # Schedule with highest priority (on-demand execution)
        await flow_scheduler.schedule_flow_on_demand(flow)

        logger.info(f"[API] Scheduled on-demand execution for flow {flow_id}")
        return {"success": True, "message": f"Flow {flow_id} scheduled for execution"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to execute flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Performance Metrics Endpoint
# ============================================================================

@app.get("/api/flows/metrics")
async def get_flow_metrics(device_id: Optional[str] = None):
    """
    Get performance metrics for flows

    Args:
        device_id: Optional device ID to filter metrics (if not provided, returns all)

    Returns:
        Performance metrics including:
        - Total executions
        - Success rate
        - Average execution time
        - Recent alerts
        - Queue depth
    """
    try:
        if not performance_monitor:
            raise HTTPException(status_code=503, detail="Performance monitor not initialized")

        if device_id:
            # Get metrics for specific device
            metrics = performance_monitor.get_metrics(device_id)
            return {"device_id": device_id, "metrics": metrics}
        else:
            # Get metrics for all devices
            all_metrics = performance_monitor.get_all_metrics()
            return {"all_devices": all_metrics}

    except Exception as e:
        logger.error(f"[API] Failed to get flow metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/flows/alerts")
async def get_flow_alerts(device_id: Optional[str] = None, limit: int = 10):
    """
    Get recent performance alerts

    Args:
        device_id: Optional device ID to filter alerts
        limit: Maximum number of alerts to return (default: 10)

    Returns:
        List of recent alerts with severity, message, and recommendations
    """
    try:
        if not performance_monitor:
            raise HTTPException(status_code=503, detail="Performance monitor not initialized")

        alerts = performance_monitor.get_recent_alerts(device_id=device_id, limit=limit)

        return {
            "alerts": alerts,
            "count": len(alerts),
            "device_id": device_id
        }
    except Exception as e:
        logger.error(f"[API] Failed to get flow alerts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Scheduler Control Endpoints
# ============================================================================

@app.get("/api/scheduler/status")
async def get_scheduler_status():
    """
    Get overall scheduler status

    Returns:
        Scheduler state including running/paused status and per-device info
    """
    try:
        if not flow_scheduler:
            raise HTTPException(status_code=503, detail="Flow scheduler not initialized")

        status = flow_scheduler.get_status()
        return {"success": True, "status": status}

    except Exception as e:
        logger.error(f"[API] Failed to get scheduler status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduler/pause")
async def pause_scheduler():
    """
    Pause periodic scheduling

    Note: Currently executing flows will complete, but no new periodic
    flows will be queued until resumed.
    """
    try:
        if not flow_scheduler:
            raise HTTPException(status_code=503, detail="Flow scheduler not initialized")

        await flow_scheduler.pause()
        return {"success": True, "message": "Scheduler paused"}

    except Exception as e:
        logger.error(f"[API] Failed to pause scheduler: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduler/resume")
async def resume_scheduler():
    """
    Resume periodic scheduling
    """
    try:
        if not flow_scheduler:
            raise HTTPException(status_code=503, detail="Flow scheduler not initialized")

        await flow_scheduler.resume()
        return {"success": True, "message": "Scheduler resumed"}

    except Exception as e:
        logger.error(f"[API] Failed to resume scheduler: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/scheduler/queue/{device_id}")
async def get_scheduler_queue(device_id: str):
    """
    Get queue information for a device

    Args:
        device_id: Device ID to check

    Returns:
        Queue depth and status for the device
    """
    try:
        if not flow_scheduler:
            raise HTTPException(status_code=503, detail="Flow scheduler not initialized")

        queue_info = flow_scheduler.get_queued_flows(device_id)
        metrics = flow_scheduler.get_metrics(device_id)

        return {
            "success": True,
            "device_id": device_id,
            "queue": queue_info,
            "metrics": metrics
        }

    except Exception as e:
        logger.error(f"[API] Failed to get scheduler queue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/flows/alerts")
async def clear_flow_alerts(device_id: Optional[str] = None):
    """
    Clear performance alerts

    Args:
        device_id: Optional device ID (if not provided, clears all alerts)

    Returns:
        Confirmation message
    """
    try:
        if not performance_monitor:
            raise HTTPException(status_code=503, detail="Performance monitor not initialized")

        performance_monitor.clear_alerts(device_id=device_id)

        message = f"Cleared alerts for {device_id}" if device_id else "Cleared all alerts"
        return {"success": True, "message": message}
    except Exception as e:
        logger.error(f"[API] Failed to clear flow alerts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/flows/thresholds")
async def get_alert_thresholds():
    """
    Get current alert threshold configuration

    Returns:
        Alert thresholds for queue depth, backlog ratio, and failure rates
    """
    try:
        if not performance_monitor:
            raise HTTPException(status_code=503, detail="Performance monitor not initialized")

        return {
            "queue_depth_warning": performance_monitor.QUEUE_DEPTH_WARNING,
            "queue_depth_critical": performance_monitor.QUEUE_DEPTH_CRITICAL,
            "backlog_ratio": performance_monitor.BACKLOG_RATIO,
            "failure_rate_warning": performance_monitor.FAILURE_RATE_WARNING,
            "failure_rate_critical": performance_monitor.FAILURE_RATE_CRITICAL,
            "alert_cooldown_seconds": performance_monitor.ALERT_COOLDOWN_SECONDS
        }
    except Exception as e:
        logger.error(f"[API] Failed to get alert thresholds: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/flows/thresholds")
async def update_alert_thresholds(thresholds: dict):
    """
    Update alert threshold configuration

    Args:
        thresholds: Dictionary with threshold values to update

    Accepted fields:
        - queue_depth_warning: int
        - queue_depth_critical: int
        - backlog_ratio: float (0-1)
        - failure_rate_warning: float (0-1)
        - failure_rate_critical: float (0-1)
        - alert_cooldown_seconds: int

    Returns:
        Updated threshold configuration
    """
    try:
        if not performance_monitor:
            raise HTTPException(status_code=503, detail="Performance monitor not initialized")

        # Update thresholds (with validation)
        if "queue_depth_warning" in thresholds:
            value = int(thresholds["queue_depth_warning"])
            if value < 1 or value > 100:
                raise HTTPException(status_code=400, detail="queue_depth_warning must be between 1 and 100")
            performance_monitor.QUEUE_DEPTH_WARNING = value

        if "queue_depth_critical" in thresholds:
            value = int(thresholds["queue_depth_critical"])
            if value < 1 or value > 100:
                raise HTTPException(status_code=400, detail="queue_depth_critical must be between 1 and 100")
            performance_monitor.QUEUE_DEPTH_CRITICAL = value

        if "backlog_ratio" in thresholds:
            value = float(thresholds["backlog_ratio"])
            if value < 0 or value > 1:
                raise HTTPException(status_code=400, detail="backlog_ratio must be between 0 and 1")
            performance_monitor.BACKLOG_RATIO = value

        if "failure_rate_warning" in thresholds:
            value = float(thresholds["failure_rate_warning"])
            if value < 0 or value > 1:
                raise HTTPException(status_code=400, detail="failure_rate_warning must be between 0 and 1")
            performance_monitor.FAILURE_RATE_WARNING = value

        if "failure_rate_critical" in thresholds:
            value = float(thresholds["failure_rate_critical"])
            if value < 0 or value > 1:
                raise HTTPException(status_code=400, detail="failure_rate_critical must be between 0 and 1")
            performance_monitor.FAILURE_RATE_CRITICAL = value

        if "alert_cooldown_seconds" in thresholds:
            value = int(thresholds["alert_cooldown_seconds"])
            if value < 0 or value > 3600:
                raise HTTPException(status_code=400, detail="alert_cooldown_seconds must be between 0 and 3600")
            performance_monitor.ALERT_COOLDOWN_SECONDS = value

        logger.info(f"[API] Updated alert thresholds: {thresholds}")

        # Return updated configuration
        return {
            "success": True,
            "message": "Alert thresholds updated",
            "thresholds": {
                "queue_depth_warning": performance_monitor.QUEUE_DEPTH_WARNING,
                "queue_depth_critical": performance_monitor.QUEUE_DEPTH_CRITICAL,
                "backlog_ratio": performance_monitor.BACKLOG_RATIO,
                "failure_rate_warning": performance_monitor.FAILURE_RATE_WARNING,
                "failure_rate_critical": performance_monitor.FAILURE_RATE_CRITICAL,
                "alert_cooldown_seconds": performance_monitor.ALERT_COOLDOWN_SECONDS
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Failed to update alert thresholds: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


################################################################################
#                              MIDDLEWARE                                      #
################################################################################

# Custom middleware to serve HTML with no-cache headers (development mode only)
# Set DISABLE_HTML_CACHE=false in production to enable browser caching
DISABLE_HTML_CACHE = os.getenv("DISABLE_HTML_CACHE", "true").lower() == "true"

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    """Add no-cache headers to HTML files during development

    In development: HTML files are served with no-cache headers to ensure
                    fresh content on every page load
    In production: Set DISABLE_HTML_CACHE=false to enable browser caching
                   for better performance
    """
    response = await call_next(request)

    # If the response is an HTML file and caching is disabled, add no-cache headers
    if DISABLE_HTML_CACHE and response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return response


# =============================================================================
# LIVE STREAMING - Quality Settings
# =============================================================================

# Quality presets: max_height, jpeg_quality, target_fps
QUALITY_PRESETS = {
    'high': {'max_height': None, 'jpeg_quality': 85, 'target_fps': 5, 'frame_delay': 0.2},
    'medium': {'max_height': 720, 'jpeg_quality': 75, 'target_fps': 10, 'frame_delay': 0.1},
    'low': {'max_height': 480, 'jpeg_quality': 65, 'target_fps': 15, 'frame_delay': 0.066},
    'fast': {'max_height': 360, 'jpeg_quality': 55, 'target_fps': 20, 'frame_delay': 0.05},
}

def resize_image_for_quality(img_bytes: bytes, quality: str) -> bytes:
    """Resize image based on quality preset. Returns JPEG bytes."""
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS['medium'])

    try:
        img = Image.open(io.BytesIO(img_bytes))

        # Resize if needed
        if preset['max_height'] and img.height > preset['max_height']:
            ratio = preset['max_height'] / img.height
            new_width = int(img.width * ratio)
            img = img.resize((new_width, preset['max_height']), Image.Resampling.LANCZOS)

        # Convert to JPEG
        output = io.BytesIO()
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        img.save(output, format='JPEG', quality=preset['jpeg_quality'], optimize=True)
        return output.getvalue()
    except Exception as e:
        logger.warning(f"[Quality] Resize failed: {e}, returning original")
        return img_bytes

# =============================================================================
# LIVE STREAMING - WebSocket Endpoint (Base64 JSON - Original POC)
# =============================================================================

@app.websocket("/ws/stream/{device_id}")
async def stream_device(websocket: WebSocket, device_id: str):
    """
    WebSocket endpoint for live screenshot streaming.

    Query params:
    - quality: 'high', 'medium', 'low', 'fast' (default: medium)

    Message format (JSON):
    {
        "type": "frame",
        "image": "<base64 JPEG>",
        "elements": [...],
        "timestamp": 1234567890.123,
        "capture_ms": 150,
        "frame_number": 1
    }
    """
    await websocket.accept()

    # Parse quality from query string
    quality = websocket.query_params.get('quality', 'medium')
    if quality not in QUALITY_PRESETS:
        quality = 'medium'
    preset = QUALITY_PRESETS[quality]

    logger.info(f"[WS-Stream] Client connected for device: {device_id}, quality: {quality} (target {preset['target_fps']} FPS)")

    frame_number = 0

    try:
        # Capture initial screenshot to get native device dimensions
        try:
            init_screenshot = await adb_bridge.capture_screenshot(device_id)
            if len(init_screenshot) > 1000:
                from PIL import Image
                import io
                init_img = Image.open(io.BytesIO(init_screenshot))
                device_width, device_height = init_img.size
                # Send config with native device dimensions
                await websocket.send_json({
                    "type": "config",
                    "width": device_width,
                    "height": device_height,
                    "quality": quality,
                    "target_fps": preset['target_fps']
                })
                logger.info(f"[WS-Stream] Device dimensions: {device_width}x{device_height}")
        except Exception as init_err:
            logger.warning(f"[WS-Stream] Failed to get device dimensions: {init_err}")

        while True:
            frame_number += 1
            capture_start = time.time()

            try:
                # Capture screenshot with per-frame timeout (3 seconds max)
                # This prevents a single slow capture from blocking the stream
                try:
                    screenshot_bytes = await asyncio.wait_for(
                        adb_bridge.capture_screenshot(device_id),
                        timeout=3.0  # 3 second max per frame
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[WS-Stream] Frame {frame_number}: Capture timeout (>3s), skipping")
                    await asyncio.sleep(0.5)
                    continue

                capture_time = (time.time() - capture_start) * 1000  # ms

                # Skip if invalid/empty screenshot
                if len(screenshot_bytes) < 1000:
                    logger.warning(f"[WS-Stream] Frame {frame_number}: Screenshot too small ({len(screenshot_bytes)} bytes), skipping")
                    await asyncio.sleep(0.5)
                    continue

                # Resize based on quality (also converts to JPEG)
                if quality != 'high':
                    processed_bytes = resize_image_for_quality(screenshot_bytes, quality)
                else:
                    processed_bytes = screenshot_bytes

                # Debug: Log periodically
                if frame_number <= 3 or frame_number % 100 == 0:
                    logger.info(f"[WS-Stream] Frame {frame_number}: {len(screenshot_bytes)} -> {len(processed_bytes)} bytes ({quality})")

                # Encode and send
                screenshot_base64 = base64.b64encode(processed_bytes).decode('utf-8')

                # Determine image type
                is_jpeg = processed_bytes[:2] == b'\xff\xd8'
                image_prefix = 'data:image/jpeg;base64,' if is_jpeg else 'data:image/png;base64,'

                await websocket.send_json({
                    "type": "frame",
                    "image": screenshot_base64,
                    "elements": [],  # Empty - elements fetched on-demand via Refresh Elements button
                    "timestamp": time.time(),
                    "capture_ms": round(capture_time, 1),
                    "frame_number": frame_number
                })

                # Sleep based on quality preset
                sleep_time = max(0.03, preset['frame_delay'] - (time.time() - capture_start))
                await asyncio.sleep(sleep_time)

            except Exception as capture_error:
                logger.warning(f"[WS-Stream] Capture error: {capture_error}")
                # Send error frame but keep connection alive
                await websocket.send_json({
                    "type": "error",
                    "message": str(capture_error),
                    "timestamp": time.time()
                })
                await asyncio.sleep(1)  # Wait before retry

    except WebSocketDisconnect:
        logger.info(f"[WS-Stream] Client disconnected: {device_id}")
    except Exception as e:
        logger.error(f"[WS-Stream] Connection error: {e}")
    finally:
        logger.info(f"[WS-Stream] Stream ended for device: {device_id}, frames sent: {frame_number}")


# =============================================================================
# LIVE STREAMING - MJPEG Binary Endpoint (Enhanced - ~30% less bandwidth)
# =============================================================================

@app.websocket("/ws/stream-mjpeg/{device_id}")
async def stream_device_mjpeg(websocket: WebSocket, device_id: str):
    """
    WebSocket endpoint for live MJPEG binary streaming.

    Sends raw JPEG binary frames instead of base64 JSON for ~30% bandwidth reduction.

    Query params:
    - quality: 'high', 'medium', 'low', 'fast' (default: medium)

    Message format (Binary + JSON header):
    - First message: JSON config {"width": 1200, "height": 1920, "format": "jpeg"}
    - Subsequent messages: Binary JPEG data with 8-byte header
        - Bytes 0-3: Frame number (uint32 big-endian)
        - Bytes 4-7: Capture time ms (uint32 big-endian)
        - Bytes 8+: JPEG image data
    """
    import struct

    await websocket.accept()

    # Parse quality from query string
    quality = websocket.query_params.get('quality', 'medium')
    if quality not in QUALITY_PRESETS:
        quality = 'medium'
    preset = QUALITY_PRESETS[quality]

    logger.info(f"[WS-MJPEG] Client connected for device: {device_id}, quality: {quality} (target {preset['target_fps']} FPS)")

    frame_number = 0

    try:
        # Capture initial screenshot to get native device dimensions
        device_width, device_height = 1080, 1920  # Defaults
        try:
            init_screenshot = await adb_bridge.capture_screenshot(device_id)
            if len(init_screenshot) > 1000:
                from PIL import Image
                import io
                init_img = Image.open(io.BytesIO(init_screenshot))
                device_width, device_height = init_img.size
                logger.info(f"[WS-MJPEG] Device dimensions: {device_width}x{device_height}")
        except Exception as init_err:
            logger.warning(f"[WS-MJPEG] Failed to get device dimensions: {init_err}")

        # Send initial config as JSON with device dimensions
        await websocket.send_json({
            "type": "config",
            "format": "mjpeg",
            "width": device_width,
            "height": device_height,
            "quality": quality,
            "target_fps": preset['target_fps'],
            "message": "MJPEG binary streaming ready. Subsequent frames are binary."
        })

        while True:
            frame_number += 1
            capture_start = time.time()

            try:
                # Capture screenshot with per-frame timeout (3 seconds max)
                # This prevents a single slow capture from blocking the stream
                try:
                    screenshot_bytes = await asyncio.wait_for(
                        adb_bridge.capture_screenshot(device_id),
                        timeout=3.0  # 3 second max per frame
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[WS-MJPEG] Frame {frame_number}: Capture timeout (>3s), skipping")
                    await asyncio.sleep(0.5)
                    continue

                capture_time = int((time.time() - capture_start) * 1000)  # ms as int

                # Skip if invalid/empty screenshot
                if len(screenshot_bytes) < 1000:
                    logger.warning(f"[WS-MJPEG] Frame {frame_number}: Screenshot too small ({len(screenshot_bytes)} bytes), skipping")
                    await asyncio.sleep(0.5)
                    continue

                # Resize and convert to JPEG based on quality preset
                try:
                    jpeg_bytes = resize_image_for_quality(screenshot_bytes, quality)
                except Exception as convert_error:
                    logger.warning(f"[WS-MJPEG] JPEG conversion failed: {convert_error}, sending PNG")
                    jpeg_bytes = screenshot_bytes  # Fallback to PNG

                # Create binary frame with header
                # Header: 4 bytes frame_number + 4 bytes capture_time
                header = struct.pack('>II', frame_number, capture_time)
                frame_data = header + jpeg_bytes

                # Send binary frame
                await websocket.send_bytes(frame_data)

                # Log periodically
                if frame_number <= 3 or frame_number % 60 == 0:
                    logger.info(f"[WS-MJPEG] Frame {frame_number}: {len(jpeg_bytes)} bytes JPEG, {capture_time}ms capture, quality={quality}")

                # Use frame delay from quality preset
                sleep_time = max(0.05, preset['frame_delay'] - (time.time() - capture_start))
                await asyncio.sleep(sleep_time)

            except Exception as capture_error:
                logger.warning(f"[WS-MJPEG] Capture error: {capture_error}")
                # Send error as JSON (not binary)
                await websocket.send_json({
                    "type": "error",
                    "message": str(capture_error),
                    "timestamp": time.time()
                })
                await asyncio.sleep(1)  # Wait before retry

    except WebSocketDisconnect:
        logger.info(f"[WS-MJPEG] Client disconnected: {device_id}")
    except Exception as e:
        logger.error(f"[WS-MJPEG] Connection error: {e}")
    finally:
        logger.info(f"[WS-MJPEG] Stream ended for device: {device_id}, frames sent: {frame_number}")


# === Real-Time Log Viewer ===

@app.get("/api/logs/recent")
async def get_recent_logs(count: int = 50):
    """Get recent log entries from buffer"""
    return {
        "success": True,
        "logs": ws_log_handler.get_recent_logs(count),
        "connected_clients": len(ws_log_handler.clients)
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
        await websocket.send_json({
            "type": "history",
            "data": recent_logs
        })

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


# Mount static files LAST (catch-all route)
app.mount("/", StaticFiles(directory="www", html=True), name="www")

if __name__ == "__main__":
    # Default to port 3000, can be overridden by environment variable
    port = int(os.getenv("PORT", 3000))
    
    logger.info(f"Starting Visual Mapper v0.0.4 (Phase 3 - Sensor Creation)")
    logger.info(f"Server: http://localhost:{port}")
    logger.info(f"API: http://localhost:{port}/api")
    logger.info(f"HTML Cache: {'DISABLED (development mode)' if DISABLE_HTML_CACHE else 'ENABLED (production mode)'}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
