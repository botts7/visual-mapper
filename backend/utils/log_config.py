"""
Logging setup - honour the add-on `log_level` option.

run.sh exports LOG_LEVEL from the add-on options. Home Assistant offers
trace/debug/info/notice/warning/error/fatal; these map onto Python levels.
Chatty third-party libraries stay at WARNING so debug logs stay readable.
"""

import logging
import os
from typing import Optional

DEFAULT_LEVEL = logging.INFO

_LEVELS = {
    "trace": logging.DEBUG,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
    "critical": logging.CRITICAL,
}

NOISY_LOGGERS = (
    "zeroconf",
    "asyncio",
    "urllib3",
    "httpx",
    "httpcore",
    "websockets",
    "multipart",
    "PIL",
    "adb_shell",
    "aiomqtt",
)


def parse_log_level(value: Optional[str]) -> int:
    """Map a LOG_LEVEL string to a logging level. Unknown/empty -> INFO."""
    if not value:
        return DEFAULT_LEVEL
    return _LEVELS.get(value.strip().lower(), DEFAULT_LEVEL)


def configure_logging(
    level_name: Optional[str] = None,
    fmt: str = "[%(asctime)s] %(levelname)s - %(message)s",
    datefmt: str = "%Y-%m-%d %H:%M:%S",
) -> int:
    """
    Configure root logging from LOG_LEVEL (or `level_name`).

    Returns:
        The level applied to the root logger
    """
    if level_name is None:
        level_name = os.environ.get("LOG_LEVEL")
    level = parse_log_level(level_name)

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)
    # basicConfig is a no-op if handlers already exist; set the level anyway.
    logging.getLogger().setLevel(level)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(level, logging.WARNING))

    return level
