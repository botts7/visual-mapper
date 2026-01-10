#!/usr/bin/env python3
"""
Test script for Samsung device unlock flow.
Run this directly to test unlock without rebuilding Docker.

Usage:
    python test_unlock.py <device_ip:port> <pin>
    python test_unlock.py 192.168.86.2:46747 1109
"""

import subprocess
import sys
import time

# Device settings
DEVICE_ID = sys.argv[1] if len(sys.argv) > 1 else "192.168.86.2:46747"
PIN = sys.argv[2] if len(sys.argv) > 2 else "1109"


def adb(cmd: str) -> str:
    """Run ADB command and return output."""
    full_cmd = f"adb -s {DEVICE_ID} {cmd}"
    print(f"  > {full_cmd}")
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    output = result.stdout.strip()
    if output:
        print(f"    {output[:200]}")
    return output


def is_screen_on() -> bool:
    """Check if screen is on."""
    result = adb("shell dumpsys power | grep 'mWakefulness='")
    return "Awake" in result


def is_locked() -> bool:
    """Check if device is locked."""
    result = adb("shell dumpsys window")

    if "mShowingLockscreen=true" in result:
        print("    -> LOCKED (mShowingLockscreen=true)")
        return True
    if "mDreamingLockscreen=true" in result:
        print("    -> LOCKED (mDreamingLockscreen=true)")
        return True
    if "mShowingLockscreen=false" in result:
        print("    -> UNLOCKED (mShowingLockscreen=false)")
        return False

    # Check keyguard
    kg_result = adb("shell dumpsys window policy | grep -E 'mKeyguardShowing|isKeyguardShowing'")
    if "mKeyguardShowing=true" in kg_result or "isKeyguardShowing=true" in kg_result:
        print("    -> LOCKED (keyguard showing)")
        return True
    if "mKeyguardShowing=false" in kg_result or "isKeyguardShowing=false" in kg_result:
        print("    -> UNLOCKED (keyguard not showing)")
        return False

    print("    -> UNKNOWN (assuming unlocked)")
    return False


def get_current_activity() -> str:
    """Get current foreground activity."""
    result = adb("shell dumpsys activity activities | grep mCurrentFocus")
    return result


def get_manufacturer() -> str:
    """Get device manufacturer."""
    result = adb("shell getprop ro.product.manufacturer")
    return result.lower()


def unlock_samsung(pin: str):
    """Samsung-specific unlock sequence."""
    print("\n=== SAMSUNG UNLOCK SEQUENCE ===")

    # Step 1: Wake screen
    print("\n[Step 1] Checking screen state...")
    if not is_screen_on():
        print("  Screen is OFF, sending POWER key...")
        adb("shell input keyevent 26")  # POWER
        time.sleep(0.5)
    else:
        print("  Screen is already ON")

    # Step 2: Check if locked
    print("\n[Step 2] Checking lock status...")
    if not is_locked():
        print("  Device is already UNLOCKED!")
        return True

    # Step 3: Press MENU to go to PIN screen (Samsung One UI)
    print("\n[Step 3] Pressing MENU key to show PIN screen...")
    adb("shell input keyevent 82")  # MENU
    time.sleep(0.5)

    # Step 4: Enter PIN
    print(f"\n[Step 4] Entering PIN: {pin}")
    adb(f"shell input text {pin}")
    time.sleep(0.3)

    # Step 5: Press ENTER to confirm
    print("\n[Step 5] Pressing ENTER to confirm...")
    adb("shell input keyevent 66")  # ENTER
    time.sleep(1.0)

    # Step 6: Verify unlock
    print("\n[Step 6] Verifying unlock status...")
    if is_locked():
        print("  FAILED - Device is still locked!")
        return False
    else:
        print("  SUCCESS - Device is now UNLOCKED!")
        return True


def test_sleep_and_unlock():
    """Full test: sleep device, then unlock."""
    print("\n" + "="*60)
    print("FULL TEST: Sleep -> Lock -> Unlock")
    print("="*60)

    # Sleep the device first
    print("\n[PREP] Sleeping device...")
    adb("shell input keyevent 223")  # SLEEP
    time.sleep(2)

    # Verify it's locked
    print("\n[VERIFY] Checking lock status after sleep...")
    adb("shell input keyevent 26")  # Brief wake to check
    time.sleep(0.5)

    locked = is_locked()
    print(f"  Device locked: {locked}")

    if not locked:
        print("  WARNING: Device didn't lock! Check lock settings.")
        return False

    # Now try unlock
    manufacturer = get_manufacturer()
    print(f"\n[INFO] Manufacturer: {manufacturer}")

    success = unlock_samsung(PIN)

    # Final status
    print("\n" + "="*60)
    if success:
        print("TEST PASSED - Unlock successful!")
    else:
        print("TEST FAILED - Could not unlock device")
    print("="*60)

    # Show current activity
    print(f"\nCurrent activity: {get_current_activity()}")

    return success


def main():
    print("="*60)
    print("VISUAL MAPPER - UNLOCK TEST SCRIPT")
    print("="*60)
    print(f"Device: {DEVICE_ID}")
    print(f"PIN: {PIN}")

    # Check connection
    print("\n[CHECK] Testing ADB connection...")
    result = adb("shell echo connected")
    if "connected" not in result:
        print("ERROR: Cannot connect to device!")
        sys.exit(1)
    print("  Connected!")

    # Get device info
    print("\n[INFO] Device info:")
    print(f"  Manufacturer: {get_manufacturer()}")

    # Current state
    print("\n[STATE] Current device state:")
    print(f"  Screen on: {is_screen_on()}")
    print(f"  Locked: {is_locked()}")

    # Menu
    print("\n" + "-"*60)
    print("OPTIONS:")
    print("  1. Test unlock now")
    print("  2. Full test (sleep -> unlock)")
    print("  3. Manual ADB commands")
    print("-"*60)

    choice = input("\nSelect (1-3): ").strip()

    if choice == "1":
        unlock_samsung(PIN)
    elif choice == "2":
        test_sleep_and_unlock()
    elif choice == "3":
        print("\nEnter ADB shell commands (type 'exit' to quit):")
        while True:
            cmd = input("adb> ").strip()
            if cmd == "exit":
                break
            adb(cmd)


if __name__ == "__main__":
    main()
