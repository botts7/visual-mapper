"""
Tests for new zero-config sensor features (v0.4.0-beta)

Tests:
- Auto Sensors (App Screen, Screen Change)
- Element Watchers
- Region Capture
"""

import pytest
import sys
import ast
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))


class TestAutoSensorsSyntax:
    """Verify auto_sensors module syntax and structure."""

    def test_auto_sensors_file_exists(self):
        """auto_sensors.py should exist."""
        path = backend_path / "services" / "auto_sensors.py"
        assert path.exists(), f"auto_sensors.py not found at {path}"

    def test_auto_sensors_syntax_valid(self):
        """auto_sensors.py should have valid Python syntax."""
        path = backend_path / "services" / "auto_sensors.py"
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"Syntax error in auto_sensors.py: {e}")

    def test_auto_sensors_imports(self):
        """auto_sensors.py should be importable."""
        from services.auto_sensors import (
            AutoSensorManager,
            get_auto_sensor_manager,
            AppScreenState,
            ScreenChangeState,
        )
        assert AutoSensorManager is not None
        assert get_auto_sensor_manager is not None

    def test_auto_sensors_route_exists(self):
        """auto_sensors route should exist."""
        path = backend_path / "routes" / "auto_sensors.py"
        assert path.exists(), f"auto_sensors route not found at {path}"

    def test_auto_sensors_route_syntax(self):
        """auto_sensors route should have valid Python syntax."""
        path = backend_path / "routes" / "auto_sensors.py"
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"Syntax error in auto_sensors route: {e}")


class TestElementWatcherSyntax:
    """Verify element_watcher module syntax and structure."""

    def test_element_watcher_file_exists(self):
        """element_watcher.py should exist."""
        path = backend_path / "core" / "element_watcher.py"
        assert path.exists(), f"element_watcher.py not found at {path}"

    def test_element_watcher_syntax_valid(self):
        """element_watcher.py should have valid Python syntax."""
        path = backend_path / "core" / "element_watcher.py"
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"Syntax error in element_watcher.py: {e}")

    def test_element_watcher_imports(self):
        """element_watcher.py should be importable."""
        from core.element_watcher import (
            ElementWatcher,
            ElementWatcherManager,
            ElementSignature,
            get_element_watcher_manager,
        )
        assert ElementWatcher is not None
        assert ElementWatcherManager is not None
        assert ElementSignature is not None

    def test_element_watcher_route_exists(self):
        """element_watchers route should exist."""
        path = backend_path / "routes" / "element_watchers.py"
        assert path.exists(), f"element_watchers route not found at {path}"

    def test_element_watcher_route_syntax(self):
        """element_watchers route should have valid Python syntax."""
        path = backend_path / "routes" / "element_watchers.py"
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"Syntax error in element_watchers route: {e}")


class TestRegionCaptureSyntax:
    """Verify region_capture module syntax and structure."""

    def test_region_capture_file_exists(self):
        """region_capture.py should exist."""
        path = backend_path / "core" / "region_capture.py"
        assert path.exists(), f"region_capture.py not found at {path}"

    def test_region_capture_syntax_valid(self):
        """region_capture.py should have valid Python syntax."""
        path = backend_path / "core" / "region_capture.py"
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"Syntax error in region_capture.py: {e}")

    def test_region_capture_imports(self):
        """region_capture.py should be importable."""
        from core.region_capture import (
            CapturedRegion,
            RegionCaptureManager,
            RegionBounds,
            get_region_capture_manager,
        )
        assert CapturedRegion is not None
        assert RegionCaptureManager is not None
        assert RegionBounds is not None

    def test_region_capture_route_exists(self):
        """region_capture route should exist."""
        path = backend_path / "routes" / "region_capture.py"
        assert path.exists(), f"region_capture route not found at {path}"

    def test_region_capture_route_syntax(self):
        """region_capture route should have valid Python syntax."""
        path = backend_path / "routes" / "region_capture.py"
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"Syntax error in region_capture route: {e}")


