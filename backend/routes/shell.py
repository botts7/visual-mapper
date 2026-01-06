"""
Shell Routes - Persistent ADB Shell Management

Provides persistent shell session management for faster command execution.
Uses a connection pool to maintain long-lived shell sessions, avoiding the
overhead of spawning new ADB processes for each command.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
import time
import asyncio
from routes import get_deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/shell", tags=["shell"])


# Request models
class ShellExecuteRequest(BaseModel):
    command: str


class ShellBatchRequest(BaseModel):
    commands: list


@router.get("/stats")
async def get_shell_pool_stats():
    """Get persistent shell pool statistics"""
    deps = get_deps()
    if not deps.shell_pool:
        raise HTTPException(status_code=503, detail="Shell pool not initialized")
    return {"success": True, "stats": deps.shell_pool.get_stats()}


@router.post("/{device_id}/execute")
async def execute_shell_command(device_id: str, request: ShellExecuteRequest):
    """Execute a command using persistent shell session (faster than individual adb shell calls)"""
    deps = get_deps()
    if not deps.shell_pool:
        raise HTTPException(status_code=503, detail="Shell pool not initialized")

    try:
        shell = await deps.shell_pool.get_shell(device_id)
        success, output = await shell.execute(request.command)
        return {
            "success": success,
            "output": output,
            "session": shell.stats
        }
    except Exception as e:
        logger.error(f"[Shell] Execute error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{device_id}/batch")
async def execute_shell_batch(device_id: str, request: ShellBatchRequest):
    """Execute multiple commands in a persistent shell session"""
    deps = get_deps()
    if not deps.shell_pool:
        raise HTTPException(status_code=503, detail="Shell pool not initialized")

    try:
        shell = await deps.shell_pool.get_shell(device_id)
        results = await shell.execute_batch(request.commands)
        return {
            "success": True,
            "results": [{"success": r[0], "output": r[1]} for r in results],
            "session": shell.stats
        }
    except Exception as e:
        logger.error(f"[Shell] Batch execute error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{device_id}/benchmark")
async def benchmark_shell_session(device_id: str, iterations: int = 10):
    """Benchmark persistent shell vs regular adb shell performance"""
    deps = get_deps()
    if not deps.shell_pool:
        raise HTTPException(status_code=503, detail="Shell pool not initialized")
    if not deps.adb_bridge:
        raise HTTPException(status_code=503, detail="ADB Bridge not initialized")

    test_command = "echo test"
    results = {
        "persistent_shell": {"times_ms": [], "avg_ms": 0},
        "regular_adb": {"times_ms": [], "avg_ms": 0},
        "improvement_percent": 0
    }

    # Benchmark persistent shell
    try:
        shell = await deps.shell_pool.get_shell(device_id)
        for _ in range(iterations):
            start = time.time()
            await shell.execute(test_command)
            elapsed = (time.time() - start) * 1000
            results["persistent_shell"]["times_ms"].append(round(elapsed, 1))
    except Exception as e:
        logger.error(f"[Shell] Benchmark persistent shell error: {e}")
        results["persistent_shell"]["error"] = str(e)

    # Benchmark regular adb shell (spawning new process each time)
    try:
        for _ in range(iterations):
            start = time.time()
            proc = await asyncio.create_subprocess_exec(
                'adb', '-s', device_id, 'shell', test_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            elapsed = (time.time() - start) * 1000
            results["regular_adb"]["times_ms"].append(round(elapsed, 1))
    except Exception as e:
        logger.error(f"[Shell] Benchmark regular adb error: {e}")
        results["regular_adb"]["error"] = str(e)

    # Calculate averages
    if results["persistent_shell"]["times_ms"]:
        results["persistent_shell"]["avg_ms"] = round(
            sum(results["persistent_shell"]["times_ms"]) / len(results["persistent_shell"]["times_ms"]), 1
        )
    if results["regular_adb"]["times_ms"]:
        results["regular_adb"]["avg_ms"] = round(
            sum(results["regular_adb"]["times_ms"]) / len(results["regular_adb"]["times_ms"]), 1
        )

    # Calculate improvement
    if results["regular_adb"]["avg_ms"] > 0 and results["persistent_shell"]["avg_ms"] > 0:
        improvement = (
            (results["regular_adb"]["avg_ms"] - results["persistent_shell"]["avg_ms"])
            / results["regular_adb"]["avg_ms"]
        ) * 100
        results["improvement_percent"] = round(improvement, 1)

    return {"success": True, "benchmark": results, "iterations": iterations}


@router.delete("/{device_id}")
async def close_device_shells(device_id: str):
    """Close all persistent shell sessions for a device"""
    deps = get_deps()
    if not deps.shell_pool:
        raise HTTPException(status_code=503, detail="Shell pool not initialized")

    await deps.shell_pool.close_device_sessions(device_id)
    return {"success": True, "message": f"Closed all shell sessions for {device_id}"}
