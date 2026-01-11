#!/usr/bin/env python3
"""
Automated App Exploration for ML Training

This script automatically triggers exploration of multiple Android apps
to generate training data for the Q-learning model.

Just run this script and it will:
1. Connect to MQTT
2. Discover connected Android devices
3. Trigger exploration for each app in the list
4. Wait for each exploration to complete
5. Move to the next app

IMPORTANT: App Whitelist
------------------------
The Android app has a privacy whitelist feature. Apps must be whitelisted
in the Android app's Privacy Settings before they can be explored.
This automation does NOT bypass the whitelist - it respects your privacy settings.

To whitelist apps for training:
1. Open Visual Mapper Companion on Android
2. Go to Settings -> Privacy Settings
3. Add apps you want to explore to the whitelist

Usage:
    python auto_explore_apps.py                    # Use default apps
    python auto_explore_apps.py --auto             # Auto-discover safe apps
    python auto_explore_apps.py --apps "app1,app2" # Specify apps
    python auto_explore_apps.py --discover         # List installed apps
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import List, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Installing paho-mqtt...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paho-mqtt"])
    import paho.mqtt.client as mqtt


# ============================================================================
# Configuration
# ============================================================================

# MQTT Broker - update to your Home Assistant IP
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

# Priority apps to ALWAYS explore (add your important apps here)
PRIORITY_APPS = [
    # "com.example.yourapp",          # Add your main apps here
]

# Default apps to explore for training (good variety of UI patterns)
# NOTE: com.android.settings and com.android.vending are blocked by Android app's sensitive blacklist
# NOTE: com.google.android.apps.maps blocked due to READ_CONTACTS permission
DEFAULT_APPS = [
    "com.google.android.youtube",     # YouTube
    "com.google.android.deskclock",   # Clock app
    "com.google.android.calculator",  # Calculator app
    # Add more apps below:
    # "com.example.app",
]

# Apps to SKIP when auto-discovering
# Includes: system apps, personal data apps, sensitive apps
SKIP_APPS = [
    # System apps
    "com.android.inputmethod",        # Keyboards
    "com.google.android.inputmethod",
    "com.samsung.android.honeyboard",
    "com.visualmapper.companion",     # Our own app!
    "com.android.systemui",           # System UI
    "com.android.launcher",           # Launchers
    "com.sec.android.app.launcher",
    "com.google.android.apps.nexuslauncher",

    # Email apps - PERSONAL DATA
    "com.google.android.gm",          # Gmail
    "com.microsoft.office.outlook",   # Outlook
    "com.samsung.android.email",      # Samsung Email
    "com.yahoo.mobile.client.android.mail",  # Yahoo Mail
    "mail",                           # Generic mail apps

    # Messaging apps - PERSONAL DATA
    "com.whatsapp",                   # WhatsApp
    "com.facebook.orca",              # Messenger
    "org.telegram.messenger",         # Telegram
    "com.discord",                    # Discord
    "com.viber.voip",                 # Viber
    "com.samsung.android.messaging",  # Samsung Messages
    "com.google.android.apps.messaging",  # Google Messages
    "message",                        # Generic messaging apps
    "sms",                            # SMS apps
    "chat",                           # Chat apps

    # Banking & Finance - SENSITIVE
    "banking",                        # Any banking app
    "bank",
    "finance",
    "wallet",
    "com.paypal",                     # PayPal
    "com.venmo",                      # Venmo
    "com.squareup.cash",              # Cash App

    # Social Media - PERSONAL DATA
    "com.facebook.katana",            # Facebook
    "com.instagram.android",          # Instagram
    "com.twitter.android",            # Twitter/X
    "com.snapchat.android",           # Snapchat
    "com.linkedin.android",           # LinkedIn
    "com.tiktok",                     # TikTok

    # Authentication & Security
    "authenticator",                  # 2FA apps
    "password",                       # Password managers
    "com.google.android.apps.authenticator2",
    "com.authy.authy",
    "com.lastpass.lpandroid",
    "com.onepassword",

    # Photos & Personal Media
    "com.google.android.apps.photos", # Google Photos
    "com.samsung.android.gallery",    # Samsung Gallery
    "gallery",                        # Generic gallery apps
    "photo",                          # Photo apps

    # Health & Fitness - PERSONAL DATA
    "health",
    "fitness",
    "com.google.android.apps.fitness",

    # Dating apps - PERSONAL DATA
    "dating",
    "com.tinder",
    "com.bumble",

    # Notes & Documents - PERSONAL DATA
    "com.google.android.keep",        # Google Keep
    "com.evernote",                   # Evernote
    "com.microsoft.office",           # Office apps
    "notes",                          # Note apps
    "document",                       # Document apps

    # Phone & Contacts - PERSONAL DATA
    "com.android.contacts",           # Contacts
    "com.android.dialer",             # Phone dialer
    "contacts",
    "dialer",
    "phone",

    # Calendar - PERSONAL DATA
    "calendar",
    "com.google.android.calendar",
]

# Exploration settings
EXPLORATION_CONFIG = {
    "maxDepth": 8,           # Max navigation depth
    "maxElements": 40,       # Max elements per screen
    "transitionWait": 2500,  # Wait time between taps (ms)
    "timeout": 300000,       # 5 minute timeout per app
}

# Time to wait for each app exploration (seconds)
WAIT_PER_APP = 180  # 3 minutes default

# Auto-discovery settings
AUTO_DISCOVER_COUNT = 5  # How many random apps to add when using --auto


# ============================================================================
# MQTT Client
# ============================================================================

class ExplorationController:
    """Controls app exploration via MQTT"""

    def __init__(self, broker: str, port: int):
        self.broker = broker
        self.port = port
        self.client = mqtt.Client(client_id=f"auto_explorer_{int(time.time())}")
        self.connected = False
        self.device_id = None
        self.accessibility_enabled = False  # Track accessibility status
        self.exploration_active = False
        self.exploration_complete = False
        self.last_status = None

        # Setup callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"[OK] Connected to MQTT broker at {self.broker}:{self.port}")
            self.connected = True
            # Subscribe to status topics
            client.subscribe("visual_mapper/+/status")
            client.subscribe("visual_mapper/+/explore/status")
            # Also subscribe to new format from Android app
            client.subscribe("visualmapper/exploration/status/+")
        else:
            print(f"[X] Failed to connect: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        print("Disconnected from MQTT")
        self.connected = False

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')

            # Extract device ID from topic
            parts = topic.split('/')
            if len(parts) >= 2 and parts[0] == "visual_mapper":
                topic_device_id = parts[1]

                # Device status message
                if topic.endswith("/status") and not topic.endswith("/explore/status"):
                    try:
                        status = json.loads(payload)
                        # Track accessibility status
                        self.accessibility_enabled = status.get("accessibility_enabled", False)

                        # Use topic device ID - this is what we need to publish to
                        # Prefer device IDs that look like IP-based (our app uses these)
                        if topic_device_id and '_' in topic_device_id:
                            # IP-based device ID like 192_168_86_129_46747
                            if self.device_id != topic_device_id:
                                self.device_id = topic_device_id
                                acc_status = "enabled" if self.accessibility_enabled else "DISABLED"
                                print(f"[OK] Found device: {self.device_id} (accessibility: {acc_status})")
                        elif self.device_id is None:
                            # Fallback to any device ID
                            self.device_id = topic_device_id
                            acc_status = "enabled" if self.accessibility_enabled else "DISABLED"
                            print(f"[OK] Found device: {self.device_id} (accessibility: {acc_status})")
                    except json.JSONDecodeError:
                        pass

                # Exploration status (handle both old and new topic formats)
                if topic.endswith("/explore/status") or topic.startswith("visualmapper/exploration/status/"):
                    try:
                        status = json.loads(payload)
                        self.last_status = status
                        state = status.get("status", "")

                        # Handle both field naming conventions
                        screens = status.get("screens", status.get("screens_explored", 0))
                        elements = status.get("elements", status.get("elements_explored", 0))
                        queue = status.get("queue_size", 0)
                        message = status.get("message", status.get("error", ""))
                        pkg = status.get("package", "")

                        if state == "completed":
                            self.exploration_complete = True
                            self.exploration_active = False
                            print(f"\n  [OK] Exploration complete: {screens} screens, {elements} elements")

                        elif state in ("failed", "cancelled"):
                            self.exploration_complete = True
                            self.exploration_active = False
                            print(f"\n  [X] Exploration {state}: {message or 'Unknown error'}")

                        elif state == "started":
                            self.exploration_active = True
                            self.exploration_complete = False
                            print(f"  [OK] Exploration started for {pkg}")

                        elif state == "exploring":
                            self.exploration_active = True
                            print(f"  -> Exploring: {screens} screens, {elements} elements, {queue} queued", end='\r')

                    except json.JSONDecodeError:
                        pass

        except Exception as e:
            print(f"Error processing message: {e}")

    def connect(self) -> bool:
        """Connect to MQTT broker"""
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()

            # Wait for connection
            for _ in range(10):
                if self.connected:
                    return True
                time.sleep(0.5)

            return self.connected
        except Exception as e:
            print(f"[X] Connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from MQTT"""
        self.client.loop_stop()
        self.client.disconnect()

    def wait_for_device(self, timeout: int = 30) -> bool:
        """Wait for an Android device to be discovered"""
        print("Waiting for Android device...")
        start = time.time()
        while time.time() - start < timeout:
            if self.device_id:
                # Note: Accessibility check removed - we enable it via ADB which is reliable
                # The app's MQTT status may not reflect the true accessibility state
                # because the app caches this at startup
                if not self.accessibility_enabled:
                    print("  [!] App reports accessibility disabled (may be stale)")
                    print("  [OK] Proceeding anyway - accessibility was enabled via ADB")
                return True
            time.sleep(1)
        print("[X] No device found. Make sure the Android app is running and connected to MQTT.")
        return False

    def start_exploration(self, package: str, config: Optional[dict] = None) -> bool:
        """Start exploration of an app"""
        if not self.device_id:
            print("[X] No device available")
            return False

        config = config or EXPLORATION_CONFIG
        topic = f"visual_mapper/{self.device_id}/explore/start"
        payload = json.dumps({
            "package": package,
            "config": config
        })

        self.exploration_active = True  # Assume it started
        self.exploration_complete = False
        self.last_status = None

        self.client.publish(topic, payload)
        print(f"  -> Started exploration of {package}")

        # Give the app a moment to receive the command
        time.sleep(2)
        return True  # Assume success - app doesn't publish status yet

    def wait_for_completion(self, timeout: int = WAIT_PER_APP) -> bool:
        """Wait for current exploration to complete"""
        print(f"  [...] Waiting {timeout}s for exploration...")
        start = time.time()
        while time.time() - start < timeout:
            if self.exploration_complete:
                return True
            # Show progress every 10 seconds
            elapsed = int(time.time() - start)
            if elapsed > 0 and elapsed % 10 == 0:
                print(f"  [...] {elapsed}s / {timeout}s", end='\r')
            time.sleep(1)

        print(f"\n  [OK] Completed {timeout}s exploration")
        return True  # Assume success after timeout

    def enable_ml_training(self) -> bool:
        """Enable ML training mode on the device"""
        if not self.device_id:
            print("[X] No device available")
            return False

        topic = f"visual_mapper/{self.device_id}/ml_training"
        payload = json.dumps({"enabled": True})
        self.client.publish(topic, payload)
        print("  [OK] ML Training mode enabled via MQTT")
        time.sleep(1)
        return True

    def stop_exploration(self):
        """Stop current exploration"""
        if self.device_id:
            topic = f"visual_mapper/{self.device_id}/explore/stop"
            self.client.publish(topic, "{}")
            time.sleep(2)


