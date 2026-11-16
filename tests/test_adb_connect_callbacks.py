"""Explicit connects run the same post-connect callbacks as auto-import.

No real ADB or MQTT: the bridge is built without its constructor and the
connection, identity resolver and `adb devices` output are mocked.
"""

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

DEVICE_ID = "10.0.0.5:5555"


@pytest.fixture
def bridge_module(monkeypatch):
    backend = Path(__file__).resolve().parents[1] / "backend"
    monkeypatch.syspath_prepend(str(backend))
    # Drop anything imported here once the test ends.
    with patch.dict(sys.modules):
        module = importlib.import_module("core.adb.adb_bridge")
        with patch.object(
            module, "get_device_identity_resolver", return_value=Mock()
        ):
            yield module


def make_bridge(module, callbacks):
    bridge = object.__new__(module.ADBBridge)
    bridge.devices = {}
    bridge._adb_lock = asyncio.Lock()
    bridge._device_discovered_callbacks = list(callbacks)
    conn = SimpleNamespace(
        connect=AsyncMock(return_value=True),
        shell=AsyncMock(return_value="Pixel 7\n"),
    )
    bridge.manager = SimpleNamespace(get_connection=AsyncMock(return_value=conn))
    bridge.get_device_serial = AsyncMock(return_value="SERIAL1")
    return bridge


def adb_devices_listing(*args, **kwargs):
    return SimpleNamespace(
        returncode=0,
        stdout=f"List of devices attached\n{DEVICE_ID} device model:Pixel_7\n",
    )


def test_connect_fires_callback_once_and_discovery_does_not_repeat(bridge_module):
    async def exercise():
        callback = AsyncMock()
        bridge = make_bridge(bridge_module, [callback])

        assert await bridge.connect_device("10.0.0.5", 5555) == DEVICE_ID
        callback.assert_awaited_once_with(DEVICE_ID, "Pixel 7")

        # A later scan sees the device already tracked and must not re-fire.
        with patch("subprocess.run", side_effect=adb_devices_listing):
            await bridge.discover_devices()
        callback.assert_awaited_once()

    asyncio.run(exercise())


def test_already_connected_returns_early_without_callbacks(bridge_module):
    # The first connect already ran the post-connect path, so a repeat
    # connect is a no-op: no new connection and no second callback run.
    async def exercise():
        callback = AsyncMock()
        bridge = make_bridge(bridge_module, [callback])

        await bridge.connect_device("10.0.0.5", 5555)
        assert await bridge.connect_device("10.0.0.5", 5555) == DEVICE_ID

        bridge.manager.get_connection.assert_awaited_once()
        callback.assert_awaited_once()

    asyncio.run(exercise())


@pytest.mark.parametrize("error", [RuntimeError("boom"), TypeError("boom")])
def test_failing_callback_does_not_fail_connect(bridge_module, error):
    # TypeError takes the no-model fallback, which fails again here too.
    async def exercise():
        failing = AsyncMock(side_effect=error)
        later = AsyncMock()
        bridge = make_bridge(bridge_module, [failing, later])

        assert await bridge.connect_device("10.0.0.5", 5555) == DEVICE_ID
        assert DEVICE_ID in bridge.devices
        later.assert_awaited_once_with(DEVICE_ID, "Pixel 7")

    asyncio.run(exercise())
