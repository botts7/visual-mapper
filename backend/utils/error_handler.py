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
