"""
Auto Sensors - Zero-config sensors created automatically on device connect.

These sensors require no user setup and provide immediate value:
- App Screen Sensor: Current foreground app + activity/screen type
- Screen Frozen Sensor: Detects when screen content hasn't changed
- Screen Changed Sensor: Triggers when screen content changes
- Battery Level: Battery percentage (0-100%)
- Battery Charging: Whether device is charging
- Battery Temperature: Battery temperature in Celsius
- Screen Brightness: Display brightness percentage
- WiFi Signal: WiFi RSSI signal strength in dBm
- Memory Available: Available RAM percentage

All sensors auto-publish via MQTT discovery to Home Assistant.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable, Awaitable
from enum import Enum

logger = logging.getLogger(__name__)


class ScreenType(Enum):
    """Inferred screen types based on activity name patterns."""
    HOME = "home"
    PLAYER = "player"
    SEARCH = "search"
    SETTINGS = "settings"
    DETAIL = "detail"
    LIST = "list"
    LOGIN = "login"
    LOADING = "loading"
    ERROR = "error"
    UNKNOWN = "unknown"


# Activity name patterns for screen type detection
SCREEN_TYPE_PATTERNS = {
    ScreenType.PLAYER: [
        r"player", r"video", r"watch", r"playback", r"media",
        r"stream", r"fullscreen", r"exoplayer"
    ],
    ScreenType.SEARCH: [
        r"search", r"find", r"query", r"browse"
    ],
    ScreenType.SETTINGS: [
        r"setting", r"pref", r"config", r"option"
    ],
    ScreenType.HOME: [
        r"main", r"home", r"launch", r"dashboard", r"landing"
    ],
    ScreenType.DETAIL: [
        r"detail", r"info", r"view", r"show", r"item"
    ],
    ScreenType.LIST: [
        r"list", r"grid", r"collection", r"feed", r"timeline"
    ],
    ScreenType.LOGIN: [
        r"login", r"signin", r"auth", r"credential", r"password"
    ],
    ScreenType.LOADING: [
        r"splash", r"loading", r"init"
    ],
    ScreenType.ERROR: [
        r"error", r"crash", r"fail"
    ],
}


@dataclass
class AppScreenState:
    """Current state of the foreground app/screen."""
    package: str = ""
    app_name: str = ""
    activity: str = ""
    screen_type: ScreenType = ScreenType.UNKNOWN
    timestamp: float = field(default_factory=time.time)

    @property
    def display_state(self) -> str:
        """Human-readable state for sensor."""
        if not self.app_name:
            return "Unknown"
        if self.screen_type != ScreenType.UNKNOWN:
            return f"{self.app_name} - {self.screen_type.value.title()}"
        return self.app_name

    def to_attributes(self) -> Dict[str, Any]:
        """Convert to HA sensor attributes."""
        return {
            "package": self.package,
            "app_name": self.app_name,
            "activity": self.activity,
            "screen_type": self.screen_type.value,
            "last_updated": self.timestamp,
        }


@dataclass
class ScreenChangeState:
    """Track screen content changes via frame hashing."""
    last_hash: Optional[str] = None
    last_change_time: float = field(default_factory=time.time)
    static_since: float = field(default_factory=time.time)
    is_frozen: bool = False
    change_count: int = 0

    def to_attributes(self) -> Dict[str, Any]:
        """Convert to HA sensor attributes."""
        static_duration = time.time() - self.static_since if self.is_frozen else 0
        return {
            "last_change": self.last_change_time,
            "static_since": self.static_since if self.is_frozen else None,
            "static_seconds": int(static_duration),
            "change_count": self.change_count,
        }


@dataclass
class DeviceState:
    """Track device hardware state (battery, WiFi, memory, brightness)."""
    # Battery
    battery_level: int = -1
    battery_charging: bool = False
    battery_temperature: float = 0.0
    battery_status: str = "unknown"  # charging, discharging, full, not_charging

    # WiFi
    wifi_rssi: int = -100
    wifi_ssid: str = ""
    wifi_link_speed: int = 0

    # Display
    screen_brightness: int = -1
    screen_brightness_mode: str = "manual"  # manual or auto

    # Memory
    memory_total_mb: int = 0
    memory_available_mb: int = 0
    memory_percent_available: int = 0

    # Screen
    screen_on: bool = True
    screen_on_initialized: bool = False  # Track if initial state published

    # Companion / Connectivity
    companion_streaming: bool = False
    companion_connected: bool = False
    companion_initialized: bool = False  # Track if initial state published
    accessibility_enabled: bool = False
    accessibility_initialized: bool = False  # Track if initial state published

    # Timestamp
    last_updated: float = field(default_factory=time.time)

    def battery_attributes(self) -> Dict[str, Any]:
        """Battery sensor attributes."""
        return {
            "charging": self.battery_charging,
            "temperature_c": self.battery_temperature,
            "status": self.battery_status,
            "last_updated": self.last_updated,
        }

    def wifi_attributes(self) -> Dict[str, Any]:
        """WiFi sensor attributes."""
        return {
            "ssid": self.wifi_ssid,
            "link_speed_mbps": self.wifi_link_speed,
            "last_updated": self.last_updated,
        }

    def brightness_attributes(self) -> Dict[str, Any]:
        """Brightness sensor attributes."""
        return {
            "mode": self.screen_brightness_mode,
            "raw_value": self.screen_brightness,
            "last_updated": self.last_updated,
        }

    def memory_attributes(self) -> Dict[str, Any]:
        """Memory sensor attributes."""
        return {
            "total_mb": self.memory_total_mb,
            "available_mb": self.memory_available_mb,
            "last_updated": self.last_updated,
        }

    def screen_attributes(self) -> Dict[str, Any]:
        """Screen on/off sensor attributes."""
        return {
            "last_updated": self.last_updated,
        }

    def companion_attributes(self) -> Dict[str, Any]:
        """Companion status sensor attributes."""
        return {
            "streaming": self.companion_streaming,
            "connected": self.companion_connected,
            "last_updated": self.last_updated,
        }

    def accessibility_attributes(self) -> Dict[str, Any]:
        """Accessibility sensor attributes."""
        return {
            "last_updated": self.last_updated,
        }


def infer_screen_type(activity_name: str) -> ScreenType:
    """
    Infer the screen type from an Android activity name.

    Examples:
        PlayerActivity -> ScreenType.PLAYER
        MainActivity -> ScreenType.HOME
        SearchFragment -> ScreenType.SEARCH
    """
    if not activity_name:
        return ScreenType.UNKNOWN

    activity_lower = activity_name.lower()

    for screen_type, patterns in SCREEN_TYPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, activity_lower):
                return screen_type

    return ScreenType.UNKNOWN


def parse_app_label(package: str) -> str:
    """
    Convert package name to friendly app name.

    Examples:
        com.netflix.mediaclient -> Netflix
        com.byd.aeri -> BYD
        com.google.android.youtube -> YouTube
    """
    # Common package -> name mappings
    KNOWN_APPS = {
        "com.netflix.mediaclient": "Netflix",
        "com.google.android.youtube": "YouTube",
        "com.spotify.music": "Spotify",
        "com.amazon.avod": "Prime Video",
        "com.disney.disneyplus": "Disney+",
        "com.byd.aeri": "BYD",
        "com.tesla.android": "Tesla",
        "tv.plex.android": "Plex",
        "com.hbo.hbonow": "HBO Max",
        "com.google.android.apps.photos": "Google Photos",
        "com.whatsapp": "WhatsApp",
        "com.facebook.katana": "Facebook",
        "com.instagram.android": "Instagram",
        "com.twitter.android": "Twitter",
        "com.android.chrome": "Chrome",
        "com.android.settings": "Settings",
        "com.android.launcher": "Launcher",
        "com.sec.android.app.launcher": "Samsung Launcher",
        "com.miui.home": "MIUI Launcher",
    }

    if package in KNOWN_APPS:
        return KNOWN_APPS[package]

    # Extract app name from package
    # com.company.appname -> Appname
    parts = package.split(".")
    if len(parts) >= 2:
        # Try last part, then second-to-last
        for idx in [-1, -2]:
            name = parts[idx]
            # Skip generic names
            if name.lower() not in ["android", "app", "mobile", "client", "lite"]:
                # Capitalize and clean
                return name.replace("_", " ").title()

    return package.split(".")[-1].title()


class AutoSensorManager:
    """
    Manages auto-created sensors for connected devices.

    Provides zero-config sensors:
    - sensor.{device}_app_screen: Current foreground app + screen type
    - binary_sensor.{device}_screen_frozen: True if screen unchanged for 60s+
    - binary_sensor.{device}_screen_changed: Pulses on screen content change
    """

    FROZEN_THRESHOLD_SECONDS = 60  # Screen unchanged for this long = frozen
    UPDATE_INTERVAL_SECONDS = 5   # How often to check screen state
    DEVICE_STATE_INTERVAL = 30    # How often to check device hardware state

    def __init__(self, adb_bridge, mqtt_manager):
        self.adb_bridge = adb_bridge
        self.mqtt_manager = mqtt_manager

        # State tracking per device
        self._app_states: Dict[str, AppScreenState] = {}
        self._screen_states: Dict[str, ScreenChangeState] = {}
        self._device_states: Dict[str, DeviceState] = {}
        self._update_tasks: Dict[str, asyncio.Task] = {}
        self._device_state_tasks: Dict[str, asyncio.Task] = {}
        self._running = False

        # Track last update time for device state (battery/wifi/etc)
        self._last_device_update: Dict[str, float] = {}

        # Callbacks for state changes
        self._on_app_change_callbacks: list[Callable] = []
        self._on_screen_change_callbacks: list[Callable] = []

    async def start_device(self, device_id: str, stable_device_id: str):
        """
        Start auto-sensor monitoring for a device.

        Called when a device connects. Publishes MQTT discovery and starts
        the update loop.
        """
        logger.info(f"[AutoSensors] Starting auto-sensors for {device_id}")

        # Initialize state
        self._app_states[device_id] = AppScreenState()
        self._screen_states[device_id] = ScreenChangeState()
        self._device_states[device_id] = DeviceState()

        # Publish MQTT discovery for auto-sensors
        await self._publish_discovery(device_id, stable_device_id)

        # Start update loop for app/screen sensors (fast - 5s)
        if device_id not in self._update_tasks or self._update_tasks[device_id].done():
            self._update_tasks[device_id] = asyncio.create_task(
                self._update_loop(device_id, stable_device_id)
            )

        # Start device state loop (slower - 30s for battery/wifi/memory)
        if device_id not in self._device_state_tasks or self._device_state_tasks[device_id].done():
            self._device_state_tasks[device_id] = asyncio.create_task(
                self._device_state_loop(device_id, stable_device_id)
            )

    async def stop_device(self, device_id: str):
        """Stop auto-sensor monitoring for a device."""
        logger.info(f"[AutoSensors] Stopping auto-sensors for {device_id}")

        # Cancel update task
        if device_id in self._update_tasks:
            self._update_tasks[device_id].cancel()
            try:
                await self._update_tasks[device_id]
            except asyncio.CancelledError:
                pass
            del self._update_tasks[device_id]

        # Cancel device state task
        if device_id in self._device_state_tasks:
            self._device_state_tasks[device_id].cancel()
            try:
                await self._device_state_tasks[device_id]
            except asyncio.CancelledError:
                pass
            del self._device_state_tasks[device_id]

        # Clean up state
        self._app_states.pop(device_id, None)
        self._screen_states.pop(device_id, None)
        self._device_states.pop(device_id, None)
        self._last_device_update.pop(device_id, None)

    async def _publish_discovery(self, device_id: str, stable_device_id: str):
        """Publish MQTT discovery payloads for auto-sensors."""
        if not self.mqtt_manager:
            return

        device_name = device_id.replace(":", "_").replace(".", "_")

        # App Screen Sensor
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_app_screen",
            name="App Screen",
            sensor_type="sensor",
            icon="mdi:application",
            device_class=None,
            unit=None,
        )

        # Screen Frozen Binary Sensor
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_screen_frozen",
            name="Screen Frozen",
            sensor_type="binary_sensor",
            icon="mdi:snowflake-alert",
            device_class="problem",
            unit=None,
        )

        # Screen Changed Binary Sensor
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_screen_changed",
            name="Screen Changed",
            sensor_type="binary_sensor",
            icon="mdi:monitor-eye",
            device_class=None,
            unit=None,
        )

        # Battery Level Sensor
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_battery_level",
            name="Battery Level",
            sensor_type="sensor",
            icon="mdi:battery",
            device_class="battery",
            unit="%",
        )

        # Battery Charging Binary Sensor
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_battery_charging",
            name="Battery Charging",
            sensor_type="binary_sensor",
            icon="mdi:battery-charging",
            device_class="battery_charging",
            unit=None,
        )

        # Battery Temperature Sensor
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_battery_temperature",
            name="Battery Temperature",
            sensor_type="sensor",
            icon="mdi:thermometer",
            device_class="temperature",
            unit="°C",
        )

        # Screen Brightness Sensor
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_screen_brightness",
            name="Screen Brightness",
            sensor_type="sensor",
            icon="mdi:brightness-6",
            device_class=None,
            unit="%",
        )

        # WiFi Signal Sensor
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_wifi_signal",
            name="WiFi Signal",
            sensor_type="sensor",
            icon="mdi:wifi",
            device_class="signal_strength",
            unit="dBm",
        )

        # Memory Available Sensor
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_memory_available",
            name="Memory Available",
            sensor_type="sensor",
            icon="mdi:memory",
            device_class=None,
            unit="%",
        )

        # Screen On Binary Sensor
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_screen_on",
            name="Screen On",
            sensor_type="binary_sensor",
            icon="mdi:monitor",
            device_class=None,
            unit=None,
        )

        # Companion Streaming Binary Sensor
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_companion_streaming",
            name="Companion Streaming",
            sensor_type="binary_sensor",
            icon="mdi:cast-connected",
            device_class="connectivity",
            unit=None,
        )

        # Companion Connected Binary Sensor (via MQTT)
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_companion_connected",
            name="Companion Connected",
            sensor_type="binary_sensor",
            icon="mdi:cellphone-link",
            device_class="connectivity",
            unit=None,
        )

        # Accessibility Service Enabled Binary Sensor
        await self.mqtt_manager.publish_auto_sensor_discovery(
            device_id=device_id,
            stable_device_id=stable_device_id,
            sensor_id=f"{device_name}_accessibility_enabled",
            name="Accessibility Service",
            sensor_type="binary_sensor",
            icon="mdi:human",
            device_class=None,
            unit=None,
        )

        logger.info(f"[AutoSensors] Published discovery for {device_id}")

    async def _update_loop(self, device_id: str, stable_device_id: str):
        """Background loop to update auto-sensor states."""
        device_name = device_id.replace(":", "_").replace(".", "_")
        # Use stable_device_id for MQTT topics to match discovery
        mqtt_device_id = stable_device_id or device_name

        while True:
            try:
                # Update app screen state
                await self._update_app_screen(device_id, device_name, mqtt_device_id)

                # Update screen change state
                await self._update_screen_change(device_id, device_name, mqtt_device_id)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[AutoSensors] Update error for {device_id}: {e}")

            await asyncio.sleep(self.UPDATE_INTERVAL_SECONDS)

    async def _update_app_screen(self, device_id: str, device_name: str, mqtt_device_id: str):
        """Update the app screen sensor."""
        try:
            # Get foreground app info via ADB using the robust get_current_activity method
            try:
                activity_info = await self.adb_bridge.get_current_activity(device_id, as_dict=True)
            except Exception as e:
                logger.debug(f"[AutoSensors] get_current_activity failed for {device_id}: {e}")
                return

            if not activity_info or not activity_info.get("package"):
                logger.debug(f"[AutoSensors] No activity info for {device_id}")
                return

            package = activity_info.get("package", "")
            activity = activity_info.get("activity", "")

            # Get current state
            current = self._app_states.get(device_id, AppScreenState())

            # Check if changed
            if package != current.package or activity != current.activity:
                # Create new state
                new_state = AppScreenState(
                    package=package,
                    app_name=parse_app_label(package),
                    activity=activity,
                    screen_type=infer_screen_type(activity),
                    timestamp=time.time(),
                )
                self._app_states[device_id] = new_state

                # Publish to MQTT (use mqtt_device_id to match discovery topic)
                if self.mqtt_manager:
                    await self.mqtt_manager.publish_auto_sensor_state(
                        device_name=mqtt_device_id,
                        sensor_id=f"{device_name}_app_screen",
                        state=new_state.display_state,
                        attributes=new_state.to_attributes(),
                    )

                logger.info(
                    f"[AutoSensors] {device_id} app changed: {new_state.display_state}"
                )

                # Notify callbacks
                for callback in self._on_app_change_callbacks:
                    try:
                        await callback(device_id, new_state)
                    except Exception as e:
                        logger.warning(f"[AutoSensors] Callback error: {e}")

        except Exception as e:
            logger.debug(f"[AutoSensors] App screen update failed: {e}")

    async def _update_screen_change(self, device_id: str, device_name: str, mqtt_device_id: str):
        """Update screen frozen/changed sensors using frame hashing."""
        try:
            # Get current screenshot hash
            current_hash = await self._get_screen_hash(device_id)

            if not current_hash:
                return

            state = self._screen_states.get(device_id, ScreenChangeState())
            now = time.time()

            if state.last_hash is None:
                # First capture - publish initial state
                state.last_hash = current_hash
                state.last_change_time = now
                state.static_since = now
                state.is_frozen = False
                self._screen_states[device_id] = state

                # Publish initial screen_frozen = OFF
                if self.mqtt_manager:
                    await self.mqtt_manager.publish_auto_sensor_state(
                        device_name=mqtt_device_id,
                        sensor_id=f"{device_name}_screen_frozen",
                        state="OFF",
                        attributes=state.to_attributes(),
                    )
                return

            # Check if screen changed
            screen_changed = current_hash != state.last_hash

            if screen_changed:
                state.last_hash = current_hash
                state.last_change_time = now
                state.static_since = now
                state.is_frozen = False
                state.change_count += 1

                # Publish screen_changed = ON (momentary)
                if self.mqtt_manager:
                    await self.mqtt_manager.publish_auto_sensor_state(
                        device_name=mqtt_device_id,
                        sensor_id=f"{device_name}_screen_changed",
                        state="ON",
                        attributes=state.to_attributes(),
                    )

                # Notify callbacks
                for callback in self._on_screen_change_callbacks:
                    try:
                        await callback(device_id, state)
                    except Exception as e:
                        logger.warning(f"[AutoSensors] Callback error: {e}")
            else:
                # Screen unchanged - check if frozen
                static_duration = now - state.static_since
                was_frozen = state.is_frozen
                state.is_frozen = static_duration >= self.FROZEN_THRESHOLD_SECONDS

                # Publish screen_changed = OFF
                if self.mqtt_manager:
                    await self.mqtt_manager.publish_auto_sensor_state(
                        device_name=mqtt_device_id,
                        sensor_id=f"{device_name}_screen_changed",
                        state="OFF",
                        attributes=state.to_attributes(),
                    )

                # Publish screen_frozen state change
                if state.is_frozen != was_frozen and self.mqtt_manager:
                    await self.mqtt_manager.publish_auto_sensor_state(
                        device_name=mqtt_device_id,
                        sensor_id=f"{device_name}_screen_frozen",
                        state="ON" if state.is_frozen else "OFF",
                        attributes=state.to_attributes(),
                    )

            self._screen_states[device_id] = state

        except Exception as e:
            logger.debug(f"[AutoSensors] Screen change update failed: {e}")

    async def _device_state_loop(self, device_id: str, stable_device_id: str):
        """Background loop to update device hardware state (battery, WiFi, memory, brightness)."""
        device_name = device_id.replace(":", "_").replace(".", "_")
        mqtt_device_id = stable_device_id or device_name

        # Wait a bit before first update to let other sensors initialize first
        await asyncio.sleep(2)

        while True:
            try:
                await self._update_device_state(device_id, device_name, mqtt_device_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[AutoSensors] Device state update error for {device_id}: {e}")

            await asyncio.sleep(self.DEVICE_STATE_INTERVAL)

    async def _update_device_state(self, device_id: str, device_name: str, mqtt_device_id: str):
        """Update device hardware state sensors (battery, WiFi, memory, brightness)."""
        state = self._device_states.get(device_id, DeviceState())
        state.last_updated = time.time()

        # Fetch all device info in parallel
        battery_task = self._fetch_battery_info(device_id)
        wifi_task = self._fetch_wifi_info(device_id)
        memory_task = self._fetch_memory_info(device_id)
        brightness_task = self._fetch_brightness_info(device_id)

        results = await asyncio.gather(
            battery_task, wifi_task, memory_task, brightness_task,
            return_exceptions=True
        )

        battery_info, wifi_info, memory_info, brightness_info = results

        # Update battery state
        if isinstance(battery_info, dict):
            old_level = state.battery_level
            old_charging = state.battery_charging
            state.battery_level = battery_info.get("level", -1)
            state.battery_charging = battery_info.get("charging", False)
            state.battery_temperature = battery_info.get("temperature", 0.0)
            state.battery_status = battery_info.get("status", "unknown")

            # Publish battery level (always publish on first run or change)
            if self.mqtt_manager and (old_level != state.battery_level or old_level == -1):
                await self.mqtt_manager.publish_auto_sensor_state(
                    device_name=mqtt_device_id,
                    sensor_id=f"{device_name}_battery_level",
                    state=str(state.battery_level),
                    attributes=state.battery_attributes(),
                )

            # Publish battery charging
            if self.mqtt_manager and (old_charging != state.battery_charging or old_level == -1):
                await self.mqtt_manager.publish_auto_sensor_state(
                    device_name=mqtt_device_id,
                    sensor_id=f"{device_name}_battery_charging",
                    state="ON" if state.battery_charging else "OFF",
                    attributes=state.battery_attributes(),
                )

            # Publish battery temperature (always publish)
            if self.mqtt_manager:
                await self.mqtt_manager.publish_auto_sensor_state(
                    device_name=mqtt_device_id,
                    sensor_id=f"{device_name}_battery_temperature",
                    state=str(round(state.battery_temperature, 1)),
                    attributes=state.battery_attributes(),
                )

        # Update WiFi state
        if isinstance(wifi_info, dict):
            old_rssi = state.wifi_rssi
            state.wifi_rssi = wifi_info.get("rssi", -100)
            state.wifi_ssid = wifi_info.get("ssid", "")
            state.wifi_link_speed = wifi_info.get("link_speed", 0)

            if self.mqtt_manager and (old_rssi != state.wifi_rssi or old_rssi == -100):
                await self.mqtt_manager.publish_auto_sensor_state(
                    device_name=mqtt_device_id,
                    sensor_id=f"{device_name}_wifi_signal",
                    state=str(state.wifi_rssi),
                    attributes=state.wifi_attributes(),
                )

        # Update memory state
        if isinstance(memory_info, dict):
            old_mem = state.memory_percent_available
            state.memory_total_mb = memory_info.get("total_mb", 0)
            state.memory_available_mb = memory_info.get("available_mb", 0)
            state.memory_percent_available = memory_info.get("percent_available", 0)

            if self.mqtt_manager and (old_mem != state.memory_percent_available or old_mem == 0):
                await self.mqtt_manager.publish_auto_sensor_state(
                    device_name=mqtt_device_id,
                    sensor_id=f"{device_name}_memory_available",
                    state=str(state.memory_percent_available),
                    attributes=state.memory_attributes(),
                )

        # Update brightness state
        if isinstance(brightness_info, dict):
            old_brightness = state.screen_brightness
            state.screen_brightness = brightness_info.get("brightness", -1)
            state.screen_brightness_mode = brightness_info.get("mode", "manual")

            # Convert 0-255 to percentage
            brightness_pct = round((state.screen_brightness / 255) * 100) if state.screen_brightness >= 0 else 0

            if self.mqtt_manager and (old_brightness != state.screen_brightness or old_brightness == -1):
                await self.mqtt_manager.publish_auto_sensor_state(
                    device_name=mqtt_device_id,
                    sensor_id=f"{device_name}_screen_brightness",
                    state=str(brightness_pct),
                    attributes=state.brightness_attributes(),
                )

        # Fetch and update screen on, companion, and accessibility states
        screen_on_task = self._fetch_screen_on(device_id)
        companion_task = self._fetch_companion_status(device_id)
        accessibility_task = self._fetch_accessibility_status(device_id)

        additional_results = await asyncio.gather(
            screen_on_task, companion_task, accessibility_task,
            return_exceptions=True
        )

        screen_on_info, companion_info, accessibility_info = additional_results

        # Update screen on state
        if isinstance(screen_on_info, dict):
            old_screen_on = state.screen_on
            state.screen_on = screen_on_info.get("screen_on", True)

            # Publish on change OR first time
            if self.mqtt_manager and (old_screen_on != state.screen_on or not state.screen_on_initialized):
                state.screen_on_initialized = True
                await self.mqtt_manager.publish_auto_sensor_state(
                    device_name=mqtt_device_id,
                    sensor_id=f"{device_name}_screen_on",
                    state="ON" if state.screen_on else "OFF",
                    attributes=state.screen_attributes(),
                )

        # Update companion streaming/connected state
        if isinstance(companion_info, dict):
            old_streaming = state.companion_streaming
            old_connected = state.companion_connected
            state.companion_streaming = companion_info.get("streaming", False)
            state.companion_connected = companion_info.get("connected", False)

            # Publish on change OR first time
            needs_publish = not state.companion_initialized
            if self.mqtt_manager and (old_streaming != state.companion_streaming or needs_publish):
                await self.mqtt_manager.publish_auto_sensor_state(
                    device_name=mqtt_device_id,
                    sensor_id=f"{device_name}_companion_streaming",
                    state="ON" if state.companion_streaming else "OFF",
                    attributes=state.companion_attributes(),
                )

            if self.mqtt_manager and (old_connected != state.companion_connected or needs_publish):
                await self.mqtt_manager.publish_auto_sensor_state(
                    device_name=mqtt_device_id,
                    sensor_id=f"{device_name}_companion_connected",
                    state="ON" if state.companion_connected else "OFF",
                    attributes=state.companion_attributes(),
                )

            state.companion_initialized = True

        # Update accessibility state
        if isinstance(accessibility_info, dict):
            old_accessibility = state.accessibility_enabled
            state.accessibility_enabled = accessibility_info.get("enabled", False)

            # Publish on change OR first time
            if self.mqtt_manager and (old_accessibility != state.accessibility_enabled or not state.accessibility_initialized):
                state.accessibility_initialized = True
                await self.mqtt_manager.publish_auto_sensor_state(
                    device_name=mqtt_device_id,
                    sensor_id=f"{device_name}_accessibility_enabled",
                    state="ON" if state.accessibility_enabled else "OFF",
                    attributes=state.accessibility_attributes(),
                )

        self._device_states[device_id] = state
        logger.info(f"[AutoSensors] Updated device state for {device_id}: battery={state.battery_level}%, wifi={state.wifi_rssi}dBm, mem={state.memory_percent_available}%")

    async def _fetch_battery_info(self, device_id: str) -> Dict[str, Any]:
        """Fetch battery info via ADB."""
        try:
            result = await self.adb_bridge.shell_command(device_id, "dumpsys battery")
            if not result:
                return {}

            info = {}
            for line in result.split("\n"):
                line = line.strip()
                if line.startswith("level:"):
                    info["level"] = int(line.split(":")[1].strip())
                elif line.startswith("AC powered:"):
                    info["ac_powered"] = line.split(":")[1].strip().lower() == "true"
                elif line.startswith("USB powered:"):
                    info["usb_powered"] = line.split(":")[1].strip().lower() == "true"
                elif line.startswith("Wireless powered:"):
                    info["wireless_powered"] = line.split(":")[1].strip().lower() == "true"
                elif line.startswith("status:"):
                    status_code = int(line.split(":")[1].strip())
                    # Android battery status codes: 1=unknown, 2=charging, 3=discharging, 4=not_charging, 5=full
                    status_map = {1: "unknown", 2: "charging", 3: "discharging", 4: "not_charging", 5: "full"}
                    info["status"] = status_map.get(status_code, "unknown")
                elif line.startswith("temperature:"):
                    # Temperature is in tenths of a degree Celsius
                    temp = int(line.split(":")[1].strip())
                    info["temperature"] = temp / 10.0

            # Determine if charging (any power source)
            info["charging"] = info.get("ac_powered", False) or info.get("usb_powered", False) or info.get("wireless_powered", False)

            return info
        except Exception as e:
            logger.debug(f"[AutoSensors] Battery fetch failed: {e}")
            return {}

    async def _fetch_wifi_info(self, device_id: str) -> Dict[str, Any]:
        """Fetch WiFi info via ADB."""
        try:
            result = await self.adb_bridge.shell_command(device_id, "dumpsys wifi | grep mWifiInfo")
            if not result:
                return {}

            info = {}
            # Parse mWifiInfo line: SSID: "NetworkName", ... RSSI: -42, Link speed: 433Mbps
            ssid_match = re.search(r'SSID:\s*"([^"]*)"', result)
            if ssid_match:
                info["ssid"] = ssid_match.group(1)

            rssi_match = re.search(r'RSSI:\s*(-?\d+)', result)
            if rssi_match:
                info["rssi"] = int(rssi_match.group(1))

            speed_match = re.search(r'Link speed:\s*(\d+)', result)
            if speed_match:
                info["link_speed"] = int(speed_match.group(1))

            return info
        except Exception as e:
            logger.debug(f"[AutoSensors] WiFi fetch failed: {e}")
            return {}

    async def _fetch_memory_info(self, device_id: str) -> Dict[str, Any]:
        """Fetch memory info via ADB."""
        try:
            result = await self.adb_bridge.shell_command(device_id, "cat /proc/meminfo | head -5")
            if not result:
                return {}

            info = {}
            for line in result.split("\n"):
                if line.startswith("MemTotal:"):
                    # Value is in kB
                    kb = int(re.search(r'(\d+)', line).group(1))
                    info["total_mb"] = kb // 1024
                elif line.startswith("MemAvailable:"):
                    kb = int(re.search(r'(\d+)', line).group(1))
                    info["available_mb"] = kb // 1024

            if info.get("total_mb") and info.get("available_mb"):
                info["percent_available"] = round((info["available_mb"] / info["total_mb"]) * 100)

            return info
        except Exception as e:
            logger.debug(f"[AutoSensors] Memory fetch failed: {e}")
            return {}

    async def _fetch_brightness_info(self, device_id: str) -> Dict[str, Any]:
        """Fetch screen brightness via ADB."""
        try:
            # Get brightness value (0-255)
            brightness = await self.adb_bridge.shell_command(device_id, "settings get system screen_brightness")
            # Get brightness mode (0=manual, 1=auto)
            mode = await self.adb_bridge.shell_command(device_id, "settings get system screen_brightness_mode")

            info = {}
            if brightness and brightness.strip().isdigit():
                info["brightness"] = int(brightness.strip())

            if mode and mode.strip().isdigit():
                info["mode"] = "auto" if mode.strip() == "1" else "manual"

            return info
        except Exception as e:
            logger.debug(f"[AutoSensors] Brightness fetch failed: {e}")
            return {}

    async def _fetch_screen_on(self, device_id: str) -> Dict[str, Any]:
        """Check if screen is on via ADB."""
        try:
            # Use the adb_bridge method if available
            if hasattr(self.adb_bridge, 'is_screen_on'):
                screen_on = await self.adb_bridge.is_screen_on(device_id)
                return {"screen_on": screen_on}

            # Fallback: check display power state
            result = await self.adb_bridge.shell_command(device_id, "dumpsys display | grep mScreenState")
            if result:
                # mScreenState=ON or mScreenState=OFF
                return {"screen_on": "ON" in result.upper()}
            return {"screen_on": True}  # Default to on if unknown
        except Exception as e:
            logger.debug(f"[AutoSensors] Screen on fetch failed: {e}")
            return {}

    async def _fetch_companion_status(self, device_id: str) -> Dict[str, Any]:
        """Check companion streaming and connection status."""
        try:
            info = {"streaming": False, "connected": False}

            # Check streaming status from companion_stream_manager
            try:
                from core.streaming.companion_receiver import companion_stream_manager
                if companion_stream_manager:
                    info["streaming"] = companion_stream_manager.is_streaming(device_id)
                    # If streaming, also consider it connected
                    if info["streaming"]:
                        info["connected"] = True
            except (ImportError, AttributeError):
                pass

            # Check MQTT connection for device (companion announces via MQTT)
            # Only check MQTT if not already connected via streaming
            if not info["connected"]:
                if self.mqtt_manager and hasattr(self.mqtt_manager, 'is_device_connected'):
                    info["connected"] = self.mqtt_manager.is_device_connected(device_id)
                elif self.mqtt_manager and hasattr(self.mqtt_manager, '_device_states'):
                    # Fallback: check if device has recent MQTT activity
                    device_state = self.mqtt_manager._device_states.get(device_id)
                    if device_state:
                        info["connected"] = device_state.get("online", False)

            return info
        except Exception as e:
            logger.debug(f"[AutoSensors] Companion status fetch failed: {e}")
            return {}

    async def _fetch_accessibility_status(self, device_id: str) -> Dict[str, Any]:
        """Check if Visual Mapper accessibility service is enabled."""
        try:
            # Check enabled accessibility services
            result = await self.adb_bridge.shell_command(
                device_id,
                "settings get secure enabled_accessibility_services"
            )
            if result:
                # Check if our service is in the list
                enabled = "com.visualmapper.companion" in result.lower()
                return {"enabled": enabled}
            return {"enabled": False}
        except Exception as e:
            logger.debug(f"[AutoSensors] Accessibility fetch failed: {e}")
            return {}

    def _parse_window_dump(self, dump: str) -> tuple[str, str]:
        """
        Parse dumpsys window output to extract package and activity.

        Returns:
            Tuple of (package_name, activity_name)
        """
        package = ""
        activity = ""

        # Look for mCurrentFocus or mFocusedApp
        # Format: mCurrentFocus=Window{... com.package/com.package.Activity ...}
        patterns = [
            r"mCurrentFocus=.*\s+([a-zA-Z0-9_.]+)/([a-zA-Z0-9_.]+)",
            r"mFocusedApp=.*\s+([a-zA-Z0-9_.]+)/([a-zA-Z0-9_.]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, dump)
            if match:
                package = match.group(1)
                activity_full = match.group(2)
                # Extract just the activity class name
                activity = activity_full.split(".")[-1]
                break

        return package, activity

    async def _get_screen_hash(self, device_id: str) -> Optional[str]:
        """
        Get a perceptual hash of the current screen.

        Uses a simple hash based on downsampled grayscale image.
        """
        try:
            # Get screenshot bytes
            screenshot = await self.adb_bridge.capture_screenshot(device_id)

            if not screenshot or len(screenshot) < 1000:
                return None

            # Simple hash: use first 1KB + length
            # For better matching, could use imagehash library
            import hashlib
            hash_input = screenshot[:1024] + str(len(screenshot)).encode()
            return hashlib.md5(hash_input).hexdigest()

        except Exception:
            return None

    def get_app_state(self, device_id: str) -> Optional[AppScreenState]:
        """Get current app screen state for a device."""
        return self._app_states.get(device_id)

    def get_screen_state(self, device_id: str) -> Optional[ScreenChangeState]:
        """Get current screen change state for a device."""
        return self._screen_states.get(device_id)

    def get_device_state(self, device_id: str) -> Optional[DeviceState]:
        """Get current device hardware state (battery, wifi, memory, etc.)."""
        return self._device_states.get(device_id)

    def get_tracked_devices(self) -> list[str]:
        """Get list of devices being tracked by auto sensors."""
        return list(self._app_states.keys())

    def on_app_change(self, callback: Callable[[str, AppScreenState], Awaitable[None]]):
        """Register callback for app screen changes."""
        self._on_app_change_callbacks.append(callback)

    def on_screen_change(self, callback: Callable[[str, ScreenChangeState], Awaitable[None]]):
        """Register callback for screen content changes."""
        self._on_screen_change_callbacks.append(callback)


# Singleton instance
_auto_sensor_manager: Optional[AutoSensorManager] = None


def get_auto_sensor_manager() -> Optional[AutoSensorManager]:
    """Get the global AutoSensorManager instance."""
    return _auto_sensor_manager


def init_auto_sensor_manager(adb_bridge, mqtt_manager) -> AutoSensorManager:
    """Initialize the global AutoSensorManager instance."""
    global _auto_sensor_manager
    _auto_sensor_manager = AutoSensorManager(adb_bridge, mqtt_manager)
    return _auto_sensor_manager
