"""
Performance & Diagnostics Routes - System Monitoring and Benchmarking

Provides performance metrics, cache statistics, and diagnostic tools.
Includes both aggregate metrics and detailed benchmarking capabilities.
"""

from fastapi import APIRouter, HTTPException
import logging
import time
import subprocess
import platform
from routes import get_deps
from utils.version import APP_VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["performance", "diagnostics"])

# Global streaming metrics (updated by streaming endpoints)
streaming_metrics = {}


# =============================================================================
# PERFORMANCE METRICS ENDPOINTS
# =============================================================================


@router.get("/performance/metrics")
async def get_performance_metrics():
    """
    Get comprehensive performance metrics for monitoring and optimization.

    Returns aggregated metrics from all subsystems:
    - Screenshot cache hit rate
    - ADB connection pool status
    - Performance monitor statistics
    - MQTT publishing stats
    """
    deps = get_deps()
    metrics = {
        "timestamp": time.time(),
        "version": APP_VERSION,
    }

    # Screenshot cache statistics
    if deps.adb_bridge:
        cache_stats = deps.adb_bridge.get_screenshot_cache_stats()
        metrics["screenshot_cache"] = cache_stats

    # ADB connection pool stats (if available)
    if deps.adb_bridge:
        try:
            # Get connected devices count
            devices = await deps.adb_bridge.get_devices()
            metrics["adb_connections"] = {
                "total_devices": len(devices),
                "connected_devices": len(
                    [d for d in devices if d.get("connected", False)]
                ),
                "device_ids": [d.get("id") for d in devices if d.get("id")],
            }
        except Exception as e:
            logger.error(f"[API] Failed to get ADB stats: {e}")
            metrics["adb_connections"] = {"error": str(e)}

    # Performance monitor stats (if available)
    if deps.performance_monitor:
        try:
            perf_stats = await deps.performance_monitor.get_stats()
            metrics["performance"] = perf_stats
        except Exception as e:
            logger.error(f"[API] Failed to get performance stats: {e}")
            metrics["performance"] = {"error": str(e)}

    # MQTT stats
    if deps.mqtt_manager:
        metrics["mqtt"] = {
            "connected": deps.mqtt_manager.is_connected,
            "broker": (
                deps.mqtt_manager.broker_host
                if hasattr(deps.mqtt_manager, "broker_host")
                else "unknown"
            ),
        }

    return metrics


@router.get("/performance/cache")
async def get_cache_stats():
    """
    Get detailed screenshot cache statistics.

    Useful for tuning cache TTL and monitoring cache effectiveness.
    High hit rate (>80%) indicates effective caching.
    """
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB bridge not initialized")

    return deps.adb_bridge.get_screenshot_cache_stats()