# ============================================================================
# Intelligent Sensitive App Detection
# ============================================================================

# High-sensitivity permissions (even one = skip)
HIGH_SENSITIVITY_PERMISSIONS = [
    "android.permission.READ_SMS",
    "android.permission.SEND_SMS",
    "android.permission.READ_CONTACTS",
    "android.permission.READ_CALL_LOG",
    "android.permission.BODY_SENSORS",
]

# Permissions that indicate personal data (3+ = skip)
SENSITIVE_PERMISSIONS = [
    "android.permission.READ_SMS",
    "android.permission.SEND_SMS",
    "android.permission.READ_CONTACTS",
    "android.permission.WRITE_CONTACTS",
    "android.permission.READ_CALL_LOG",
    "android.permission.GET_ACCOUNTS",
    "android.permission.READ_CALENDAR",
    "android.permission.WRITE_CALENDAR",
    "android.permission.BODY_SENSORS",
    "android.permission.ACTIVITY_RECOGNITION",
    "android.permission.READ_PHONE_STATE",
    "android.permission.READ_PHONE_NUMBERS",
    "android.permission.USE_BIOMETRIC",
    "android.permission.USE_FINGERPRINT",
]

# Sensitive keywords in app label/name
SENSITIVE_KEYWORDS = [
    "bank", "banking", "finance", "money", "wallet", "pay", "payment",
    "mail", "email", "message", "chat", "sms", "text",
    "password", "vault", "secure", "authenticator", "2fa",
    "health", "medical", "fitness", "doctor",
    "dating", "social", "private", "secret",
    "contact", "calendar", "diary", "journal",
]


