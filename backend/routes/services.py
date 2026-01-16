"""
Service Control API Routes

Provides endpoints to control backend services:
- ML Training Server (start/stop/status)
- MQTT Broker (status)
- Main Server (status)

Used by:
- Web UI (Services page)
- Android app (Settings → Service Control)
"""

import logging
import os
import subprocess
import signal
import sys
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from routes.settings import load_settings, save_settings

logger = logging.getLogger(__name__)


def _save_ml_auto_start(enabled: bool):
    """Save ML server auto-start preference to settings"""
    try:
        settings = load_settings()
        settings["ml_server_auto_start"] = enabled
        save_settings(settings)
        logger.info(f"[Services] ML auto-start preference saved: {enabled}")
    except Exception as e:
        logger.warning(f"[Services] Failed to save ML auto-start preference: {e}")

router = APIRouter(prefix="/api/services", tags=["services"])

# Track subprocess for ML training server (started via Start button)
ml_training_process: Optional[subprocess.Popen] = None
ml_training_log_file = None  # Track log file for proper cleanup

# Track in-process ML server (auto-started on server startup)
# Set by main.py when ML server starts as a thread
ml_training_thread = None  # threading.Thread reference
ml_training_instance = None  # MLTrainingServer instance


class ServiceStatus(BaseModel):
    """Status of a single service"""

    name: str
    running: bool
    pid: Optional[int] = None
    uptime: Optional[str] = None
    details: Optional[str] = None
    docker_mode: Optional[bool] = (
        None  # True if running as Docker container (Start/Stop disabled)
    )
    mode: Optional[str] = None  # For ML: disabled, local, or remote


class AllServicesStatus(BaseModel):
    """Status of all services"""

    mqtt: ServiceStatus
    server: ServiceStatus
    ml_training: ServiceStatus


class ServiceCommand(BaseModel):
    """Command to control a service"""

    action: str  # start, stop, restart


def check_mqtt_status() -> ServiceStatus:
    """Check if MQTT broker is reachable"""
    try:
        import paho.mqtt.client as mqtt

        broker = os.environ.get("MQTT_BROKER", "localhost")
        port = int(os.environ.get("MQTT_PORT", "1883"))
        username = os.environ.get("MQTT_USERNAME", "")
        password = os.environ.get("MQTT_PASSWORD", "")

        # Compatible with both paho-mqtt 1.x and 2.x
        try:
            # paho-mqtt 2.x
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            # paho-mqtt 1.x (used with aiomqtt)
            client = mqtt.Client()

        # Set credentials if provided
        if username:
            client.username_pw_set(username, password)

        client.connect(broker, port, keepalive=5)
        client.disconnect()

        return ServiceStatus(
            name="MQTT Broker", running=True, details=f"Connected to {broker}:{port}"
        )
    except Exception as e:
        return ServiceStatus(name="MQTT Broker", running=False, details=str(e))


def _get_ml_training_mode() -> str:
    """Get the configured ML training mode from env/settings"""
    # Check environment variable first
    mode = os.environ.get("ML_TRAINING_MODE", "").lower()
    if mode in ("local", "remote", "disabled"):
        return mode

    # Check saved settings for auto-start preference
    try:
        settings = load_settings()
        if settings.get("ml_server_auto_start", False):
            return "local"
    except Exception:
        pass

    return "disabled"


def check_ml_training_status() -> ServiceStatus:
    """Check ML training server status"""
    global ml_training_process, ml_training_thread, ml_training_instance

    # Get configured mode
    mode = _get_ml_training_mode()

    # Check subprocess first (started via Start button)
    if ml_training_process is not None:
        poll = ml_training_process.poll()
        if poll is None:
            # Process is running
            return ServiceStatus(
                name="ML Training Server",
                running=True,
                pid=ml_training_process.pid,
                details="Running locally (subprocess)",
                mode="local",
            )
        else:
            # Process exited
            ml_training_process = None

    # Check in-process ML server (auto-started on server startup as thread)
    if ml_training_thread is not None and ml_training_thread.is_alive():
        return ServiceStatus(
            name="ML Training Server",
            running=True,
            pid=None,
            details="Running locally (auto-started)",
            mode="local",
        )

    # Check if running as Docker container (ML_SERVER_ENABLED env var)
    ml_server_enabled = os.environ.get("ML_SERVER_ENABLED", "").lower() == "true"
    if ml_server_enabled:
        # In Docker Compose mode - ML container should be running
        # Check MQTT connection as proxy for ML server availability
        mqtt_status = check_mqtt_status()
        if mqtt_status.running:
            return ServiceStatus(
                name="ML Training Server",
                running=True,
                pid=None,
                details="Running via Docker container",
                docker_mode=True,  # Start/Stop disabled in Docker mode
                mode="local",
            )
        else:
            return ServiceStatus(
                name="ML Training Server",
                running=False,
                details="Docker container mode but MQTT disconnected",
                docker_mode=True,  # Start/Stop disabled in Docker mode
                mode="local",
            )

    # Check for remote mode
    if mode == "remote":
        remote_host = os.environ.get("ML_REMOTE_HOST", "")
        if remote_host:
            return ServiceStatus(
                name="ML Training Server",
                running=True,  # Assume remote is running
                details=f"Remote: {remote_host}",
                mode="remote",
            )
        else:
            return ServiceStatus(
                name="ML Training Server",
                running=False,
                details="Remote mode but no host configured",
                mode="remote",
            )

    return ServiceStatus(
        name="ML Training Server",
        running=False,
        details="Not running",
        mode=mode,  # disabled or local (but not started)
    )