class TestAppScreenInference:
    """Test app screen type inference logic."""

    def test_infer_screen_type_home(self):
        """Home/main activities should be detected."""
        from services.auto_sensors import infer_screen_type, ScreenType
        # infer_screen_type works on activity names, not package names
        assert infer_screen_type("MainActivity") == ScreenType.HOME
        assert infer_screen_type("HomeActivity") == ScreenType.HOME
        assert infer_screen_type("LauncherActivity") == ScreenType.HOME

    def test_infer_screen_type_settings(self):
        """Settings activities should be detected."""
        from services.auto_sensors import infer_screen_type, ScreenType
        assert infer_screen_type("SettingsActivity") == ScreenType.SETTINGS
        assert infer_screen_type("PreferencesActivity") == ScreenType.SETTINGS

    def test_infer_screen_type_player(self):
        """Player/media activities should be detected."""
        from services.auto_sensors import infer_screen_type, ScreenType
        assert infer_screen_type("PlayerActivity") == ScreenType.PLAYER
        assert infer_screen_type("VideoPlayerActivity") == ScreenType.PLAYER
        assert infer_screen_type("ExoPlayerActivity") == ScreenType.PLAYER

    def test_infer_screen_type_search(self):
        """Search activities should be detected."""
        from services.auto_sensors import infer_screen_type, ScreenType
        assert infer_screen_type("SearchActivity") == ScreenType.SEARCH
        assert infer_screen_type("BrowseActivity") == ScreenType.SEARCH

    def test_infer_screen_type_unknown(self):
        """Unknown activities should return UNKNOWN."""
        from services.auto_sensors import infer_screen_type, ScreenType
        assert infer_screen_type("SomeRandomActivity") == ScreenType.UNKNOWN
        assert infer_screen_type("") == ScreenType.UNKNOWN


class TestAppLabelParsing:
    """Test package name to friendly name parsing."""

    def test_parse_simple_package(self):
        """Simple package names should be parsed from last segment."""
        from services.auto_sensors import parse_app_label
        # Last segment, capitalized
        assert parse_app_label("com.example.myapp") == "Myapp"

    def test_parse_known_package(self):
        """Known packages should return their friendly names."""
        from services.auto_sensors import parse_app_label
        # YouTube has specific capitalization in KNOWN_APPS
        assert parse_app_label("com.google.android.youtube") == "YouTube"
        assert parse_app_label("com.netflix.mediaclient") == "Netflix"
        assert parse_app_label("com.spotify.music") == "Spotify"

    def test_parse_unknown_package(self):
        """Unknown packages should extract from last segment."""
        from services.auto_sensors import parse_app_label
        result = parse_app_label("com.unknown.testapp")
        assert result == "Testapp"


class TestElementSignature:
    """Test element signature matching."""

    def test_signature_creation(self):
        """Signatures should be created with dataclass fields."""
        from core.element_watcher import ElementSignature

        sig = ElementSignature(
            resource_id="com.example:id/button",
            text="Hello World",
            content_desc="",
            class_name="android.widget.Button",
            bounds={"x": 100, "y": 200, "width": 50, "height": 30},
        )
        assert sig.text == "Hello World"
        assert sig.resource_id == "com.example:id/button"
        assert sig.class_name == "android.widget.Button"
        assert sig.bounds["x"] == 100
        assert sig.bounds["y"] == 200

    def test_signature_matches_by_resource_id(self):
        """Resource ID match should succeed."""
        from core.element_watcher import ElementSignature

        sig = ElementSignature(
            resource_id="com.example:id/button",
            text="",
            content_desc="",
            class_name="",
            bounds=None,
        )

        element = {
            "resource_id": "com.example:id/button",
            "text": "Different text",
        }

        assert sig.matches(element), "Resource ID match should succeed"

    def test_signature_matches_by_text(self):
        """Text match should succeed when resource_id empty."""
        from core.element_watcher import ElementSignature

        sig = ElementSignature(
            resource_id="",
            text="Click Me",
            content_desc="",
            class_name="",
            bounds=None,
        )

        element = {
            "text": "Click Me",
        }

        assert sig.matches(element), "Text match should succeed"

    def test_signature_no_match(self):
        """Different elements should not match."""
        from core.element_watcher import ElementSignature

        sig = ElementSignature(
            resource_id="com.example:id/button1",
            text="Hello",
            content_desc="",
            class_name="Button",
            bounds=None,
        )

        element = {
            "resource_id": "com.example:id/button2",
            "text": "Goodbye",
            "class": "TextView",
        }

        assert not sig.matches(element), "Different elements should not match"


