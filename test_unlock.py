#!/usr/bin/env python3
"""
Samsung Unlock Test Script
Tests different unlock methods to find what works for the Samsung tablet.
"""

import requests
import time
import sys

# Configuration
BASE_URL = "http://192.168.86.68:8080/api"
DEVICE_ID = "192.168.86.2:46747"
PIN = "1109"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def get_device_status():
    """Get current device status"""
    try:
        r = requests.get(f"{BASE_URL}/adb/devices", timeout=5)
        if r.ok:
            devices = r.json().get("devices", [])
            for d in devices:
                if d["id"] == DEVICE_ID:
                    return d.get("current_activity", "unknown")
        return "not_found"
    except Exception as e:
        return f"error: {e}"

def send_keyevent(keycode, desc=""):
    """Send a keyevent to device"""
    try:
        r = requests.post(f"{BASE_URL}/adb/keyevent",
                         json={"device_id": DEVICE_ID, "keycode": keycode},
                         timeout=5)
        success = r.ok
        log(f"  Keyevent {keycode} ({desc}): {'OK' if success else 'FAILED'}")
        return success
    except Exception as e:
        log(f"  Keyevent {keycode} ({desc}): ERROR - {e}")
        return False

def send_swipe(start_x, start_y, end_x, end_y, duration=300, desc=""):
    """Send swipe to device"""
    try:
        r = requests.post(f"{BASE_URL}/adb/swipe",
                         json={
                             "device_id": DEVICE_ID,
                             "start_x": start_x, "start_y": start_y,
                             "end_x": end_x, "end_y": end_y,
                             "duration": duration
                         },
                         timeout=10)
        success = r.ok
        log(f"  Swipe ({start_x},{start_y})->({end_x},{end_y}) {desc}: {'OK' if success else 'FAILED'}")
        return success
    except Exception as e:
        log(f"  Swipe {desc}: ERROR - {e}")
        return False

def send_text(text, desc=""):
    """Send text input to device"""
    try:
        r = requests.post(f"{BASE_URL}/adb/text",
                         json={"device_id": DEVICE_ID, "text": text},
                         timeout=5)
        success = r.ok
        log(f"  Text '{text}' ({desc}): {'OK' if success else 'FAILED'}")
        return success
    except Exception as e:
        log(f"  Text {desc}: ERROR - {e}")
        return False

def test_wake_methods():
    """Test different wake methods"""
    log("\n=== Testing WAKE Methods ===")
    status_before = get_device_status()
    log(f"Status before: {status_before}")

    methods = [
        (224, "KEYCODE_WAKEUP"),
        (26, "KEYCODE_POWER"),
        (82, "KEYCODE_MENU"),
        (3, "KEYCODE_HOME"),
    ]

    for keycode, name in methods:
        send_keyevent(keycode, name)
        time.sleep(0.3)

    time.sleep(0.5)
    status_after = get_device_status()
    log(f"Status after: {status_after}")
    return status_after

def test_swipe_patterns():
    """Test different swipe patterns"""
    log("\n=== Testing SWIPE Patterns ===")

    # Samsung tablet is 1920x1200 (landscape) or 1200x1920 (portrait)
    patterns = [
        # (start_x, start_y, end_x, end_y, desc)
        (600, 1800, 600, 400, "Center bottom-to-top"),
        (600, 1000, 600, 200, "Center middle-to-top"),
        (960, 1800, 960, 200, "Wide center up"),
        (100, 1000, 900, 1000, "Left-to-right"),
    ]

    for start_x, start_y, end_x, end_y, desc in patterns:
        status_before = get_device_status()
        log(f"\nTrying: {desc}")
        log(f"  Before: {status_before}")
        send_swipe(start_x, start_y, end_x, end_y, 300, desc)
        time.sleep(1)
        status_after = get_device_status()
        log(f"  After: {status_after}")

        if status_after != status_before and status_after != "NotificationShade":
            log(f"  >>> SUCCESS! Swipe pattern worked!")
            return True, desc

    return False, None

def test_pin_entry():
    """Test PIN entry methods"""
    log("\n=== Testing PIN Entry ===")

    # Method 1: Using text input
    log("\nMethod 1: Text input")
    send_text(PIN, "PIN via text")
    time.sleep(0.5)
    send_keyevent(66, "ENTER")
    time.sleep(1)

    status = get_device_status()
    log(f"Status after text input: {status}")
    if status not in ["NotificationShade", "com.android.systemui"]:
        return True, "text_input"

    # Method 2: Individual keyevents
    log("\nMethod 2: Individual keyevents")
    # Android keycodes: 0=7, 1=8, 2=9, 3=10, 4=11, 5=12, 6=13, 7=14, 8=15, 9=16
    keycode_map = {'0': 7, '1': 8, '2': 9, '3': 10, '4': 11,
                   '5': 12, '6': 13, '7': 14, '8': 15, '9': 16}

    for digit in PIN:
        keycode = keycode_map.get(digit)
        if keycode:
            send_keyevent(keycode, f"Digit {digit}")
            time.sleep(0.2)

    send_keyevent(66, "ENTER")
    time.sleep(1)

    status = get_device_status()
    log(f"Status after keyevents: {status}")
    if status not in ["NotificationShade", "com.android.systemui"]:
        return True, "keyevents"

    return False, None

def test_full_unlock_sequence():
    """Test full unlock sequence"""
    log("\n=== Full Unlock Sequence Test ===")

    # Step 1: Wake
    log("\nStep 1: Wake screen")
    send_keyevent(224, "WAKEUP")
    time.sleep(0.3)
    send_keyevent(26, "POWER")
    time.sleep(0.5)

    status = get_device_status()
    log(f"After wake: {status}")

    # Step 2: Dismiss keyguard
    log("\nStep 2: Dismiss keyguard")
    send_keyevent(82, "MENU")
    time.sleep(0.3)

    status = get_device_status()
    log(f"After MENU: {status}")

    # Step 3: Swipe
    log("\nStep 3: Swipe up")
    send_swipe(600, 1800, 600, 400, 300, "unlock swipe")
    time.sleep(1)

    status = get_device_status()
    log(f"After swipe: {status}")

    # Step 4: Enter PIN if needed
    if "NotificationShade" not in status and "systemui" in status.lower():
        log("\nStep 4: Enter PIN")
        send_text(PIN, "PIN")
        time.sleep(0.3)
        send_keyevent(66, "ENTER")
        time.sleep(1)

        status = get_device_status()
        log(f"After PIN: {status}")

    return status

def main():
    log("=" * 60)
    log("Samsung Unlock Test Script")
    log("=" * 60)
    log(f"Device: {DEVICE_ID}")
    log(f"PIN: {PIN}")

    # Initial status
    log(f"\nInitial status: {get_device_status()}")

    # Run tests
    input("\nPress Enter to test WAKE methods...")
    test_wake_methods()

    input("\nPress Enter to test SWIPE patterns...")
    test_swipe_patterns()

    input("\nPress Enter to test PIN entry...")
    test_pin_entry()

    input("\nPress Enter to test FULL unlock sequence...")
    final_status = test_full_unlock_sequence()

    log("\n" + "=" * 60)
    log(f"Final status: {final_status}")
    log("=" * 60)

if __name__ == "__main__":
    main()
