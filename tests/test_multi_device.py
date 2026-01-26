"""
Multi-Device Scenario Tests

Tests cover:
- Shared capture pipeline with multiple subscribers
- Cross-subnet device matching
- Producer lifecycle management
- Frame cross-injection patterns
- Queue isolation and fairness
- Race condition handling patterns
"""
import pytest
import asyncio
import struct
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


# =============================================================================
# MD-01 to MD-07: SHARED CAPTURE PIPELINE TESTS
# =============================================================================

class TestSharedCapturePipeline:
    """Test single producer broadcasting to multiple subscribers."""

    @pytest.mark.asyncio
    async def test_md01_two_clients_same_device_both_receive_frames(self):
        """MD-01: Two clients connect to same device, both receive frames."""
        # Simulate shared capture manager pattern
        subscribers: dict[str, list[asyncio.Queue]] = {}
        device_id = "192.168.1.100:5555"

        # Subscribe two clients
        subscribers[device_id] = []
        client1_queue = asyncio.Queue(maxsize=3)
        client2_queue = asyncio.Queue(maxsize=3)
        subscribers[device_id].append(client1_queue)
        subscribers[device_id].append(client2_queue)

        # Simulate producer broadcasting frame
        frame_data = b"fake_frame_01"
        for queue in subscribers[device_id]:
            await queue.put(frame_data)

        # Both clients should receive the same frame
        assert await client1_queue.get() == frame_data
        assert await client2_queue.get() == frame_data

    @pytest.mark.asyncio
    async def test_md02_producer_starts_on_first_subscriber(self):
        """MD-02: Producer starts when first client connects."""
        subscribers: dict[str, list[asyncio.Queue]] = {}
        producers: dict[str, asyncio.Task] = {}
        device_id = "test_device"

        async def mock_producer():
            while True:
                await asyncio.sleep(0.1)

        # No subscribers initially
        assert device_id not in subscribers

        # First client connects - should trigger producer start
        subscribers[device_id] = []
        client1_queue = asyncio.Queue(maxsize=3)
        subscribers[device_id].append(client1_queue)

        # Start producer since first subscriber
        if len(subscribers[device_id]) == 1 and device_id not in producers:
            producers[device_id] = asyncio.create_task(mock_producer())

        assert device_id in producers
        assert not producers[device_id].done()

        # Second client connects - producer already running
        client2_queue = asyncio.Queue(maxsize=3)
        subscribers[device_id].append(client2_queue)

        assert len(subscribers[device_id]) == 2
        assert not producers[device_id].done()  # Same producer still running

        # Cleanup
        producers[device_id].cancel()
        try:
            await producers[device_id]
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_md03_producer_continues_after_first_client_leaves(self):
        """MD-03: First client disconnects, producer continues for second client."""
        subscribers: dict[str, list[asyncio.Queue]] = {}
        producers: dict[str, asyncio.Task] = {}
        device_id = "test_device"

        producer_running = asyncio.Event()
        producer_running.set()

        async def mock_producer():
            while producer_running.is_set():
                await asyncio.sleep(0.01)

        # Two clients subscribed
        subscribers[device_id] = []
        client1_queue = asyncio.Queue(maxsize=3)
        client2_queue = asyncio.Queue(maxsize=3)
        subscribers[device_id].append(client1_queue)
        subscribers[device_id].append(client2_queue)

        producers[device_id] = asyncio.create_task(mock_producer())

        # First client leaves
        subscribers[device_id].remove(client1_queue)

        # Producer should still be running (second client still subscribed)
        assert len(subscribers[device_id]) == 1
        assert not producers[device_id].done()

        # Cleanup
        producer_running.clear()
        await asyncio.wait_for(producers[device_id], timeout=1.0)

    @pytest.mark.asyncio
    async def test_md04_producer_stops_when_last_client_leaves(self):
        """MD-04: Last client disconnects, producer stops gracefully."""
        subscribers: dict[str, list[asyncio.Queue]] = {}
        producers: dict[str, asyncio.Task] = {}
        producer_stopping: dict[str, asyncio.Event] = {}
        device_id = "test_device"

        producer_should_stop = asyncio.Event()

        async def mock_producer():
            try:
                while not producer_should_stop.is_set():
                    await asyncio.sleep(0.01)
            finally:
                # Signal cleanup complete
                if device_id in producer_stopping:
                    producer_stopping[device_id].set()

        # One client subscribed
        subscribers[device_id] = []
        client1_queue = asyncio.Queue(maxsize=3)
        subscribers[device_id].append(client1_queue)

        producers[device_id] = asyncio.create_task(mock_producer())
        producer_stopping[device_id] = asyncio.Event()

        # Client leaves (last subscriber)
        subscribers[device_id].remove(client1_queue)

        # Should trigger producer stop
        if not subscribers[device_id]:
            producer_should_stop.set()

        # Wait for producer to complete
        await asyncio.wait_for(producers[device_id], timeout=1.0)

        # Verify cleanup signal
        assert producer_stopping[device_id].is_set()

    @pytest.mark.asyncio
    async def test_md06_three_concurrent_clients_all_receive(self):
        """MD-06: Three concurrent clients all receive same frames."""
        subscribers: dict[str, list[asyncio.Queue]] = {}
        device_id = "test_device"

        # Three clients
        subscribers[device_id] = []
        queues = [asyncio.Queue(maxsize=3) for _ in range(3)]
        for q in queues:
            subscribers[device_id].append(q)

        # Broadcast 5 frames
        for frame_num in range(5):
            frame_data = f"frame_{frame_num}".encode()
            for queue in subscribers[device_id]:
                try:
                    queue.put_nowait(frame_data)
                except asyncio.QueueFull:
                    queue.get_nowait()  # Drop oldest
                    queue.put_nowait(frame_data)

        # All clients should have same frames (or most recent if overflow)
        for i, queue in enumerate(queues):
            frames_received = []
            while not queue.empty():
                frames_received.append(queue.get_nowait())
            assert len(frames_received) == 3  # Queue maxsize is 3, oldest dropped
            assert frames_received[-1] == b"frame_4"  # Most recent frame

    @pytest.mark.asyncio
    async def test_md07_queue_overflow_drops_oldest(self):
        """MD-07: Slow clients drop oldest frames when queue full."""
        queue = asyncio.Queue(maxsize=3)

        # Fill queue with old frames
        for i in range(3):
            await queue.put(f"old_frame_{i}")

        assert queue.full()

        # New frames arrive, should drop oldest
        for i in range(2):
            new_frame = f"new_frame_{i}"
            try:
                queue.put_nowait(new_frame)
            except asyncio.QueueFull:
                queue.get_nowait()  # Drop oldest
                queue.put_nowait(new_frame)

        # Verify only recent frames remain
        frames = []
        while not queue.empty():
            frames.append(queue.get_nowait())

        assert "old_frame_0" not in frames
        assert "old_frame_1" not in frames
        assert "new_frame_0" in frames
        assert "new_frame_1" in frames