@router.post("/performance/cache/clear")
async def clear_cache():
    """
    Clear screenshot cache for all devices.

    Useful for testing or forcing fresh captures.
    """
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB bridge not initialized")

    try:
        # Clear the cache
        deps.adb_bridge._screenshot_cache.clear()
        deps.adb_bridge._screenshot_cache_hits = 0
        deps.adb_bridge._screenshot_cache_misses = 0

        return {
            "success": True,
            "message": "Screenshot cache cleared",
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[API] Failed to clear cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/performance/adb")
async def get_adb_performance():
    """
    Get ADB subsystem performance metrics.

    Includes connection health, response times, and optimization status.
    """
    deps = get_deps()
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB bridge not initialized")

    try:
        devices = await deps.adb_bridge.get_devices()

        return {
            "timestamp": time.time(),
            "devices": {
                "total": len(devices),
                "connected": len([d for d in devices if d.get("connected", False)]),
                "models": [d.get("model", "Unknown") for d in devices],
            },
            "cache": deps.adb_bridge.get_screenshot_cache_stats(),
            "optimizations": {
                "screenshot_cache_enabled": deps.adb_bridge._screenshot_cache_enabled,
                "cache_ttl_ms": deps.adb_bridge._screenshot_cache_ttl_ms,
                "bounds_only_mode": "Available",
                "batch_commands": "Available",
                "persistent_shell_pool": "Initialized",
            },
        }
    except Exception as e:
        logger.error(f"[API] Failed to get ADB performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DIAGNOSTICS ENDPOINTS
# =============================================================================


@router.get("/diagnostics/adb/{device_id}")
async def get_adb_diagnostics(device_id: str, samples: int = 5):
    """
    Run ADB diagnostic tests and return comprehensive timing info.
    Helps debug performance issues by benchmarking capture speed.

    Args:
        device_id: The ADB device ID
        samples: Number of screenshot samples to take (1-10, default 5)
    """
    deps = get_deps()

    # Clamp samples to reasonable range
    samples = max(1, min(10, samples))

    results = {
        "device_id": device_id,
        "timestamp": time.time(),
        "connection_type": "unknown",
        "adb_version": None,
        "device_info": {},
        "screenshot_benchmark": {
            "samples_ms": [],
            "min_ms": None,
            "max_ms": None,
            "avg_ms": None,
            "success_count": 0,
            "failure_count": 0,
        },
        "ui_dump_timing": {"time_ms": None, "element_count": 0},
        "errors": [],
    }

    # Get ADB version
    try:
        adb_version = subprocess.run(
            ["adb", "version"], capture_output=True, text=True, timeout=5
        )
        if adb_version.returncode == 0:
            results["adb_version"] = adb_version.stdout.strip().split("\n")[0]
    except Exception as e:
        results["errors"].append(f"ADB version check failed: {e}")

    # Check connection type (USB vs WiFi)
    try:
        if ":" in device_id and not device_id.startswith("emulator"):
            results["connection_type"] = "wifi"
        else:
            results["connection_type"] = "usb"
    except:
        pass

    # Get device info
    try:
        device_info = await deps.adb_bridge.get_device_info(device_id)
        results["device_info"] = device_info
    except Exception as e:
        results["errors"].append(f"Device info failed: {e}")

    # Screenshot benchmark (configurable samples)
    logger.info(
        f"[Diagnostics] Running screenshot benchmark for {device_id} ({samples} samples)"
    )
    sample_times = []
    for i in range(samples):
        try:
            start = time.time()
            screenshot = await deps.adb_bridge.capture_screenshot(device_id)
            elapsed = (time.time() - start) * 1000  # ms

            if screenshot and len(screenshot) > 1000:
                sample_times.append(elapsed)
                results["screenshot_benchmark"]["success_count"] += 1
            else:
                results["screenshot_benchmark"]["failure_count"] += 1
                results["errors"].append(f"Sample {i+1}: Empty screenshot")
        except Exception as e:
            results["screenshot_benchmark"]["failure_count"] += 1
            results["errors"].append(f"Sample {i+1}: {e}")

    if sample_times:
        results["screenshot_benchmark"]["samples_ms"] = [
            round(s, 1) for s in sample_times
        ]
        results["screenshot_benchmark"]["min_ms"] = round(min(sample_times), 1)
        results["screenshot_benchmark"]["max_ms"] = round(max(sample_times), 1)
        results["screenshot_benchmark"]["avg_ms"] = round(
            sum(sample_times) / len(sample_times), 1
        )

    # UI dump timing
    try:
        start = time.time()
        elements = await deps.adb_bridge.get_ui_elements(device_id)
        elapsed = (time.time() - start) * 1000
        results["ui_dump_timing"]["time_ms"] = round(elapsed, 1)
        results["ui_dump_timing"]["element_count"] = len(elements) if elements else 0
    except Exception as e:
        results["errors"].append(f"UI dump failed: {e}")

    logger.info(
        f"[Diagnostics] Benchmark complete: avg={results['screenshot_benchmark']['avg_ms']}ms"
    )
    return results


@router.get("/diagnostics/streaming/{device_id}")
async def get_streaming_diagnostics(device_id: str):
    """Get current streaming performance metrics for a device."""
    deps = get_deps()

    # First try stream_manager metrics (enhanced)
    if deps.stream_manager:
        sm_metrics = deps.stream_manager.get_metrics(device_id)
        if sm_metrics:
            return {
                "active": True,
                "mode": "enhanced",
                "source": "stream_manager",
                **sm_metrics,
            }

    # Fall back to global streaming_metrics
    metrics = streaming_metrics.get(
        device_id,
        {
            "active": False,
            "mode": None,
            "current_fps": 0,
            "avg_capture_time_ms": 0,
            "frames_sent": 0,
            "frames_dropped": 0,
            "last_frame_time": None,
            "connection_duration_s": 0,
        },
    )
    return metrics


@router.get("/diagnostics/benchmark/{device_id}")
async def benchmark_capture(device_id: str, iterations: int = 5):
    """
    Benchmark capture performance across different backends.

    Compares adbutils vs adb_bridge capture speeds.
    """
    deps = get_deps()
    if not deps.stream_manager:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    if device_id not in deps.adb_bridge.devices:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    logger.info(
        f"[Diagnostics] Running capture benchmark for {device_id} ({iterations} iterations)"
    )
    results = await deps.stream_manager.benchmark_capture(device_id, iterations)
    logger.info(
        f"[Diagnostics] Benchmark complete: recommended={results.get('recommended_backend')}"
    )
    return results


@router.get("/diagnostics/system")
async def get_system_diagnostics():
    """Get overall system diagnostics - CPU, memory, connected devices."""
    deps = get_deps()

    result = {
        "platform": platform.system(),
        "python_version": platform.python_version(),
        "cpu_percent": 0.0,
        "memory_used_mb": 0,
        "memory_total_mb": 0,
        "connected_devices": len(deps.adb_bridge.devices),
        "active_streams": len(
            [d for d, m in streaming_metrics.items() if m.get("active")]
        ),
        "mqtt_connected": (
            deps.mqtt_manager.is_connected if deps.mqtt_manager else False
        ),
        "uptime_seconds": 0,
        # Flow scheduler status
        "flow_scheduler": (
            {
                "running": (
                    deps.flow_scheduler.is_running if deps.flow_scheduler else False
                ),
                "paused": (
                    deps.flow_scheduler.is_paused if deps.flow_scheduler else False
                ),
                "active_flows": (
                    len(deps.flow_scheduler._periodic_tasks)
                    if deps.flow_scheduler
                    else 0
                ),
            }
            if deps.flow_scheduler
            else None
        ),
    }

    # Try to get psutil metrics (optional dependency)
    try:
        import psutil

        result["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        result["memory_used_mb"] = round(mem.used / (1024 * 1024))
        result["memory_total_mb"] = round(mem.total / (1024 * 1024))

        # Get process uptime
        import os

        process = psutil.Process(os.getpid())
        result["uptime_seconds"] = int(time.time() - process.create_time())
    except ImportError:
        logger.warning(
            "[Diagnostics] psutil not installed - system metrics unavailable"
        )
    except Exception as e:
        logger.error(f"[Diagnostics] Error getting system metrics: {e}")

    return result
