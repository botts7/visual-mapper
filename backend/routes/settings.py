"""
Settings routes for Visual Mapper
Handles user preferences and saved device persistence
"""

import json
import os
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from routes import get_deps
from routes.auth import verify_companion_auth

logger = logging.getLogger(__name__)

# All settings endpoints require companion auth (X-Companion-Key header or localhost/Ingress)
# This protects configuration changes including MQTT credentials
router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(verify_companion_auth)]
)


def _get_data_dir() -> Path:
    """Get data directory from deps, fallback to ./data"""
    try:
        deps = get_deps()
        if deps.data_dir:
            return Path(deps.data_dir)
    except Exception:
        pass
    return Path("data")


def _get_settings_file() -> Path:
    return _get_data_dir() / "settings.json"


def _get_saved_devices_file() -> Path:
    return _get_data_dir() / "saved_devices.json"


def ensure_data_dir():
    """Ensure data directory exists"""
    _get_data_dir().mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    """Load settings from file"""
    ensure_data_dir()
    settings_file = _get_settings_file()
    try:
        if settings_file.exists():
            with open(settings_file, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"[Settings] Failed to load settings: {e}")
    return {}


def save_settings(settings: dict):
    """Save settings to file"""
    ensure_data_dir()
    settings_file = _get_settings_file()
    try:
        with open(settings_file, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"[Settings] Failed to save settings: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {e}")


def load_saved_devices() -> list:
    """Load saved devices from file"""
    ensure_data_dir()
    devices_file = _get_saved_devices_file()
    try:
        if devices_file.exists():
            with open(devices_file, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"[Settings] Failed to load saved devices: {e}")
    return []


def save_saved_devices(devices: list):
    """Save devices to file"""
    ensure_data_dir()
    devices_file = _get_saved_devices_file()
    try:
        with open(devices_file, "w") as f:
            json.dump(devices, f, indent=2)
    except Exception as e:
        print(f"[Settings] Failed to save devices: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save devices: {e}")


# === Pydantic Models ===


class AutoReconnectSetting(BaseModel):
    enabled: bool


class SavedDevice(BaseModel):
    ip: str
    port: int
    name: Optional[str] = None
    lastConnected: Optional[str] = None
    deviceId: Optional[str] = None


class SavedDevicesList(BaseModel):
    devices: List[SavedDevice]


# === Routes ===


@router.get("")
async def get_all_settings():
    """Get all settings"""
    return load_settings()


@router.post("")
async def update_settings(new_settings: dict):
    """
    Update settings (partial update - merges with existing)

    Common settings:
        - mqtt_broker: MQTT broker hostname
        - mqtt_port: MQTT broker port
        - mqtt_username: MQTT username (optional)
        - mqtt_password: MQTT password (optional)
        - auto_reconnect: Auto-reconnect to devices on startup
    """
    import logging

    logger = logging.getLogger(__name__)

    try:
        # Load existing settings
        settings = load_settings()

        # Merge new settings
        for key, value in new_settings.items():
            if value is not None:  # Don't overwrite with None
                settings[key] = value

        # Save updated settings
        save_settings(settings)

        logger.info(f"[Settings] Updated settings: {list(new_settings.keys())}")

        return {
            "success": True,
            "message": "Settings updated",
            "updated_keys": list(new_settings.keys()),
        }
    except Exception as e:
        logger.error(f"[Settings] Failed to update settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auto-reconnect")
async def get_auto_reconnect():
    """Get auto-reconnect preference"""
    settings = load_settings()
    return {"enabled": settings.get("auto_reconnect", False)}


@router.post("/auto-reconnect")
async def set_auto_reconnect(setting: AutoReconnectSetting):
    """Set auto-reconnect preference"""
    settings = load_settings()
    settings["auto_reconnect"] = setting.enabled
    save_settings(settings)
    return {"success": True, "enabled": setting.enabled}


@router.get("/saved-devices")
async def get_saved_devices():
    """Get all saved devices"""
    devices = load_saved_devices()
    return {"devices": devices}


@router.post("/saved-devices")
async def save_all_devices(data: SavedDevicesList):
    """Save all devices (replaces existing)"""
    devices = [d.dict() for d in data.devices]
    save_saved_devices(devices)
    return {"success": True, "count": len(devices)}


@router.post("/saved-devices/add")
async def add_saved_device(device: SavedDevice):
    """Add a single saved device"""
    devices = load_saved_devices()

    # Check if device already exists
    existing = next(
        (d for d in devices if d["ip"] == device.ip and d["port"] == device.port), None
    )

    if existing:
        # Update existing
        existing["name"] = device.name or existing.get("name")
        existing["lastConnected"] = device.lastConnected or datetime.now().isoformat()
    else:
        # Add new
        device_dict = device.dict()
        device_dict["lastConnected"] = (
            device_dict.get("lastConnected") or datetime.now().isoformat()
        )
        device_dict["deviceId"] = f"{device.ip}:{device.port}"
        devices.append(device_dict)

    save_saved_devices(devices)
    return {"success": True, "device": device.dict()}