def get_app_permissions(package: str) -> List[str]:
    """Get app permissions via ADB dumpsys"""
    try:
        result = subprocess.run(
            get_adb_cmd(["shell", "dumpsys", "package", package]),
            capture_output=True,
            text=True,
            timeout=10,
            encoding='utf-8',
            errors='ignore'
        )
        if result.returncode == 0:
            permissions = []
            in_permissions = False
            for line in result.stdout.split('\n'):
                if 'requested permissions:' in line.lower():
                    in_permissions = True
                    continue
                if in_permissions:
                    if line.strip().startswith('android.permission.'):
                        permissions.append(line.strip())
                    elif line.strip() and not line.strip().startswith('android.permission'):
                        # End of permissions section
                        if 'install permissions:' not in line.lower() and 'runtime permissions:' not in line.lower():
                            break
            return permissions
    except Exception as e:
        pass
    return []


def get_app_label(package: str) -> str:
    """Get app label/name via ADB"""
    try:
        result = subprocess.run(
            get_adb_cmd(["shell", "dumpsys", "package", package]),
            capture_output=True,
            text=True,
            timeout=10,
            encoding='utf-8',
            errors='ignore'
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'versionName=' in line:
                    # Extract just the app info line
                    continue
        # Try using pm command for label
        result = subprocess.run(
            get_adb_cmd(["shell", "pm", "dump", package]),
            capture_output=True,
            text=True,
            timeout=10,
            encoding='utf-8',
            errors='ignore'
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'application-label:' in line.lower():
                    return line.split(':')[1].strip().strip("'").lower()
    except Exception:
        pass
    return package.lower()


def is_sensitive_app_intelligent(package: str) -> bool:
    """
    INTELLIGENT detection: Analyze app permissions and metadata
    to determine if it handles sensitive data.

    Returns True if app should be SKIPPED (is sensitive)
    """
    # 1. Check against SKIP_APPS patterns first (fast check)
    pkg_lower = package.lower()
    for skip_pattern in SKIP_APPS:
        if skip_pattern.lower() in pkg_lower:
            print(f"    [!] Matches skip pattern '{skip_pattern}'")
            return True

    # 2. Check permissions via ADB
    permissions = get_app_permissions(package)

    # High-sensitivity permission = immediate skip
    for perm in HIGH_SENSITIVITY_PERMISSIONS:
        if perm in permissions:
            print(f"    [!] Has high-sensitivity permission: {perm}")
            return True

    # Count sensitive permissions - if 3+ = skip
    sensitive_count = sum(1 for p in SENSITIVE_PERMISSIONS if p in permissions)
    if sensitive_count >= 3:
        print(f"    [!] Has {sensitive_count} sensitive permissions")
        return True

    # 3. Check app label for sensitive keywords
    label = get_app_label(package)
    for keyword in SENSITIVE_KEYWORDS:
        if keyword in label:
            print(f"    [!] App name '{label}' contains sensitive keyword '{keyword}'")
            return True

    return False


# ============================================================================
# ADB Utilities
# ============================================================================

# Global ADB device (set during main())
ADB_DEVICE = None

def get_adb_cmd(args: List[str]) -> List[str]:
    """Build ADB command with device specification if needed"""
    if ADB_DEVICE:
        return ["adb", "-s", ADB_DEVICE] + args
    return ["adb"] + args


def get_installed_apps(third_party_only: bool = True) -> List[str]:
    """Get list of installed apps via ADB"""
    try:
        cmd = get_adb_cmd(["shell", "pm", "list", "packages"])
        if third_party_only:
            cmd.append("-3")  # -3 = third party only

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            encoding='utf-8',
            errors='ignore'
        )
        if result.returncode == 0:
            apps = []
            for line in result.stdout.strip().split('\n'):
                if line.startswith("package:"):
                    app = line.replace("package:", "").strip()
                    # Filter out skip apps
                    skip = False
                    for skip_pattern in SKIP_APPS:
                        if skip_pattern in app:
                            skip = True
                            break
                    if not skip and app:
                        apps.append(app)
            return sorted(apps)
    except Exception as e:
        print(f"Could not get app list: {e}")
    return []


def enable_accessibility_via_adb(restart_app: bool = False) -> bool:
    """Enable Visual Mapper accessibility service via ADB"""
    print("\nEnabling accessibility service via ADB...")

    try:
        # Set the accessibility service
        service_name = "com.visualmapper.companion/com.visualmapper.companion.accessibility.VisualMapperAccessibilityService"

        cmd1 = get_adb_cmd(["shell", "settings", "put", "secure", "enabled_accessibility_services", service_name])
        subprocess.run(cmd1, capture_output=True, text=True, timeout=10)

        cmd2 = get_adb_cmd(["shell", "settings", "put", "secure", "accessibility_enabled", "1"])
        subprocess.run(cmd2, capture_output=True, text=True, timeout=10)

        # Verify it's enabled
        cmd3 = get_adb_cmd(["shell", "settings", "get", "secure", "enabled_accessibility_services"])
        result3 = subprocess.run(cmd3, capture_output=True, text=True, timeout=10)

        if "visualmapper" not in result3.stdout.lower():
            print(f"  [X] Failed to enable accessibility: {result3.stdout}")
            return False

        print("  [OK] Accessibility setting enabled")

        # If requested, restart the app to activate the accessibility service
        if restart_app:
            print("  [*] Restarting app to activate accessibility service...")
            stop_cmd = get_adb_cmd(["shell", "am", "force-stop", "com.visualmapper.companion"])
            subprocess.run(stop_cmd, capture_output=True, timeout=10)
            time.sleep(1)

            start_cmd = get_adb_cmd([
                "shell", "am", "start", "-n",
                "com.visualmapper.companion/.ui.fragments.MainContainerActivity"
            ])
            subprocess.run(start_cmd, capture_output=True, timeout=10)
            print("  [OK] App restarted")
            time.sleep(5)  # Wait for app and accessibility service to initialize

        return True

    except Exception as e:
        print(f"  [X] Error enabling accessibility: {e}")
        return False


def restart_visual_mapper_app() -> bool:
    """Restart the Visual Mapper companion app to ensure fresh MQTT connection"""
    print("\nRestarting Visual Mapper companion app...")

    try:
        # Force stop the app first
        stop_cmd = get_adb_cmd(["shell", "am", "force-stop", "com.visualmapper.companion"])
        subprocess.run(stop_cmd, capture_output=True, timeout=10)
        print("  [OK] Stopped app")

        time.sleep(2)  # Wait for clean shutdown

        # Start the app
        start_cmd = get_adb_cmd([
            "shell", "am", "start", "-n",
            "com.visualmapper.companion/.ui.fragments.MainContainerActivity"
        ])
        result = subprocess.run(start_cmd, capture_output=True, text=True, timeout=10)

        if "Error" in result.stdout or "Error" in result.stderr:
            print(f"  [X] Failed to start app: {result.stderr}")
            return False

        print("  [OK] Started app")

        # Wait for app to initialize and connect to MQTT
        print("  [...] Waiting for app to connect to MQTT (10s)...")
        time.sleep(10)

        return True

    except Exception as e:
        print(f"  [X] Error restarting app: {e}")
        return False


def auto_select_apps(count: int = AUTO_DISCOVER_COUNT) -> List[str]:
    """Auto-select apps for training: priority apps + random discovered apps"""
    import random

    apps = []

    # Always include priority apps first
    print("Adding priority apps...")
    for app in PRIORITY_APPS:
        if app not in apps:
            apps.append(app)
            print(f"  + {app} (priority)")

    # Get all installed third-party apps
    print("Discovering installed apps...")
    installed = get_installed_apps(third_party_only=True)

    # Remove already-added apps
    available = [a for a in installed if a not in apps]

    if available:
        # Randomly select additional apps
        random.shuffle(available)
        selected = available[:count]
        for app in selected:
            apps.append(app)
            print(f"  + {app} (auto-selected)")

    print(f"\nTotal apps to explore: {len(apps)}")
    return apps


def check_adb_device() -> Optional[str]:
    """Check for connected ADB device"""
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=10,
            encoding='utf-8',
            errors='ignore'
        )
        lines = result.stdout.strip().split('\n')[1:]  # Skip header
        for line in lines:
            if '\tdevice' in line:
                return line.split('\t')[0]
    except Exception as e:
        print(f"ADB check failed: {e}")
    return None


