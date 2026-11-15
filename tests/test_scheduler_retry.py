"""Exercise delayed retries without starting ADB, MQTT or the web server."""

import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest


@pytest.fixture
def scheduler_module(monkeypatch):
    backend = Path(__file__).resolve().parents[1] / "backend"
    monkeypatch.syspath_prepend(str(backend))
    # The flows package initializer eagerly imports the entire execution stack.
    # Load the real scheduler and its sibling models in an isolated package.
    package = ModuleType("_scheduler_retry_tests")
    package.__path__ = [str(backend / "core" / "flows")]
    main = ModuleType("main")
    main.wizard_active_devices = set()
    with patch.dict(sys.modules, {package.__name__: package, "main": main}):
        yield importlib.import_module(f"{package.__name__}.flow_scheduler")


@pytest.mark.parametrize(
    "disable_first, disable_second, stop_scheduler, expected_ids",
    [
        (False, False, False, ["first", "second"]),
        (False, True, False, ["first"]),
        (True, False, False, ["second"]),
        (False, False, True, []),
    ],
)
def test_retry_keeps_its_queue_item(
    scheduler_module, disable_first, disable_second, stop_scheduler, expected_ids
):
    async def exercise():
        module = scheduler_module
        executor = SimpleNamespace(
            adb_bridge=SimpleNamespace(get_connected_devices=AsyncMock(return_value=[]))
        )
        scheduler = module.FlowScheduler(executor, Mock())
        scheduler._running = True
        scheduler.resolve_device_id = Mock(return_value="device")
        scheduler._auto_unlock_if_needed = AsyncMock(return_value=False)
        scheduler.schedule_flow = AsyncMock()
        queue = asyncio.PriorityQueue()
        scheduler._queues["device"] = queue
        scheduler._device_locks["device"] = asyncio.Lock()
        first = SimpleNamespace(
            flow_id="first", name="First", device_id="device", enabled=True
        )
        second = SimpleNamespace(
            flow_id="second", name="Second", device_id="device",
            enabled=not disable_second,
        )
        await queue.put(module.QueuedFlow(10, 1, first, "periodic"))
        await queue.put(module.QueuedFlow(18, 2, second, "periodic"))

        retries = []
        # Hold delayed coroutines until the real loop has consumed both items.
        # No wall-clock sleep is needed to reproduce the closure race.
        clock = SimpleNamespace(
            create_task=retries.append,
            sleep=AsyncMock(),
            CancelledError=asyncio.CancelledError,
        )
        with patch.object(module, "asyncio", clock):
            worker = asyncio.create_task(scheduler._run_device_scheduler("device"))
            try:
                await asyncio.wait_for(queue.join(), timeout=2)
            finally:
                worker.cancel()
                await worker

            first.enabled = not disable_first
            scheduler._running = not stop_scheduler
            try:
                for retry in retries:
                    await retry
            finally:
                for retry in retries:
                    retry.close()

        calls = scheduler.schedule_flow.await_args_list
        assert [call.args[0].flow_id for call in calls] == expected_ids
        expected_flows = {"first": first, "second": second}
        expected_priorities = {"first": 15, "second": 20}
        for call in calls:
            flow_id = call.args[0].flow_id
            assert call.args[0] is expected_flows[flow_id]
            assert call.kwargs == {
                "priority": expected_priorities[flow_id],
                "reason": "retry_after_locked",
            }

    asyncio.run(exercise())
