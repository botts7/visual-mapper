"""
Startup Reconnect - reconnect one stored device when the add-on starts.

Stored device IDs (sensors_*.json "device_id") may be a stable hardware ID
after migration, which `adb connect` cannot use. Resolve to the known ip:port
endpoints first, connect through ADBBridge.connect_device (same path as a
manual connect: identity registration, migration, monitor, MQTT), and if no
endpoint answers, try TLS port recovery once on the most recent IP.
"""

import logging
import os
from typing import Dict, Iterable, Mapping, Optional

from services.endpoint_resolver import (
    resolve_adb_endpoints,
    resolve_stable_id,
    split_endpoint,
)

logger = logging.getLogger(__name__)


async def reconnect_stored_device(
    stored_id: str,
    adb_bridge,
    connection_monitor=None,
    resolver=None,
    device_map: Optional[Dict[str, Iterable[str]]] = None,
) -> Optional[str]:
    """
    Reconnect a device from its stored ID.

    Returns:
        The connected ip:port, or None
    """
    endpoints = resolve_adb_endpoints(stored_id, resolver, device_map)
    if not endpoints:
        logger.info(f"[Server] Auto-reconnect: no ip:port known for {stored_id}, skipping")
        return None
    if endpoints != [stored_id]:
        logger.info(f"[Server] Auto-reconnect: {stored_id} resolved to {endpoints}")

    for endpoint in endpoints:
        host, port = split_endpoint(endpoint)
        try:
            device_id = await adb_bridge.connect_device(host, port)
            logger.info(f"[Server] Auto-reconnected to {device_id}")
            return device_id
        except Exception as e:
            logger.info(f"[Server] Auto-reconnect to {endpoint} failed: {e}")

    stable_id = resolve_stable_id(stored_id, resolver, device_map)
    if not stable_id or connection_monitor is None:
        return None
    # Android 11+ wireless debugging may be on a new TLS port (same IP)
    return await connection_monitor.recover_moved_endpoint(endpoints[0], stable_id)


async def connect_configured_device(
    adb_bridge, env: Optional[Mapping[str, str]] = None
) -> Optional[str]:
    """
    Connect the device set in the add-on options (adb_device_ip/port).

    Reads ADB_DEVICE_IP and ADB_DEVICE_PORT (default 5555). Does nothing when
    the IP is empty. Uses connect_device, the same path as a manual connect.

    Returns:
        The connected ip:port, or None
    """
    env = os.environ if env is None else env
    host = (env.get("ADB_DEVICE_IP") or "").strip()
    if not host:
        return None
    port_text = (env.get("ADB_DEVICE_PORT") or "").strip()
    try:
        port = int(port_text) if port_text else 5555
    except ValueError:
        logger.warning(f"[Server] Invalid ADB_DEVICE_PORT {port_text!r}, using 5555")
        port = 5555

    try:
        device_id = await adb_bridge.connect_device(host, port)
        logger.info(f"[Server] Connected configured device {device_id}")
        return device_id
    except Exception as e:
        logger.warning(f"[Server] Could not connect configured device {host}:{port}: {e}")
        return None