def check_server_status() -> ServiceStatus:
    """Check main server status (always running if we can respond)"""
    return ServiceStatus(
        name="Main Server",
        running=True,
        pid=os.getpid(),
        details="FastAPI server running",
    )


@router.get("/status", response_model=AllServicesStatus)
async def get_all_services_status():
    """Get status of all backend services"""
    return AllServicesStatus(
        mqtt=check_mqtt_status(),
        server=check_server_status(),
        ml_training=check_ml_training_status(),
    )


@router.get("/mqtt/status", response_model=ServiceStatus)
async def get_mqtt_status():
    """Get MQTT broker status"""
    return check_mqtt_status()


@router.get("/ml/status", response_model=ServiceStatus)
async def get_ml_status():
    """Get ML training server status"""
    return check_ml_training_status()


@router.post("/ml/start", response_model=ServiceStatus)
async def start_ml_training():
    """Start the ML training server"""
    global ml_training_process, ml_training_log_file

    # Check if already running
    if ml_training_process is not None:
        poll = ml_training_process.poll()
        if poll is None:
            return ServiceStatus(
                name="ML Training Server",
                running=True,
                pid=ml_training_process.pid,
                details="Already running",
            )
        else:
            # Process exited, clear it
            ml_training_process = None

    try:
        broker = os.environ.get("MQTT_BROKER", "localhost")
        port = os.environ.get("MQTT_PORT", "1883")
        username = os.environ.get("MQTT_USERNAME", "")
        password = os.environ.get("MQTT_PASSWORD", "")

        # Start ML training server as subprocess
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ml_script = os.path.join(backend_dir, "ml_components", "ml_training_server.py")

        # Check if script exists
        if not os.path.exists(ml_script):
            raise HTTPException(
                status_code=500, detail=f"ML script not found: {ml_script}"
            )

        # Build command with optional auth
        cmd = [sys.executable, ml_script, "--broker", broker, "--port", str(port)]
        if username:
            cmd.extend(["--username", username])
        if password:
            cmd.extend(["--password", password])

        # Log file for debugging - store in global for cleanup
        log_dir = os.path.join(backend_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        ml_training_log_file = open(os.path.join(log_dir, "ml_training.log"), "a")

        startup_failed = False
        try:
            ml_training_process = subprocess.Popen(
                cmd,
                stdout=ml_training_log_file,
                stderr=subprocess.STDOUT,
                cwd=backend_dir,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )

            # Give it a moment to start and check if it's still running
            import time

            time.sleep(1)

            poll = ml_training_process.poll()
            if poll is not None:
                startup_failed = True
                # Process already exited - read log for error
                with open(os.path.join(log_dir, "ml_training.log"), "r") as f:
                    lines = f.readlines()
                    last_lines = "".join(lines[-20:]) if lines else "No output"
                raise HTTPException(
                    status_code=500,
                    detail=f"ML server exited immediately (code {poll}). Check logs: {last_lines[-500:]}",
                )

            logger.info(f"Started ML training server with PID {ml_training_process.pid}")
        except Exception:
            startup_failed = True
            raise
        finally:
            if startup_failed:
                # Clean up on startup failure
                if ml_training_log_file:
                    ml_training_log_file.close()
                    ml_training_log_file = None
                if ml_training_process:
                    try:
                        ml_training_process.terminate()
                        ml_training_process.wait(timeout=2)
                    except Exception:
                        try:
                            ml_training_process.kill()
                        except Exception:
                            pass
                    ml_training_process = None

        # Save preference so server auto-starts on next app restart
        _save_ml_auto_start(True)

        return ServiceStatus(
            name="ML Training Server",
            running=True,
            pid=ml_training_process.pid,
            details="Started successfully",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start ML training server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ml/stop", response_model=ServiceStatus)
async def stop_ml_training():
    """Stop the ML training server"""
    global ml_training_process, ml_training_log_file

    if ml_training_process is None:
        return ServiceStatus(
            name="ML Training Server", running=False, details="Not running"
        )

    try:
        # Send SIGTERM for graceful shutdown
        ml_training_process.terminate()

        # Wait up to 5 seconds for graceful shutdown
        try:
            ml_training_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Force kill if still running
            ml_training_process.kill()
            ml_training_process.wait()

        pid = ml_training_process.pid
        ml_training_process = None

        # Close the log file handle
        if ml_training_log_file is not None:
            try:
                ml_training_log_file.close()
            except Exception:
                pass
            ml_training_log_file = None

        logger.info(f"Stopped ML training server (PID {pid})")

        # Save preference so server stays stopped on next app restart
        _save_ml_auto_start(False)

        return ServiceStatus(
            name="ML Training Server", running=False, details=f"Stopped (was PID {pid})"
        )
    except Exception as e:
        logger.error(f"Failed to stop ML training server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ml/restart", response_model=ServiceStatus)
async def restart_ml_training():
    """Restart the ML training server"""
    await stop_ml_training()
    return await start_ml_training()
