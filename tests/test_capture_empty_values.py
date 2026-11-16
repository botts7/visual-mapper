"""Empty sensor extraction must not count as a fresh capture (issue #11).

Runs the real capture step without starting ADB, MQTT or the web server.
"""

import asyncio
import importlib
import io
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from PIL import Image

OLD_TIME = datetime(2020, 1, 1)


@pytest.fixture
def flows(monkeypatch):
    backend = Path(__file__).resolve().parents[1] / "backend"
    monkeypatch.syspath_prepend(str(backend))
    # The flows package initializer eagerly imports the entire execution stack.
    # Load the real executor and its sibling models in an isolated package.
    package = ModuleType("_capture_empty_tests")
    package.__path__ = [str(backend / "core" / "flows")]
    with patch.dict(sys.modules, {package.__name__: package}):
        yield SimpleNamespace(
            executor=importlib.import_module(f"{package.__name__}.flow_executor"),
            models=importlib.import_module(f"{package.__name__}.flow_models"),
        )


def make_sensor(sensor_id, fallback=None):
    return SimpleNamespace(
        sensor_id=sensor_id,
        friendly_name=sensor_id,
        sensor_type="sensor",
        update_interval_seconds=60,
        current_value="last-good",
        last_updated=OLD_TIME,
        source=SimpleNamespace(
            custom_bounds=None,
            element_resource_id=None,
            element_text=None,
            element_class=None,
        ),
        extraction_rule=SimpleNamespace(fallback_value=fallback),
    )


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="PNG")
    return buf.getvalue()


def run_capture(flows, sensors, texts, extracted):
    """sensors: list; texts/extracted: sensor_id -> element text / extractor output."""
    by_id = {s.sensor_id: s for s in sensors}
    order = iter([s.sensor_id for s in sensors])

    def find_element(**_kwargs):
        sensor_id = next(order)
        return SimpleNamespace(
            found=True,
            method="stored_bounds",
            confidence=1.0,
            bounds=None,
            message="",
            element={"text": texts[sensor_id], "sid": sensor_id},
        )

    def extract(text, rule):
        for sensor_id, sensor in by_id.items():
            if sensor.extraction_rule is rule:
                return extracted[sensor_id]
        raise AssertionError("unknown rule")

    executor = object.__new__(flows.executor.FlowExecutor)
    executor._session_captured_sensors = {}
    executor.adb_bridge = SimpleNamespace(
        get_current_activity=AsyncMock(return_value="com.app/.Main"),
        capture_screenshot=AsyncMock(return_value=png_bytes()),
        get_ui_elements=AsyncMock(return_value=[]),
        devices={},
    )
    executor.sensor_manager = SimpleNamespace(
        get_sensor=lambda _device, sensor_id: by_id.get(sensor_id),
        update_sensor=Mock(),
    )
    executor.element_finder = SimpleNamespace(find_element=find_element)
    executor.text_extractor = SimpleNamespace(extract=Mock(side_effect=extract))
    executor.mqtt_manager = SimpleNamespace(
        publish_discovery=AsyncMock(),
        publish_state_batch=AsyncMock(
            side_effect=lambda updates: {"success": len(updates), "failed": 0}
        ),
    )
    step = SimpleNamespace(
        sensor_ids=[s.sensor_id for s in sensors],
        screen_package=None,
        screen_activity=None,
    )
    result = flows.models.FlowExecutionResult(
        flow_id="flow", success=True, executed_steps=0, execution_time_ms=0
    )
    ok = asyncio.run(executor._execute_capture_sensors("device", step, result))
    published = {}
    for call in executor.mqtt_manager.publish_state_batch.await_args_list:
        for sensor, value in call.args[0]:
            published[sensor.sensor_id] = value
    return SimpleNamespace(
        ok=ok, result=result, executor=executor, published=published
    )


def assert_untouched(run, sensor):
    assert sensor.sensor_id not in run.published
    assert sensor.current_value == "last-good"
    assert sensor.last_updated == OLD_TIME
    assert sensor.sensor_id not in run.executor._session_captured_sensors
    assert sensor.sensor_id not in run.result.captured_sensors
    persisted = [c.args[0] for c in run.executor.sensor_manager.update_sensor.call_args_list]
    assert sensor not in persisted


def test_empty_element_text_is_a_failed_capture(flows):
    sensor = make_sensor("empty")
    run = run_capture(flows, [sensor], {"empty": ""}, {"empty": "unused"})
    assert run.ok is False
    assert_untouched(run, sensor)


def test_extractor_returning_empty_is_a_failed_capture(flows):
    sensor = make_sensor("blank")
    run = run_capture(flows, [sensor], {"blank": "  "}, {"blank": "   "})
    assert run.ok is False
    assert_untouched(run, sensor)


def test_extractor_returning_none_is_a_failed_capture(flows):
    sensor = make_sensor("none")
    run = run_capture(flows, [sensor], {"none": "abc"}, {"none": None})
    assert run.ok is False
    assert_untouched(run, sensor)


def test_zero_is_a_real_value(flows):
    sensor = make_sensor("zero")
    run = run_capture(flows, [sensor], {"zero": "0 kW"}, {"zero": "0"})
    assert run.ok is True
    assert run.published == {"zero": "0"}
    assert sensor.current_value == "0"
    assert sensor.last_updated != OLD_TIME
    assert run.executor._session_captured_sensors["zero"] == "0"


def test_mixed_capture_publishes_only_good_value(flows):
    good = make_sensor("good")
    empty = make_sensor("empty")
    run = run_capture(
        flows, [good, empty], {"good": "42", "empty": ""}, {"good": "42", "empty": "x"}
    )
    assert run.ok is True
    assert run.published == {"good": "42"}
    assert good.current_value == "42"
    assert_untouched(run, empty)


def test_non_empty_fallback_value_is_still_published(flows):
    sensor = make_sensor("fb", fallback="N/A")
    run = run_capture(flows, [sensor], {"fb": ""}, {"fb": "unused"})
    assert run.ok is True
    assert run.published == {"fb": "N/A"}
    assert sensor.current_value == "N/A"
