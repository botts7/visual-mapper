"""
Startup Reconnect - reconnect one stored device when the add-on starts.

Stored device IDs (sensors_*.json "device_id") may be a stable hardware ID
after migration, which `adb connect` cannot use. Resolve to the known ip:port
endpoints first, connect through ADBBridge.connect_device (same path as a
manual connect: identity registration, migration, monitor, MQTT), and if no
endpoint answers, try TLS port recovery once on the most recent IP.
"""

import logging
from typing import Dict, Iterable, Optional

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
