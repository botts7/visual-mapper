"""Beta.4 tester findings: disabled sensors, connection options, stale endpoint.

1. A disabled sensor must not have its cached state republished at startup.
2. connection_* add-on options and adb_device_ip/port reach the backend.
3. After an endpoint remap, sensors carry the new ip:port in device_id and
   their MQTT attributes are republished.

No ADB, MQTT broker or web server: managers are mocked and the startup
wiring in main.py is checked structurally (it lives inside lifespan()).
"""

import ast
import asyncio
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
OLD_ID = "10.0.0.5:37001"
NEW_ID = "10.0.0.5:41234"
STABLE_ID = "PIXEL8ASERIAL"


@pytest.fixture
def load(monkeypatch):
    monkeypatch.syspath_prepend(str(BACKEND))
    with patch.dict(sys.modules):
        yield importlib.import_module


def sensor(enabled=True, value="62", device_id=OLD_ID, stable=STABLE_ID, sensor_id="soc"):
    return SimpleNamespace(
        sensor_id=sensor_id,
        enabled=enabled,
        current_value=value,
        device_id=device_id,
        stable_device_id=stable,
        last_updated=None,
        source=SimpleNamespace(element_resource_id="com.app:id/soc"),
        extraction_rule=SimpleNamespace(method="numeric"),
    )


def fake_mqtt():
    return SimpleNamespace(
        publish_discovery=AsyncMock(return_value=True),
        publish_state=AsyncMock(return_value=True),
        publish_attributes=AsyncMock(return_value=True),
    )


# --- 1. disabled sensors -----------------------------------------------------


@pytest.mark.parametrize("label", ["initial", "delayed"])
def test_disabled_sensor_gets_discovery_but_no_cached_state(load, label):
    module = load("services.sensor_publish")
    mqtt = fake_mqtt()
    disabled = sensor(enabled=False, value="62")

    published = asyncio.run(module.publish_sensor_on_startup(mqtt, disabled, label))

    assert published is False
    mqtt.publish_discovery.assert_awaited_once_with(disabled)
    mqtt.publish_state.assert_not_awaited()


def test_enabled_sensor_startup_behaviour_unchanged(load):
    module = load("services.sensor_publish")
    mqtt = fake_mqtt()
    enabled = sensor(enabled=True, value="80")
    empty = sensor(enabled=True, value=None, sensor_id="empty")

    assert asyncio.run(module.publish_sensor_on_startup(mqtt, enabled)) is True
    assert asyncio.run(module.publish_sensor_on_startup(mqtt, empty)) is False

    mqtt.publish_state.assert_awaited_once_with(enabled, "80")
    assert mqtt.publish_discovery.await_count == 2


def _calls(tree, name):
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == name)
            or (isinstance(node.func, ast.Name) and node.func.id == name)
        )
    ]


def test_main_startup_paths_use_the_disabled_aware_helper():
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8"))
    # on_device_discovered and publish_existing_devices both go through it,
    # and nothing in main.py publishes a cached state directly any more.
    assert len(_calls(tree, "publish_sensor_on_startup")) == 2
    assert _calls(tree, "publish_state") == []


def test_sensor_routes_gate_cached_state_on_enabled():
    tree = ast.parse((BACKEND / "routes" / "sensors.py").read_text(encoding="utf-8"))
    assert len(_calls(tree, "should_publish_cached_state")) == 2


# --- 2. connection options ---------------------------------------------------


def test_connection_settings_from_env(load, monkeypatch):
    module = load("config.defaults")
    monkeypatch.setenv("CONNECTION_CHECK_INTERVAL", "15")
    monkeypatch.setenv("CONNECTION_MAX_RETRY_DELAY", "120")
    monkeypatch.setenv("CONNECTION_RETRY_ENABLED", "false")
    settings = module.AppDefaults.from_env()
    assert settings.CONNECTION_CHECK_INTERVAL == 15
    assert settings.CONNECTION_MAX_RETRY_DELAY == 120
    assert settings.CONNECTION_RETRY_ENABLED is False

    monkeypatch.setenv("CONNECTION_CHECK_INTERVAL", "not-a-number")
    monkeypatch.setenv("CONNECTION_RETRY_ENABLED", "true")
    monkeypatch.delenv("CONNECTION_MAX_RETRY_DELAY")
    settings = module.AppDefaults.from_env()
    assert settings.CONNECTION_CHECK_INTERVAL == 30
    assert settings.CONNECTION_MAX_RETRY_DELAY == 300
    assert settings.CONNECTION_RETRY_ENABLED is True


def test_main_passes_connection_settings_to_monitor():
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8"))
    (call,) = _calls(tree, "ConnectionMonitor")
    kwargs = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
    assert kwargs["check_interval"] == "connection_settings.CONNECTION_CHECK_INTERVAL"
    assert kwargs["max_retry_delay"] == "connection_settings.CONNECTION_MAX_RETRY_DELAY"
    assert kwargs["retry_enabled"] == "connection_settings.CONNECTION_RETRY_ENABLED"


def test_retry_disabled_tracks_status_without_reconnecting(load):
    module = load("services.connection_monitor")
    bridge = SimpleNamespace(
        lookup_tls_connect_services=AsyncMock(), discover_devices=AsyncMock()
    )
    monitor = module.ConnectionMonitor(
        adb_bridge=bridge,
        command_queue=Mock(),
        check_interval=7,
        max_retry_delay=99,
        retry_enabled=False,
    )
    monitor._try_direct_reconnect = AsyncMock(return_value=True)

    async def exercise():
        await monitor.add_device(OLD_ID, STABLE_ID)
        for _ in range(6):
            monitor._devices[OLD_ID].last_seen = 0
            await monitor._handle_device_state(OLD_ID, False)

    asyncio.run(exercise())

    assert monitor.check_interval == 7
    assert monitor.max_retry_delay == 99
    assert monitor._devices[OLD_ID].online is False
    monitor._try_direct_reconnect.assert_not_awaited()
    bridge.lookup_tls_connect_services.assert_not_awaited()
    bridge.discover_devices.assert_not_awaited()


