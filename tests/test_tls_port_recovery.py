"""Wireless debugging TLS port change recovery (issue #12).

Android 11+ wireless debugging restarts on a new random port. The monitor
must find the new `_adb-tls-connect._tcp` endpoint over mDNS, verify it is the
same device by stable ID, then retire the old ip:port.

No real ADB: subprocess, the bridge and the scheduler are mocked.
"""

import asyncio
import importlib
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
OLD_ID = "10.0.0.5:37001"
NEW_ID = "10.0.0.5:41234"
STABLE_ID = "PIXEL7SERIAL"

MDNS_OUTPUT = (
    "List of discovered mdns services\n"
    "adb-PIXEL7SERIAL-AbCdEf\t_adb-tls-connect._tcp\t10.0.0.5:41234\n"
    "adb-PIXEL7SERIAL-AbCdEf\t_adb-tls-pairing._tcp\t10.0.0.5:39999\n"
    "adb-OTHER123-QwErTy\t_adb-tls-connect._tcp.\t10.0.0.9:40001\n"
    "emulator-legacy\t_adb._tcp\t10.0.0.7:5555\n"
)


@pytest.fixture
def backend_path(monkeypatch):
    monkeypatch.syspath_prepend(str(BACKEND))
    with patch.dict(sys.modules):
        yield


@pytest.fixture
def mdns_module(backend_path):
    return importlib.import_module("core.adb.adb_mdns")


@pytest.fixture
def monitor_module(backend_path):
    return importlib.import_module("services.connection_monitor")


@pytest.fixture
def bridge_module(backend_path):
    module = importlib.import_module("core.adb.adb_bridge")
    with patch.object(module, "get_device_identity_resolver", return_value=Mock()):
        yield module


@pytest.fixture
def scheduler_module(backend_path):
    # Same isolation as test_scheduler_retry: skip the flows package init.
    package = ModuleType("_tls_recovery_scheduler")
    package.__path__ = [str(BACKEND / "core" / "flows")]
    main = ModuleType("main")
    main.wizard_active_devices = set()
    with patch.dict(sys.modules, {package.__name__: package, "main": main}):
        yield importlib.import_module(f"{package.__name__}.flow_scheduler")


# --- parser -----------------------------------------------------------------


def test_parser_keeps_only_tls_connect_entries(mdns_module):
    services = mdns_module.parse_tls_connect_services(MDNS_OUTPUT)
    assert services == [
        {"name": "adb-PIXEL7SERIAL-AbCdEf", "ip": "10.0.0.5", "port": 41234},
        {"name": "adb-OTHER123-QwErTy", "ip": "10.0.0.9", "port": 40001},
    ]


@pytest.mark.parametrize(
    "output",
    [
        "",
        None,
        "List of discovered mdns services\n",
        "adb-X\t_adb-tls-connect._tcp\n",  # no address
        "adb-X\t_adb-tls-connect._tcp\t10.0.0.5\n",  # no port
        "adb-X\t_adb-tls-connect._tcp\t10.0.0.5:abc\n",
        "adb-X\t_adb-tls-connect._tcp\t10.0.0.5:0\n",
        "adb-X\t_adb-tls-connect._tcp\t10.0.0.5:70000\n",
        "garbage line without tabs\n",
        "unknown command mdns\n",
    ],
)
def test_parser_ignores_malformed_lines(mdns_module, output):
    assert mdns_module.parse_tls_connect_services(output) == []


def test_parser_handles_spaces_crlf_and_duplicates(mdns_module):
    output = (
        "adb-A-1   _adb-tls-connect._tcp   192.168.1.20:37123\r\n"
        "adb-A-1\t_adb-tls-connect._tcp\t192.168.1.20:37123\r\n"
        "adb-B-2\t_adb-tls-connect._tcp\t192.168.1.21:41000\r\n"
    )
    services = mdns_module.parse_tls_connect_services(output)
    assert [(s["ip"], s["port"]) for s in services] == [
        ("192.168.1.20", 37123),
        ("192.168.1.21", 41000),
    ]


# --- ADBBridge.list_tls_connect_services ------------------------------------


ZEROCONF_SERVICES = [{"name": "adb-PIXEL7SERIAL-x", "ip": "10.0.0.5", "port": 41234}]

# Alpine android-tools adb (34.0.0-android-tools) has no mDNS backend.
ALPINE_UNSUPPORTED = [
    SimpleNamespace(
        returncode=1,
        stdout="List of discovered mdns services\n",
        stderr="error: unknown host service\n",
    ),
    SimpleNamespace(
        returncode=0,
        stdout="List of discovered mdns services\nerror: unknown host service\n",
        stderr="",
    ),
]