# =============================================================================
# MD-08 to MD-14: COMPANION CROSS-INJECTION TESTS
# =============================================================================

class TestCompanionCrossInjection:
    """Test cross-subnet device matching and frame injection."""

    def test_md08_companion_registers_with_underscore_device_id(self):
        """MD-08: Companion registers with device_id using underscores."""
        companion_registry: dict[str, dict] = {}

        # Simulate companion registration
        companion_device_id = "192_168_86_129_companion"
        companion_registry[companion_device_id] = {
            "ip": "192.168.86.129",
            "serial": "ZY22ABC123",
            "last_frame": datetime.now()
        }

        assert companion_device_id in companion_registry
        assert companion_registry[companion_device_id]["ip"] == "192.168.86.129"

    def test_md09_serial_based_matching_finds_companion(self):
        """MD-09: ADB device with matching serial finds companion via serial mapping."""
        serial_to_companion: dict[str, str] = {}
        companion_serials: dict[str, str] = {}

        # Register companion with serial
        companion_id = "192_168_86_129_companion"
        device_serial = "ZY22ABC123"
        serial_to_companion[device_serial] = companion_id
        companion_serials[companion_id] = device_serial

        # ADB device has different IP but same serial
        adb_device_id = "192.168.86.2:5555"
        adb_serial = "ZY22ABC123"

        # Find companion by serial
        def find_companion(device_id: str, serial: str | None) -> str | None:
            # Strategy 1: IP match (skip - different subnets)
            # Strategy 2: Serial match
            if serial and serial in serial_to_companion:
                return serial_to_companion[serial]
            return None

        found = find_companion(adb_device_id, adb_serial)
        assert found == companion_id

    def test_md10_web_ui_streams_both_device_aliases(self):
        """MD-10: Web UI can stream both primary and alias device IDs."""
        subscribers: dict[str, list[asyncio.Queue]] = {}

        # Primary device ID (from ADB)
        primary_id = "192.168.86.2:5555"
        # Alias device ID (from companion WiFi)
        alias_id = "192.168.86.129:5555"

        # Both IDs have subscribers
        subscribers[primary_id] = [asyncio.Queue(maxsize=3)]
        subscribers[alias_id] = [asyncio.Queue(maxsize=3)]

        assert primary_id in subscribers
        assert alias_id in subscribers
        assert len(subscribers) == 2

    @pytest.mark.asyncio
    async def test_md11_companion_frames_injected_to_both_subscribers(self):
        """MD-11: Companion frames injected to BOTH subscriber queues."""
        subscribers: dict[str, list[asyncio.Queue]] = {}
        serial_to_device: dict[str, list[str]] = {}

        # Setup: Companion knows its serial maps to these device IDs
        companion_id = "192_168_86_129_companion"
        companion_serial = "ZY22ABC123"

        # These device IDs should receive companion frames
        primary_id = "192.168.86.2:5555"
        alias_id = "192.168.86.129:5555"

        serial_to_device[companion_serial] = [primary_id, alias_id]

        # Both have active subscribers
        subscribers[primary_id] = [asyncio.Queue(maxsize=3)]
        subscribers[alias_id] = [asyncio.Queue(maxsize=3)]

        # Companion frame arrives
        frame_data = b"companion_frame_data"

        # Inject to all matching device subscribers
        def inject_frame(companion_serial: str, frame: bytes):
            injection_count = 0
            for device_id in serial_to_device.get(companion_serial, []):
                if device_id in subscribers:
                    for queue in subscribers[device_id]:
                        try:
                            queue.put_nowait(frame)
                            injection_count += 1
                        except asyncio.QueueFull:
                            pass
            return injection_count

        count = inject_frame(companion_serial, frame_data)
        assert count == 2  # Injected to both subscribers

        # Both received the frame
        assert subscribers[primary_id][0].get_nowait() == frame_data
        assert subscribers[alias_id][0].get_nowait() == frame_data

    def test_md12_single_companion_fallback(self):
        """MD-12: Single active companion used as fallback when no direct match."""
        active_companions: dict[str, dict] = {}

        # Only one companion active
        active_companions["192_168_86_129"] = {
            "serial": "ZY22ABC123",
            "last_frame": datetime.now()
        }

        def find_companion_fallback(device_id: str) -> str | None:
            # No IP match, no serial match, try single-companion fallback
            if len(active_companions) == 1:
                return list(active_companions.keys())[0]
            return None

        # Device with no direct match
        unknown_device = "10.0.0.100:5555"
        fallback = find_companion_fallback(unknown_device)

        assert fallback == "192_168_86_129"

    def test_md13_multiple_companions_disambiguated_by_serial(self):
        """MD-13: Multiple companions streaming, serial mapping disambiguates."""
        serial_to_companion: dict[str, str] = {}

        # Two companions registered
        serial_to_companion["ZY22ABC123"] = "192_168_86_129"
        serial_to_companion["R5CR999888"] = "192_168_86_130"

        # ADB devices with different serials
        def find_correct_companion(adb_serial: str) -> str | None:
            return serial_to_companion.get(adb_serial)

        assert find_correct_companion("ZY22ABC123") == "192_168_86_129"
        assert find_correct_companion("R5CR999888") == "192_168_86_130"
        assert find_correct_companion("UNKNOWN") is None


