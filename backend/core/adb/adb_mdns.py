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
"""

import asyncio
import ipaddress
import logging
import re
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