def test_retry_enabled_still_reconnects(load):
    module = load("services.connection_monitor")
    monitor = module.ConnectionMonitor(adb_bridge=None, command_queue=Mock())
    monitor._try_direct_reconnect = AsyncMock(return_value=False)

    async def exercise():
        await monitor.add_device(OLD_ID, STABLE_ID)
        await monitor._handle_device_state(OLD_ID, False)

    asyncio.run(exercise())
    monitor._try_direct_reconnect.assert_awaited_once_with(OLD_ID)


@pytest.mark.parametrize(
    "env, expected_call",
    [
        ({"ADB_DEVICE_IP": "10.0.0.5", "ADB_DEVICE_PORT": "5555"}, ("10.0.0.5", 5555)),
        ({"ADB_DEVICE_IP": " 10.0.0.5 ", "ADB_DEVICE_PORT": "41234"}, ("10.0.0.5", 41234)),
        ({"ADB_DEVICE_IP": "10.0.0.5"}, ("10.0.0.5", 5555)),
        ({"ADB_DEVICE_IP": "10.0.0.5", "ADB_DEVICE_PORT": "abc"}, ("10.0.0.5", 5555)),
        ({"ADB_DEVICE_IP": "", "ADB_DEVICE_PORT": "5555"}, None),
        ({}, None),
    ],
)
def test_configured_device_connects_at_startup(load, env, expected_call):
    module = load("services.startup_reconnect")
    bridge = SimpleNamespace(
        connect_device=AsyncMock(side_effect=lambda h, p: f"{h}:{p}")
    )
    result = asyncio.run(module.connect_configured_device(bridge, env))
    if expected_call is None:
        assert result is None
        bridge.connect_device.assert_not_awaited()
    else:
        bridge.connect_device.assert_awaited_once_with(*expected_call)
        assert result == f"{expected_call[0]}:{expected_call[1]}"


def test_configured_device_failure_does_not_raise(load):
    module = load("services.startup_reconnect")
    bridge = SimpleNamespace(connect_device=AsyncMock(side_effect=ConnectionError("x")))
    assert asyncio.run(
        module.connect_configured_device(bridge, {"ADB_DEVICE_IP": "10.0.0.5"})
    ) is None


def test_main_connects_configured_device_at_startup():
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8"))
    assert len(_calls(tree, "connect_configured_device")) == 1


# --- 3. stale endpoint metadata ----------------------------------------------


def write_sensor_file(data_dir, name, list_device_id, sensors):
    base = {
        "friendly_name": "SOC",
        "sensor_type": "sensor",
        "source": {"source_type": "element", "element_index": 1},
        "extraction_rule": {"method": "numeric"},
    }
    payload = {
        "device_id": list_device_id,
        "sensors": [{**base, **s} for s in sensors],
    }
    path = data_dir / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_remap_updates_sensor_device_id_and_keeps_stable_id(load, tmp_path):
    module = load("core.sensors.sensor_manager")
    with patch.object(module, "get_device_identity_resolver", return_value=Mock()):
        manager = module.SensorManager(data_dir=str(tmp_path))
    path = write_sensor_file(
        tmp_path,
        f"sensors_{STABLE_ID}.json",
        OLD_ID,
        [
            {"sensor_id": "soc", "device_id": OLD_ID, "stable_device_id": STABLE_ID},
            {"sensor_id": "odo", "device_id": OLD_ID, "stable_device_id": STABLE_ID,
             "enabled": False},
            {"sensor_id": "other", "device_id": "10.0.0.9:5555",
             "stable_device_id": "OTHER"},
            {"sensor_id": "usb", "device_id": STABLE_ID, "stable_device_id": STABLE_ID},
        ],
    )

    updated = manager.remap_device_endpoint(STABLE_ID, NEW_ID)

    assert sorted(s.sensor_id for s in updated) == ["odo", "soc"]
    saved = json.loads(path.read_text(encoding="utf-8"))
    by_id = {s["sensor_id"]: s for s in saved["sensors"]}
    assert saved["device_id"] == NEW_ID
    assert by_id["soc"]["device_id"] == NEW_ID
    assert by_id["soc"]["stable_device_id"] == STABLE_ID
    assert by_id["other"]["device_id"] == "10.0.0.9:5555"
    assert by_id["usb"]["device_id"] == STABLE_ID
    # Idempotent: already pointing at the new endpoint.
    assert manager.remap_device_endpoint(STABLE_ID, NEW_ID) == []


def test_remapped_enabled_sensors_get_attributes_republished(load):
    module = load("services.sensor_publish")
    mqtt = fake_mqtt()
    enabled = sensor(enabled=True, device_id=NEW_ID)
    disabled = sensor(enabled=False, device_id=NEW_ID, sensor_id="odo")

    count = asyncio.run(module.republish_sensor_attributes(mqtt, [enabled, disabled]))

    assert count == 1
    mqtt.publish_attributes.assert_awaited_once()
    published_sensor, attributes = mqtt.publish_attributes.await_args.args
    assert published_sensor is enabled
    assert attributes["device_id"] == NEW_ID
    assert attributes["source_element"] == "com.app:id/soc"
    assert attributes["extraction_method"] == "numeric"


def test_main_remaps_sensors_on_device_discovered():
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8"))
    assert len(_calls(tree, "remap_device_endpoint")) == 1
    assert len(_calls(tree, "republish_sensor_attributes")) == 1
