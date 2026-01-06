"""
Authentication Dependencies - Dual-Zone Security for Visual Mapper

This module implements the "Dual-Zone Security" pattern from the Server Remediation Plan:

1. **Protected Zone (Companion API):**
   - Requires `X-Companion-Key` header matching `COMPANION_API_KEY` env var
   - Used for sensitive endpoints that control devices or execute actions

2. **Localhost/Ingress Exception:**
   - Requests from localhost (127.0.0.1) are automatically trusted
   - Home Assistant Ingress requests (with X-Ingress-Path header) are trusted
   - This allows the Web UI to work without complex authentication

Usage:
    from routes.auth import verify_companion_auth

    @router.post("/sensitive-endpoint")
    async def handler(auth: bool = Depends(verify_companion_auth)):
        # Only reached if auth passes
        return {"success": True}
"""

import os
import logging
from typing import Optional
from fastapi import Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

# API Key for companion app authentication (loaded from environment)
# In standalone: set in .env file
# In HA Add-on: set via options.json -> ENV mapping
COMPANION_API_KEY = os.getenv("COMPANION_API_KEY", "")

# Trusted IP ranges for HA Add-on (Docker internal networks)
# Common Docker internal subnet: 172.16.0.0/12
HA_TRUSTED_SUBNETS = [
    "127.",      # Localhost
    "172.30.",   # HA Add-on network (common)
    "172.31.",   # HA Add-on network (alternate)
]


def _is_trusted_source(request: Request) -> bool:
    """
    Check if request originates from a trusted source.

    Trusted sources:
    1. Localhost (127.0.0.1, ::1)
    2. HA Ingress requests (have X-Ingress-Path header)
    3. Docker internal networks (172.30.x.x, etc.)

    Args:
        request: FastAPI Request object

    Returns:
        True if request is from trusted source
    """
    # Check for HA Ingress header (standard in Home Assistant)
    # When request comes through HA Ingress proxy, this header is added
    if request.headers.get("X-Ingress-Path"):
        logger.debug("[Auth] Request trusted: X-Ingress-Path header present")
        return True

    # Get client IP address
    # Check X-Forwarded-For first (common with reverse proxies)
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()

    # Fall back to direct client address
    if not client_ip and request.client:
        client_ip = request.client.host

    if not client_ip:
        logger.warning("[Auth] Could not determine client IP")
        return False

    # Check for localhost (IPv4 and IPv6)
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        logger.debug(f"[Auth] Request trusted: localhost ({client_ip})")
        return True

    # Check for trusted Docker subnets (HA Add-on internal networks)
    for subnet in HA_TRUSTED_SUBNETS:
        if client_ip.startswith(subnet):
            logger.debug(f"[Auth] Request trusted: Docker subnet ({client_ip})")
            return True

    return False


def _verify_api_key(request: Request) -> bool:
    """
    Verify the X-Companion-Key header matches COMPANION_API_KEY.

    Args:
        request: FastAPI Request object

    Returns:
        True if API key is valid
    """
    if not COMPANION_API_KEY:
        # No API key configured - allow all (development mode warning)
        logger.warning("[Auth] COMPANION_API_KEY not configured - companion auth disabled!")
        return True

    provided_key = request.headers.get("X-Companion-Key", "")

    if provided_key == COMPANION_API_KEY:
        logger.debug("[Auth] Valid X-Companion-Key provided")
        return True

    return False


async def verify_companion_auth(request: Request) -> bool:
    """
    FastAPI dependency to verify companion app authentication.

    Authentication passes if ANY of these conditions are met:
    1. Request is from localhost (127.0.0.1)
    2. Request has X-Ingress-Path header (Home Assistant Ingress)
    3. Request has valid X-Companion-Key header
    4. COMPANION_API_KEY is not configured (development mode)

    Usage:
        @router.post("/companion/execute")
        async def execute(request: Request, auth: bool = Depends(verify_companion_auth)):
            # This code only runs if auth passes
            return {"success": True}

    Raises:
        HTTPException 401: If authentication fails

    Returns:
        True (always, if no exception raised)
    """
    # Check trusted source first (localhost, HA Ingress)
    if _is_trusted_source(request):
        return True

    # Check API key
    if _verify_api_key(request):
        return True

    # Authentication failed
    client_ip = request.client.host if request.client else "unknown"
    logger.warning(f"[Auth] Unauthorized request from {client_ip} to {request.url.path}")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Valid X-Companion-Key required or access from localhost/Ingress",
        headers={"WWW-Authenticate": "X-Companion-Key"}
    )


async def optional_companion_auth(request: Request) -> Optional[bool]:
    """
    Optional authentication - doesn't raise exception if auth fails.

    Use this for endpoints that work differently based on auth status.

    Returns:
        True if authenticated, False if not (never raises exception)
    """
    try:
        return await verify_companion_auth(request)
    except HTTPException:
        return False


# Export public API
__all__ = [
    "verify_companion_auth",
    "optional_companion_auth",
    "COMPANION_API_KEY",
]
