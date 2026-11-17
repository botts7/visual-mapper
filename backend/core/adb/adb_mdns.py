"""
ADB mDNS helpers - find Android 11+ wireless debugging endpoints.

Android 11+ wireless debugging advertises its current TLS connect port as an
`_adb-tls-connect._tcp` mDNS service. The port is random and changes whenever
wireless debugging restarts, so this is how a paired device is found again.

Two sources, same {"name", "ip", "port"} result shape:
- parse_tls_connect_services(): parses `adb mdns services` output. Pure, no
  subprocess, so it can be unit tested directly.
- browse_tls_connect_services(): browses with python-zeroconf, for adb builds
  without an mDNS backend (e.g. Alpine android-tools: "unknown host service").
- unicast_query_tls_connect_services(): asks one IP directly on port 5353,
  for networks where multicast answers never arrive.
"""

import asyncio
import ipaddress
import logging
import random
import re
import socket
import time
from typing import Dict, List

logger = logging.getLogger(__name__)

TLS_CONNECT_SERVICE = "_adb-tls-connect._tcp"
TLS_CONNECT_ZEROCONF_TYPE = "_adb-tls-connect._tcp.local."

# How long a zeroconf browse listens for answers, and how long each
# found service may take to resolve to an address.
BROWSE_SECONDS = 3.0
RESOLVE_SECONDS = 1.5

# Example line (tab or space separated, older adb adds a trailing dot):
#   adb-1A2B3C4D-xYz12a	_adb-tls-connect._tcp	192.168.1.50:37123
_SERVICE_LINE = re.compile(
    r"^(?P<name>\S+)\s+_adb-tls-connect\._tcp\.?\s+"
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3}):(?P<port>\d{1,5})$"
)


def describe_error(error: Exception) -> str:
    """Short "Type: message" text for diagnostics."""
    text = str(error)
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


def parse_tls_connect_services(output: str) -> List[Dict]:
    """
    Parse `adb mdns services` output into TLS connect endpoints.

    Pairing (`_adb-tls-pairing._tcp`) and legacy (`_adb._tcp`) entries,
    headers and malformed lines are ignored.

    Returns:
        List of {"name": str, "ip": str, "port": int}, de-duplicated
    """
    services = []
    seen = set()
    for line in (output or "").splitlines():
        match = _SERVICE_LINE.match(line.strip())
        if not match:
            continue
        _add_service(services, seen, match.group("name"), match.group("ip"),
                     int(match.group("port")))
    return services


def _add_service(services: List[Dict], seen: set, name: str, ip: str, port: int):
    """Append an IPv4 endpoint once, skipping invalid ports and addresses."""
    if not 0 < port < 65536:
        return
    try:
        if ipaddress.ip_address(ip).version != 4:
            return
    except ValueError:
        return
    if (ip, port) in seen:
        return
    seen.add((ip, port))
    services.append({"name": name, "ip": ip, "port": port})


async def browse_tls_connect_services(
    timeout: float = BROWSE_SECONDS, raise_errors: bool = False
) -> List[Dict]:
    """
    Browse `_adb-tls-connect._tcp.local.` with python-zeroconf.

    Listens for `timeout` seconds, then resolves each service to its IPv4
    address and port. The zeroconf instance is always closed.

    Args:
        timeout: Seconds to listen for services
        raise_errors: Re-raise ImportError/socket errors instead of returning
            [] (lets the caller tell "unavailable" from "nothing found")

    Returns:
        List of {"name": str, "ip": str, "port": int}, IPv4 only, de-duplicated
    """
    try:
        return await _browse(timeout)
    except Exception as e:
        if raise_errors:
            raise
        logger.debug(f"[ADBmDNS] zeroconf browse failed: {e}")
        return []


async def _browse(timeout: float) -> List[Dict]:
    # Lazy import: a missing package must never break startup.
    from zeroconf import IPVersion, ServiceStateChange
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

    found_names: List[str] = []

    def on_change(zeroconf, service_type, name, state_change):
        if state_change is not ServiceStateChange.Removed and name not in found_names:
            found_names.append(name)

    aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    _log_interfaces_once()
    browser = None
    try:
        browser = AsyncServiceBrowser(
            aiozc.zeroconf, TLS_CONNECT_ZEROCONF_TYPE, handlers=[on_change]
        )
        await asyncio.sleep(timeout)

        infos = [AsyncServiceInfo(TLS_CONNECT_ZEROCONF_TYPE, n) for n in found_names]
        await asyncio.gather(
            *(i.async_request(aiozc.zeroconf, RESOLVE_SECONDS * 1000) for i in infos),
            return_exceptions=True,
        )

        services: List[Dict] = []
        seen: set = set()
        suffix = "." + TLS_CONNECT_ZEROCONF_TYPE
        for info in infos:
            if not info.port:
                continue
            name = info.name
            if name.endswith(suffix):
                name = name[: -len(suffix)]
            for ip in info.parsed_addresses(IPVersion.V4Only):
                _add_service(services, seen, name, ip, int(info.port))
        return services
    finally:
        if browser is not None:
            try:
                await browser.async_cancel()
            except Exception:
                pass
        await aiozc.async_close()