@router.delete("/saved-devices/{ip}/{port}")
async def remove_saved_device(ip: str, port: int):
    """Remove a saved device"""
    devices = load_saved_devices()
    original_count = len(devices)
    devices = [d for d in devices if not (d["ip"] == ip and d["port"] == port)]

    if len(devices) == original_count:
        raise HTTPException(status_code=404, detail="Device not found")

    save_saved_devices(devices)
    return {"success": True, "message": f"Device {ip}:{port} removed"}


@router.put("/saved-devices/{ip}/{port}/name")
async def update_device_name(ip: str, port: int, name: str):
    """Update a saved device's name"""
    devices = load_saved_devices()
    device = next((d for d in devices if d["ip"] == ip and d["port"] == port), None)

    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device["name"] = name
    save_saved_devices(devices)
    return {"success": True, "name": name}


# === Backend Preference Settings ===


class BackendPreference(BaseModel):
    capture_backend: Optional[str] = None  # "auto", "companion", "adbutils", "subprocess"
    shell_method: Optional[str] = None  # "auto", "persistent", "regular"


@router.get("/backend/{device_id}")
async def get_backend_preference(device_id: str):
    """Get capture backend preference for a device"""
    import logging
    logger = logging.getLogger(__name__)

    deps = get_deps()

    # Get current preferred backend from adb_bridge
    current_capture = deps.adb_bridge._preferred_backend.get(device_id, "auto")

    # Get shell preference from settings
    settings = load_settings()
    device_prefs = settings.get("device_backend_prefs", {}).get(device_id, {})
    shell_method = device_prefs.get("shell_method", "auto")

    logger.info(f"[Settings] Backend prefs for {device_id}: capture={current_capture}, shell={shell_method}")

    return {
        "device_id": device_id,
        "capture_backend": current_capture,
        "shell_method": shell_method,
        "available_capture_backends": ["auto", "companion", "adbutils", "subprocess"],
        "available_shell_methods": ["auto", "persistent", "regular"]
    }


@router.post("/backend/{device_id}")
async def set_backend_preference(device_id: str, prefs: BackendPreference):
    """Set capture backend and shell method preference for a device"""
    import logging
    logger = logging.getLogger(__name__)

    deps = get_deps()
    result = {"device_id": device_id, "updated": []}

    # Update capture backend preference
    if prefs.capture_backend:
        valid_backends = ["auto", "companion", "adbutils", "subprocess"]
        if prefs.capture_backend not in valid_backends:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid capture_backend. Must be one of: {valid_backends}"
            )

        if prefs.capture_backend == "auto":
            # Remove preference to let auto-detection work
            deps.adb_bridge._preferred_backend.pop(device_id, None)
        else:
            deps.adb_bridge._preferred_backend[device_id] = prefs.capture_backend

        # PERSIST to settings.json so it survives restart
        settings = load_settings()
        if "device_backend_prefs" not in settings:
            settings["device_backend_prefs"] = {}
        if device_id not in settings["device_backend_prefs"]:
            settings["device_backend_prefs"][device_id] = {}
        settings["device_backend_prefs"][device_id]["capture_backend"] = prefs.capture_backend
        save_settings(settings)

        result["capture_backend"] = prefs.capture_backend
        result["updated"].append("capture_backend")
        logger.info(f"[Settings] Set capture backend for {device_id}: {prefs.capture_backend}")

    # Update shell method preference (persisted to settings.json)
    if prefs.shell_method:
        valid_methods = ["auto", "persistent", "regular"]
        if prefs.shell_method not in valid_methods:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid shell_method. Must be one of: {valid_methods}"
            )

        settings = load_settings()
        if "device_backend_prefs" not in settings:
            settings["device_backend_prefs"] = {}
        if device_id not in settings["device_backend_prefs"]:
            settings["device_backend_prefs"][device_id] = {}

        settings["device_backend_prefs"][device_id]["shell_method"] = prefs.shell_method
        save_settings(settings)

        result["shell_method"] = prefs.shell_method
        result["updated"].append("shell_method")
        logger.info(f"[Settings] Set shell method for {device_id}: {prefs.shell_method}")

    return result


@router.get("/backend")
async def get_all_backend_preferences():
    """Get all device backend preferences"""
    deps = get_deps()
    settings = load_settings()

    all_prefs = {}

    # Merge capture backend prefs (from adb_bridge runtime)
    for device_id, backend in deps.adb_bridge._preferred_backend.items():
        if device_id not in all_prefs:
            all_prefs[device_id] = {}
        all_prefs[device_id]["capture_backend"] = backend

    # Merge shell method prefs (from settings)
    device_prefs = settings.get("device_backend_prefs", {})
    for device_id, prefs in device_prefs.items():
        if device_id not in all_prefs:
            all_prefs[device_id] = {}
        all_prefs[device_id]["shell_method"] = prefs.get("shell_method", "auto")

    return {
        "preferences": all_prefs,
        "available_capture_backends": ["auto", "companion", "adbutils", "subprocess"],
        "available_shell_methods": ["auto", "persistent", "regular"]
    }


