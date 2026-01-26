"""
Tests for v0.4.0-beta.3 bug fixes
Verifies all modified files are syntactically correct and importable
"""
import pytest
import ast
import sys
import os

# Add backend to path
backend_path = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, backend_path)


class TestPythonSyntax:
    """Verify Python files have valid syntax"""

    @pytest.mark.parametrize("filepath", [
        "backend/core/adb/adb_network.py",
        "backend/core/adb/adb_bridge.py",
        "backend/core/flows/flow_executor.py",
        "backend/main.py",
        "backend/routes/services.py",
        "backend/services/connection_monitor.py",
        "backend/utils/error_handler.py",
        "backend/config/__init__.py",
        "backend/config/defaults.py",
    ])
    def test_python_syntax(self, filepath):
        """Check Python file has valid syntax"""
        full_path = os.path.join(os.path.dirname(__file__), '..', filepath)
        with open(full_path, 'r', encoding='utf-8') as f:
            source = f.read()
        ast.parse(source)  # Raises SyntaxError if invalid


class TestConfigModule:
    """Test new centralized config module"""

    def test_config_import(self):
        """Config module should import without errors"""
        from config import Defaults, AppDefaults
        assert Defaults is not None
        assert isinstance(Defaults, AppDefaults)

    def test_config_values(self):
        """Config should have expected default values"""
        from config import Defaults
        assert Defaults.SERVER_PORT == 8082
        assert Defaults.MQTT_PORT == 1883
        assert Defaults.API_TIMEOUT == 30
        assert Defaults.SENSOR_UPDATE_INTERVAL == 30
        assert Defaults.CONNECTION_CHECK_INTERVAL == 30


class TestErrorHandler:
    """Test error handler improvements"""

    def test_success_response_with_data(self):
        """Test create_success_response with data"""
        from utils.error_handler import create_success_response

        response = create_success_response(data={"test": 1})
        assert response["success"] == True
        assert response["data"]["test"] == 1
        assert "message" not in response

    def test_success_response_with_message(self):
        """Test create_success_response with message"""
        from utils.error_handler import create_success_response

        response = create_success_response(message="OK")
        assert response["success"] == True
        assert response["message"] == "OK"
        assert "data" not in response

    def test_success_response_with_both(self):
        """Test create_success_response with data and message"""
        from utils.error_handler import create_success_response

        response = create_success_response(data={"id": 123}, message="Created")
        assert response["success"] == True
        assert response["data"]["id"] == 123
        assert response["message"] == "Created"

    def test_error_response(self):
        """Test create_error_response exists and works"""
        from utils.error_handler import create_error_response

        response = create_error_response(ValueError("test error"))
        assert response.status_code == 500
        # Response body should have success=False


class TestJavaScriptSyntax:
    """Verify JavaScript files have valid syntax using basic checks"""

    @pytest.mark.parametrize("filepath", [
        "frontend/www/js/modules/device-manager.js",
        "frontend/www/js/modules/flow-wizard.js",
        "frontend/www/js/modules/flow-wizard-step2.js",
        "frontend/www/js/modules/flow-wizard-step3.js",
        "frontend/www/js/modules/smart-suggestions.js",
        "frontend/www/js/modules/gesture-handler.js",
        "frontend/www/js/modules/stream-manager.js",
        "frontend/www/js/modules/element-tree.js",
        "frontend/www/js/modules/debug.js",
        "frontend/www/js/init.js",
    ])
    def test_js_file_exists_and_readable(self, filepath):
        """Check JS file exists and is readable"""
        full_path = os.path.join(os.path.dirname(__file__), '..', filepath)
        assert os.path.exists(full_path), f"File not found: {filepath}"

        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Basic syntax checks
        assert len(content) > 0, f"File is empty: {filepath}"

        # Check for balanced braces (simple heuristic)
        open_braces = content.count('{')
        close_braces = content.count('}')
        assert open_braces == close_braces, f"Unbalanced braces in {filepath}: {open_braces} open, {close_braces} close"

        # Check for balanced parentheses
        open_parens = content.count('(')
        close_parens = content.count(')')
        assert open_parens == close_parens, f"Unbalanced parentheses in {filepath}: {open_parens} open, {close_parens} close"


class TestDebugModule:
    """Test the new debug utility module"""

    def test_debug_js_exports(self):
        """Verify debug.js has expected exports"""
        filepath = os.path.join(os.path.dirname(__file__), '..',
                               'frontend/www/js/modules/debug.js')
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for expected exports
        assert 'export function debug' in content
        assert 'export function debugWarn' in content
        assert 'export function debugError' in content
        assert 'export function enableDebug' in content
        assert 'export function disableDebug' in content


class TestBeta3Fixes:
    """Verify specific bug fixes are in place"""

    def test_socket_cleanup_in_adb_network(self):
        """Verify socket cleanup pattern exists in adb_network.py"""
        filepath = os.path.join(os.path.dirname(__file__), '..',
                               'backend/core/adb/adb_network.py')
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for try-finally pattern
        assert 'finally:' in content
        assert 'sock.close()' in content

    def test_no_bare_excepts_in_flow_executor(self):
        """Verify no bare except clauses in flow_executor.py"""
        filepath = os.path.join(os.path.dirname(__file__), '..',
                               'backend/core/flows/flow_executor.py')
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Check for bare except (just "except:" without Exception)
            if stripped == 'except:':
                pytest.fail(f"Bare except found at line {i}: {line.strip()}")

    def test_no_bare_excepts_in_adb_bridge(self):
        """Verify no bare except clauses in adb_bridge.py"""
        filepath = os.path.join(os.path.dirname(__file__), '..',
                               'backend/core/adb/adb_bridge.py')
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped == 'except:':
                pytest.fail(f"Bare except found at line {i}: {line.strip()}")

    def test_background_tasks_tracking(self):
        """Verify background tasks list exists in main.py"""
        filepath = os.path.join(os.path.dirname(__file__), '..',
                               'backend/main.py')
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        assert '_background_tasks' in content
        assert '_background_tasks.append' in content

    def test_gesture_handler_null_check(self):
        """Verify null check exists in gesture-handler.js"""
        filepath = os.path.join(os.path.dirname(__file__), '..',
                               'frontend/www/js/modules/gesture-handler.js')
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        assert 'if (!container)' in content

    def test_abort_controller_in_stream_manager(self):
        """Verify AbortController usage in stream-manager.js"""
        filepath = os.path.join(os.path.dirname(__file__), '..',
                               'frontend/www/js/modules/stream-manager.js')
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        assert 'AbortController' in content
        assert 'abortController.abort()' in content

    def test_element_tree_race_condition_fix(self):
        """Verify race condition prevention in element-tree.js"""
        filepath = os.path.join(os.path.dirname(__file__), '..',
                               'frontend/www/js/modules/element-tree.js')
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        assert '_isUpdating' in content
        assert '_pendingElements' in content
