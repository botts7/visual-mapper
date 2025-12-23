# Visual Mapper - Plugin System Architecture

**Version:** 1.0.0
**Last Updated:** 2025-12-23
**Status:** Design Document (Implementation Pending)

---

## 📖 Table of Contents

1. [Overview](#overview)
2. [Plugin Types](#plugin-types)
3. [Plugin Structure](#plugin-structure)
4. [Plugin API](#plugin-api)
5. [Plugin Loader](#plugin-loader)
6. [Security & Sandboxing](#security--sandboxing)
7. [Example Plugins](#example-plugins)
8. [Plugin Development Guide](#plugin-development-guide)

---

## Overview

The Visual Mapper Plugin System enables community-created extensions for:
- **Custom Sensor Extractors** - New text extraction methods
- **Custom Action Types** - New device control actions
- **UI Extensions** - Custom pages and components
- **Integration Plugins** - Third-party service integrations
- **Export Formats** - Custom data export formats
- **Themes** - Visual customization

### Design Goals

1. **Simple API** - Easy for developers to create plugins
2. **Secure** - Sandboxed execution, permission system
3. **Extensible** - Support all major Visual Mapper features
4. **Discoverable** - Plugin registry and marketplace
5. **Version-Safe** - Handle API changes gracefully

---

## Plugin Types

### 1. Sensor Extractor Plugins

Adds new text extraction methods to complement built-in extractors.

**Use Cases:**
- Custom OCR engines (Google Vision, Azure CV, etc.)
- ML-based text extraction
- Barcode/QR code readers
- Image recognition

**Interface:**
```python
class SensorExtractorPlugin:
    name: str = "my_extractor"
    version: str = "1.0.0"

    def extract(self, screenshot: bytes, bounds: Dict, config: Dict) -> str:
        """
        Extract text from screenshot region

        Args:
            screenshot: Screenshot image bytes (PNG)
            bounds: {x, y, width, height}
            config: Extractor-specific configuration

        Returns:
            Extracted text value
        """
        pass
```

**Example: Google Vision OCR Plugin**
```python
from google.cloud import vision

class GoogleVisionExtractor(SensorExtractorPlugin):
    name = "google_vision"
    version = "1.0.0"

    def extract(self, screenshot: bytes, bounds: Dict, config: Dict) -> str:
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=screenshot)

        # Crop to bounds
        cropped = self._crop_image(image, bounds)

        # OCR
        response = client.text_detection(image=cropped)
        texts = response.text_annotations

        return texts[0].description if texts else ""
```

### 2. Action Type Plugins

Adds new action types for device control.

**Use Cases:**
- Custom gestures (pinch, rotate)
- AI-powered element finding
- Computer vision-based actions
- External device control (via SSH, HTTP, etc.)

**Interface:**
```python
class ActionTypePlugin:
    name: str = "my_action"
    version: str = "1.0.0"

    async def execute(self, device_id: str, params: Dict, context: Dict) -> bool:
        """
        Execute action on device

        Args:
            device_id: Target device ID
            params: Action parameters
            context: Execution context (adb_bridge, etc.)

        Returns:
            True if successful
        """
        pass
```

**Example: Find and Tap Plugin**
```python
import cv2
import numpy as np

class FindAndTapAction(ActionTypePlugin):
    name = "find_and_tap"
    version = "1.0.0"

    async def execute(self, device_id: str, params: Dict, context: Dict) -> bool:
        # Get current screenshot
        screenshot = await context['adb_bridge'].capture_screenshot(device_id)

        # Find element by template matching
        template = params['template_image']
        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        if max_val > params.get('threshold', 0.8):
            # Found! Tap center of match
            x = max_loc[0] + template.shape[1] // 2
            y = max_loc[1] + template.shape[0] // 2

            await context['adb_bridge'].tap(device_id, x, y)
            return True

        return False  # Not found
```

### 3. UI Extension Plugins

Adds new pages or UI components.

**Use Cases:**
- Custom dashboards
- Advanced sensor/action editors
- Data visualization tools
- Configuration wizards

**Interface:**
```python
class UIExtensionPlugin:
    name: str = "my_ui"
    version: str = "1.0.0"
    routes: List[Dict] = []  # API routes
    pages: List[Dict] = []   # HTML pages

    def get_routes(self) -> List[Dict]:
        """Return API route definitions"""
        return [
            {
                "path": "/plugin/my_ui/data",
                "method": "GET",
                "handler": self.get_data
            }
        ]

    def get_pages(self) -> List[Dict]:
        """Return HTML page definitions"""
        return [
            {
                "path": "/plugin/my_ui",
                "title": "My Plugin Page",
                "html_file": "plugin_my_ui.html"
            }
        ]
```

### 4. Integration Plugins

Integrates with external services.

**Use Cases:**
- Telegram bot integration
- Discord notifications
- Pushbullet alerts
- Custom MQTT topics
- Cloud storage sync

**Interface:**
```python
class IntegrationPlugin:
    name: str = "my_integration"
    version: str = "1.0.0"

    async def on_sensor_update(self, sensor: SensorDefinition, value: str):
        """Called when sensor updates"""
        pass

    async def on_action_execute(self, action: ActionDefinition, result: bool):
        """Called when action executes"""
        pass

    async def on_device_connect(self, device_id: str):
        """Called when device connects"""
        pass
```

**Example: Telegram Notification Plugin**
```python
import telegram

class TelegramNotifier(IntegrationPlugin):
    name = "telegram_notifier"
    version = "1.0.0"

    def __init__(self, config: Dict):
        self.bot = telegram.Bot(token=config['telegram_token'])
        self.chat_id = config['chat_id']
        self.watched_sensors = config.get('watched_sensors', [])

    async def on_sensor_update(self, sensor: SensorDefinition, value: str):
        if sensor.name in self.watched_sensors:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=f"📊 {sensor.name}: {value}"
            )
```

### 5. Export Format Plugins

Adds new data export formats.

**Use Cases:**
- CSV export
- Excel spreadsheets
- JSON schemas
- Database exports
- Cloud service uploads

**Interface:**
```python
class ExportFormatPlugin:
    name: str = "my_export"
    version: str = "1.0.0"
    file_extension: str = ".csv"

    def export_sensors(self, sensors: List[SensorDefinition]) -> bytes:
        """Export sensor configurations"""
        pass

    def export_actions(self, actions: List[ActionDefinition]) -> bytes:
        """Export action configurations"""
        pass
```

### 6. Theme Plugins

Custom visual themes.

**Use Cases:**
- Dark/light mode variations
- Brand-specific themes
- Accessibility themes
- Holiday themes

**Interface:**
```python
class ThemePlugin:
    name: str = "my_theme"
    version: str = "1.0.0"

    def get_css(self) -> str:
        """Return CSS stylesheet"""
        return """
        :root {
            --primary-color: #ff6b6b;
            --background-color: #1e1e1e;
        }
        """
```

---

## Plugin Structure

### Directory Layout

```
plugins/
├── extractor_google_vision/
│   ├── plugin.json              # Plugin manifest
│   ├── __init__.py              # Plugin entry point
│   ├── extractor.py             # Main code
│   ├── requirements.txt         # Python dependencies
│   ├── README.md                # Documentation
│   └── icon.png                 # Plugin icon
│
├── action_find_and_tap/
│   ├── plugin.json
│   ├── __init__.py
│   ├── action.py
│   └── requirements.txt
│
└── integration_telegram/
    ├── plugin.json
    ├── __init__.py
    ├── integration.py
    ├── config_schema.json       # Configuration UI schema
    └── requirements.txt
```

### Plugin Manifest (plugin.json)

```json
{
  "name": "google_vision_extractor",
  "display_name": "Google Vision OCR",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "Extract text using Google Cloud Vision API",
  "homepage": "https://github.com/yourusername/plugin-google-vision",
  "license": "MIT",

  "type": "sensor_extractor",
  "entry_point": "extractor:GoogleVisionExtractor",

  "api_version": "0.0.5",
  "visual_mapper_version": ">=0.0.5",

  "permissions": [
    "network",
    "screenshot_access"
  ],

  "dependencies": [
    "google-cloud-vision>=3.0.0"
  ],

  "configuration": {
    "schema": "config_schema.json",
    "required": ["api_key"]
  },

  "icon": "icon.png",
  "screenshots": [
    "screenshot1.png",
    "screenshot2.png"
  ],

  "tags": ["ocr", "google", "ml", "cloud"]
}
```

---

## Plugin API

### Core API (Available to All Plugins)

```python
class PluginContext:
    """Context provided to plugins"""

    # Device management
    async def get_devices(self) -> List[str]:
        """Get list of connected devices"""
        pass

    async def get_device_info(self, device_id: str) -> Dict:
        """Get device information"""
        pass

    # Sensor management
    async def get_sensors(self, device_id: str) -> List[SensorDefinition]:
        """Get sensors for device"""
        pass

    async def create_sensor(self, sensor: SensorDefinition) -> bool:
        """Create new sensor"""
        pass

    async def update_sensor(self, sensor_id: str, sensor: SensorDefinition) -> bool:
        """Update sensor"""
        pass

    # Action management
    async def get_actions(self, device_id: str) -> List[ActionDefinition]:
        """Get actions for device"""
        pass

    async def execute_action(self, device_id: str, action_id: str) -> bool:
        """Execute action"""
        pass

    # ADB access (restricted permission)
    async def capture_screenshot(self, device_id: str) -> bytes:
        """Capture screenshot"""
        pass

    async def get_ui_elements(self, device_id: str) -> List[Dict]:
        """Get UI elements"""
        pass

    # MQTT access (restricted permission)
    async def publish_mqtt(self, topic: str, payload: str) -> bool:
        """Publish MQTT message"""
        pass

    # Storage
    async def get_plugin_data(self, key: str) -> Any:
        """Get plugin-specific data"""
        pass

    async def set_plugin_data(self, key: str, value: Any) -> bool:
        """Set plugin-specific data"""
        pass

    # Logging
    def log_info(self, message: str):
        """Log info message"""
        pass

    def log_error(self, message: str):
        """Log error message"""
        pass
```

### Permission System

Plugins must declare required permissions in `plugin.json`:

```json
{
  "permissions": [
    "network",              // Make HTTP requests
    "screenshot_access",    // Access screenshots
    "adb_access",          // Full ADB control
    "mqtt_access",         // Publish MQTT
    "storage",             // Persistent storage
    "ui_extension"         // Add UI pages
  ]
}
```

Users must approve permissions when installing plugins.

---

## Plugin Loader

### Implementation

```python
# plugins/plugin_loader.py

import json
import importlib
import os
from typing import Dict, List, Any
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

class PluginManifest(BaseModel):
    name: str
    display_name: str
    version: str
    author: str
    description: str
    type: str
    entry_point: str
    api_version: str
    visual_mapper_version: str
    permissions: List[str] = []
    dependencies: List[str] = []
    configuration: Dict[str, Any] = {}

class PluginLoader:
    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = plugins_dir
        self.loaded_plugins: Dict[str, Any] = {}
        self.plugin_manifests: Dict[str, PluginManifest] = {}

    def discover_plugins(self) -> List[str]:
        """Discover all plugins in plugins directory"""
        plugins = []

        if not os.path.exists(self.plugins_dir):
            os.makedirs(self.plugins_dir)
            return plugins

        for item in os.listdir(self.plugins_dir):
            plugin_path = os.path.join(self.plugins_dir, item)
            manifest_path = os.path.join(plugin_path, "plugin.json")

            if os.path.isdir(plugin_path) and os.path.exists(manifest_path):
                plugins.append(item)
                logger.info(f"[PluginLoader] Discovered plugin: {item}")

        return plugins

    def load_plugin(self, plugin_name: str) -> bool:
        """Load a single plugin"""
        try:
            # Read manifest
            manifest_path = os.path.join(self.plugins_dir, plugin_name, "plugin.json")
            with open(manifest_path, 'r') as f:
                manifest_data = json.load(f)

            manifest = PluginManifest(**manifest_data)

            # Check Visual Mapper version compatibility
            # TODO: Implement version checking

            # Install dependencies
            self._install_dependencies(plugin_name, manifest.dependencies)

            # Import plugin module
            module_name, class_name = manifest.entry_point.split(":")
            plugin_module_path = f"plugins.{plugin_name}.{module_name}"

            plugin_module = importlib.import_module(plugin_module_path)
            plugin_class = getattr(plugin_module, class_name)

            # Instantiate plugin
            plugin_instance = plugin_class()

            # Store
            self.loaded_plugins[plugin_name] = plugin_instance
            self.plugin_manifests[plugin_name] = manifest

            logger.info(f"[PluginLoader] Loaded plugin: {manifest.display_name} v{manifest.version}")
            return True

        except Exception as e:
            logger.error(f"[PluginLoader] Failed to load plugin {plugin_name}: {e}")
            return False

    def unload_plugin(self, plugin_name: str) -> bool:
        """Unload a plugin"""
        if plugin_name in self.loaded_plugins:
            # Call plugin cleanup if exists
            plugin = self.loaded_plugins[plugin_name]
            if hasattr(plugin, 'on_unload'):
                plugin.on_unload()

            del self.loaded_plugins[plugin_name]
            del self.plugin_manifests[plugin_name]

            logger.info(f"[PluginLoader] Unloaded plugin: {plugin_name}")
            return True

        return False

    def get_plugins_by_type(self, plugin_type: str) -> List[Any]:
        """Get all loaded plugins of a specific type"""
        return [
            plugin for name, plugin in self.loaded_plugins.items()
            if self.plugin_manifests[name].type == plugin_type
        ]

    def _install_dependencies(self, plugin_name: str, dependencies: List[str]):
        """Install plugin Python dependencies"""
        if not dependencies:
            return

        logger.info(f"[PluginLoader] Installing dependencies for {plugin_name}")

        # TODO: Implement safe dependency installation
        # Consider using venv per plugin for isolation

        import subprocess
        for dep in dependencies:
            try:
                subprocess.check_call(['pip', 'install', dep])
            except Exception as e:
                logger.error(f"[PluginLoader] Failed to install {dep}: {e}")
```

### Integration with Visual Mapper

```python
# server.py additions

from plugins.plugin_loader import PluginLoader

# Initialize plugin loader
plugin_loader = PluginLoader(plugins_dir="plugins")

# Load all plugins on startup
async def load_plugins():
    discovered = plugin_loader.discover_plugins()
    logger.info(f"[Server] Discovered {len(discovered)} plugins")

    for plugin_name in discovered:
        success = plugin_loader.load_plugin(plugin_name)
        if success:
            logger.info(f"[Server] Plugin loaded: {plugin_name}")

# Call during server startup
@app.on_event("startup")
async def startup_event():
    await load_plugins()
    # ... rest of startup

# Extend text extractor with plugins
class TextExtractor:
    def __init__(self, plugin_loader: PluginLoader):
        self.plugin_loader = plugin_loader
        self.builtin_methods = {
            "text": self._extract_text,
            "ocr_tesseract": self._extract_tesseract,
            # ... etc
        }

    def extract(self, screenshot, elements, bounds, method, config=None):
        # Check if method is from plugin
        extractor_plugins = self.plugin_loader.get_plugins_by_type("sensor_extractor")

        for plugin in extractor_plugins:
            if plugin.name == method:
                return plugin.extract(screenshot, bounds, config or {})

        # Fallback to built-in
        if method in self.builtin_methods:
            return self.builtin_methods[method](screenshot, bounds, config)

        raise ValueError(f"Unknown extraction method: {method}")
```

---

## Security & Sandboxing

### Permission Checks

```python
class PluginContext:
    def __init__(self, plugin_name: str, permissions: List[str]):
        self.plugin_name = plugin_name
        self.permissions = permissions

    def _check_permission(self, permission: str):
        if permission not in self.permissions:
            raise PermissionError(f"Plugin {self.plugin_name} lacks permission: {permission}")

    async def capture_screenshot(self, device_id: str) -> bytes:
        self._check_permission("screenshot_access")
        return await adb_bridge.capture_screenshot(device_id)

    async def publish_mqtt(self, topic: str, payload: str) -> bool:
        self._check_permission("mqtt_access")
        return await mqtt_manager.publish(topic, payload)
```

### Resource Limits

```python
import resource
import signal

class PluginExecutor:
    def execute_with_limits(self, plugin_func, *args, **kwargs):
        """Execute plugin function with resource limits"""

        # Set CPU time limit (5 seconds)
        signal.signal(signal.SIGXCPU, self._timeout_handler)
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))

        # Set memory limit (256MB)
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))

        try:
            return plugin_func(*args, **kwargs)
        except Exception as e:
            logger.error(f"[PluginExecutor] Plugin execution failed: {e}")
            raise
        finally:
            # Reset limits
            resource.setrlimit(resource.RLIMIT_CPU, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
            resource.setrlimit(resource.RLIMIT_AS, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
```

### Code Sandboxing (Advanced)

For maximum security, use subprocess isolation:

```python
import subprocess
import json

class SandboxedPluginExecutor:
    def execute_plugin(self, plugin_name: str, method: str, args: Dict) -> Any:
        """Execute plugin in isolated subprocess"""

        # Serialize args to JSON
        args_json = json.dumps(args)

        # Run in subprocess
        result = subprocess.run(
            ['python', '-m', f'plugins.{plugin_name}.executor', method, args_json],
            capture_output=True,
            timeout=10,  # 10 second timeout
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"Plugin execution failed: {result.stderr}")

        return json.loads(result.stdout)
```

---

## Example Plugins

### Example 1: Barcode Scanner Plugin

```python
# plugins/extractor_barcode/barcode_extractor.py

from pyzbar.pyzbar import decode
from PIL import Image
import io

class BarcodeExtractor:
    name = "barcode"
    version = "1.0.0"

    def extract(self, screenshot: bytes, bounds: Dict, config: Dict) -> str:
        # Convert to PIL Image
        image = Image.open(io.BytesIO(screenshot))

        # Crop to bounds
        cropped = image.crop((
            bounds['x'],
            bounds['y'],
            bounds['x'] + bounds['width'],
            bounds['y'] + bounds['height']
        ))

        # Decode barcodes
        barcodes = decode(cropped)

        if barcodes:
            return barcodes[0].data.decode('utf-8')

        return ""
```

```json
// plugins/extractor_barcode/plugin.json
{
  "name": "extractor_barcode",
  "display_name": "Barcode/QR Code Scanner",
  "version": "1.0.0",
  "author": "Visual Mapper Community",
  "description": "Extract text from barcodes and QR codes",
  "type": "sensor_extractor",
  "entry_point": "barcode_extractor:BarcodeExtractor",
  "api_version": "0.0.5",
  "visual_mapper_version": ">=0.0.5",
  "permissions": ["screenshot_access"],
  "dependencies": ["pyzbar", "Pillow"],
  "tags": ["barcode", "qr", "scanner"]
}
```

### Example 2: Pushbullet Integration

```python
# plugins/integration_pushbullet/pushbullet_integration.py

from pushbullet import Pushbullet

class PushbulletIntegration:
    name = "pushbullet"
    version = "1.0.0"

    def __init__(self):
        self.pb = None
        self.config = {}

    def on_load(self, config: Dict, context):
        """Called when plugin loads"""
        self.config = config
        self.pb = Pushbullet(config['api_key'])
        context.log_info("Pushbullet integration loaded")

    async def on_sensor_update(self, sensor, value):
        """Send notification when sensor updates"""
        if sensor.name in self.config.get('watched_sensors', []):
            self.pb.push_note(
                f"Sensor Update: {sensor.name}",
                f"New value: {value}"
            )

    async def on_action_execute(self, action, result):
        """Send notification when action executes"""
        if action.name in self.config.get('watched_actions', []):
            status = "✅ Success" if result else "❌ Failed"
            self.pb.push_note(
                f"Action Executed: {action.name}",
                f"Status: {status}"
            )
```

---

## Plugin Development Guide

### Quick Start

**1. Create Plugin Directory**
```bash
mkdir -p plugins/my_plugin
cd plugins/my_plugin
```

**2. Create Manifest**
```json
{
  "name": "my_plugin",
  "display_name": "My Awesome Plugin",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "Does something cool",
  "type": "sensor_extractor",
  "entry_point": "plugin:MyPlugin",
  "api_version": "0.0.5",
  "visual_mapper_version": ">=0.0.5",
  "permissions": ["screenshot_access"],
  "dependencies": []
}
```

**3. Create Plugin Code**
```python
# plugin.py

class MyPlugin:
    name = "my_extractor"
    version = "1.0.0"

    def extract(self, screenshot: bytes, bounds: Dict, config: Dict) -> str:
        # Your extraction logic here
        return "extracted_value"
```

**4. Test Plugin**
```bash
# Restart Visual Mapper
python server.py

# Check logs for:
# [PluginLoader] Discovered plugin: my_plugin
# [PluginLoader] Loaded plugin: My Awesome Plugin v1.0.0
```

**5. Use Plugin**
- Create sensor in UI
- Select extraction method: `my_extractor`
- Test extraction

### Best Practices

1. **Error Handling** - Always catch exceptions
2. **Logging** - Use context.log_info() and context.log_error()
3. **Configuration** - Provide config schema for user settings
4. **Testing** - Include unit tests
5. **Documentation** - Write clear README.md
6. **Versioning** - Follow semantic versioning
7. **Dependencies** - Minimize external dependencies
8. **Performance** - Optimize for speed (< 1s execution time)

### Publishing Plugins

**1. Create GitHub Repository**
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/yourusername/visual-mapper-plugin-name
git push -u origin main
```

**2. Add to Plugin Registry**
Submit PR to Visual Mapper plugin registry:
https://github.com/YOUR_USERNAME/visual-mapper-plugins

**3. Community Sharing**
- Post on Discord
- Share on Home Assistant forums
- Create demo video

---

**Document Version:** 1.0.0
**Created:** 2025-12-23
**Implementation Status:** Design Complete, Implementation Pending

**Next Steps:**
1. Implement PluginLoader class
2. Add plugin API endpoints to server.py
3. Create plugin management UI page
4. Develop example plugins
5. Create plugin registry repository
6. Write plugin development tutorial

**Related Documentation:**
- [USER_GUIDE.md](USER_GUIDE.md) - User documentation
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) - Technical overview
- [MISSING_FEATURES.md](MISSING_FEATURES.md) - Future features
