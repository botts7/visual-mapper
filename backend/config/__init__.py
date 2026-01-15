"""
Visual Mapper Configuration Module

Provides centralized configuration management.

Usage:
    from config import Defaults
    timeout = Defaults.API_TIMEOUT
"""

from .defaults import Defaults, AppDefaults, load_defaults_from_env

__all__ = ["Defaults", "AppDefaults", "load_defaults_from_env"]
