"""
TLS Endpoint Recovery - find a wireless device after its debug port changed.

Android 11+ wireless debugging listens on a random TLS port that changes
whenever wireless debugging restarts (toggle, reboot, Wi-Fi reconnect). The
device stays paired and keeps its IP, so the stored ip:port goes stale.

This looks up the device's current `_adb-tls-connect._tcp` mDNS endpoint on
the same IP, connects to it and only accepts it if the stable device ID
matches. Shared by the connection monitor and startup auto-reconnect.
"""

import logging
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


def split_endpoint(device_id: str):
    """Split "ip:port" into (ip, port). Returns (None, None) for USB serials."""
    if not device_id or ":" not in device_id:
        return None, None
    ip, _, port = device_id.rpartition(":")
    if not port.isdigit():
        return None, None
    return ip, int(port)


async def find_moved_tls_endpoint(
    adb_bridge,
    old_device_id: str,
    stable_device_id: str,
    on_rejected: Optional[Callable[[str], Awaitable[None]]] = None,
) -> Optional[str]:
    """
    Connect to the device's new wireless debugging port, verified by stable ID.

    Args:
        adb_bridge: ADBBridge (list_tls_connect_services, connect_device,
            get_device_serial, disconnect_device)
        old_device_id: Stale "ip:port" endpoint
        stable_device_id: Stable ID recorded for that device
        on_rejected: Optional async callback for a candidate that turned out
            to be a different device (after it was disconnected)

    Returns:
        New device_id ("ip:port") if found and verified, else None
    """
    old_ip, old_port = split_endpoint(old_device_id)
    if not old_ip or not stable_device_id:
        return None

    services = await adb_bridge.list_tls_connect_services()
    candidates = [
        s for s in services if s["ip"] == old_ip and s["port"] != old_port
    ]
    if not candidates:
        logger.debug(
            f"[TLSRecovery] No new wireless debugging port advertised for {old_ip}"
        )
        return None

    for service in candidates:
        candidate = f"{service['ip']}:{service['port']}"
        logger.info(
            f"[TLSRecovery] Found new wireless debugging port {candidate} "
            f"({service['name']}) for {old_device_id}, stable ID {stable_device_id}"
        )
        try:
            new_device_id = await adb_bridge.connect_device(
                service["ip"], service["port"]
            )
        except Exception as e:
            logger.info(f"[TLSRecovery] Could not connect to {candidate}: {e}")
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
            return new_device_id

        logger.warning(
            f"[TLSRecovery] {new_device_id} is a different device "
            f"(stable ID {serial}, expected {stable_device_id}), disconnecting"
        )
        try:
            await adb_bridge.disconnect_device(new_device_id)
        except Exception as e:
            logger.debug(f"[TLSRecovery] Disconnect of {new_device_id} failed: {e}")
        if on_rejected:
            try:
                await on_rejected(new_device_id)
            except Exception as e:
                logger.debug(f"[TLSRecovery] on_rejected for {new_device_id} failed: {e}")

    return None
