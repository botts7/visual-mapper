"""
Simple WebSocket-only test to verify companion command routing.
Run this while companion is streaming to test if commands work without stopping the stream.
"""
import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.command_router import CommandRouter, CommandMethod
from core.streaming.companion_receiver import companion_stream_manager


async def test_websocket_routing():
    """Test that commands route through WebSocket when companion is streaming."""

    print("\n" + "="*60)
    print("WebSocket-Only Command Routing Test")
    print("="*60)

    # Get the command router instance
    try:
        from core.command_router import command_router
        router = command_router
    except ImportError:
        router = CommandRouter()

    # Check what devices have WebSocket connections
    print("\n1. Checking registered WebSocket connections...")
    ws_devices = list(router._websocket_connections.keys())
    print(f"   WebSocket devices: {ws_devices}")

    # Check companion streaming status
    print("\n2. Checking companion streaming status...")
    companion_stats = companion_stream_manager.get_stats()
    print(f"   Companion streams: {companion_stats}")

    active_devices = companion_stream_manager.get_active_devices()
    print(f"   Active devices: {active_devices}")

    if not ws_devices and not active_devices:
        print("\n❌ No WebSocket connections or companion streams found!")
        print("   Please start companion streaming first, then run this test.")
        return

    # Pick a device to test
    test_device = ws_devices[0] if ws_devices else None
    if not test_device and active_devices:
        # Try to find WebSocket for active companion
        for dev in active_devices:
            if router.has_websocket(dev):
                test_device = dev
                break

    if not test_device:
        print("\n❌ No device with active WebSocket found!")
        return

    print(f"\n3. Testing device: {test_device}")

    # Check routing availability
    ws_available = router._should_use_websocket(test_device)
    mqtt_available = router._should_use_mqtt(test_device)
    print(f"   WebSocket available: {ws_available}")
    print(f"   MQTT available: {mqtt_available}")

    if not ws_available:
        print("\n❌ WebSocket not available for this device!")
        return

    # Test 1: Simple tap command via WebSocket
    print("\n4. Testing TAP command via WebSocket...")
    result = await router.execute(
        test_device,
        "tap",
        {"x": 100, "y": 100},
        timeout=5.0
    )
    print(f"   Result: success={result.success}, method={result.method}, latency={result.latency_ms:.1f}ms")
    if result.error:
        print(f"   Error: {result.error}")

    if result.method != CommandMethod.WEBSOCKET:
        print(f"   ⚠️  Command used {result.method} instead of WEBSOCKET!")

    # Wait a moment
    await asyncio.sleep(1)

    # Test 2: Get screen state via WebSocket
    print("\n5. Testing GET_SCREEN_STATE via WebSocket...")
    result = await router.execute(
        test_device,
        "get_screen_state",
        {},
        timeout=5.0
    )
    print(f"   Result: success={result.success}, method={result.method}")
    if result.data:
        print(f"   Screen state: {result.data}")
    if result.error:
        print(f"   Error: {result.error}")

    # Test 3: Launch app via WebSocket (the critical test!)
    print("\n6. Testing LAUNCH_APP via WebSocket...")
    print("   ⚠️  Watch the stream - it should NOT stop if accessibility is working!")

    # Use a safe app to launch (the companion itself or settings)
    result = await router.execute(
        test_device,
        "launch_app",
        {"package_name": "com.android.settings"},
        timeout=10.0
    )
    print(f"   Result: success={result.success}, method={result.method}, latency={result.latency_ms:.1f}ms")
    if result.error:
        print(f"   Error: {result.error}")

    if result.method != CommandMethod.WEBSOCKET:
        print(f"   ⚠️  Command used {result.method} instead of WEBSOCKET!")
        print("   This might explain why the stream stops!")

    # Check if companion is still streaming
    await asyncio.sleep(2)
    print("\n7. Checking if companion is still streaming...")
    still_streaming = companion_stream_manager.is_streaming(test_device)
    print(f"   Still streaming: {still_streaming}")

    if still_streaming:
        print("\n✅ SUCCESS: Stream stayed alive after launch_app via WebSocket!")
    else:
        print("\n❌ FAILED: Stream stopped after launch_app!")
        print("   Possible causes:")
        print("   - Accessibility service not enabled/working")
        print("   - Command didn't actually go through WebSocket")
        print("   - Companion app issue")

    print("\n" + "="*60)
    print("Test complete!")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(test_websocket_routing())
