"""Pre-execution unlock wakes a sleeping no-PIN device before giving up (#13).

Runs FlowExecutor.auto_unlock_if_needed against mocked ADB, no real device.
"""

import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest


@pytest.fixture
def executor_module(monkeypatch):
    backend = Path(__file__).resolve().parents[1] / "backend"
    monkeypatch.syspath_prepend(str(backend))
    # The flows package initializer eagerly imports the entire execution stack.
    # Load the real executor in an isolated package instead.
    package = ModuleType("_unlock_wake_tests")
    package.__path__ = [str(backend / "core" / "flows")]
    with patch.dict(sys.modules, {package.__name__: package}):
        yield importlib.import_module(f"{package.__name__}.flow_executor")


def make_bridge(locked_states):
    """is_locked() returns each value in turn, then the last one forever."""
    states = list(locked_states)

    async def is_locked(_device_id):
        return states.pop(0) if len(states) > 1 else states[0]

    return SimpleNamespace(
        get_unlock_status=Mock(return_value={}),
        get_device_serial=AsyncMock(return_value="device"),
        is_locked=AsyncMock(side_effect=is_locked),
        ensure_screen_on=AsyncMock(return_value=True),
        unlock_screen=AsyncMock(return_value=True),
        unlock_device=AsyncMock(return_value=True),
    )


def run_unlock(module, bridge, config, passcode=None):
    executor = module.FlowExecutor.__new__(module.FlowExecutor)
    executor.adb_bridge = bridge
    executor.security_manager = SimpleNamespace(
        get_lock_config=Mock(return_value=config),
        get_passcode=Mock(return_value=passcode),
    )
    clock = SimpleNamespace(sleep=AsyncMock())
    with patch.object(module, "asyncio", clock):
        return asyncio.run(executor.auto_unlock_if_needed("device"))


NO_LOCK = {"strategy": "no_lock"}


@pytest.mark.parametrize("config", [NO_LOCK, None])
def test_wake_alone_unlocks(executor_module, config):
    # Locked only because the screen was off: waking is enough.
    bridge = make_bridge([True, False])
    result = run_unlock(executor_module, bridge, config)
    assert result == {"success": True}
    bridge.ensure_screen_on.assert_awaited_once_with("device")
    bridge.unlock_screen.assert_not_awaited()


@pytest.mark.parametrize("config", [NO_LOCK, None])
def test_swipe_after_wake_unlocks(executor_module, config):
    bridge = make_bridge([True, True, False])
    result = run_unlock(executor_module, bridge, config)
    assert result == {"success": True}
    bridge.ensure_screen_on.assert_awaited_once()
    bridge.unlock_screen.assert_awaited_once_with("device")
    bridge.unlock_device.assert_not_awaited()


@pytest.mark.parametrize("config", [NO_LOCK, None])
def test_still_locked_reports_not_configured(executor_module, config):
    bridge = make_bridge([True])
    result = run_unlock(executor_module, bridge, config)
    assert result["success"] is False
    assert result["reason"] == "not_configured"
    assert "still locked after waking and swiping" in result["error"]
    bridge.ensure_screen_on.assert_awaited_once()
    bridge.unlock_screen.assert_awaited_once()
    bridge.unlock_device.assert_not_awaited()


def test_manual_only_wakes_but_never_swipes(executor_module):
    bridge = make_bridge([True])
    result = run_unlock(executor_module, bridge, {"strategy": "manual_only"})
    assert result["success"] is False
    assert result["reason"] == "manual_only"
    bridge.ensure_screen_on.assert_awaited_once()
    bridge.unlock_screen.assert_not_awaited()


def test_manual_only_wake_can_still_succeed(executor_module):
    bridge = make_bridge([True, False])
    result = run_unlock(executor_module, bridge, {"strategy": "manual_only"})
    assert result == {"success": True}
    bridge.unlock_screen.assert_not_awaited()


def test_auto_unlock_uses_pin_path(executor_module):
    # Existing behaviour: AUTO_UNLOCK goes straight to PIN entry, no new branch.
    bridge = make_bridge([True, False])
    result = run_unlock(
        executor_module, bridge, {"strategy": "auto_unlock"}, passcode="1234"
    )
    assert result == {"success": True}
    bridge.unlock_device.assert_awaited_once_with("device", "1234")
    bridge.ensure_screen_on.assert_not_awaited()
    bridge.unlock_screen.assert_not_awaited()


def test_already_unlocked_does_nothing(executor_module):
    bridge = make_bridge([False])
    result = run_unlock(executor_module, bridge, NO_LOCK)
    assert result == {"success": True}
    bridge.ensure_screen_on.assert_not_awaited()
    bridge.unlock_screen.assert_not_awaited()