class TestRegionBounds:
    """Test region bounds dataclass."""

    def test_bounds_to_dict(self):
        """Bounds should serialize to dict."""
        from core.region_capture import RegionBounds

        bounds = RegionBounds(x=10, y=20, width=100, height=50)
        d = bounds.to_dict()

        assert d["x"] == 10
        assert d["y"] == 20
        assert d["width"] == 100
        assert d["height"] == 50

    def test_bounds_from_dict(self):
        """Bounds should deserialize from dict."""
        from core.region_capture import RegionBounds

        d = {"x": 10, "y": 20, "width": 100, "height": 50}
        bounds = RegionBounds.from_dict(d)

        assert bounds.x == 10
        assert bounds.y == 20
        assert bounds.width == 100
        assert bounds.height == 50


class TestCapturedRegion:
    """Test captured region dataclass."""

    def test_region_to_dict(self):
        """Region should serialize to dict."""
        from core.region_capture import CapturedRegion, RegionBounds

        region = CapturedRegion(
            id="test_region",
            device_id="192.168.1.100:5555",
            name="Test Region",
            bounds=RegionBounds(x=0, y=0, width=100, height=100),
            linked_sensors=["sensor.test"],
            jpeg_quality=80,
        )

        d = region.to_dict()
        assert d["id"] == "test_region"
        assert d["name"] == "Test Region"
        assert d["linked_sensors"] == ["sensor.test"]
        assert d["jpeg_quality"] == 80

    def test_region_from_dict(self):
        """Region should deserialize from dict."""
        from core.region_capture import CapturedRegion

        d = {
            "id": "test_region",
            "device_id": "192.168.1.100:5555",
            "name": "Test Region",
            "bounds": {"x": 0, "y": 0, "width": 100, "height": 100},
            "linked_sensors": ["sensor.test"],
            "jpeg_quality": 80,
        }

        region = CapturedRegion.from_dict(d)
        assert region.id == "test_region"
        assert region.name == "Test Region"
        assert region.linked_sensors == ["sensor.test"]


class TestMainIntegration:
    """Test that main.py integrates new features."""

    def test_main_imports_auto_sensors(self):
        """main.py should import auto_sensors."""
        path = backend_path / "main.py"
        source = path.read_text(encoding="utf-8")
        assert "auto_sensors" in source, "main.py should import auto_sensors"

    def test_main_imports_element_watcher(self):
        """main.py should import element_watcher."""
        path = backend_path / "main.py"
        source = path.read_text(encoding="utf-8")
        assert "element_watcher" in source, "main.py should import element_watcher"

    def test_main_imports_region_capture(self):
        """main.py should import region_capture."""
        path = backend_path / "main.py"
        source = path.read_text(encoding="utf-8")
        assert "region_capture" in source, "main.py should import region_capture"

    def test_main_registers_routes(self):
        """main.py should register new routers."""
        path = backend_path / "main.py"
        source = path.read_text(encoding="utf-8")
        # Check for router includes
        assert "auto_sensors_router" in source or "auto_sensors.router" in source
        assert "element_watchers_router" in source or "element_watchers.router" in source
        assert "region_capture_router" in source or "region_capture.router" in source