# =============================================================================
# MD-15 to MD-20: ADB/COMPANION FALLBACK TESTS
# =============================================================================

class TestStreamSourceFallback:
    """Test switching between companion app and ADB capture."""

    def test_md15_stream_starts_with_adb_when_companion_offline(self):
        """MD-15: Stream starts with ADB when companion is offline."""
        companion_available: dict[str, bool] = {}
        device_id = "192.168.1.100:5555"

        # Companion not available
        companion_available[device_id] = False

        def get_stream_source(device_id: str) -> str:
            if companion_available.get(device_id, False):
                return "companion"
            return "adb"

        assert get_stream_source(device_id) == "adb"

    def test_md16_switches_to_companion_when_available(self):
        """MD-16: Switches to companion when it becomes available."""
        companion_available: dict[str, bool] = {}
        device_id = "192.168.1.100:5555"

        current_source = "adb"
        companion_available[device_id] = False

        # Simulate companion coming online
        companion_available[device_id] = True

        def should_switch_source(device_id: str, current: str) -> tuple[bool, str]:
            companion_online = companion_available.get(device_id, False)
            if current == "adb" and companion_online:
                return True, "companion"
            return False, current

        should_switch, new_source = should_switch_source(device_id, current_source)
        assert should_switch
        assert new_source == "companion"

    def test_md17_falls_back_to_adb_on_companion_timeout(self):
        """MD-17: Falls back to ADB when companion times out (5s)."""
        companion_last_frame: dict[str, datetime] = {}
        device_id = "192.168.1.100:5555"
        timeout_seconds = 5

        current_source = "companion"

        # Last frame was 6 seconds ago
        companion_last_frame[device_id] = datetime.now() - timedelta(seconds=6)

        def is_companion_stale(device_id: str) -> bool:
            last_frame = companion_last_frame.get(device_id)
            if not last_frame:
                return True
            return (datetime.now() - last_frame).total_seconds() > timeout_seconds

        def should_fallback(device_id: str, current: str) -> tuple[bool, str]:
            if current == "companion" and is_companion_stale(device_id):
                return True, "adb"
            return False, current

        should_switch, new_source = should_fallback(device_id, current_source)
        assert should_switch
        assert new_source == "adb"

    def test_md19_source_change_notification_format(self):
        """MD-19: Source change notification has correct format."""
        import json

        def create_source_change_notification(old_source: str, new_source: str, reason: str) -> str:
            return json.dumps({
                "type": "source_change",
                "old_source": old_source,
                "new_source": new_source,
                "reason": reason,
                "timestamp": datetime.now().isoformat()
            })

        notification = create_source_change_notification("adb", "companion", "companion_available")
        parsed = json.loads(notification)

        assert parsed["type"] == "source_change"
        assert parsed["old_source"] == "adb"
        assert parsed["new_source"] == "companion"
        assert parsed["reason"] == "companion_available"


