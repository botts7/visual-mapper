"""
Screenshot Stitcher Package

A modular refactoring of the monolithic screenshot_stitcher.py (3133 lines).
This package provides the same functionality with better maintainability.

Modules:
- utils: Utility functions (duplicate removal, height estimation)
- device: Device control and scrolling (Phase 2)
- elements: Element fingerprinting and analysis (Phase 3)
- overlap: Overlap detection and image comparison (Phase 4)
- compose: Image stitching and composition (Phase 5)
"""

# Import utility functions
from .utils import (
    remove_consecutive_duplicates,
    estimate_from_patterns,
    estimate_from_numbered_items,
    estimate_from_bounds,
    get_scrollable_container_info,
    get_element_y_center,
)

# Import device controller
from .device import DeviceController

# Import element analyzer
from .elements import ElementAnalyzer

# Import overlap detector
from .overlap import OverlapDetector

# Import image composer
from .compose import ImageComposer

# Main ScreenshotStitcher class remains in screenshot_stitcher.py
# and imports from this package for modular composition

__all__ = [
    # Utils
    'remove_consecutive_duplicates',
    'estimate_from_patterns',
    'estimate_from_numbered_items',
    'estimate_from_bounds',
    'get_scrollable_container_info',
    'get_element_y_center',
    # Device
    'DeviceController',
    # Elements
    'ElementAnalyzer',
    # Overlap
    'OverlapDetector',
    # Compose
    'ImageComposer',
]

__version__ = '0.1.0'
