"""Issue #12 pass 2: field findings from a Pixel 8a on HAOS.

- LOG_LEVEL from the add-on option is honoured.
- Stored stable IDs are resolved to ip:port before `adb connect`.
- Unicast mDNS fallback straight to <device ip>:5353.
- One INFO summary line per recovery attempt.
- /api/adb/devices does not report a monitor-offline endpoint as connected.

No real ADB or network: subprocess, sockets and the bridge are faked.
"""

import asyncio
import importlib
import logging
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
IP = "10.0.0.5"
OLD_ID = f"{IP}:37001"
NEW_ID = f"{IP}:41234"
STABLE_ID = "PIXEL8ASERIAL"
TYPE = "_adb-tls-connect._tcp.local."
INSTANCE = f"adb-{STABLE_ID}-AbCdEf.{TYPE}"


@pytest.fixture
def backend_path(monkeypatch):
    monkeypatch.syspath_prepend(str(BACKEND))
    with patch.dict(sys.modules):
        yield


@pytest.fixture
def load(backend_path):
    return importlib.import_module


class FakeResolver:
    """Minimal DeviceIdentityResolver stand-in."""

    def __init__(self, current=None, history=(), stable=STABLE_ID):
        self.stable = stable
        self.current = current
        self.history = list(history)

    def get_stable_id(self, connection_id):
        known = {self.current, *self.history}
        return self.stable if connection_id in known else None

    def resolve_any_id(self, device_id):
        if device_id == self.stable or device_id in {self.current, *self.history}:
            return self.stable
        return device_id

    def get_connection_id(self, stable_device_id):
        return self.current if stable_device_id == self.stable else None

    def get_device_info(self, stable_device_id):
        if stable_device_id != self.stable:
            return None
        return {"current_connection": self.current, "connection_history": self.history}


# --- logging -----------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("debug", logging.DEBUG),
        ("DEBUG", logging.DEBUG),
        ("trace", logging.DEBUG),
        ("info", logging.INFO),
        ("notice", logging.INFO),
        ("warning", logging.WARNING),
        ("error", logging.ERROR),
        ("fatal", logging.CRITICAL),
        ("", logging.INFO),
        (None, logging.INFO),
        ("nonsense", logging.INFO),
    ],
)
def test_log_level_mapping(load, value, expected):
    assert load("utils.log_config").parse_log_level(value) == expected


def test_configure_logging_reads_env_and_quiets_libraries(load, monkeypatch):
    module = load("utils.log_config")
    root = logging.getLogger()
    saved = (root.level, {n: logging.getLogger(n).level for n in module.NOISY_LOGGERS})
    try:
        monkeypatch.setenv("LOG_LEVEL", "debug")
        assert module.configure_logging() == logging.DEBUG
        assert root.level == logging.DEBUG
        assert logging.getLogger("zeroconf").level == logging.WARNING
        assert logging.getLogger("asyncio").level == logging.WARNING

        monkeypatch.setenv("LOG_LEVEL", "error")
        module.configure_logging()
        assert root.level == logging.ERROR
        assert logging.getLogger("zeroconf").level == logging.ERROR
    finally:
        root.setLevel(saved[0])
        for name, level in saved[1].items():
            logging.getLogger(name).setLevel(level)


# --- endpoint resolution -----------------------------------------------------


def test_endpoint_passthrough_and_stable_id_resolution(load):
    module = load("services.endpoint_resolver")
    resolver = FakeResolver(current=OLD_ID, history=[f"{IP}:30000", OLD_ID])

    assert module.resolve_adb_endpoints(OLD_ID, resolver) == [OLD_ID]
    # Current connection first, then history newest first, de-duplicated.
    assert module.resolve_adb_endpoints(STABLE_ID, resolver) == [OLD_ID, f"{IP}:30000"]
    assert module.resolve_stable_id(STABLE_ID, resolver) == STABLE_ID
    assert module.resolve_stable_id(OLD_ID, resolver) == STABLE_ID


def test_endpoint_resolution_uses_migrator_map_and_skips_unknown(load):
    module = load("services.endpoint_resolver")
    empty = FakeResolver(stable="OTHER")
    device_map = {STABLE_ID: {OLD_ID, "USBSERIAL"}}

    assert module.resolve_adb_endpoints(STABLE_ID, empty, device_map) == [OLD_ID]
    assert module.resolve_stable_id(OLD_ID, empty, device_map) == STABLE_ID
    assert module.resolve_adb_endpoints("UNKNOWN", empty, device_map) == []


# --- startup reconnect -------------------------------------------------------


