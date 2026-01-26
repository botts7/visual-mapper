"""
Validation Function Tests for Visual Mapper v0.4.0-beta.4

Tests for:
- Duplicate sensor name validation
- Regex pattern validation
- Error hint classification
"""
import pytest
import sys
from pathlib import Path

# Add backend to path for imports
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))


class TestRegexValidation:
    """Test regex pattern validation"""

    def test_valid_simple_regex(self):
        """Valid simple regex patterns should pass"""
        from routes.sensors import validate_regex_pattern

        valid, error = validate_regex_pattern(r"\d+")
        assert valid is True
        assert error == ""

    def test_valid_complex_regex(self):
        """Valid complex regex patterns should pass"""
        from routes.sensors import validate_regex_pattern

        valid, error = validate_regex_pattern(r"(\d+)°([CF])")
        assert valid is True
        assert error == ""

    def test_valid_temperature_regex(self):
        """Temperature extraction regex should pass"""
        from routes.sensors import validate_regex_pattern

        valid, error = validate_regex_pattern(r"(\d+(?:\.\d+)?)\s*°?[FCK]?")
        assert valid is True
        assert error == ""

    def test_empty_pattern_is_valid(self):
        """Empty pattern should be valid (no regex needed)"""
        from routes.sensors import validate_regex_pattern

        valid, error = validate_regex_pattern("")
        assert valid is True
        assert error == ""

    def test_none_pattern_is_valid(self):
        """None pattern should be valid"""
        from routes.sensors import validate_regex_pattern

        valid, error = validate_regex_pattern(None)
        assert valid is True
        assert error == ""

    def test_invalid_unclosed_bracket(self):
        """Unclosed bracket should fail"""
        from routes.sensors import validate_regex_pattern

        valid, error = validate_regex_pattern("[unclosed")
        assert valid is False
        assert "Invalid regex pattern" in error

    def test_invalid_unmatched_paren(self):
        """Unmatched parenthesis should fail"""
        from routes.sensors import validate_regex_pattern

        valid, error = validate_regex_pattern("(test")
        assert valid is False
        assert "Invalid regex pattern" in error

    def test_invalid_bad_escape(self):
        """Bad escape sequence should fail"""
        from routes.sensors import validate_regex_pattern

        # Using invalid escape - trailing backslash with nothing to escape
        valid, error = validate_regex_pattern("test\\")
        assert valid is False
        assert "Invalid regex pattern" in error


class TestErrorHintClassification:
    """Test error hint classification"""

    def test_classify_device_locked(self):
        """Device locked errors should be classified correctly"""
        from utils.error_handler import classify_error

        assert classify_error("Device is locked") == "device_locked"
        assert classify_error("Screen is locked, cannot proceed") == "device_locked"
        assert classify_error("unlock failed") == "device_locked"

    def test_classify_device_offline(self):
        """Device offline errors should be classified correctly"""
        from utils.error_handler import classify_error

        assert classify_error("Device not connected") == "device_offline"
        assert classify_error("device offline") == "device_offline"
        assert classify_error("Cannot reach device") == "device_offline"
        assert classify_error("device unreachable") == "device_offline"

    def test_classify_adb_connection(self):
        """ADB connection errors should be classified correctly"""
        from utils.error_handler import classify_error

        assert classify_error("ADB connection failed") == "adb_connection"
        assert classify_error("adb error: device not found") == "adb_connection"

    def test_classify_element_not_found(self):
        """Element not found errors should be classified correctly"""
        from utils.error_handler import classify_error

        assert classify_error("Element not found on screen") == "element_not_found"
        assert classify_error("UI element missing") == "element_not_found"
        assert classify_error("Could not find button") == "element_not_found"

    def test_classify_timeout(self):
        """Timeout errors should be classified correctly"""
        from utils.error_handler import classify_error

        assert classify_error("Flow execution timed out") == "timeout"
        assert classify_error("Operation timeout after 30s") == "timeout"
        assert classify_error("Request timeout") == "timeout"

    def test_classify_navigation_failed(self):
        """Navigation failed errors should be classified correctly"""
        from utils.error_handler import classify_error

        assert classify_error("Failed to navigate to screen") == "navigation_failed"
        assert classify_error("Navigation failed: wrong screen") == "navigation_failed"

    def test_classify_unknown_error(self):
        """Unknown errors should return None"""
        from utils.error_handler import classify_error

        assert classify_error("Some random error") is None
        assert classify_error("") is None

    def test_get_error_with_hint_device_locked(self):
        """Should return proper hint for device locked"""
        from utils.error_handler import get_error_with_hint

        result = get_error_with_hint("device_locked", "Device is locked")
        assert result["error"] == "Device is locked"
        assert "AUTO_UNLOCK" in result["hint"]
        assert result["docs"] == "/docs/auto-unlock"

    def test_get_error_with_hint_unknown_type(self):
        """Should handle unknown error type gracefully"""
        from utils.error_handler import get_error_with_hint

        result = get_error_with_hint("unknown_type", "Some error")
        assert result["error"] == "Some error"
        assert result["hint"] == ""