_interfaces_logged = False


def _log_interfaces_once():
    """Log (INFO, once) the IPv4 addresses zeroconf listens on (all interfaces)."""
    global _interfaces_logged
    if _interfaces_logged:
        return
    _interfaces_logged = True
    try:
        import ifaddr  # zeroconf dependency

        addresses = [
            f"{adapter.nice_name}={ip.ip}"
            for adapter in ifaddr.get_adapters()
            for ip in adapter.ips
            if isinstance(ip.ip, str)
        ]
    except Exception as e:
        addresses = [f"unknown ({e})"]
    logger.info(f"[ADBmDNS] zeroconf bound to IPv4 interfaces: {addresses}")


# --- Unicast fallback --------------------------------------------------------
#
# Some hosts never see multicast answers (IGMP snooping, docker bridges,
# Wi-Fi client isolation for multicast). A "legacy unicast" query (RFC 6762
# 6.7) sent straight to <device ip>:5353 from an ephemeral port is answered
# by the device's responder directly to us.

MDNS_PORT = 5353
UNICAST_SECONDS = 2.0

_DNS_TYPE_A = 1
_DNS_TYPE_PTR = 12
_DNS_TYPE_SRV = 33
_DNS_CLASS_IN = 1


async def unicast_query_tls_connect_services(
    ip: str,
    timeout: float = UNICAST_SECONDS,
    raise_errors: bool = False,
    sock_factory=None,
) -> List[Dict]:
    """
    Ask one host directly for its `_adb-tls-connect._tcp` services.

    Sends a PTR query to <ip>:5353 and collects PTR/SRV/A answers for up to
    `timeout` seconds. Only datagrams from `ip` are read, and an SRV whose
    A record points elsewhere is rejected.

    Returns:
        List of {"name": str, "ip": str, "port": int}; [] on failure unless
        raise_errors is set
    """
    try:
        return await asyncio.to_thread(
            _unicast_query, ip, timeout, sock_factory or socket.socket
        )
    except Exception as e:
        if raise_errors:
            raise
        logger.debug(f"[ADBmDNS] unicast query to {ip} failed: {e}")
        return []


def _unicast_query(ip: str, timeout: float, sock_factory) -> List[Dict]:
    # Lazy import: a missing package must never break startup.
    from zeroconf import (
        DNSAddress,
        DNSIncoming,
        DNSOutgoing,
        DNSPointer,
        DNSQuestion,
        DNSService,
    )

    suffix = ("." + TLS_CONNECT_ZEROCONF_TYPE).lower()
    instances: Dict[str, str] = {}  # lower name -> name
    ports: Dict[str, int] = {}
    servers: Dict[str, str] = {}
    addresses: Dict[str, str] = {}
    srv_asked: set = set()

    sock = sock_factory(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("", 0))

        def send(questions):
            out = DNSOutgoing(0, multicast=False, id_=random.randint(1, 0xFFFF))
            for name, qtype in questions:
                out.add_question(DNSQuestion(name, qtype, _DNS_CLASS_IN))
            for packet in out.packets():
                sock.sendto(packet, (ip, MDNS_PORT))

        send([(TLS_CONNECT_ZEROCONF_TYPE, _DNS_TYPE_PTR)])
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, addr = sock.recvfrom(9000)
            except (socket.timeout, TimeoutError, BlockingIOError):
                break
            if addr[0] != ip:
                continue
            msg = DNSIncoming(data)
            if not msg.valid or not msg.is_response():
                continue

            for rec in msg.answers():
                key = rec.name.lower()
                if isinstance(rec, DNSPointer):
                    if key == TLS_CONNECT_ZEROCONF_TYPE.lower():
                        instances[rec.alias.lower()] = rec.alias
                elif isinstance(rec, DNSService):
                    if key.endswith(suffix):
                        instances.setdefault(key, rec.name)
                        ports[key] = int(rec.port)
                        servers[key] = rec.server.lower()
                elif isinstance(rec, DNSAddress) and rec.type == _DNS_TYPE_A:
                    addresses[key] = socket.inet_ntoa(rec.address)

            missing = [n for n in instances if n not in ports and n not in srv_asked]
            if missing:
                send([(instances[n], _DNS_TYPE_SRV) for n in missing])
                srv_asked.update(missing)
            elif instances and all(n in ports for n in instances):
                break
    finally:
        sock.close()

    services: List[Dict] = []
    seen: set = set()
    for key, name in instances.items():
        port = ports.get(key)
        if not port:
            continue
        address = addresses.get(servers.get(key, ""))
        if address is not None and address != ip:
            logger.debug(
                f"[ADBmDNS] unicast answer for {name} points at {address}, not {ip}"
            )
            continue
        short = name[: -len(suffix)] if name.lower().endswith(suffix) else name
        _add_service(services, seen, short, ip, port)
    return services