def startup_bridge(fail=()):
    async def connect(host, port):
        endpoint = f"{host}:{port}"
        if endpoint in fail:
            raise ConnectionError(f"Failed to connect to {endpoint}")
        return endpoint

    return SimpleNamespace(connect_device=AsyncMock(side_effect=connect))


def test_startup_resolves_stable_id_before_connecting(load):
    module = load("services.startup_reconnect")
    bridge = startup_bridge()
    monitor = SimpleNamespace(recover_moved_endpoint=AsyncMock())

    result = asyncio.run(
        module.reconnect_stored_device(STABLE_ID, bridge, monitor, FakeResolver(OLD_ID))
    )

    assert result == OLD_ID
    bridge.connect_device.assert_awaited_once_with(IP, 37001)
    monitor.recover_moved_endpoint.assert_not_awaited()


def test_startup_runs_tls_recovery_once_when_endpoint_is_dead(load):
    module = load("services.startup_reconnect")
    bridge = startup_bridge(fail={OLD_ID})
    monitor = SimpleNamespace(recover_moved_endpoint=AsyncMock(return_value=NEW_ID))

    result = asyncio.run(
        module.reconnect_stored_device(STABLE_ID, bridge, monitor, FakeResolver(OLD_ID))
    )

    assert result == NEW_ID
    monitor.recover_moved_endpoint.assert_awaited_once_with(OLD_ID, STABLE_ID)


def test_startup_skips_ids_with_no_known_endpoint(load):
    module = load("services.startup_reconnect")
    bridge = startup_bridge()
    monitor = SimpleNamespace(recover_moved_endpoint=AsyncMock())

    result = asyncio.run(
        module.reconnect_stored_device(
            "UNKNOWN", bridge, monitor, FakeResolver(stable="OTHER")
        )
    )

    assert result is None
    bridge.connect_device.assert_not_awaited()
    monitor.recover_moved_endpoint.assert_not_awaited()


# --- recovery summary line ---------------------------------------------------


def recovery_bridge(report, serials):
    return SimpleNamespace(
        lookup_tls_connect_services=AsyncMock(return_value=report),
        connect_device=AsyncMock(side_effect=lambda ip, port: f"{ip}:{port}"),
        get_device_serial=AsyncMock(
            side_effect=lambda device_id, force_refresh=False: serials.get(device_id)
        ),
        disconnect_device=AsyncMock(),
    )


def report(services, adb="unavailable", zeroconf=None, unicast="skipped"):
    return {
        "services": services,
        "adb": adb,
        "zeroconf": zeroconf if zeroconf is not None else f"{len(services)} services",
        "unicast": unicast,
    }


def svc(ip, port, name="adb-x"):
    return {"name": name, "ip": ip, "port": port}


def summary(caplog):
    lines = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.INFO and r.getMessage().startswith("[TLSRecovery] lookup for")
    ]
    assert len(lines) == 1, lines
    return lines[0]


@pytest.mark.parametrize(
    "lookup, serials, expected_parts, adopted",
    [
        (
            report([svc(IP, 41234)], zeroconf="1 services"),
            {NEW_ID: STABLE_ID},
            ["adb=unavailable", "zeroconf=1 services", "unicast=skipped",
             f"candidates on {IP}: [41234]", f"result=adopted {NEW_ID}"],
            NEW_ID,
        ),
        (
            report([svc(IP, 41234)]),
            {NEW_ID: "SOMEONE_ELSE"},
            [f"candidates on {IP}: [41234]",
             f"result=rejected (serial mismatch: {NEW_ID} is SOMEONE_ELSE)"],
            None,
        ),
        (
            report([svc("10.0.0.9", 40001)], unicast="0 services"),
            {},
            ["zeroconf=1 services", "unicast=0 services", f"candidates on {IP}: []",
             f"result=none (1 services, none on {IP} with a new port)"],
            None,
        ),
        (
            report([], zeroconf="0 services", unicast="0 services"),
            {},
            ["zeroconf=0 services", "unicast=0 services", "result=none"],
            None,
        ),
        (
            report([], zeroconf="error: OSError: [Errno 98] Address in use",
                   unicast="error: TimeoutError"),
            {},
            ["zeroconf=error: OSError: [Errno 98] Address in use",
             "unicast=error: TimeoutError", "result=none"],
            None,
        ),
    ],
)
def test_recovery_summary_line(load, caplog, lookup, serials, expected_parts, adopted):
    module = load("services.tls_endpoint_recovery")
    bridge = recovery_bridge(lookup, serials)
    with caplog.at_level(logging.INFO):
        result = asyncio.run(module.find_moved_tls_endpoint(bridge, OLD_ID, STABLE_ID))
    line = summary(caplog)
    assert line.startswith(f"[TLSRecovery] lookup for {OLD_ID} (stable {STABLE_ID}): ")
    for part in expected_parts:
        assert part in line
    assert result == adopted
    bridge.lookup_tls_connect_services.assert_awaited_once_with(target_ip=IP)


