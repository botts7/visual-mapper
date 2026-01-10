"""
Settings routes for Visual Mapper
Handles user preferences and saved device persistence
"""

import json
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from routes import get_deps

router = APIRouter(prefix="/api/settings", tags=["settings"])


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
            with open(settings_file, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"[Settings] Failed to load settings: {e}")
    return {}


def save_settings(settings: dict):
    """Save settings to file"""
    ensure_data_dir()
    settings_file = _get_settings_file()
    try:
        with open(settings_file, 'w') as f:
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
            with open(devices_file, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"[Settings] Failed to load saved devices: {e}")
    return []


def save_saved_devices(devices: list):
    """Save devices to file"""
    ensure_data_dir()
    devices_file = _get_saved_devices_file()
    try:
        with open(devices_file, 'w') as f:
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
            "updated_keys": list(new_settings.keys())
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
    existing = next((d for d in devices if d['ip'] == device.ip and d['port'] == device.port), None)

    if existing:
        # Update existing
        existing['name'] = device.name or existing.get('name')
        existing['lastConnected'] = device.lastConnected or datetime.now().isoformat()
    else:
        # Add new
        device_dict = device.dict()
        device_dict['lastConnected'] = device_dict.get('lastConnected') or datetime.now().isoformat()
        device_dict['deviceId'] = f"{device.ip}:{device.port}"
        devices.append(device_dict)

    save_saved_devices(devices)
    return {"success": True, "device": device.dict()}


@router.delete("/saved-devices/{ip}/{port}")
async def remove_saved_device(ip: str, port: int):
    """Remove a saved device"""
    devices = load_saved_devices()
    original_count = len(devices)
    devices = [d for d in devices if not (d['ip'] == ip and d['port'] == port)]

    if len(devices) == original_count:
        raise HTTPException(status_code=404, detail="Device not found")

    save_saved_devices(devices)
    return {"success": True, "message": f"Device {ip}:{port} removed"}


@router.put("/saved-devices/{ip}/{port}/name")
async def update_device_name(ip: str, port: int, name: str):
    """Update a saved device's name"""
    devices = load_saved_devices()
    device = next((d for d in devices if d['ip'] == ip and d['port'] == port), None)

    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device['name'] = name
    save_saved_devices(devices)
    return {"success": True, "name": name}