ADB_UNAVAILABLE = ALPINE_UNSUPPORTED + [
    SimpleNamespace(returncode=1, stdout="", stderr="adb: unknown command mdns"),
    FileNotFoundError("adb"),
    TimeoutError("timed out"),
]


def run_patch(effect):
    if isinstance(effect, Exception):
        return patch("subprocess.run", side_effect=effect)
    return patch("subprocess.run", return_value=effect)


def warnings_in(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING]


def test_list_services_parses_adb_output(bridge_module):
    bridge = object.__new__(bridge_module.ADBBridge)
    result = SimpleNamespace(returncode=0, stdout=MDNS_OUTPUT, stderr="")
    browse = AsyncMock(return_value=ZEROCONF_SERVICES)
    with patch("subprocess.run", return_value=result) as run, patch.object(
        bridge_module, "browse_tls_connect_services", browse
    ):
        services = asyncio.run(bridge.list_tls_connect_services())
    assert run.call_args[0][0] == ["adb", "mdns", "services"]
    assert [s["port"] for s in services] == [41234, 40001]
    browse.assert_not_awaited()  # adb answered, no zeroconf browse


@pytest.mark.parametrize("effect", ALPINE_UNSUPPORTED)
def test_adb_unknown_host_service_is_unavailable_and_uses_zeroconf(
    bridge_module, caplog, effect
):
    bridge = object.__new__(bridge_module.ADBBridge)
    browse = AsyncMock(return_value=ZEROCONF_SERVICES)
    with caplog.at_level(logging.DEBUG), run_patch(effect), patch.object(
        bridge_module, "browse_tls_connect_services", browse
    ):
        services, error = asyncio.run(bridge._adb_mdns_services())
        assert services == []
        assert error == "error: unknown host service"
        assert asyncio.run(bridge.list_tls_connect_services()) == ZEROCONF_SERVICES
    browse.assert_awaited_once()
    assert warnings_in(caplog) == []
    assert any("source: zeroconf" in r.getMessage() for r in caplog.records)


def test_adb_empty_result_falls_through_to_zeroconf(bridge_module):
    bridge = object.__new__(bridge_module.ADBBridge)
    empty = SimpleNamespace(
        returncode=0, stdout="List of discovered mdns services\n", stderr=""
    )
    browse = AsyncMock(return_value=ZEROCONF_SERVICES)
    with run_patch(empty), patch.object(
        bridge_module, "browse_tls_connect_services", browse
    ):
        assert asyncio.run(bridge.list_tls_connect_services()) == ZEROCONF_SERVICES


@pytest.mark.parametrize("effect", ADB_UNAVAILABLE)
def test_both_sources_unavailable_returns_empty_and_warns_once(
    bridge_module, caplog, effect
):
    bridge = object.__new__(bridge_module.ADBBridge)
    browse = AsyncMock(side_effect=ImportError("No module named 'zeroconf'"))
    with caplog.at_level(logging.DEBUG), run_patch(effect), patch.object(
        bridge_module, "browse_tls_connect_services", browse
    ):
        assert asyncio.run(bridge.list_tls_connect_services()) == []
        assert asyncio.run(bridge.list_tls_connect_services()) == []
    warnings = warnings_in(caplog)
    assert len(warnings) == 1
    assert "mdns" in warnings[0].getMessage().lower()


def test_adb_unavailable_zeroconf_finds_nothing_does_not_warn(bridge_module, caplog):
    bridge = object.__new__(bridge_module.ADBBridge)
    with caplog.at_level(logging.DEBUG), run_patch(ALPINE_UNSUPPORTED[0]), patch.object(
        bridge_module, "browse_tls_connect_services", AsyncMock(return_value=[])
    ):
        assert asyncio.run(bridge.list_tls_connect_services()) == []
    assert warnings_in(caplog) == []


# --- zeroconf browse ---------------------------------------------------------


def test_browse_without_zeroconf_package_returns_empty(mdns_module):
    # A None entry in sys.modules makes `import zeroconf` raise ImportError.
    with patch.dict(sys.modules, {"zeroconf": None, "zeroconf.asyncio": None}):
        assert asyncio.run(mdns_module.browse_tls_connect_services(timeout=0)) == []
        with pytest.raises(ImportError):
            asyncio.run(
                mdns_module.browse_tls_connect_services(timeout=0, raise_errors=True)
            )