# ============================================================================
# Main
# ============================================================================

def explore_apps(apps: List[str], controller: ExplorationController):
    """Explore multiple apps for training"""
    total = len(apps)
    successful = 0
    failed = 0
    skipped = 0

    print(f"\n{'='*60}")
    print(f"  Starting exploration of {total} apps")
    print(f"  (Sensitive apps will be automatically skipped)")
    print(f"{'='*60}\n")

    for i, app in enumerate(apps, 1):
        print(f"\n[{i}/{total}] {app}")
        print("-" * 40)

        # INTELLIGENT SENSITIVE APP CHECK (runs first!)
        print(f"  Checking if app is sensitive...")
        if is_sensitive_app_intelligent(app):
            print(f"  [X] SKIPPED - Sensitive app (personal data)")
            skipped += 1
            continue
        print(f"  [OK] App passed sensitivity check")

        # Check if app is installed (via ADB)
        try:
            result = subprocess.run(
                get_adb_cmd(["shell", "pm", "path", app]),
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='ignore'
            )
            if not result.stdout.strip():
                print(f"  [!] App not installed, skipping")
                skipped += 1
                continue
        except Exception:
            print(f"  [!] Could not verify app, trying anyway...")

        # Re-enable accessibility before each app (it tends to die)
        # restart_app=True forces the app to restart, which activates the accessibility service
        print("  [*] Enabling accessibility service...")
        enable_accessibility_via_adb(restart_app=True)

        # Start exploration
        if controller.start_exploration(app):
            if controller.wait_for_completion():
                successful += 1
            else:
                failed += 1
                controller.stop_exploration()
        else:
            print(f"  [X] Failed to start exploration")
            failed += 1

        # Brief pause between apps
        if i < total:
            print(f"\n  Waiting 10s before next app...")
            time.sleep(10)

    return successful, failed, skipped


