"""
Centralized Version Management for Visual Mapper

Reads version from .build-version file to ensure consistency
across all modules (API, MQTT, logs, etc.)
"""
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def get_version() -> str:
    """
    Read version from .build-version file.

    Searches in multiple locations to support both Docker and local development:
    - /app/.build-version (Docker container)
    - backend/../.build-version (local dev - one level up from backend)
    - backend/../../.build-version (alternative local layout)

    Returns:
        Version string (e.g., "0.2.35") or "unknown" if file not found
    """
    version_paths = [
        Path("/app/.build-version"),  # Docker container
        Path(__file__).parent.parent.parent / ".build-version",  # Local dev (backend/../)
        Path(__file__).parent.parent / ".build-version",  # Alternative layout
    ]

    for path in version_paths:
        if path.exists():
            version = path.read_text().strip()
            logger.debug(f"[Version] Loaded version {version} from {path}")
            return version

    logger.warning("[Version] .build-version file not found, using 'unknown'")
    return "unknown"


# Module-level constant for easy import
APP_VERSION = get_version()
