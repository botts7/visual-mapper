"""
Centralized Error Handling Module for Visual Mapper

Provides consistent error responses, logging, and user-friendly messages.
"""

import logging
import traceback
from typing import Dict, Any, Optional
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse

# Configure logging
logger = logging.getLogger("visual_mapper")


# =============================================================================
# ERROR HINTS - User-friendly troubleshooting suggestions
# =============================================================================

ERROR_HINTS = {
    "device_locked": {
        "message": "Device is locked",
        "hint": "Enable AUTO_UNLOCK in device settings with your PIN/password, or manually unlock the device.",
        "docs": "/docs/auto-unlock"
    },
    "device_offline": {
        "message": "Device not connected",
        "hint": "Check that the device is on the same network and has WiFi debugging enabled. Try reconnecting from the Devices page.",
        "docs": "/docs/connection"
    },
    "adb_connection": {
        "message": "ADB connection failed",
        "hint": "Restart ADB on the device: Settings > Developer Options > Revoke USB debugging authorizations, then re-enable Wireless debugging.",
        "docs": "/docs/adb-troubleshooting"
    },
    "element_not_found": {
        "message": "Element not found on screen",
        "hint": "The app UI may have changed. Re-record this step in the Flow Wizard, or add a longer wait before this step.",
        "docs": "/docs/flow-recording"
    },
    "navigation_failed": {
        "message": "Failed to navigate to expected screen",
        "hint": "The app may have updated or shown an unexpected dialog. Check if there's a popup blocking navigation.",
        "docs": "/docs/navigation"
    },
    "timeout": {
        "message": "Flow execution timed out",
        "hint": "Increase the flow timeout in flow settings, or optimize steps to run faster.",
        "docs": "/docs/flow-settings"
    },
    "sensor_extraction": {
        "message": "Failed to extract sensor value",
        "hint": "The element text format may have changed. Edit the sensor and update the extraction rule.",
        "docs": "/docs/sensors"
    },
    "regex_invalid": {
        "message": "Invalid regex pattern",
        "hint": "Check your regex syntax. Common issues: unescaped special characters (use \\. for literal dot), unmatched parentheses.",
        "docs": "/docs/extraction-rules"
    },
    "app_not_found": {
        "message": "App not installed or package name incorrect",
        "hint": "Verify the app is installed on the device. Check the package name in the flow settings matches the installed app.",
        "docs": "/docs/app-setup"
    },
    "screenshot_failed": {
        "message": "Failed to capture screenshot",
        "hint": "The device may be busy or the screen may be off. Try waking the device first or adding a short wait before this step.",
        "docs": "/docs/screenshots"
    },
    "mqtt_publish_failed": {
        "message": "Failed to publish sensor value to MQTT",
        "hint": "Check your MQTT broker connection settings. Ensure the broker is running and accessible.",
        "docs": "/docs/mqtt-setup"
    },
    "permission_denied": {
        "message": "Permission denied on device",
        "hint": "The app may need additional permissions. Check the device and grant any requested permissions.",
        "docs": "/docs/permissions"
    },
}


def get_error_with_hint(error_type: str, original_message: str = "") -> dict:
    """
    Get error message with troubleshooting hint.

    Args:
        error_type: Key from ERROR_HINTS dictionary
        original_message: Original error message to include

    Returns:
        Dict with error, hint, and optional docs link
    """
    hint_info = ERROR_HINTS.get(error_type, {})
    return {
        "error": original_message or hint_info.get("message", "Unknown error"),
        "hint": hint_info.get("hint", ""),
        "docs": hint_info.get("docs", "")
    }