def fake_zeroconf(adverts, closed):
    """Stand-in zeroconf modules. `adverts` maps full name -> (port, [ips])."""
    from enum import Enum

    class IPVersion(Enum):
        V4Only = 1

    class ServiceStateChange(Enum):
        Added = 1
        Removed = 2

    class AsyncZeroconf:
        def __init__(self, **kwargs):
            self.zeroconf = object()

        async def async_close(self):
            closed.append(True)

    class AsyncServiceBrowser:
        def __init__(self, zc, type_, handlers):
            for name in adverts:
                for handler in handlers:
                    handler(zeroconf=zc, service_type=type_, name=name,
                            state_change=ServiceStateChange.Added)

        async def async_cancel(self):
            pass

    class AsyncServiceInfo:
        def __init__(self, type_, name):
            self.name = name
            self.port = None

        async def async_request(self, zc, timeout_ms):
            self.port = adverts[self.name][0]
            return True

        def parsed_addresses(self, version):
            return [ip for ip in adverts[self.name][1] if ":" not in ip]

    zc = ModuleType("zeroconf")
    zc.IPVersion = IPVersion
    zc.ServiceStateChange = ServiceStateChange
    zc_asyncio = ModuleType("zeroconf.asyncio")
    zc_asyncio.AsyncZeroconf = AsyncZeroconf
    zc_asyncio.AsyncServiceBrowser = AsyncServiceBrowser
    zc_asyncio.AsyncServiceInfo = AsyncServiceInfo
    return {"zeroconf": zc, "zeroconf.asyncio": zc_asyncio}


def test_browse_maps_services_ipv4_only_deduped_and_closes(mdns_module):
    suffix = "._adb-tls-connect._tcp.local."
    adverts = {
        "adb-PIXEL7SERIAL-x" + suffix: (41234, ["10.0.0.5", "fe80::1", "10.0.0.5"]),
        "adb-OTHER-y" + suffix: (40001, ["10.0.0.9"]),
        "adb-V6ONLY-z" + suffix: (40002, ["fe80::2"]),
    }
    closed = []
    with patch.dict(sys.modules, fake_zeroconf(adverts, closed)):
        services = asyncio.run(mdns_module.browse_tls_connect_services(timeout=0))
    assert services == [
        {"name": "adb-PIXEL7SERIAL-x", "ip": "10.0.0.5", "port": 41234},
        {"name": "adb-OTHER-y", "ip": "10.0.0.9", "port": 40001},
    ]
    assert closed == [True]


def test_browse_returns_empty_when_nothing_answers(mdns_module):
    pytest.importorskip("zeroconf")
    # A service type nobody advertises, so no real device can answer.
    with patch.object(
        mdns_module, "TLS_CONNECT_ZEROCONF_TYPE", "_vm-issue12-none._tcp.local."
    ):
        assert asyncio.run(mdns_module.browse_tls_connect_services(timeout=0.3)) == []


# --- ConnectionMonitor recovery ---------------------------------------------


def make_bridge(services, serials):
    """Fake ADBBridge. `serials` maps device_id -> stable ID."""
    return SimpleNamespace(
        list_tls_connect_services=AsyncMock(return_value=services),
        connect_device=AsyncMock(side_effect=lambda ip, port: f"{ip}:{port}"),
        get_device_serial=AsyncMock(
            side_effect=lambda device_id, force_refresh=False: serials.get(device_id)
        ),
        disconnect_device=AsyncMock(),
        discover_devices=AsyncMock(return_value=[]),
    )


def make_monitor(module, bridge, scheduler=None):
    monitor = module.ConnectionMonitor(
        adb_bridge=bridge,
        command_queue=Mock(),
        flow_scheduler=scheduler,
    )
    monitor._try_direct_reconnect = AsyncMock(return_value=False)
    return monitor


async def fail_until_scan(monitor, device_id=OLD_ID):
    """Register the device, then fail reconnect attempts 1..3."""
    await monitor.add_device(device_id, STABLE_ID)
    status = monitor._devices[device_id]
    status.online = False
    for _ in range(3):
        status.last_seen = 0  # bypass backoff wait
        await monitor._attempt_reconnection(device_id)
        if device_id not in monitor._devices:
            break


def test_new_port_found_verified_and_old_endpoint_retired(monitor_module):
    async def exercise():
        bridge = make_bridge(
            [{"name": "adb-PIXEL7SERIAL-x", "ip": "10.0.0.5", "port": 41234}],
            {NEW_ID: STABLE_ID},
        )
        scheduler = SimpleNamespace(retire_device=AsyncMock())
        monitor = make_monitor(monitor_module, bridge, scheduler)

        await fail_until_scan(monitor)

        bridge.connect_device.assert_awaited_once_with("10.0.0.5", 41234)
        bridge.get_device_serial.assert_awaited_with(NEW_ID, force_refresh=True)
        bridge.disconnect_device.assert_awaited_once_with(OLD_ID)
        assert OLD_ID not in monitor._devices
        scheduler.retire_device.assert_awaited_once_with(OLD_ID, NEW_ID)
        # Recovered via mDNS, so the legacy discover fallback is skipped.
        bridge.discover_devices.assert_not_awaited()

    asyncio.run(exercise())