def main():
    global WAIT_PER_APP  # Declare global at start of function

    parser = argparse.ArgumentParser(description="Automated App Exploration for ML Training")
    parser.add_argument("--broker", default=MQTT_BROKER, help="MQTT broker address")
    parser.add_argument("--port", type=int, default=MQTT_PORT, help="MQTT broker port")
    parser.add_argument("--apps", help="Comma-separated list of apps to explore")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-discover and select apps (priority + random)")
    parser.add_argument("--auto-count", type=int, default=AUTO_DISCOVER_COUNT,
                        help=f"Number of random apps to add in auto mode (default: {AUTO_DISCOVER_COUNT})")
    parser.add_argument("--discover", action="store_true", help="List installed apps and exit")
    parser.add_argument("--wait", type=int, default=180, help="Seconds to wait per app (default: 180)")

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  Smart Explorer - Automated Training")
    print("=" * 60)

    # Check ADB
    global ADB_DEVICE
    device = check_adb_device()
    if device:
        ADB_DEVICE = device  # Set global for all ADB commands
        print(f"[OK] ADB device: {device}")
    else:
        print("[!] No ADB device found (some features may not work)")

    # Discover mode
    if args.discover:
        print("\nInstalled third-party apps:")
        print("-" * 40)
        apps = get_installed_apps()
        for app in apps:
            print(f"  {app}")
        print(f"\nTotal: {len(apps)} apps")
        return

    # Get app list
    if args.apps:
        apps = [a.strip() for a in args.apps.split(",")]
        print(f"\nUsing specified apps ({len(apps)} apps)")
    elif args.auto:
        print(f"\nAuto-discovering apps (priority + {args.auto_count} random)...")
        apps = auto_select_apps(count=args.auto_count)
    else:
        apps = DEFAULT_APPS
        print(f"\nUsing default app list ({len(apps)} apps)")
        print("To customize, edit DEFAULT_APPS in this script or use --apps")
        print("Use --auto to auto-discover apps from your device")

    # Filter to only installed apps
    print("\nChecking which apps are installed...")
    installed = []
    for app in apps:
        try:
            result = subprocess.run(
                get_adb_cmd(["shell", "pm", "path", app]),
                capture_output=True,
                text=True,
                timeout=10,
                encoding='utf-8',
                errors='ignore'
            )
            if result.stdout.strip():
                installed.append(app)
                print(f"  [OK] {app}")
            else:
                print(f"  [X] {app} (not installed)")
        except Exception:
            installed.append(app)  # Try anyway if ADB fails
            print(f"  ? {app} (couldn't verify)")

    if not installed:
        print("\n[X] No apps to explore!")
        return

    # Enable accessibility service via ADB (in case it got disabled)
    enable_accessibility_via_adb()

    # Give the system a moment to register the accessibility service
    time.sleep(3)

    # Connect to MQTT
    print(f"\nConnecting to MQTT broker at {args.broker}:{args.port}...")
    controller = ExplorationController(args.broker, args.port)

    if not controller.connect():
        print("[X] Failed to connect to MQTT broker")
        print("  Make sure the broker is running and accessible")
        return

    # Wait for device
    if not controller.wait_for_device():
        controller.disconnect()
        return

    # Enable ML training mode
    controller.enable_ml_training()

    # Run exploration
    WAIT_PER_APP = args.wait

    try:
        successful, failed, skipped = explore_apps(installed, controller)
    except KeyboardInterrupt:
        print("\n\nStopping exploration...")
        controller.stop_exploration()
        successful, failed, skipped = 0, 0, 0
    finally:
        controller.disconnect()

    # Summary
    print("\n" + "=" * 60)
    print("  Training Session Complete")
    print("=" * 60)
    print(f"  [OK] Successful: {successful}")
    print(f"  [X] Failed: {failed}")
    print(f"  [!] Skipped (sensitive): {skipped}")
    print(f"  Total apps: {len(installed)}")
    print("=" * 60)
    if skipped > 0:
        print(f"\n  Note: {skipped} apps were skipped because they contain")
        print(f"        personal data (email, banking, messaging, etc.)")
        print(f"        This protects your privacy during training.")


if __name__ == "__main__":
    main()