def test_recovery_accepts_stable_id_as_old_device_id(load, caplog):
    module = load("services.tls_endpoint_recovery")
    bridge = recovery_bridge(report([svc(IP, 41234)]), {NEW_ID: STABLE_ID})
    with caplog.at_level(logging.INFO):
        result = asyncio.run(
            module.find_moved_tls_endpoint(
                bridge, STABLE_ID, STABLE_ID, resolver=FakeResolver(OLD_ID)
            )
        )
    assert result == NEW_ID
    bridge.lookup_tls_connect_services.assert_awaited_once_with(target_ip=IP)
    bridge.connect_device.assert_awaited_once_with(IP, 41234)
    assert f"via {OLD_ID}" in summary(caplog)


def test_recovery_with_unresolvable_id_logs_and_returns_none(load, caplog):
    module = load("services.tls_endpoint_recovery")
    bridge = recovery_bridge(report([]), {})
    with caplog.at_level(logging.INFO):
        result = asyncio.run(
            module.find_moved_tls_endpoint(
                bridge, "UNKNOWN", STABLE_ID, resolver=FakeResolver(stable="OTHER")
            )
        )
    assert result is None
    bridge.lookup_tls_connect_services.assert_not_awaited()
    assert "no ip:port known; result=none" in summary(caplog)


# --- ADBBridge.lookup_tls_connect_services -----------------------------------


@pytest.fixture
def bridge_module(backend_path):
    module = importlib.import_module("core.adb.adb_bridge")
    with patch.object(module, "get_device_identity_resolver", return_value=Mock()):
        yield module


ALPINE_ADB = SimpleNamespace(
    returncode=1,
    stdout="List of discovered mdns services\n",
    stderr="error: unknown host service\n",
)


def test_lookup_uses_unicast_when_multicast_finds_nothing_on_target(bridge_module):
    bridge = object.__new__(bridge_module.ADBBridge)
    browse = AsyncMock(return_value=[svc("10.0.0.9", 40001, "adb-other")])
    unicast = AsyncMock(return_value=[svc(IP, 41234, "adb-pixel")])
    with patch("subprocess.run", return_value=ALPINE_ADB), patch.object(
        bridge_module, "browse_tls_connect_services", browse
    ), patch.object(bridge_module, "unicast_query_tls_connect_services", unicast):
        result = asyncio.run(bridge.lookup_tls_connect_services(target_ip=IP))
    unicast.assert_awaited_once()
    assert unicast.await_args.args[0] == IP
    assert result["adb"] == "unavailable"
    assert result["zeroconf"] == "1 services"
    assert result["unicast"] == "1 services"
    assert [(s["ip"], s["port"]) for s in result["services"]] == [
        ("10.0.0.9", 40001),
        (IP, 41234),
    ]


def test_lookup_skips_unicast_when_target_already_found(bridge_module):
    bridge = object.__new__(bridge_module.ADBBridge)
    unicast = AsyncMock()
    with patch("subprocess.run", return_value=ALPINE_ADB), patch.object(
        bridge_module,
        "browse_tls_connect_services",
        AsyncMock(return_value=[svc(IP, 41234)]),
    ), patch.object(bridge_module, "unicast_query_tls_connect_services", unicast):
        result = asyncio.run(bridge.lookup_tls_connect_services(target_ip=IP))
    unicast.assert_not_awaited()
    assert result["unicast"] == "skipped"


def test_lookup_reports_errors_per_source(bridge_module):
    bridge = object.__new__(bridge_module.ADBBridge)
    with patch("subprocess.run", return_value=ALPINE_ADB), patch.object(
        bridge_module,
        "browse_tls_connect_services",
        AsyncMock(side_effect=OSError("no multicast")),
    ), patch.object(
        bridge_module,
        "unicast_query_tls_connect_services",
        AsyncMock(side_effect=ImportError("No module named 'zeroconf'")),
    ):
        result = asyncio.run(bridge.lookup_tls_connect_services(target_ip=IP))
    assert result["services"] == []
    assert result["zeroconf"] == "error: OSError: no multicast"
    assert result["unicast"] == "error: ImportError: No module named 'zeroconf'"


# --- unicast mDNS query ------------------------------------------------------