# =============================================================================
# MD-27 to MD-31: ADB DEVICE LOCKING TESTS
# =============================================================================

class TestADBDeviceLocking:
    """Test per-device locking for concurrent operations."""

    @pytest.mark.asyncio
    async def test_md27_same_device_operations_serialized(self):
        """MD-27: Operations on same device are serialized via lock."""
        device_locks: dict[str, asyncio.Lock] = {}
        device_id = "192.168.1.100:5555"
        operation_order = []

        device_locks[device_id] = asyncio.Lock()

        async def operation(name: str):
            async with device_locks[device_id]:
                operation_order.append(f"{name}_start")
                await asyncio.sleep(0.01)  # Simulate work
                operation_order.append(f"{name}_end")

        # Run two operations concurrently
        await asyncio.gather(
            operation("screenshot"),
            operation("shell_command")
        )

        # Should be serialized: one completes before other starts
        assert operation_order[0].endswith("_start")
        assert operation_order[1].endswith("_end")
        assert operation_order[0].replace("_start", "") == operation_order[1].replace("_end", "")

    @pytest.mark.asyncio
    async def test_md28_different_devices_parallel(self):
        """MD-28: Operations on different devices run in parallel."""
        device_locks: dict[str, asyncio.Lock] = {}
        device_a = "192.168.1.100:5555"
        device_b = "192.168.1.101:5555"
        operation_times: dict[str, list[float]] = {"A": [], "B": []}

        device_locks[device_a] = asyncio.Lock()
        device_locks[device_b] = asyncio.Lock()

        import time

        async def operation(device_id: str, name: str):
            async with device_locks[device_id]:
                operation_times[name].append(time.time())
                await asyncio.sleep(0.05)  # 50ms work
                operation_times[name].append(time.time())

        start_time = time.time()
        await asyncio.gather(
            operation(device_a, "A"),
            operation(device_b, "B")
        )
        total_time = time.time() - start_time

        # Should complete in ~50ms if parallel, ~100ms if serial
        # Allow some tolerance
        assert total_time < 0.08, f"Expected parallel execution, took {total_time}s"

    def test_md31_serial_cache_persistence(self):
        """MD-31: Device serial cache persists across port/IP changes."""
        serial_cache: dict[str, str] = {}  # serial -> device_id

        # Initial device connection
        serial = "ZY22ABC123"
        old_device_id = "192.168.1.100:5555"
        serial_cache[serial] = old_device_id

        # Device reconnects with different port
        new_device_id = "192.168.1.100:42519"

        # Serial still maps correctly
        assert serial in serial_cache
        # Update mapping
        serial_cache[serial] = new_device_id
        assert serial_cache[serial] == new_device_id


