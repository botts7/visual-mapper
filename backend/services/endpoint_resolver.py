"""
Endpoint Resolver - turn any stored device ID into ADB ip:port endpoints.

After stable-ID migration, stored IDs (sensors_*.json "device_id", monitor
entries, flows) may be a hardware serial instead of ip:port. `adb connect`
needs ip:port, so resolve through the identity registry first.
"""

import logging
import os
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


def split_endpoint(device_id: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
    """Split "ip:port" into (ip, port). Returns (None, None) for anything else."""
    if not device_id or ":" not in device_id:
        return None, None
    host, _, port = device_id.rpartition(":")
    if not host or not port.isdigit():
        return None, None
    return host, int(port)


def is_network_endpoint(device_id: Optional[str]) -> bool:
    return split_endpoint(device_id)[0] is not None


def _default_resolver():
    try:
        from services.device_identity import get_device_identity_resolver

        return get_device_identity_resolver(os.environ.get("DATA_DIR", "data"))
    except Exception as e:
        logger.debug(f"[EndpointResolver] identity registry unavailable: {e}")
        return None


def resolve_stable_id(
    device_id: str, resolver=None, device_map: Optional[Dict[str, Iterable[str]]] = None
) -> Optional[str]:
    """
    Stable ID for a stored device ID.

    ip:port -> registry/migrator lookup (None if unknown).
    anything else -> registry mapping, else the ID itself (it is a stable ID).
    """
    if not device_id:
        return None
    resolver = resolver if resolver is not None else _default_resolver()

    if is_network_endpoint(device_id):
        if resolver is not None:
            stable = resolver.get_stable_id(device_id)
            if stable:
                return stable
        for stable, ids in (device_map or {}).items():
            if device_id in ids:
                return stable
        return None

    if resolver is not None:
        return resolver.resolve_any_id(device_id) or device_id
    return device_id


def resolve_adb_endpoints(
    device_id: str, resolver=None, device_map: Optional[Dict[str, Iterable[str]]] = None
) -> List[str]:
    """
    ADB ip:port endpoints for a stored device ID, most recent first.

    ip:port input is returned as-is. A stable ID resolves to the registry's
    current connection, then its connection history (newest first), then any
    other ip:port the migrator knows (order unknown).
    """
    if not device_id:
        return []
    if is_network_endpoint(device_id):
        return [device_id]

    resolver = resolver if resolver is not None else _default_resolver()
    stable = resolve_stable_id(device_id, resolver, device_map)

    candidates: List[str] = []
    if resolver is not None and stable:
        current = resolver.get_connection_id(stable)
        if current:
            candidates.append(current)
        info = resolver.get_device_info(stable) or {}
        candidates.extend(reversed(info.get("connection_history", []) or []))
    for key in dict.fromkeys([device_id, stable]):
        candidates.extend(sorted((device_map or {}).get(key, ()) or ()))

    endpoints: List[str] = []
    for candidate in candidates:
        if is_network_endpoint(candidate) and candidate not in endpoints:
            endpoints.append(candidate)
    return endpoints
