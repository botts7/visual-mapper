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
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
import uvicorn
from pathlib import Path

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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Visual Mapper API",
    version="0.0.4",
    description="Android Device Monitoring & Automation for Home Assistant"
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

# MQTT Configuration (loaded from environment or config)
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_DISCOVERY_PREFIX = os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant")
AUTO_START_UPDATES = os.getenv("AUTO_START_UPDATES", "true").lower() == "true"


# Request/Response Models
class ConnectDeviceRequest(BaseModel):
    host: str
    port: int = 5555


class DisconnectDeviceRequest(BaseModel):
    device_id: str


class ScreenshotRequest(BaseModel):
    device_id: str


class ScreenshotStitchRequest(BaseModel):
    device_id: str
    max_scrolls: Optional[int] = 20
    scroll_ratio: Optional[float] = 0.75
    overlap_ratio: Optional[float] = 0.25


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
    keycode: str


class PairingRequest(BaseModel):
    pairing_host: str
    pairing_port: int
    pairing_code: str
    connection_port: int  # The actual ADB port to connect to after pairing


# Startup and Shutdown Events
@app.on_event("startup")
async def startup_event():
    """Initialize MQTT connection on startup"""
    global mqtt_manager, sensor_updater, flow_manager, flow_executor, flow_scheduler, performance_monitor, screenshot_stitcher

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
        screenshot_stitcher = ScreenshotStitcher(adb_bridge)

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

# Root API info
@app.get("/api/")
async def api_root():
    """API root endpoint"""
    return {
        "name": "Visual Mapper API",
        "version": "0.0.4",
        "endpoints": {
            "health": "/api/health",
            "connect": "/api/adb/connect",
            "pair": "/api/adb/pair",
            "disconnect": "/api/adb/disconnect",
            "devices": "/api/adb/devices",
            "screenshot": "/api/adb/screenshot",
            "sensors": "/api/sensors",
            "sensors_by_device": "/api/sensors/{device_id}",
            "sensor_detail": "/api/sensors/{device_id}/{sensor_id}",
            "device_classes": "/api/device-classes"
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
    """Capture screenshot and UI elements from device"""
    try:
        logger.info(f"[API] Capturing screenshot from {request.device_id}")

        # Capture PNG screenshot
        screenshot_bytes = await adb_bridge.capture_screenshot(request.device_id)

        # Extract UI elements
        elements = await adb_bridge.get_ui_elements(request.device_id)

        # Encode screenshot to base64
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        logger.info(f"[API] Screenshot captured: {len(screenshot_bytes)} bytes, {len(elements)} UI elements")

        return {
            "screenshot": screenshot_base64,
            "elements": elements,
            "timestamp": datetime.now().isoformat()
        }
    except ValueError as e:
        logger.error(f"[API] Screenshot failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Screenshot failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Screenshot Stitching Endpoint
@app.post("/api/adb/screenshot/stitch")
async def capture_stitched_screenshot(request: ScreenshotStitchRequest):
    """Capture full scrollable page by stitching multiple screenshots"""
    try:
        logger.info(f"[API] Capturing stitched screenshot from {request.device_id}")
        logger.debug(f"  max_scrolls={request.max_scrolls}, scroll_ratio={request.scroll_ratio}, overlap_ratio={request.overlap_ratio}")

        # Ensure screenshot_stitcher is initialized
        if screenshot_stitcher is None:
            logger.error("[API] ScreenshotStitcher not initialized")
            raise HTTPException(status_code=500, detail="Screenshot stitcher not available")

        # Capture scrolling screenshot
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

        return {
            "screenshot": screenshot_base64,
            "metadata": result['metadata'],
            "debug_screenshots": result.get('debug_screenshots', []),
            "timestamp": datetime.now().isoformat()
        }
    except ValueError as e:
        logger.error(f"[API] Stitched screenshot failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[API] Stitched screenshot failed: {e}")
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


# Sensor Management Endpoints
@app.post("/api/sensors")
async def create_sensor(sensor: SensorDefinition):
    """Create a new sensor"""
    try:
        logger.info(f"[API] Creating sensor for device {sensor.device_id}")
        created_sensor = sensor_manager.create_sensor(sensor)
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


# Mount static files LAST (catch-all route)
app.mount("/", StaticFiles(directory="www", html=True), name="www")

if __name__ == "__main__":
    logger.info("Starting Visual Mapper v0.0.4 (Phase 3 - Sensor Creation)")
    logger.info("Server: http://localhost:3000")
    logger.info("API: http://localhost:3000/api")
    logger.info(f"HTML Cache: {'DISABLED (development mode)' if DISABLE_HTML_CACHE else 'ENABLED (production mode)'}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=3000,
        log_level="info"
    )
