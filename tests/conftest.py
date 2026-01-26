"""
Test Configuration for Visual Mapper
Provides fixtures for API and Playwright tests
"""
import pytest
import asyncio
import subprocess
import time
import httpx
import sys
import os
import tempfile
import shutil
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# Server configuration
TEST_HOST = "127.0.0.1"
TEST_PORT = 8765  # Use different port to avoid conflicts
BASE_URL = f"http://{TEST_HOST}:{TEST_PORT}"
API_BASE = f"{BASE_URL}/api"
TEST_COMPANION_KEY = "test-companion-key"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def backend_server():
    """Start backend server for testing"""
    backend_dir = Path(__file__).parent.parent / "backend"
    env = os.environ.copy()
    env["COMPANION_API_KEY"] = TEST_COMPANION_KEY
    env["TRUST_PROXY_HEADERS"] = "true"
    test_data_dir = Path(tempfile.mkdtemp(prefix="vm-tests-"))
    env["DATA_DIR"] = str(test_data_dir)

    # Start server process
    process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "main:app",
            "--host", TEST_HOST,
            "--port", str(TEST_PORT),
            "--log-level", "warning"
        ],
        cwd=str(backend_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
        env=env,
    )

    # Wait for server to start (can take 5-10 seconds for full initialization)
    max_retries = 60
    for i in range(max_retries):
        try:
            response = httpx.get(f"{API_BASE}/", timeout=2)
            if response.status_code == 200:
                print(f"\n[Test] Backend server started on {BASE_URL}")
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        # Get stderr for debugging
        stderr = process.stderr.read().decode() if process.stderr else "No stderr"
        stdout = process.stdout.read().decode() if process.stdout else "No stdout"
        process.terminate()
        raise RuntimeError(
            "Failed to start backend server. "
            f"Stderr: {stderr[:1000]} "
            f"Stdout: {stdout[:1000]}"
        )

    yield process

    # Cleanup
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    print("\n[Test] Backend server stopped")
    shutil.rmtree(test_data_dir, ignore_errors=True)


@pytest.fixture
def api_client(backend_server):
    """HTTP client for API tests"""
    with httpx.Client(base_url=API_BASE, timeout=10) as client:
        yield client


@pytest.fixture
def async_api_client(backend_server):
    """Async HTTP client for API tests"""
    return httpx.AsyncClient(base_url=API_BASE, timeout=10)


@pytest.fixture(scope="session")
def companion_key():
    """Shared test companion key for auth-protected endpoints."""
    return TEST_COMPANION_KEY