def classify_error(error_message: str) -> str:
    """
    Classify an error message to determine the appropriate hint type.

    Args:
        error_message: The error message to classify

    Returns:
        Error type key for ERROR_HINTS lookup
    """
    msg = error_message.lower()

    # Device connection errors
    if "locked" in msg or "lock screen" in msg:
        return "device_locked"
    if "device" in msg and ("not found" in msg or "offline" in msg or "disconnected" in msg):
        return "device_offline"
    if "adb" in msg or "connection refused" in msg or "connection reset" in msg:
        return "adb_connection"

    # Element finding errors
    if "element" in msg and ("not found" in msg or "could not find" in msg or "no match" in msg):
        return "element_not_found"

    # Navigation errors
    if "navigation" in msg or "navigate" in msg or "wrong screen" in msg:
        return "navigation_failed"

    # Timeout errors
    if "timeout" in msg or "timed out" in msg:
        return "timeout"

    # Extraction errors
    if "extract" in msg or "extraction" in msg:
        return "sensor_extraction"

    # Regex errors
    if "regex" in msg or "pattern" in msg or "invalid regex" in msg:
        return "regex_invalid"

    # App errors
    if "app" in msg and ("not found" in msg or "not installed" in msg):
        return "app_not_found"

    # Screenshot errors
    if "screenshot" in msg:
        return "screenshot_failed"

    # MQTT errors
    if "mqtt" in msg or "publish" in msg:
        return "mqtt_publish_failed"

    # Permission errors
    if "permission" in msg or "denied" in msg:
        return "permission_denied"

    # Default - no specific hint
    return ""