class TestDuplicateSensorNameValidation:
    """Test duplicate sensor name validation"""

    def test_unique_name_passes(self):
        """Unique sensor name should pass validation"""
        from routes.sensors import validate_sensor_config
        from pydantic import BaseModel
        from typing import Optional, Dict, Any

        # Create minimal sensor model for testing
        class MockSensor(BaseModel):
            sensor_id: str
            friendly_name: str
            sensor_type: str = "sensor"
            device_class: Optional[str] = None
            state_class: Optional[str] = None
            unit_of_measurement: Optional[str] = None
            extraction_rule: Optional[Dict[str, Any]] = None

        new_sensor = MockSensor(sensor_id="test_1", friendly_name="Unique Sensor")
        existing = [
            MockSensor(sensor_id="existing_1", friendly_name="Other Sensor"),
            MockSensor(sensor_id="existing_2", friendly_name="Another Sensor"),
        ]

        error = validate_sensor_config(new_sensor, existing)
        assert error is None

    def test_duplicate_name_fails(self):
        """Duplicate sensor name should fail validation"""
        from routes.sensors import validate_sensor_config
        from pydantic import BaseModel
        from typing import Optional, Dict, Any

        class MockSensor(BaseModel):
            sensor_id: str
            friendly_name: str
            sensor_type: str = "sensor"
            device_class: Optional[str] = None
            state_class: Optional[str] = None
            unit_of_measurement: Optional[str] = None
            extraction_rule: Optional[Dict[str, Any]] = None

        new_sensor = MockSensor(sensor_id="test_1", friendly_name="Duplicate Name")
        existing = [
            MockSensor(sensor_id="existing_1", friendly_name="Duplicate Name"),
        ]

        error = validate_sensor_config(new_sensor, existing)
        assert error is not None
        assert "already exists" in error

    def test_case_insensitive_duplicate(self):
        """Case-insensitive duplicate should fail validation"""
        from routes.sensors import validate_sensor_config
        from pydantic import BaseModel
        from typing import Optional, Dict, Any

        class MockSensor(BaseModel):
            sensor_id: str
            friendly_name: str
            sensor_type: str = "sensor"
            device_class: Optional[str] = None
            state_class: Optional[str] = None
            unit_of_measurement: Optional[str] = None
            extraction_rule: Optional[Dict[str, Any]] = None

        new_sensor = MockSensor(sensor_id="test_1", friendly_name="temperature sensor")
        existing = [
            MockSensor(sensor_id="existing_1", friendly_name="Temperature Sensor"),
        ]

        error = validate_sensor_config(new_sensor, existing)
        assert error is not None
        assert "already exists" in error

    def test_edit_same_name_allowed(self):
        """Editing sensor should allow keeping same name"""
        from routes.sensors import validate_sensor_config
        from pydantic import BaseModel
        from typing import Optional, Dict, Any

        class MockSensor(BaseModel):
            sensor_id: str
            friendly_name: str
            sensor_type: str = "sensor"
            device_class: Optional[str] = None
            state_class: Optional[str] = None
            unit_of_measurement: Optional[str] = None
            extraction_rule: Optional[Dict[str, Any]] = None

        sensor = MockSensor(sensor_id="test_1", friendly_name="My Sensor")
        existing = [
            MockSensor(sensor_id="test_1", friendly_name="My Sensor"),
            MockSensor(sensor_id="test_2", friendly_name="Other Sensor"),
        ]

        # When editing, exclude self from duplicate check
        error = validate_sensor_config(sensor, existing, exclude_sensor_id="test_1")
        assert error is None


class TestScreenDimensions:
    """Test screen dimension detection"""

    def test_parse_wm_size_output(self):
        """Should parse wm size output correctly"""
        # This would require mocking ADB bridge
        # For now, test the regex parsing logic
        import re

        wm_output = "Physical size: 1080x2400"
        match = re.search(r"(\d+)x(\d+)", wm_output)
        assert match is not None
        assert int(match.group(1)) == 1080
        assert int(match.group(2)) == 2400

    def test_parse_override_size(self):
        """Should handle override size in output"""
        import re

        wm_output = "Physical size: 1080x2400\nOverride size: 1080x2340"
        match = re.search(r"(\d+)x(\d+)", wm_output)
        assert match is not None
        # Should get first match (physical size)
        assert int(match.group(1)) == 1080
        assert int(match.group(2)) == 2400