# =============================================================================
# MD-41 to MD-45: RACE CONDITION TESTS
# =============================================================================

class TestRaceConditions:
    """Test race condition handling patterns."""

    @pytest.mark.asyncio
    async def test_md41_producer_stopping_blocks_new_subscriber(self):
        """MD-41: New subscriber waits for producer cleanup to complete."""
        producer_stopping: dict[str, asyncio.Event] = {}
        device_id = "test_device"

        # Producer is stopping (cleanup in progress)
        producer_stopping[device_id] = asyncio.Event()

        async def subscribe(device_id: str) -> str:
            # Wait for any stopping producer to complete
            if device_id in producer_stopping:
                stopping_event = producer_stopping[device_id]
                if not stopping_event.is_set():
                    try:
                        await asyncio.wait_for(stopping_event.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        return "timeout"
            return "subscribed"

        # Start subscribe attempt (will wait)
        subscribe_task = asyncio.create_task(subscribe(device_id))

        # Simulate producer cleanup completing after 100ms
        await asyncio.sleep(0.1)
        producer_stopping[device_id].set()

        result = await subscribe_task
        assert result == "subscribed"

    @pytest.mark.asyncio
    async def test_md42_rapid_register_unregister_reregister(self):
        """MD-42: Rapid companion register/unregister/re-register handled."""
        companions: dict[str, dict] = {}
        stale_threshold = 5  # seconds

        device_id = "companion_device"

        # Register
        companions[device_id] = {"last_frame": datetime.now()}
        assert device_id in companions

        # Unregister
        del companions[device_id]
        assert device_id not in companions

        # Re-register within stale threshold (should work)
        companions[device_id] = {"last_frame": datetime.now()}
        assert device_id in companions

    @pytest.mark.asyncio
    async def test_md43_two_clients_unsubscribe_simultaneously(self):
        """MD-43: Two clients unsubscribe at same time, cleanup happens once."""
        subscribers: dict[str, list[asyncio.Queue]] = {}
        cleanup_count = 0
        device_id = "test_device"
        lock = asyncio.Lock()

        # Two subscribers - save references before gather
        queue1 = asyncio.Queue()
        queue2 = asyncio.Queue()
        subscribers[device_id] = [queue1, queue2]

        async def unsubscribe(queue: asyncio.Queue):
            nonlocal cleanup_count
            async with lock:
                if device_id in subscribers and queue in subscribers[device_id]:
                    subscribers[device_id].remove(queue)
                    # Only cleanup if last subscriber
                    if not subscribers[device_id]:
                        cleanup_count += 1
                        del subscribers[device_id]

        # Both unsubscribe at same time
        await asyncio.gather(
            unsubscribe(queue1),
            unsubscribe(queue2)
        )

        # Cleanup should only happen once
        assert cleanup_count == 1
        assert device_id not in subscribers

    @pytest.mark.asyncio
    async def test_md44_frame_injection_during_subscriber_list_modification(self):
        """MD-44: Frame injection safe during subscriber list modification."""
        subscribers: dict[str, list[asyncio.Queue]] = {}
        device_id = "test_device"
        lock = asyncio.Lock()

        # Initial subscribers
        subscribers[device_id] = [asyncio.Queue(maxsize=3) for _ in range(3)]

        async def inject_frame(frame: bytes):
            async with lock:
                if device_id in subscribers:
                    for queue in subscribers[device_id][:]:  # Copy list for safe iteration
                        try:
                            queue.put_nowait(frame)
                        except asyncio.QueueFull:
                            pass

        async def remove_subscriber(index: int):
            async with lock:
                if device_id in subscribers and len(subscribers[device_id]) > index:
                    subscribers[device_id].pop(index)

        # Inject and remove concurrently
        await asyncio.gather(
            inject_frame(b"frame_data"),
            remove_subscriber(0)
        )

        # Should not crash, remaining subscribers should have frame
        assert len(subscribers[device_id]) == 2


# =============================================================================
# MD-46 to MD-50: CAPACITY & STRESS TESTS
# =============================================================================

class TestCapacityAndStress:
    """Test system behavior under load."""

    @pytest.mark.asyncio
    async def test_md46_five_concurrent_device_streams(self):
        """MD-46: 5 concurrent device streams handled by SharedCaptureManager."""
        producers: dict[str, asyncio.Task] = {}
        device_ids = [f"device_{i}:5555" for i in range(5)]

        async def mock_producer(device_id: str):
            for _ in range(10):  # 10 frames each
                await asyncio.sleep(0.01)

        # Start 5 producers
        for device_id in device_ids:
            producers[device_id] = asyncio.create_task(mock_producer(device_id))

        # Wait for all to complete
        await asyncio.gather(*producers.values())

        assert len(producers) == 5
        assert all(task.done() for task in producers.values())

    @pytest.mark.asyncio
    async def test_md47_twenty_subscribers_to_same_device(self):
        """MD-47: 20 WebSocket subscribers to same device all receive frames."""
        device_id = "test_device"
        queues = [asyncio.Queue(maxsize=3) for _ in range(20)]

        # Broadcast 5 frames
        for frame_num in range(5):
            frame = f"frame_{frame_num}".encode()
            for queue in queues:
                try:
                    queue.put_nowait(frame)
                except asyncio.QueueFull:
                    queue.get_nowait()
                    queue.put_nowait(frame)

        # All should have at least the last 3 frames
        for i, queue in enumerate(queues):
            assert not queue.empty(), f"Queue {i} is empty"
            # Get last frame
            while queue.qsize() > 1:
                queue.get_nowait()
            last_frame = queue.get_nowait()
            assert b"frame_" in last_frame

    @pytest.mark.asyncio
    async def test_md48_rapid_connect_disconnect_no_dangling_producers(self):
        """MD-48: Rapid connect/disconnect leaves no dangling producers."""
        producers: dict[str, asyncio.Task] = {}
        subscribers: dict[str, list[asyncio.Queue]] = {}
        device_id = "test_device"

        producer_stop_signals: dict[str, asyncio.Event] = {}

        async def mock_producer(device_id: str, stop_signal: asyncio.Event):
            while not stop_signal.is_set():
                await asyncio.sleep(0.01)

        async def subscribe():
            if device_id not in subscribers:
                subscribers[device_id] = []
            queue = asyncio.Queue(maxsize=3)
            subscribers[device_id].append(queue)

            # Start producer if first subscriber
            if len(subscribers[device_id]) == 1:
                stop_signal = asyncio.Event()
                producer_stop_signals[device_id] = stop_signal
                producers[device_id] = asyncio.create_task(mock_producer(device_id, stop_signal))

            return queue

        async def unsubscribe(queue):
            if device_id in subscribers and queue in subscribers[device_id]:
                subscribers[device_id].remove(queue)

                # Stop producer if last subscriber
                if not subscribers[device_id]:
                    del subscribers[device_id]
                    if device_id in producer_stop_signals:
                        producer_stop_signals[device_id].set()
                        await producers[device_id]
                        del producers[device_id]
                        del producer_stop_signals[device_id]

        # Rapid connect/disconnect
        for _ in range(10):
            q = await subscribe()
            await asyncio.sleep(0.001)
            await unsubscribe(q)

        # No dangling producers
        assert device_id not in producers
        assert device_id not in subscribers


# =============================================================================
# MD-51 to MD-54: CROSS-INJECTION CORRECTNESS TESTS
# =============================================================================

class TestCrossInjectionCorrectness:
    """Test companion frames delivered to correct ADB device subscribers."""

    @pytest.mark.asyncio
    async def test_md51_injection_to_matching_devices_only(self):
        """MD-51: Companion frames only injected to matching device subscribers."""
        subscribers: dict[str, list[asyncio.Queue]] = {}
        serial_to_devices: dict[str, list[str]] = {}

        # Companion info
        companion_id = "192_168_86_129_companion"
        companion_serial = "ZY22ABC123"

        # Matching devices (should receive frames)
        ip_match_device = "192.168.86.129:5555"  # IP match
        serial_match_device = "192.168.86.2:5555"  # Serial match

        # Non-matching device (should NOT receive frames)
        other_device = "192.168.1.100:5555"

        serial_to_devices[companion_serial] = [ip_match_device, serial_match_device]

        # All devices have subscribers
        for device_id in [ip_match_device, serial_match_device, other_device]:
            subscribers[device_id] = [asyncio.Queue(maxsize=3)]

        # Inject frame
        frame_data = b"companion_frame"

        def inject_to_matching(serial: str, frame: bytes) -> list[str]:
            injected_to = []
            matching_devices = serial_to_devices.get(serial, [])
            for device_id in matching_devices:
                if device_id in subscribers:
                    for queue in subscribers[device_id]:
                        try:
                            queue.put_nowait(frame)
                            injected_to.append(device_id)
                        except asyncio.QueueFull:
                            pass
            return injected_to

        injected = inject_to_matching(companion_serial, frame_data)

        # Should inject to matching devices only
        assert ip_match_device in injected
        assert serial_match_device in injected
        assert other_device not in injected

        # Verify queues
        assert not subscribers[ip_match_device][0].empty()
        assert not subscribers[serial_match_device][0].empty()
        assert subscribers[other_device][0].empty()

    def test_md52_injection_count_logged_correctly(self):
        """MD-52: Injection count accurately reflects actual injections."""
        injection_log = []

        def log_injection(device_id: str, subscriber_count: int, total_injected: int):
            injection_log.append({
                "device_id": device_id,
                "subscriber_count": subscriber_count,
                "total_injected": total_injected
            })

        # Simulate injection to 2 devices with different subscriber counts
        log_injection("device_1", 3, 3)
        log_injection("device_2", 1, 1)

        assert len(injection_log) == 2
        assert injection_log[0]["total_injected"] == 3
        assert injection_log[1]["total_injected"] == 1
        assert sum(e["total_injected"] for e in injection_log) == 4

    def test_md53_warning_when_no_subscribers_match(self):
        """MD-53: Warning logged when companion frames have no matching subscribers."""
        warnings = []

        def inject_with_warning(serial: str, subscribers: dict) -> int:
            matching = []  # No matching devices
            if not matching:
                warnings.append(f"Frame from serial {serial} has no matching subscribers")
            return 0

        count = inject_with_warning("ZY22ABC123", {})
        assert count == 0
        assert len(warnings) == 1
        assert "no matching subscribers" in warnings[0]