class FakeSocket:
    """UDP socket stand-in. `script(sent_packets)` returns datagrams to deliver."""

    def __init__(self, script):
        self.script = script
        self.sent = []
        self.inbox = []
        self.closed = False

    def bind(self, addr):
        pass

    def settimeout(self, value):
        pass

    def sendto(self, data, addr):
        self.sent.append((data, addr))
        self.inbox.extend(self.script(len(self.sent)))

    def recvfrom(self, size):
        if not self.inbox:
            raise socket.timeout()
        return self.inbox.pop(0)

    def close(self):
        self.closed = True


def mdns_response(records):
    zc = pytest.importorskip("zeroconf")
    out = zc.DNSOutgoing(0x8400, multicast=False, id_=0)
    for record in records:
        out.add_answer_at_time(record, 0)
    return out.packets()[0]


def ptr():
    zc = pytest.importorskip("zeroconf")
    return zc.DNSPointer(TYPE, 12, 1, 120, INSTANCE)


def srv(port=41234):
    zc = pytest.importorskip("zeroconf")
    return zc.DNSService(INSTANCE, 33, 1, 120, 0, 0, port, "Android.local.")


def a_record(ip):
    zc = pytest.importorskip("zeroconf")
    return zc.DNSAddress("Android.local.", 1, 1, 120, socket.inet_aton(ip))


def run_unicast(module, fake):
    return asyncio.run(
        module.unicast_query_tls_connect_services(
            IP, timeout=0.5, raise_errors=True, sock_factory=lambda *a: fake
        )
    )


def test_unicast_query_returns_service_from_target_ip(load):
    module = load("core.adb.adb_mdns")
    packet = mdns_response([ptr(), srv(), a_record(IP)])
    fake = FakeSocket(lambda n: [(packet, (IP, 5353))] if n == 1 else [])

    services = run_unicast(module, fake)

    assert services == [{"name": f"adb-{STABLE_ID}-AbCdEf", "ip": IP, "port": 41234}]
    assert fake.sent[0][1] == (IP, 5353)
    assert fake.closed


def test_unicast_query_asks_for_srv_when_only_ptr_arrives(load):
    module = load("core.adb.adb_mdns")
    first = mdns_response([ptr()])
    second = mdns_response([srv(), a_record(IP)])
    fake = FakeSocket(
        lambda n: [(first, (IP, 5353))] if n == 1 else [(second, (IP, 5353))]
    )

    services = run_unicast(module, fake)

    assert len(fake.sent) == 2  # PTR, then SRV follow-up
    assert [(s["ip"], s["port"]) for s in services] == [(IP, 41234)]


def test_unicast_query_ignores_other_sources_and_foreign_a_records(load):
    module = load("core.adb.adb_mdns")
    good_shape = mdns_response([ptr(), srv(), a_record(IP)])
    foreign_a = mdns_response([ptr(), srv(), a_record("10.0.0.9")])
    fake = FakeSocket(
        lambda n: [(good_shape, ("10.0.0.9", 5353)), (foreign_a, (IP, 5353))]
        if n == 1
        else []
    )

    assert run_unicast(module, fake) == []


# --- /api/adb/devices consistency --------------------------------------------


def test_offline_endpoint_not_reported_connected(load):
    module = load("services.connection_monitor")
    monitor = module.ConnectionMonitor(adb_bridge=None, command_queue=Mock())

    async def setup():
        await monitor.add_device(OLD_ID, STABLE_ID)
        await monitor.add_device(NEW_ID, STABLE_ID)

    asyncio.run(setup())
    monitor._devices[OLD_ID].online = False

    devices = [
        {"id": OLD_ID, "state": "device", "connected": True, "current_activity": "x"},
        {"id": NEW_ID, "state": "device", "connected": True, "current_activity": "y"},
        {"id": "USB123", "state": "device", "connected": True, "current_activity": "z"},
    ]
    result = monitor.annotate_devices(devices)

    assert result[0]["connected"] is False
    assert result[0]["state"] == "offline"
    assert result[1]["connected"] is True
    assert result[2]["connected"] is True


def test_retire_with_stable_id_does_not_adb_disconnect_it(load):
    module = load("services.connection_monitor")
    bridge = SimpleNamespace(disconnect_device=AsyncMock())
    monitor = module.ConnectionMonitor(adb_bridge=bridge, command_queue=Mock())

    async def exercise():
        await monitor.add_device(STABLE_ID, STABLE_ID)
        await monitor._retire_endpoint(STABLE_ID, NEW_ID)

    asyncio.run(exercise())
    bridge.disconnect_device.assert_not_awaited()
    assert STABLE_ID not in monitor._devices