class VisualMapperError(Exception):
    """Base exception for all Visual Mapper errors"""

    def __init__(
        self,
        message: str,
        code: str = "UNKNOWN_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class DeviceNotFoundError(VisualMapperError):
    """Raised when Android device is not found or disconnected"""

    def __init__(self, device_id: Optional[str] = None):
        message = (
            f"Device '{device_id}' not found or disconnected"
            if device_id
            else "No Android devices found"
        )
        super().__init__(
            message, code="DEVICE_NOT_FOUND", details={"device_id": device_id}
        )


class ADBConnectionError(VisualMapperError):
    """Raised when ADB connection fails"""

    def __init__(self, message: str, device_id: Optional[str] = None):
        super().__init__(
            message, code="ADB_CONNECTION_ERROR", details={"device_id": device_id}
        )


class ScreenshotCaptureError(VisualMapperError):
    """Raised when screenshot capture fails"""

    def __init__(self, message: str, device_id: Optional[str] = None):
        super().__init__(
            message, code="SCREENSHOT_CAPTURE_ERROR", details={"device_id": device_id}
        )


class SensorNotFoundError(VisualMapperError):
    """Raised when sensor is not found"""

    def __init__(self, sensor_id: str):
        super().__init__(
            f"Sensor '{sensor_id}' not found",
            code="SENSOR_NOT_FOUND",
            details={"sensor_id": sensor_id},
        )


class SensorValidationError(VisualMapperError):
    """Raised when sensor validation fails"""

    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(
            message, code="SENSOR_VALIDATION_ERROR", details={"field": field}
        )


class MQTTConnectionError(VisualMapperError):
    """Raised when MQTT connection fails"""

    def __init__(self, message: str, broker: Optional[str] = None):
        super().__init__(
            message, code="MQTT_CONNECTION_ERROR", details={"broker": broker}
        )


class TextExtractionError(VisualMapperError):
    """Raised when text extraction fails"""

    def __init__(self, message: str, method: Optional[str] = None):
        super().__init__(
            message, code="TEXT_EXTRACTION_ERROR", details={"method": method}
        )


class ActionNotFoundError(VisualMapperError):
    """Raised when action is not found"""

    def __init__(self, action_id: str):
        super().__init__(
            f"Action '{action_id}' not found",
            code="ACTION_NOT_FOUND",
            details={"action_id": action_id},
        )


class ActionValidationError(VisualMapperError):
    """Raised when action validation fails"""

    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(
            message, code="ACTION_VALIDATION_ERROR", details={"field": field}
        )


class ActionExecutionError(VisualMapperError):
    """Raised when action execution fails"""

    def __init__(self, message: str, action_type: Optional[str] = None):
        super().__init__(
            message, code="ACTION_EXECUTION_ERROR", details={"action_type": action_type}
        )


def create_error_response(
    error: Exception,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    include_traceback: bool = False,
) -> JSONResponse:
    """
    Create a standardized error response

    Args:
        error: The exception that occurred
        status_code: HTTP status code
        include_traceback: Include full traceback in response (debug only)

    Returns:
        JSONResponse with error details
    """
    # Build error response
    error_response = {
        "success": False,
        "error": {"message": str(error), "type": error.__class__.__name__},
    }

    # Add details for VisualMapperError
    if isinstance(error, VisualMapperError):
        error_response["error"]["code"] = error.code
        error_response["error"]["details"] = error.details

    # Add traceback if requested (debug mode only)
    if include_traceback:
        error_response["error"]["traceback"] = traceback.format_exc()

    # Log the error
    logger.error(f"{error.__class__.__name__}: {error}", exc_info=True)

    return JSONResponse(status_code=status_code, content=error_response)


def handle_api_error(error: Exception) -> JSONResponse:
    """
    Handle API errors with appropriate status codes

    Args:
        error: The exception to handle

    Returns:
        JSONResponse with appropriate status code
    """
    # Map exceptions to status codes
    if isinstance(error, DeviceNotFoundError):
        return create_error_response(error, status.HTTP_404_NOT_FOUND)

    elif isinstance(error, SensorNotFoundError):
        return create_error_response(error, status.HTTP_404_NOT_FOUND)

    elif isinstance(error, (SensorValidationError, ValueError)):
        return create_error_response(error, status.HTTP_400_BAD_REQUEST)

    elif isinstance(error, ADBConnectionError):
        return create_error_response(error, status.HTTP_503_SERVICE_UNAVAILABLE)

    elif isinstance(error, MQTTConnectionError):
        return create_error_response(error, status.HTTP_503_SERVICE_UNAVAILABLE)

    elif isinstance(error, (ScreenshotCaptureError, TextExtractionError)):
        return create_error_response(error, status.HTTP_500_INTERNAL_SERVER_ERROR)

    else:
        # Generic error
        return create_error_response(error, status.HTTP_500_INTERNAL_SERVER_ERROR)


def get_user_friendly_message(error: Exception) -> str:
    """
    Get a user-friendly error message for frontend display

    Args:
        error: The exception

    Returns:
        User-friendly error message
    """
    if isinstance(error, DeviceNotFoundError):
        return "Android device not found. Please check the device is connected and ADB is enabled."

    elif isinstance(error, ADBConnectionError):
        return "Could not connect to Android device via ADB. Please check the connection and try again."

    elif isinstance(error, ScreenshotCaptureError):
        return "Failed to capture screenshot. Please check the device connection."

    elif isinstance(error, SensorNotFoundError):
        return f"Sensor not found. It may have been deleted."

    elif isinstance(error, SensorValidationError):
        return f"Sensor configuration is invalid: {error.message}"

    elif isinstance(error, MQTTConnectionError):
        return "Could not connect to MQTT broker. Please check the broker settings."

    elif isinstance(error, TextExtractionError):
        return f"Failed to extract text: {error.message}"

    else:
        return f"An unexpected error occurred: {str(error)}"


def create_success_response(
    data: Any = None,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a standardized success response

    Args:
        data: The response data payload
        message: Optional success message

    Returns:
        Dict with success response format: {success: True, data: ..., message: ...}

    Usage:
        return create_success_response(data={"sensors": sensors})
        return create_success_response(message="Sensor created")
        return create_success_response(data=sensor, message="Sensor updated")
    """
    response = {"success": True}

    if data is not None:
        response["data"] = data

    if message is not None:
        response["message"] = message

    return response


# Decorator for error handling
def handle_errors(func):
    """
    Decorator to wrap functions with error handling

    Usage:
        @handle_errors
        async def my_endpoint():
            # code that might raise errors
            pass
    """

    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            return handle_api_error(e)

    return wrapper


# Context manager for error handling
class ErrorContext:
    """
    Context manager for error handling

    Usage:
        with ErrorContext("capturing screenshot"):
            # code that might fail
            pass
    """

    def __init__(self, operation: str, raise_as: type = VisualMapperError):
        self.operation = operation
        self.raise_as = raise_as

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            logger.error(f"Error during {self.operation}: {exc_val}", exc_info=True)
            # Re-raise as VisualMapperError
            if not isinstance(exc_val, VisualMapperError):
                raise self.raise_as(f"Failed {self.operation}: {exc_val}") from exc_val
        return False  # Don't suppress exception
