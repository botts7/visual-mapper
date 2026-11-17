"""
TLS Endpoint Recovery - find a wireless device after its debug port changed.

Android 11+ wireless debugging listens on a random TLS port that changes
whenever wireless debugging restarts (toggle, reboot, Wi-Fi reconnect). The
device stays paired and keeps its IP, so the stored ip:port goes stale.

This looks up the device's current `_adb-tls-connect._tcp` mDNS endpoint on
the same IP, connects to it and only accepts it if the stable device ID
matches. Shared by the connection monitor and startup auto-reconnect.

Every attempt logs one INFO summary line:
  [TLSRecovery] lookup for <old> (stable <id>): adb=..., zeroconf=...,
  unicast=...; candidates on <ip>: [...]; result=...
"""

import logging
from typing import Awaitable, Callable, Dict, Iterable, List, Optional

from services.endpoint_resolver import resolve_adb_endpoints, split_endpoint

logger = logging.getLogger(__name__)

__all__ = ["find_moved_tls_endpoint", "split_endpoint"]


async def find_moved_tls_endpoint(
    adb_bridge,
    old_device_id: str,
    stable_device_id: str,
    on_rejected: Optional[Callable[[str], Awaitable[None]]] = None,
    resolver=None,
    device_map: Optional[Dict[str, Iterable[str]]] = None,
) -> Optional[str]:
    """
    Connect to the device's new wireless debugging port, verified by stable ID.

    Args:
        adb_bridge: ADBBridge (lookup_tls_connect_services, connect_device,
            get_device_serial, disconnect_device)
        old_device_id: Stale "ip:port" endpoint, or a stable ID whose last
            ip:port is resolved through the identity registry
        stable_device_id: Stable ID recorded for that device
        on_rejected: Optional async callback for a candidate that turned out
            to be a different device (after it was disconnected)
        resolver / device_map: Identity registry and migrator map used to
            resolve a non ip:port `old_device_id` (defaults to the registry)

    Returns:
        New device_id ("ip:port") if found and verified, else None
    """
    endpoints = resolve_adb_endpoints(old_device_id, resolver, device_map)
    old_endpoint = endpoints[0] if endpoints else None
    old_ip, old_port = split_endpoint(old_endpoint)
    prefix = f"[TLSRecovery] lookup for {old_device_id} (stable {stable_device_id})"

    if not old_ip or not stable_device_id:
        logger.info(f"{prefix}: no ip:port known; result=none")
        return None

    try:
        report = await adb_bridge.lookup_tls_connect_services(target_ip=old_ip)
    except Exception as e:
        logger.info(f"{prefix}: lookup failed ({e}); result=none")
        return None

    services = report.get("services", [])
    candidates = [s for s in services if s["ip"] == old_ip and s["port"] != old_port]
    sources = (
        f"adb={report.get('adb')}, zeroconf={report.get('zeroconf')}, "
        f"unicast={report.get('unicast')}"
    )
    candidate_ports = [s["port"] for s in candidates]
    if old_endpoint != old_device_id:
        prefix = f"{prefix} via {old_endpoint}"

    outcomes: List[str] = []
    adopted = None
    for service in candidates:
        candidate = f"{service['ip']}:{service['port']}"
        logger.info(
            f"[TLSRecovery] Found new wireless debugging port {candidate} "
            f"({service['name']}) for {old_endpoint}, stable ID {stable_device_id}"
        )
        try:
            new_device_id = await adb_bridge.connect_device(
                service["ip"], service["port"]
            )
        except Exception as e:
            logger.info(f"[TLSRecovery] Could not connect to {candidate}: {e}")
            outcomes.append(f"connect failed ({candidate})")
            continue

        try:
            serial = await adb_bridge.get_device_serial(
                new_device_id, force_refresh=True
            )
        except Exception as e:
            logger.warning(f"[TLSRecovery] Identity check failed for {candidate}: {e}")
            serial = None

        if serial == stable_device_id:
            logger.info(
                f"[TLSRecovery] Verified {new_device_id} is stable ID {stable_device_id}"
            )
            adopted = new_device_id
            break

        logger.warning(
            f"[TLSRecovery] {new_device_id} is a different device "
            f"(stable ID {serial}, expected {stable_device_id}), disconnecting"
        )
        outcomes.append(f"rejected (serial mismatch: {new_device_id} is {serial})")
        try:
            await adb_bridge.disconnect_device(new_device_id)
        except Exception as e:
            logger.debug(f"[TLSRecovery] Disconnect of {new_device_id} failed: {e}")
        if on_rejected:
            try:
                await on_rejected(new_device_id)
            except Exception as e:
                logger.debug(f"[TLSRecovery] on_rejected for {new_device_id} failed: {e}")

    if adopted:
        result = f"adopted {adopted}"
    elif outcomes:
        result = "; ".join(outcomes)
    elif services:
        result = f"none ({len(services)} services, none on {old_ip} with a new port)"
    else:
        result = "none"

    logger.info(
        f"{prefix}: {sources}; candidates on {old_ip}: {candidate_ports}; result={result}"
    )
    return adopted
