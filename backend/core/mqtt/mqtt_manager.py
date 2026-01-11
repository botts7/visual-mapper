"""
MQTT Manager for Visual Mapper
Handles Home Assistant MQTT discovery and sensor state publishing
Cross-platform: Uses aiomqtt on Linux, paho-mqtt on Windows
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

from core.sensors.sensor_models import SensorDefinition, MQTTDiscoveryConfig, SensorStateUpdate
from utils.version import APP_VERSION

# Import ActionDefinition for action discovery
try:
    from utils.action_models import ActionDefinition
except ImportError:
    ActionDefinition = None

logger = logging.getLogger(__name__)

# Platform detection
IS_WINDOWS = sys.platform == 'win32'

if IS_WINDOWS:
    # Windows: Use synchronous paho-mqtt with async wrapper
    import paho.mqtt.client as mqtt
    logger.info("[MQTTManager] Using paho-mqtt (Windows compatibility mode)")
else:
    # Linux: Use async aiomqtt
    import aiomqtt
    from aiomqtt import Client, MqttError
    logger.info("[MQTTManager] Using aiomqtt (Linux async mode)")


class MQTTManager:
    """Manages MQTT connection and publishes sensor data to Home Assistant"""

    def __init__(
        self,
        broker: str = "localhost",
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        discovery_prefix: str = "homeassistant",
        data_dir: str = "data",
        tls_config: Optional[Dict[str, Any]] = None
    ):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.discovery_prefix = discovery_prefix
        self.data_dir = Path(data_dir)
        self.tls_config = tls_config
        self.client = None
        self._connected = False
        self._event_loop = None  # Store event loop for thread-safe async calls

        # Device info cache for friendly names in MQTT discovery
        # Maps device_id -> {model: str, friendly_name: str, app_name: str}
        self._device_info: Dict[str, Dict[str, str]] = {}
        self._device_info_file = self.data_dir / "mqtt_device_info.json"
        self._load_device_info()

        # Device capabilities cache (populated from device announcements)
        # Maps device_id -> list of capability strings
        # Standard capabilities: CAP_OVERLAY_V2, CAP_CLIENT_OCR, CAP_INTENT_PREVIEW
        self._device_capabilities: Dict[str, list] = {}

        logger.info(f"[MQTTManager] Initialized with broker={broker}:{port} (Platform: {'Windows' if IS_WINDOWS else 'Linux'})")

    def _load_device_info(self):
        """Load device info from persistent storage"""
        try:
            if self._device_info_file.exists():
                with open(self._device_info_file, 'r') as f:
                    self._device_info = json.load(f)
                logger.info(f"[MQTTManager] Loaded device info for {len(self._device_info)} devices")
        except Exception as e:
            logger.warning(f"[MQTTManager] Failed to load device info: {e}")
            self._device_info = {}

    def _save_device_info(self):
        """Save device info to persistent storage"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self._device_info_file, 'w') as f:
                json.dump(self._device_info, f, indent=2)
            logger.debug(f"[MQTTManager] Saved device info for {len(self._device_info)} devices")
        except Exception as e:
            logger.warning(f"[MQTTManager] Failed to save device info: {e}")

    def set_device_info(self, device_id: str, model: str = None, friendly_name: str = None, app_name: str = None):
        """
        Set device info for friendly MQTT device names

        Args:
            device_id: ADB device ID (e.g., "192.168.1.2:46747")
            model: Device model (e.g., "SM X205", "Galaxy Tab A7")
            friendly_name: Custom friendly name (overrides model)
            app_name: Current app name for context (e.g., "BYD")
        """
        if device_id not in self._device_info:
            self._device_info[device_id] = {}

        if model:
            self._device_info[device_id]['model'] = model
        if friendly_name:
            self._device_info[device_id]['friendly_name'] = friendly_name
        if app_name:
            self._device_info[device_id]['app_name'] = app_name

        # Persist to file
        self._save_device_info()

        logger.debug(f"[MQTTManager] Set device info for {device_id}: {self._device_info[device_id]}")

    def get_device_display_name(self, device_id: str, app_name: str = None) -> str:
        """
        Get friendly display name for device

        Format: "[Model/Name] - [App]" or "[Model/Name]" if no app
        Falls back to "Visual Mapper [device_id]" if no info

        Args:
            device_id: ADB device ID
            app_name: Optional app name to include

        Returns:
            Friendly display name
        """
        info = self._device_info.get(device_id, {})

        # Priority: friendly_name > model > device_id
        name = info.get('friendly_name') or info.get('model')

        if not name:
            return f"Visual Mapper {device_id}"

        # Use provided app_name or cached app_name
        app = app_name or info.get('app_name')

        if app:
            return f"{name} - {app}"
        else:
            return name

    def set_device_capabilities(self, device_id: str, capabilities: list) -> None:
        """
        Store device capabilities from announcement or status message.

        Args:
            device_id: Device identifier (e.g., "192.168.1.2:46747" or "SM_X205")
            capabilities: List of capability strings (e.g., ["CAP_OVERLAY_V2", "CAP_CLIENT_OCR"])
        """
        self._device_capabilities[device_id] = capabilities or []
        logger.info(f"[MQTTManager] Set capabilities for {device_id}: {capabilities}")

    def has_capability(self, device_id: str, capability: str) -> bool:
        """
        Check if a device has a specific capability.

        This is used by flow_executor and other components to determine
        execution strategy (e.g., use client-side OCR if CAP_CLIENT_OCR available).

        Standard capabilities:
        - CAP_OVERLAY_V2: Enhanced overlay with visual feedback
        - CAP_CLIENT_OCR: Device can perform OCR locally
        - CAP_INTENT_PREVIEW: Device can preview intents before execution
        - CAP_GESTURE_INJECTION: Device supports direct gesture injection
        - CAP_ACCESSIBILITY_V2: Enhanced accessibility service features

        Args:
            device_id: Device identifier
            capability: Capability name to check (e.g., "CAP_CLIENT_OCR")

        Returns:
            True if device has the capability, False otherwise
        """
        caps = self._device_capabilities.get(device_id, [])
        return capability in caps

    def get_device_capabilities(self, device_id: str) -> list:
        """
        Get all capabilities for a device.

        Args:
            device_id: Device identifier

        Returns:
            List of capability strings, empty list if device not found
        """
        return self._device_capabilities.get(device_id, [])

    async def connect(self) -> bool:
        """Connect to MQTT broker"""
        if IS_WINDOWS:
            return await self._connect_windows()
        else:
            return await self._connect_linux()

    async def _connect_windows(self) -> bool:
        """Windows connection using paho-mqtt"""
        try:
            # Store event loop for thread-safe async callbacks
            self._event_loop = asyncio.get_running_loop()

            self.client = mqtt.Client()

            # Set authentication if provided
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)

            # Set SSL if configured
            if self.tls_config:
                import ssl
                self.client.tls_set(
                    ca_certs=self.tls_config.get("ca_cert"),
                    cert_reqs=ssl.CERT_NONE if self.tls_config.get("insecure") else ssl.CERT_REQUIRED
                )
                if self.tls_config.get("insecure"):
                    self.client.tls_insecure_set(True)

            # Set callbacks
            def on_connect(client, userdata, flags, rc):
                if rc == 0:
                    logger.info(f"[MQTTManager] Connected to {self.broker}:{self.port}")
                    self._connected = True
                else:
                    logger.error(f"[MQTTManager] Connection failed with code {rc}")
                    self._connected = False

            def on_disconnect(client, userdata, rc):
                logger.info(f"[MQTTManager] Disconnected from broker (code {rc})")
                self._connected = False

            self.client.on_connect = on_connect
            self.client.on_disconnect = on_disconnect

            # Connect
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()

            # Wait for connection (up to 5 seconds)
            for _ in range(50):
                if self._connected:
                    return True
                await asyncio.sleep(0.1)

            logger.error("[MQTTManager] Connection timeout")
            return False

        except Exception as e:
            logger.error(f"[MQTTManager] Unexpected error connecting: {e}")
            self._connected = False
            return False

    async def _connect_linux(self) -> bool:
        """Linux connection using aiomqtt"""
        try:
            # Prepare client arguments
            client_kwargs = {
                "hostname": self.broker,
                "port": self.port
            }

            if self.username and self.password:
                client_kwargs["username"] = self.username
                client_kwargs["password"] = self.password

            # Configure SSL/TLS
            if self.tls_config:
                import ssl
                tls_context = ssl.create_default_context()

                if self.tls_config.get("insecure"):
                    tls_context.check_hostname = False
                    tls_context.verify_mode = ssl.CERT_NONE

                if self.tls_config.get("ca_cert"):
                    tls_context.load_verify_locations(cafile=self.tls_config.get("ca_cert"))

                client_kwargs["tls_context"] = tls_context

            self.client = Client(**client_kwargs)

            await self.client.__aenter__()
            self._connected = True
            logger.info(f"[MQTTManager] Connected to {self.broker}:{self.port}")
            return True

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to connect: {e}")
            self._connected = False
            return False

    async def disconnect(self):
        """Disconnect from MQTT broker"""
        if not self.client or not self._connected:
            return

        try:
            if IS_WINDOWS:
                self.client.loop_stop()
                self.client.disconnect()
            else:
                await self.client.__aexit__(None, None, None)

            self._connected = False
            logger.info("[MQTTManager] Disconnected from broker")
        except Exception as e:
            logger.error(f"[MQTTManager] Error disconnecting: {e}")

    @property
    def is_connected(self) -> bool:
        """Check if connected to broker"""
        return self._connected

    def _sanitize_device_id(self, device_id: str) -> str:
        """Sanitize device ID for MQTT topics (replace invalid characters)"""
        # Replace ALL invalid MQTT discovery topic characters with underscores
        # Valid characters for node_id/object_id: alphanumeric, underscore, hyphen ONLY
        # Reference: https://www.home-assistant.io/integrations/mqtt/#discovery-topic
        return device_id.replace(":", "_").replace(".", "_").replace("/", "_").replace("+", "_").replace("#", "_")

    def _get_device_id_for_topic(self, sensor: SensorDefinition) -> str:
        """Get the best device ID to use for MQTT topics (prefer stable_device_id)"""
        # Use stable_device_id if available to prevent duplicates when IP changes
        if sensor.stable_device_id:
            return sensor.stable_device_id
        return sensor.device_id

    def _get_discovery_topic(self, sensor: SensorDefinition) -> str:
        """Get MQTT discovery topic for sensor"""
        # homeassistant/sensor/{device_id}/{sensor_id}/config
        component = "binary_sensor" if sensor.sensor_type == "binary_sensor" else "sensor"
        sanitized_device = self._sanitize_device_id(self._get_device_id_for_topic(sensor))
        return f"{self.discovery_prefix}/{component}/{sanitized_device}/{sensor.sensor_id}/config"

    def _get_state_topic(self, sensor: SensorDefinition) -> str:
        """Get state topic for sensor"""
        # visual_mapper/{device_id}/{sensor_id}/state
        sanitized_device = self._sanitize_device_id(self._get_device_id_for_topic(sensor))
        return f"visual_mapper/{sanitized_device}/{sensor.sensor_id}/state"

    def _get_attributes_topic(self, sensor: SensorDefinition) -> str:
        """Get attributes topic for sensor"""
        # visual_mapper/{device_id}/{sensor_id}/attributes
        sanitized_device = self._sanitize_device_id(self._get_device_id_for_topic(sensor))
        return f"visual_mapper/{sanitized_device}/{sensor.sensor_id}/attributes"

    def _get_availability_topic(self, device_id: str) -> str:
        """Get availability topic for device"""
        # visual_mapper/{device_id}/status
        sanitized_device = self._sanitize_device_id(device_id)
        return f"visual_mapper/{sanitized_device}/status"

    def _build_discovery_payload(self, sensor: SensorDefinition) -> Dict[str, Any]:
        """Build Home Assistant MQTT discovery payload"""
        state_topic = self._get_state_topic(sensor)
        attributes_topic = self._get_attributes_topic(sensor)

        # Use stable_device_id if available (survives IP/port changes), otherwise fall back to device_id
        # CRITICAL: Use same ID for availability as we use for everything else
        effective_device_id = sensor.stable_device_id or sensor.device_id

        # availability_topic must use effective_device_id to match where we publish
        availability_topic = self._get_availability_topic(effective_device_id)
        sanitized_effective_id = self._sanitize_device_id(effective_device_id)
        sanitized_device = self._sanitize_device_id(sensor.device_id)

        # Extract app name from target_app or element_resource_id
        # Priority: target_app > element_resource_id (contains package:id/name)
        app_package = None
        app_name = None
        app_identifier = None  # Sanitized app name for device identifier

        # First try target_app
        if hasattr(sensor, 'target_app') and sensor.target_app:
            app_package = sensor.target_app

        # Fallback: extract from element_resource_id (format: "com.package.name:id/element_id")
        if not app_package and hasattr(sensor, 'source') and sensor.source:
            resource_id = getattr(sensor.source, 'element_resource_id', None)
            if resource_id and ':' in resource_id:
                app_package = resource_id.split(':')[0]  # Get package before ":"

        if app_package:
            # Extract friendly app name from package (e.g., "com.byd.autolink" -> "BYD")
            parts = app_package.split('.')
            if len(parts) >= 2:
                # Use second-to-last part if available (usually the company name)
                app_name = parts[-2].upper() if len(parts) >= 2 else parts[-1].upper()
            else:
                app_name = parts[-1].upper()
            # Create sanitized app identifier for device grouping
            app_identifier = self._sanitize_device_id(app_package)

        # Create device identifier: include app to create separate devices per device+app combo
        if app_identifier:
            device_identifier = f"visual_mapper_{sanitized_effective_id}_{app_identifier}"
        else:
            device_identifier = f"visual_mapper_{sanitized_effective_id}_default"

        logger.info(f"[MQTTManager] Discovery device identifier: {device_identifier} (app: {app_name or 'none'}, package: {app_package or 'none'})")

        payload = {
            "name": sensor.friendly_name,
            # Use stable ID + app for unique_id so HA doesn't create duplicates
            "unique_id": f"visual_mapper_{sanitized_effective_id}_{sensor.sensor_id}",
            "state_topic": state_topic,
            "availability_topic": availability_topic,
            "json_attributes_topic": attributes_topic,
            "device": {
                # Use stable ID + app for identifiers to group sensors by device+app
                "identifiers": [device_identifier],
                "name": self.get_device_display_name(sensor.device_id, app_name),
                "manufacturer": "Visual Mapper",
                "model": app_name or "Android Device Monitor",  # Use app name as model
                "sw_version": APP_VERSION
            }
        }

        # Add sensor-specific fields
        if sensor.device_class and sensor.device_class != "none":
            payload["device_class"] = sensor.device_class

        if sensor.unit_of_measurement:
            payload["unit_of_measurement"] = sensor.unit_of_measurement

        # Only include state_class for sensors with unit_of_measurement (numeric sensors)
        # Text sensors should not have state_class as HA expects numeric values
        if sensor.state_class and sensor.state_class != "none" and sensor.unit_of_measurement:
            payload["state_class"] = sensor.state_class

        if sensor.icon:
            payload["icon"] = sensor.icon

        # Binary sensor specific
        if sensor.sensor_type == "binary_sensor":
            payload["payload_on"] = "ON"
            payload["payload_off"] = "OFF"

        return payload

    async def publish_discovery(self, sensor: SensorDefinition) -> bool:
        """Publish MQTT discovery config for sensor"""
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker")
            return False

        try:
            topic = self._get_discovery_topic(sensor)
            payload = self._build_discovery_payload(sensor)
            payload_json = json.dumps(payload)

            if IS_WINDOWS:
                result = self.client.publish(topic, payload_json, retain=True)
                success = result.rc == mqtt.MQTT_ERR_SUCCESS
            else:
                await self.client.publish(topic, payload_json, retain=True)
                success = True

            if success:
                logger.info(f"[MQTTManager] Published discovery for {sensor.sensor_id}: {topic}")
            return success

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to publish discovery for {sensor.sensor_id}: {e}")
            return False

    async def remove_discovery(self, sensor: SensorDefinition) -> bool:
        """Remove sensor from Home Assistant (publish empty config)"""
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker")
            return False

        try:
            topic = self._get_discovery_topic(sensor)

            if IS_WINDOWS:
                result = self.client.publish(topic, "", retain=True)
                success = result.rc == mqtt.MQTT_ERR_SUCCESS
            else:
                await self.client.publish(topic, "", retain=True)
                success = True

            if success:
                logger.info(f"[MQTTManager] Removed discovery for {sensor.sensor_id}")
            return success

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to remove discovery for {sensor.sensor_id}: {e}")
            return False

    async def publish_state(self, sensor: SensorDefinition, value: str) -> bool:
        """Publish sensor state update"""
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker")
            return False

        try:
            state_topic = self._get_state_topic(sensor)

            # Convert binary sensor values to ON/OFF format
            if sensor.sensor_type == "binary_sensor":
                # Convert common truthy/falsy values to ON/OFF
                logger.debug(f"[MQTTManager] Binary sensor value before conversion: {value!r} (type: {type(value).__name__})")
                value_str = str(value) if value is not None else ""
                if value is None or value_str == "" or value_str == "None" or value_str == "null":
                    value = "OFF"
                    logger.debug(f"[MQTTManager] Converted to OFF (null/empty)")
                elif value_str.lower() in ("0", "false", "off", "no"):
                    value = "OFF"
                    logger.debug(f"[MQTTManager] Converted to OFF (falsy)")
                else:
                    value = "ON"
                    logger.debug(f"[MQTTManager] Converted to ON (truthy)")
                logger.info(f"[MQTTManager] Binary sensor final value: {value}")

            if IS_WINDOWS:
                result = self.client.publish(state_topic, value, retain=True)
                success = result.rc == mqtt.MQTT_ERR_SUCCESS
            else:
                await self.client.publish(state_topic, value, retain=True)
                success = True

            if success:
                logger.info(f"[MQTTManager] Published state for {sensor.sensor_id}: {value} to topic: {state_topic}")
            else:
                logger.error(f"[MQTTManager] Failed to publish state (rc={result.rc if IS_WINDOWS else 'N/A'})")
            return success

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to publish state for {sensor.sensor_id}: {e}")
            return False

    async def publish_attributes(self, sensor: SensorDefinition, attributes: Dict[str, Any]) -> bool:
        """Publish sensor attributes (metadata)"""
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker")
            return False

        try:
            attributes_topic = self._get_attributes_topic(sensor)
            attributes_json = json.dumps(attributes)

            if IS_WINDOWS:
                result = self.client.publish(attributes_topic, attributes_json, retain=True)
                success = result.rc == mqtt.MQTT_ERR_SUCCESS
            else:
                await self.client.publish(attributes_topic, attributes_json, retain=True)
                success = True

            if success:
                logger.debug(f"[MQTTManager] Published attributes for {sensor.sensor_id}")
            return success

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to publish attributes for {sensor.sensor_id}: {e}")
            return False

    async def publish_state_batch(self, sensor_updates: list) -> dict:
        """
        Publish multiple sensor state updates in a single batch operation.

        This is 20-30% faster than individual publishes due to:
        - Reduced MQTT connection overhead
        - Pipelined message transmission
        - Less network round-trips

        Args:
            sensor_updates: List of (sensor, value) tuples
                           Each tuple contains (SensorDefinition, str)

        Returns:
            Dict with success count and failed sensor IDs

        Example:
            results = await mqtt_manager.publish_state_batch([
                (sensor1, "42"),
                (sensor2, "ON"),
                (sensor3, "Hello")
            ])
        """
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker - cannot publish batch")
            return {"success": 0, "failed": len(sensor_updates), "failed_sensors": [s[0].sensor_id for s in sensor_updates]}

        success_count = 0
        failed_sensors = []

        try:
            for sensor, value in sensor_updates:
                try:
                    state_topic = self._get_state_topic(sensor)

                    # Convert binary sensor values to ON/OFF format
                    if sensor.sensor_type == "binary_sensor":
                        value_str = str(value) if value is not None else ""
                        if value is None or value_str == "" or value_str == "None" or value_str == "null":
                            value = "OFF"
                        elif value_str.lower() in ("0", "false", "off", "no"):
                            value = "OFF"
                        else:
                            value = "ON"

                    # Publish using QoS 0 for speed (fire and forget)
                    # Use retain=True so values persist across MQTT reconnects
                    if IS_WINDOWS:
                        result = self.client.publish(state_topic, value, qos=0, retain=True)
                        if result.rc == mqtt.MQTT_ERR_SUCCESS:
                            success_count += 1
                        else:
                            failed_sensors.append(sensor.sensor_id)
                    else:
                        await self.client.publish(state_topic, value, qos=0, retain=True)
                        success_count += 1

                    # Also publish attributes with last_updated timestamp
                    attributes_topic = self._get_attributes_topic(sensor)
                    attributes = {
                        "last_updated": datetime.now().isoformat(),
                        "source_element": sensor.source.element_resource_id if sensor.source else None,
                        "extraction_method": sensor.extraction_rule.method if sensor.extraction_rule else None,
                        "device_id": sensor.device_id
                    }
                    attributes_json = json.dumps(attributes)
                    if IS_WINDOWS:
                        self.client.publish(attributes_topic, attributes_json, retain=True)
                    else:
                        await self.client.publish(attributes_topic, attributes_json, retain=True)

                except Exception as e:
                    logger.debug(f"[MQTTManager] Batch publish failed for {sensor.sensor_id}: {e}")
                    failed_sensors.append(sensor.sensor_id)

            # Brief delay to allow MQTT client to pipeline messages
            await asyncio.sleep(0.01)

            if success_count > 0:
                logger.info(f"[MQTTManager] Batch published {success_count}/{len(sensor_updates)} sensor states to MQTT")

            return {
                "success": success_count,
                "failed": len(failed_sensors),
                "failed_sensors": failed_sensors
            }

        except Exception as e:
            logger.error(f"[MQTTManager] Batch publish failed: {e}")
            return {
                "success": success_count,
                "failed": len(sensor_updates) - success_count,
                "failed_sensors": failed_sensors
            }

    async def publish_availability(self, device_id: str, online: bool, stable_device_id: str = None) -> bool:
        """Publish device availability status

        Args:
            device_id: Connection ID (e.g., 192.168.1.2:46747)
            online: True for online, False for offline
            stable_device_id: Optional stable ID - if provided, use this instead of device_id
                              to match what's used in sensor discovery (prevents duplicates when IP changes)
        """
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker")
            return False

        try:
            # Use stable_device_id if provided, otherwise fall back to device_id
            # This MUST match what we use in _build_discovery_payload for availability_topic
            effective_id = stable_device_id or device_id
            topic = self._get_availability_topic(effective_id)
            payload = "online" if online else "offline"

            logger.debug(f"[MQTTManager] Publishing availability to {topic} (effective_id={effective_id}, stable={stable_device_id}, device={device_id})")

            if IS_WINDOWS:
                result = self.client.publish(topic, payload, retain=True)
                success = result.rc == mqtt.MQTT_ERR_SUCCESS
            else:
                await self.client.publish(topic, payload, retain=True)
                success = True

            if success:
                logger.info(f"[MQTTManager] Published availability for {effective_id}: {payload}")
            return success

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to publish availability for {effective_id}: {e}")
            return False

    async def publish_sensor_update(
        self,
        sensor: SensorDefinition,
        value: str,
        attributes: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Publish complete sensor update (state + attributes)"""
        if not self._connected:
            logger.error("[MQTTManager] Not connected to broker")
            return False

        # Publish state
        state_ok = await self.publish_state(sensor, value)

        # Publish attributes if provided
        attrs_ok = True
        if attributes:
            attrs_ok = await self.publish_attributes(sensor, attributes)

        return state_ok and attrs_ok

    # ========== Action Discovery Methods ==========

    def _get_action_icon(self, action_type: str) -> str:
        """Get icon for action type"""
        icons = {
            "tap": "mdi:cursor-default-click",
            "swipe": "mdi:gesture-swipe",
            "text": "mdi:keyboard",
            "keyevent": "mdi:keyboard-variant",
            "launch_app": "mdi:application",
            "delay": "mdi:timer-sand",
            "macro": "mdi:script-text"
        }
        return icons.get(action_type, "mdi:play")

    def _get_action_discovery_topic(self, action_def) -> str:
        """Get MQTT discovery topic for action (as button entity)"""
        # homeassistant/button/{device_id}/{action_id}/config
        sanitized_device = self._sanitize_device_id(action_def.action.device_id)
        return f"{self.discovery_prefix}/button/{sanitized_device}/{action_def.id}/config"

    def _get_action_command_topic(self, action_def) -> str:
        """Get command topic for action execution"""
        # visual_mapper/{device_id}/action/{action_id}/execute
        sanitized_device = self._sanitize_device_id(action_def.action.device_id)
        return f"visual_mapper/{sanitized_device}/action/{action_def.id}/execute"

    def _build_action_discovery_payload(self, action_def) -> Dict[str, Any]:
        """Build Home Assistant MQTT discovery payload for action"""
        if ActionDefinition is None:
            logger.error("[MQTTManager] ActionDefinition not imported - cannot build action discovery")
            return {}

        command_topic = self._get_action_command_topic(action_def)
        availability_topic = self._get_availability_topic(action_def.action.device_id)
        sanitized_device = self._sanitize_device_id(action_def.action.device_id)
        icon = self._get_action_icon(action_def.action.action_type)

        payload = {
            "name": action_def.action.name,
            "unique_id": f"visual_mapper_{sanitized_device}_action_{action_def.id}",
            "command_topic": command_topic,
            "availability_topic": availability_topic,
            "icon": icon,
            "device": {
                "identifiers": [f"visual_mapper_{sanitized_device}"],
                "name": self.get_device_display_name(action_def.action.device_id),
                "manufacturer": "Visual Mapper",
                "model": "Android Device Monitor",
                "sw_version": APP_VERSION
            },
            "payload_press": "EXECUTE"
        }

        return payload

    async def publish_action_discovery(self, action_def) -> bool:
        """Publish MQTT discovery config for action (as button entity)"""
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker")
            return False

        if ActionDefinition is None:
            logger.error("[MQTTManager] ActionDefinition not available - skipping action discovery")
            return False

        try:
            topic = self._get_action_discovery_topic(action_def)
            payload = self._build_action_discovery_payload(action_def)
            payload_json = json.dumps(payload)

            if IS_WINDOWS:
                result = self.client.publish(topic, payload_json, retain=True)
                success = result.rc == mqtt.MQTT_ERR_SUCCESS
            else:
                await self.client.publish(topic, payload_json, retain=True)
                success = True

            if success:
                logger.info(f"[MQTTManager] Published action discovery for {action_def.id} ({action_def.action.action_type}): {topic}")

                # Subscribe to command topic to receive execution requests
                command_topic = self._get_action_command_topic(action_def)
                if IS_WINDOWS:
                    self.client.subscribe(command_topic)
                    logger.info(f"[MQTTManager] Subscribed to action command topic: {command_topic}")
                else:
                    await self.client.subscribe(command_topic)
                    logger.info(f"[MQTTManager] Subscribed to action command topic: {command_topic}")

            return success

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to publish action discovery for {action_def.id}: {e}")
            return False

    async def remove_action_discovery(self, action_def) -> bool:
        """Remove action from Home Assistant (publish empty config)"""
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker")
            return False

        try:
            topic = self._get_action_discovery_topic(action_def)

            if IS_WINDOWS:
                result = self.client.publish(topic, "", retain=True)
                success = result.rc == mqtt.MQTT_ERR_SUCCESS
            else:
                await self.client.publish(topic, "", retain=True)
                success = True

            if success:
                logger.info(f"[MQTTManager] Removed action discovery for {action_def.id}")

                # Unsubscribe from command topic
                command_topic = self._get_action_command_topic(action_def)
                if IS_WINDOWS:
                    self.client.unsubscribe(command_topic)
                else:
                    await self.client.unsubscribe(command_topic)

            return success

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to remove action discovery for {action_def.id}: {e}")
            return False

    def set_action_command_callback(self, callback):
        """Set callback function to handle action execution commands from MQTT"""
        if not self.client:
            logger.error("[MQTTManager] Client not initialized")
            return

        async def on_message_async(client, userdata, msg):
            """Async wrapper for message callback"""
            try:
                # Extract action_id from topic: visual_mapper/{device_id}/action/{action_id}/execute
                topic_parts = msg.topic.split("/")
                if len(topic_parts) >= 4 and topic_parts[2] == "action":
                    action_id = topic_parts[3]
                    device_id_sanitized = topic_parts[1]

                    # De-sanitize device_id (reverse the sanitization)
                    # This is a simple approach - may need enhancement for complex IDs
                    device_id = device_id_sanitized.replace("_", ":")

                    payload = msg.payload.decode()
                    logger.info(f"[MQTTManager] Received action command: {device_id}/{action_id} payload={payload}")

                    if payload == "EXECUTE":
                        await callback(device_id, action_id)
            except Exception as e:
                logger.error(f"[MQTTManager] Error handling action command: {e}")

        if IS_WINDOWS:
            # Windows: paho-mqtt synchronous callback
            def on_message_sync(client, userdata, msg):
                """Sync wrapper for Windows"""
                try:
                    # Run async callback in event loop (thread-safe)
                    if self._event_loop:
                        asyncio.run_coroutine_threadsafe(
                            on_message_async(client, userdata, msg),
                            self._event_loop
                        )
                    else:
                        logger.error("[MQTTManager] Event loop not available for async callback")
                except Exception as e:
                    logger.error(f"[MQTTManager] Error in sync message handler: {e}")

            self.client.on_message = on_message_sync
            logger.info("[MQTTManager] Action command callback registered (Windows)")
        else:
            # Linux: aiomqtt async callback handled differently
            # Store callback for manual message loop processing
            self._action_callback = callback
            logger.info("[MQTTManager] Action command callback registered (Linux)")

    # ========== Companion App Communication Methods ==========

    async def subscribe_companion_device(self, device_id: str) -> bool:
        """
        Subscribe to all companion app topics for a device.

        Topics subscribed:
        - visual_mapper/{device_id}/availability - Device online/offline status
        - visual_mapper/{device_id}/status - Device capabilities and info
        - visual_mapper/{device_id}/flow/+/result - Flow execution results
        - visual_mapper/{device_id}/gesture/result - Gesture execution results
        - visual_mapper/{device_id}/navigation/learn - Navigation learning data

        Args:
            device_id: Android device ID (e.g., "192.168.1.2")

        Returns:
            True if subscriptions successful, False otherwise
        """
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker - cannot subscribe to companion device")
            return False

        try:
            sanitized_device = self._sanitize_device_id(device_id)
            topics = [
                f"visual_mapper/{sanitized_device}/availability",
                f"visual_mapper/{sanitized_device}/status",
                f"visual_mapper/{sanitized_device}/flow/+/result",
                f"visual_mapper/{sanitized_device}/gesture/result",
                f"visual_mapper/{sanitized_device}/navigation/learn"
            ]

            if IS_WINDOWS:
                for topic in topics:
                    self.client.subscribe(topic)
                    logger.info(f"[MQTTManager] Subscribed to companion topic: {topic}")
            else:
                for topic in topics:
                    await self.client.subscribe(topic)
                    logger.info(f"[MQTTManager] Subscribed to companion topic: {topic}")

            return True

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to subscribe to companion device {device_id}: {e}")
            return False

    def set_companion_status_callback(self, callback):
        """
        Set callback for companion device status updates.

        Callback signature: callback(device_id: str, status_data: dict)

        Status data includes:
        - device_id: Android device ID
        - platform: "android"
        - app_version: App version string
        - capabilities: List of capabilities
        - timestamp: Unix timestamp

        Args:
            callback: Function to call when status update received
        """
        if IS_WINDOWS:
            def on_message_sync(client, userdata, message):
                import re
                topic = message.topic
                # Match: visual_mapper/{device_id}/status
                match = re.match(r"visual_mapper/([^/]+)/status", topic)
                if match:
                    device_id = match.group(1)
                    try:
                        status_data = json.loads(message.payload.decode())
                        callback(device_id, status_data)
                    except Exception as e:
                        logger.error(f"[MQTTManager] Error processing companion status: {e}")

            # Replace existing on_message handler or chain them
            self.client.on_message = on_message_sync
            logger.info("[MQTTManager] Companion status callback registered (Windows)")
        else:
            # Linux: Store callback for manual message loop processing
            self._companion_status_callback = callback
            logger.info("[MQTTManager] Companion status callback registered (Linux)")

    def set_flow_result_callback(self, callback):
        """
        Set callback for flow execution result updates.

        Callback signature: callback(device_id: str, flow_id: str, result_data: dict)

        Result data includes:
        - flow_id: Flow ID that was executed
        - success: Boolean
        - error: Error message (if failed)
        - duration: Execution time in milliseconds
        - timestamp: Unix timestamp

        Args:
            callback: Function to call when flow result received
        """
        if IS_WINDOWS:
            def on_message_sync(client, userdata, message):
                import re
                topic = message.topic
                # Match: visual_mapper/{device_id}/flow/{flow_id}/result
                match = re.match(r"visual_mapper/([^/]+)/flow/([^/]+)/result", topic)
                if match:
                    device_id = match.group(1)
                    flow_id = match.group(2)
                    try:
                        result_data = json.loads(message.payload.decode())
                        callback(device_id, flow_id, result_data)
                    except Exception as e:
                        logger.error(f"[MQTTManager] Error processing flow result: {e}")

            self.client.on_message = on_message_sync
            logger.info("[MQTTManager] Flow result callback registered (Windows)")
        else:
            self._flow_result_callback = callback
            logger.info("[MQTTManager] Flow result callback registered (Linux)")

    def set_gesture_result_callback(self, callback):
        """
        Set callback for gesture execution result updates.

        Callback signature: callback(device_id: str, result_data: dict)

        Result data includes:
        - gesture_type: Type of gesture executed
        - success: Boolean
        - error: Error message (if failed)
        - timestamp: Unix timestamp

        Args:
            callback: Function to call when gesture result received
        """
        if IS_WINDOWS:
            def on_message_sync(client, userdata, message):
                import re
                topic = message.topic
                # Match: visual_mapper/{device_id}/gesture/result
                match = re.match(r"visual_mapper/([^/]+)/gesture/result", topic)
                if match:
                    device_id = match.group(1)
                    try:
                        result_data = json.loads(message.payload.decode())
                        callback(device_id, result_data)
                    except Exception as e:
                        logger.error(f"[MQTTManager] Error processing gesture result: {e}")

            self.client.on_message = on_message_sync
            logger.info("[MQTTManager] Gesture result callback registered (Windows)")
        else:
            self._gesture_result_callback = callback
            logger.info("[MQTTManager] Gesture result callback registered (Linux)")

    def set_navigation_learn_callback(self, callback):
        """
        Set callback for navigation learning messages from companion app.

        Callback signature: async callback(device_id: str, payload: str)

        The callback receives the raw JSON payload from the companion app
        containing transition data for navigation learning.

        Args:
            callback: Async function to call when navigation learn message received
        """
        if IS_WINDOWS:
            def on_message_sync(client, userdata, message):
                import re
                topic = message.topic
                # Match: visual_mapper/{device_id}/navigation/learn
                match = re.match(r"visual_mapper/([^/]+)/navigation/learn", topic)
                if match:
                    device_id = match.group(1)
                    try:
                        payload = message.payload.decode()
                        # Run async callback in event loop (thread-safe)
                        if self._event_loop:
                            import asyncio
                            asyncio.run_coroutine_threadsafe(
                                callback(device_id, payload),
                                self._event_loop
                            )
                        else:
                            logger.error("[MQTTManager] Event loop not available for navigation learn callback")
                    except Exception as e:
                        logger.error(f"[MQTTManager] Error processing navigation learn message: {e}")

            self.client.on_message = on_message_sync
            logger.info("[MQTTManager] Navigation learn callback registered (Windows)")
        else:
            self._navigation_learn_callback = callback
            logger.info("[MQTTManager] Navigation learn callback registered (Linux)")

    async def subscribe_to_generated_flows(self) -> bool:
        """
        Subscribe to the visualmapper/flows/generated topic.
        This receives flows generated by the Android companion app exploration.
        """
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected - cannot subscribe to generated flows")
            return False

        try:
            topic = "visualmapper/flows/generated"

            if IS_WINDOWS:
                self.client.subscribe(topic)
            else:
                await self.client.subscribe(topic)

            logger.info(f"[MQTTManager] Subscribed to {topic}")
            return True

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to subscribe to generated flows: {e}")
            return False

    def set_generated_flow_callback(self, callback):
        """
        Set callback for handling flows generated by Android companion app.

        Callback signature: callback(flow_data: dict)

        The callback receives the full flow JSON from the Android app's
        FlowGenerator which includes per-screen sensor capture steps.

        Args:
            callback: Function to call when a generated flow is received
        """
        if IS_WINDOWS:
            def on_message_sync(client, userdata, message):
                topic = message.topic
                if topic == "visualmapper/flows/generated":
                    try:
                        flow_data = json.loads(message.payload.decode())
                        logger.info(f"[MQTTManager] Received generated flow: {flow_data.get('flow_id', 'unknown')}")
                        callback(flow_data)
                    except Exception as e:
                        logger.error(f"[MQTTManager] Error processing generated flow: {e}")

            self.client.on_message = on_message_sync
            logger.info("[MQTTManager] Generated flow callback registered (Windows)")
        else:
            self._generated_flow_callback = callback
            logger.info("[MQTTManager] Generated flow callback registered (Linux)")

    async def publish_flow_command(self, device_id: str, flow_id: str, payload: dict) -> bool:
        """
        Publish flow execution command to companion app.

        Args:
            device_id: Android device ID
            flow_id: Flow ID to execute
            payload: Flow execution parameters (dict)

        Returns:
            True if published successfully, False otherwise
        """
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker")
            return False

        try:
            sanitized_device = self._sanitize_device_id(device_id)
            topic = f"visual_mapper/{sanitized_device}/flow/{flow_id}/execute"
            payload_json = json.dumps(payload)

            if IS_WINDOWS:
                result = self.client.publish(topic, payload_json, qos=1)
                success = result.rc == mqtt.MQTT_ERR_SUCCESS
            else:
                await self.client.publish(topic, payload_json, qos=1)
                success = True

            if success:
                logger.info(f"[MQTTManager] Published flow command to {device_id}: {flow_id}")
            return success

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to publish flow command: {e}")
            return False

    async def publish_gesture_command(self, device_id: str, gesture_type: str, params: dict) -> bool:
        """
        Publish gesture execution command to companion app.

        Args:
            device_id: Android device ID
            gesture_type: Type of gesture (tap, swipe, scroll, etc.)
            params: Gesture parameters (coordinates, duration, etc.)

        Returns:
            True if published successfully, False otherwise
        """
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker")
            return False

        try:
            sanitized_device = self._sanitize_device_id(device_id)
            topic = f"visual_mapper/{sanitized_device}/gesture/execute"
            payload = {
                "gesture_type": gesture_type,
                **params
            }
            payload_json = json.dumps(payload)

            if IS_WINDOWS:
                result = self.client.publish(topic, payload_json, qos=1)
                success = result.rc == mqtt.MQTT_ERR_SUCCESS
            else:
                await self.client.publish(topic, payload_json, qos=1)
                success = True

            if success:
                logger.info(f"[MQTTManager] Published gesture command to {device_id}: {gesture_type}")
            return success

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to publish gesture command: {e}")
            return False

    # ========== UI Tree Discovery Methods ==========

    async def request_ui_tree(self, device_id: str, package_name: str = None, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        """
        Request UI tree from Android companion app and wait for response.

        This uses a request-response pattern with asyncio.Future to wait
        for the companion app to return the current UI hierarchy.

        Args:
            device_id: Android device ID (sanitized or unsanitized)
            package_name: Optional package name to filter for specific app
            timeout: Maximum seconds to wait for response (default 10s)

        Returns:
            UI tree dict with elements, or None if timeout/error

        Response structure from Android:
        {
            "request_id": "uuid",
            "package": "com.example.app",
            "activity": "MainActivity",
            "elements": [
                {
                    "resource_id": "com.example:id/button1",
                    "class": "android.widget.Button",
                    "text": "Click Me",
                    "content_desc": "Button description",
                    "bounds": {"left": 0, "top": 100, "right": 200, "bottom": 150},
                    "clickable": true,
                    "scrollable": false,
                    "children": [...]
                }
            ],
            "timestamp": 1234567890
        }
        """
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker - cannot request UI tree")
            return None

        import uuid
        request_id = str(uuid.uuid4())

        # Create a Future to wait for the response
        response_future = asyncio.Future()

        # Store pending request
        if not hasattr(self, '_pending_ui_requests'):
            self._pending_ui_requests = {}
        self._pending_ui_requests[request_id] = response_future

        try:
            sanitized_device = self._sanitize_device_id(device_id)

            # Subscribe to response topic if not already
            response_topic = f"visual_mapper/{sanitized_device}/ui/response"
            if IS_WINDOWS:
                self.client.subscribe(response_topic)
            else:
                await self.client.subscribe(response_topic)

            # Build request payload
            request_payload = {
                "request_id": request_id,
                "command": "get_ui_tree",
                "package": package_name,
                "timestamp": datetime.now().isoformat()
            }

            # Publish request
            request_topic = f"visual_mapper/{sanitized_device}/ui/request"
            payload_json = json.dumps(request_payload)

            if IS_WINDOWS:
                result = self.client.publish(request_topic, payload_json, qos=1)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    logger.error(f"[MQTTManager] Failed to publish UI tree request")
                    return None
            else:
                await self.client.publish(request_topic, payload_json, qos=1)

            logger.info(f"[MQTTManager] Sent UI tree request to {device_id}, request_id={request_id}")

            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(response_future, timeout=timeout)
                logger.info(f"[MQTTManager] Received UI tree response for request {request_id}")
                return response
            except asyncio.TimeoutError:
                logger.warning(f"[MQTTManager] UI tree request timed out after {timeout}s")
                return None

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to request UI tree: {e}")
            return None
        finally:
            # Clean up pending request
            self._pending_ui_requests.pop(request_id, None)

    def _setup_ui_response_handler(self):
        """
        Setup handler for UI tree responses from companion app.
        Called once during initialization or first UI request.
        """
        if hasattr(self, '_ui_response_handler_setup'):
            return

        if IS_WINDOWS:
            # Store the original callback if any
            original_callback = getattr(self.client, 'on_message', None)

            def on_message_with_ui(client, userdata, message):
                import re
                topic = message.topic

                # Check for UI response
                match = re.match(r"visual_mapper/([^/]+)/ui/response", topic)
                if match:
                    try:
                        response_data = json.loads(message.payload.decode())
                        request_id = response_data.get('request_id')

                        if request_id and hasattr(self, '_pending_ui_requests'):
                            future = self._pending_ui_requests.get(request_id)
                            if future and not future.done():
                                # Set result in the event loop thread
                                if self._event_loop:
                                    self._event_loop.call_soon_threadsafe(
                                        future.set_result, response_data
                                    )
                    except Exception as e:
                        logger.error(f"[MQTTManager] Error processing UI response: {e}")

                # Call original callback if exists
                if original_callback:
                    original_callback(client, userdata, message)

            self.client.on_message = on_message_with_ui
            self._ui_response_handler_setup = True
            logger.info("[MQTTManager] UI response handler registered (Windows)")
        else:
            # Linux: Store for manual message loop
            self._ui_response_handler_setup = True
            logger.info("[MQTTManager] UI response handler registered (Linux)")

    async def subscribe_ui_topics(self, device_id: str) -> bool:
        """
        Subscribe to UI-related topics for a device.

        Topics subscribed:
        - visual_mapper/{device_id}/ui/response - UI tree responses

        Args:
            device_id: Android device ID

        Returns:
            True if subscription successful
        """
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker")
            return False

        try:
            # Setup response handler first
            self._setup_ui_response_handler()

            sanitized_device = self._sanitize_device_id(device_id)
            topic = f"visual_mapper/{sanitized_device}/ui/response"

            if IS_WINDOWS:
                self.client.subscribe(topic)
            else:
                await self.client.subscribe(topic)

            logger.info(f"[MQTTManager] Subscribed to UI response topic: {topic}")
            return True

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to subscribe to UI topics: {e}")
            return False

    # =========================================================================
    # Device Announcement (MQTT-based device discovery)
    # =========================================================================

    async def subscribe_device_announcements(self, callback) -> bool:
        """
        Subscribe to device announcements from Android companion apps.

        This enables MQTT-based device discovery, solving the Android 11+
        wireless debugging discovery problem (dynamic ports can't be scanned).

        Android apps publish to: visualmapper/devices/announce
        Payload: {
            "device_id": "SM_X205",
            "ip": "192.168.1.2",
            "adb_port": 46747,
            "model": "SM-X205",
            "android_version": "13",
            "already_paired": true,
            "pairing_port": 37899,  // optional
            "pairing_code": "123456"  // optional
        }

        Args:
            callback: Function(announcement_data: dict) called when device announces

        Returns:
            True if subscription successful
        """
        if not self._connected or not self.client:
            logger.error("[MQTTManager] Not connected to broker - cannot subscribe to device announcements")
            return False

        try:
            topic = "visualmapper/devices/announce"

            if IS_WINDOWS:
                def on_announcement(client, userdata, message):
                    try:
                        payload = message.payload.decode()
                        if not payload or payload.strip() == "":
                            # Empty payload = device withdrew announcement
                            logger.info("[MQTTManager] Device withdrew announcement")
                            return

                        announcement = json.loads(payload)
                        device_id = announcement.get('device_id') or f"{announcement.get('ip')}:{announcement.get('adb_port')}"
                        logger.info(f"[MQTTManager] Device announced: {device_id} ({announcement.get('model')})")

                        # Extract and store device capabilities (Capability Handshake)
                        # Android companion app sends capabilities list in announcement
                        capabilities = announcement.get('capabilities', [])
                        if capabilities:
                            self.set_device_capabilities(device_id, capabilities)
                            logger.info(f"[MQTTManager] Device {device_id} capabilities: {capabilities}")

                        # Store announced device for API access
                        if not hasattr(self, '_announced_devices'):
                            self._announced_devices = {}
                        self._announced_devices[device_id] = announcement

                        callback(announcement)
                    except Exception as e:
                        logger.error(f"[MQTTManager] Error processing device announcement: {e}")

                self.client.subscribe(topic)
                self.client.message_callback_add(topic, on_announcement)
                logger.info(f"[MQTTManager] Subscribed to device announcements: {topic} (Windows)")
            else:
                await self.client.subscribe(topic)
                self._device_announcement_callback = callback
                logger.info(f"[MQTTManager] Subscribed to device announcements: {topic} (Linux)")

            return True

        except Exception as e:
            logger.error(f"[MQTTManager] Failed to subscribe to device announcements: {e}")
            return False

    def get_announced_devices(self) -> list:
        """
        Get list of devices that have announced themselves.

        Returns:
            List of announcement dicts with device info
        """
        return list(getattr(self, '_announced_devices', {}).values())