def test_serial_mismatch_disconnects_candidate_without_remap(monitor_module):
    async def exercise():
        bridge = make_bridge(
            [{"name": "adb-SOMEONEELSE-x", "ip": "10.0.0.5", "port": 41234}],
            {NEW_ID: "SOMEONE_ELSE"},
        )
        scheduler = SimpleNamespace(retire_device=AsyncMock())
        monitor = make_monitor(monitor_module, bridge, scheduler)
        # Simulate the connect callback registering the candidate.
        await monitor.add_device(NEW_ID, "SOMEONE_ELSE")

        await fail_until_scan(monitor)

        bridge.connect_device.assert_awaited_once_with("10.0.0.5", 41234)
        bridge.disconnect_device.assert_awaited_once_with(NEW_ID)
        assert OLD_ID in monitor._devices
        assert NEW_ID not in monitor._devices
        scheduler.retire_device.assert_not_awaited()
        bridge.discover_devices.assert_awaited_once()

    asyncio.run(exercise())


def test_mdns_unavailable_falls_back_to_discover(monitor_module):
    # list_tls_connect_services returns [] on adb error / no mDNS support.
    async def exercise():
        bridge = make_bridge([], {})
        monitor = make_monitor(monitor_module, bridge)

        await fail_until_scan(monitor)

        bridge.connect_device.assert_not_awaited()
        bridge.disconnect_device.assert_not_awaited()
        bridge.discover_devices.assert_awaited_once()
        assert OLD_ID in monitor._devices

    asyncio.run(exercise())


def test_mdns_raising_does_not_crash_monitor(monitor_module):
    async def exercise():
        bridge = make_bridge([], {})
        bridge.list_tls_connect_services = AsyncMock(side_effect=OSError("boom"))
        monitor = make_monitor(monitor_module, bridge)

        await fail_until_scan(monitor)

        assert OLD_ID in monitor._devices
        bridge.connect_device.assert_not_awaited()

    asyncio.run(exercise())


def test_same_ip_same_port_only_takes_no_action(monitor_module):
    async def exercise():
        bridge = make_bridge(
            [
                {"name": "adb-PIXEL7SERIAL-x", "ip": "10.0.0.5", "port": 37001},
                {"name": "adb-OTHER-y", "ip": "10.0.0.9", "port": 41234},
            ],
            {},
        )
        scheduler = SimpleNamespace(retire_device=AsyncMock())
        monitor = make_monitor(monitor_module, bridge, scheduler)

        await fail_until_scan(monitor)

        bridge.connect_device.assert_not_awaited()
        bridge.disconnect_device.assert_not_awaited()
        scheduler.retire_device.assert_not_awaited()
        assert OLD_ID in monitor._devices

    asyncio.run(exercise())


def test_scan_runs_on_every_third_failed_retry(monitor_module):
    async def exercise():
        bridge = make_bridge([], {})
        monitor = make_monitor(monitor_module, bridge)
        await monitor.add_device(OLD_ID, STABLE_ID)
        status = monitor._devices[OLD_ID]
        status.online = False
        for _ in range(7):
            status.last_seen = 0
            await monitor._attempt_reconnection(OLD_ID)

        assert bridge.list_tls_connect_services.await_count == 2  # attempts 3, 6

    asyncio.run(exercise())


# --- FlowScheduler.retire_device --------------------------------------------


def test_scheduler_retire_device_stops_old_task(scheduler_module):
    async def exercise():
        flow_manager = Mock()
        flow_manager.get_device_flows.return_value = []
        flow_manager.get_enabled_flows.return_value = []
        scheduler = scheduler_module.FlowScheduler(Mock(), flow_manager)

        old_task = asyncio.create_task(asyncio.sleep(3600))
        scheduler._scheduler_tasks[OLD_ID] = old_task
        scheduler._queues[OLD_ID] = asyncio.PriorityQueue()
        scheduler._device_locks[OLD_ID] = asyncio.Lock()
        scheduler._queue_depths[OLD_ID] = 0
        scheduler._queued_flow_ids[OLD_ID] = {"flow_a"}

        await scheduler.retire_device(OLD_ID, NEW_ID)

        assert old_task.cancelled()
        assert OLD_ID not in scheduler._scheduler_tasks
        assert OLD_ID not in scheduler._queues
        assert OLD_ID not in scheduler._queued_flow_ids
        flow_manager.get_enabled_flows.assert_called_with(NEW_ID)

    asyncio.run(exercise())