# === MQTT Configuration ===


class MqttSettings(BaseModel):
    broker: str
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None


def _is_home_assistant_addon() -> bool:
    """Check if running as Home Assistant add-on"""
    return os.path.exists("/data/options.json") or os.environ.get("SUPERVISOR_TOKEN") is not None


def _get_ha_mqtt_settings() -> Optional[dict]:
    """Get MQTT settings from Home Assistant Supervisor API"""
    supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
    if not supervisor_token:
        return None

    try:
        import urllib.request
        import ssl

        # Create unverified context for local supervisor
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(
            "http://supervisor/services/mqtt",
            headers={"Authorization": f"Bearer {supervisor_token}"}
        )

        with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
            data = json.loads(response.read().decode())
            if data.get("result") == "ok" and data.get("data"):
                mqtt_data = data["data"]
                return {
                    "broker": mqtt_data.get("host", "core-mosquitto"),
                    "port": mqtt_data.get("port", 1883),
                    "username": mqtt_data.get("username"),
                    "password": mqtt_data.get("password"),
                    "source": "homeassistant"
                }
    except Exception as e:
        logger.warning(f"[Settings] Failed to get HA MQTT settings: {e}")

    return None


@router.get("/mqtt")
async def get_mqtt_settings():
    """
    Get current MQTT settings.

    Returns settings from (in order of priority):
    1. Home Assistant Supervisor API (if running as add-on)
    2. Saved settings in settings.json
    3. Environment variables (MQTT_BROKER, MQTT_PORT, etc.)
    """
    # Try Home Assistant first
    if _is_home_assistant_addon():
        ha_settings = _get_ha_mqtt_settings()
        if ha_settings:
            return ha_settings

    # Try saved settings
    settings = load_settings()
    mqtt_settings = settings.get("mqtt", {})

    # Fall back to environment variables
    return {
        "broker": mqtt_settings.get("broker") or os.environ.get("MQTT_BROKER", ""),
        "port": mqtt_settings.get("port") or int(os.environ.get("MQTT_PORT", "1883")),
        "username": mqtt_settings.get("username") or os.environ.get("MQTT_USERNAME", ""),
        "password": mqtt_settings.get("password") or os.environ.get("MQTT_PASSWORD", ""),
        "source": "saved" if mqtt_settings.get("broker") else "environment"
    }


@router.post("/mqtt")
async def save_mqtt_settings(mqtt: MqttSettings):
    """
    Save MQTT settings and reconnect.

    Saves to settings.json and triggers MQTT reconnection with new credentials.
    """
    deps = get_deps()

    # Save settings
    settings = load_settings()
    settings["mqtt"] = {
        "broker": mqtt.broker,
        "port": mqtt.port,
        "username": mqtt.username,
        "password": mqtt.password,
    }
    save_settings(settings)

    logger.info(f"[Settings] MQTT settings saved: {mqtt.broker}:{mqtt.port}")

    # Try to reconnect with new settings
    connected = False
    error_msg = None

    if deps.mqtt_manager:
        try:
            # Disconnect first if connected
            if deps.mqtt_manager.is_connected:
                await deps.mqtt_manager.disconnect()

            # Update settings
            deps.mqtt_manager.update_settings(
                broker=mqtt.broker,
                port=mqtt.port,
                username=mqtt.username,
                password=mqtt.password,
            )

            # Reconnect with new settings
            await deps.mqtt_manager.connect()
            connected = deps.mqtt_manager.is_connected
            if connected:
                logger.info(f"[Settings] MQTT connected to {mqtt.broker}:{mqtt.port}")
            else:
                error_msg = "Connection attempt completed but not connected"
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[Settings] MQTT reconnect failed: {e}")

    return {
        "success": True,
        "connected": connected,
        "broker": mqtt.broker,
        "port": mqtt.port,
        "error": error_msg
    }


@router.post("/mqtt/test")
async def test_mqtt_connection(mqtt: MqttSettings):
    """
    Test MQTT connection without saving settings.

    Useful to verify credentials before committing them.
    """
    try:
        import paho.mqtt.client as paho_mqtt

        # Create a temporary client to test connection
        try:
            client = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            client = paho_mqtt.Client()

        if mqtt.username:
            client.username_pw_set(mqtt.username, mqtt.password or "")

        # Try to connect with a short timeout
        client.connect(mqtt.broker, mqtt.port, keepalive=5)
        client.disconnect()

        return {
            "success": True,
            "message": f"Successfully connected to {mqtt.broker}:{mqtt.port}"
        }

    except Exception as e:
        logger.warning(f"[Settings] MQTT test connection failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }
