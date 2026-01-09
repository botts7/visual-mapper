"""
Screenshot Stitcher Device Module

Contains device control methods:
- scroll_to_top, scroll_to_bottom: Navigate scroll position
- refresh_page: Pull-to-refresh gesture
- capture_screenshot_pil: Capture screenshot as PIL Image
- get_ui_elements_with_retry: Get UI elements with retry logic
- get_device_nav_info: Get device navigation configuration
- get_scroll_position: Get current scroll position
- find_safe_scroll_x: Find safe X coordinate for scrolling
"""

import logging
import asyncio
import io
import subprocess
from typing import Optional
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)


class DeviceController:
    """Handles device control operations for screenshot stitching."""

    def __init__(self, adb_bridge):
        """
        Initialize device controller.

        Args:
            adb_bridge: ADB bridge instance for device communication
        """
        self.adb_bridge = adb_bridge

    async def get_device_nav_info(self, device_id: str) -> dict:
        """
        Get device navigation configuration to properly detect footer.

        Handles:
        - 3-button navigation (visible nav bar ~48px)
        - 2-button navigation (visible nav bar ~40px)
        - Gesture navigation (NO visible nav bar, just thin hint ~20px)
        - Fullscreen apps (NO nav bar at all)

        Returns:
            Dict with nav_mode, has_nav_bar, is_fullscreen, estimated_nav_height
        """
        try:
            # Get navigation mode
            def _get_nav_mode():
                result = subprocess.run(
                    ['adb', '-s', device_id, 'shell', 'settings', 'get', 'secure', 'navigation_mode'],
                    capture_output=True, text=True, timeout=5
                )
                try:
                    return int(result.stdout.strip())
                except:
                    return 0  # Default to 3-button

            # Check if app is fullscreen
            def _check_fullscreen():
                result = subprocess.run(
                    ['adb', '-s', device_id, 'shell', 'dumpsys', 'window', 'windows'],
                    capture_output=True, text=True, timeout=5
                )
                return 'FLAG_FULLSCREEN' in result.stdout or 'mIsFullscreen=true' in result.stdout

            nav_mode = await asyncio.to_thread(_get_nav_mode)
            is_fullscreen = await asyncio.to_thread(_check_fullscreen)

            # Determine if nav bar is visible
            # Mode 2 = gesture navigation (no visible nav bar, just a thin line)
            has_nav_bar = nav_mode != 2 and not is_fullscreen

            # Estimate nav bar height based on mode
            if is_fullscreen:
                estimated_nav_height = 0
            elif nav_mode == 2:  # Gesture
                estimated_nav_height = 20  # Just the gesture hint line
            elif nav_mode == 1:  # 2-button
                estimated_nav_height = 40
            else:  # 3-button (mode 0)
                estimated_nav_height = 48

            logger.info(f"[NavInfo] mode={nav_mode}, has_nav_bar={has_nav_bar}, fullscreen={is_fullscreen}, nav_height={estimated_nav_height}")

            return {
                'nav_mode': nav_mode,
                'has_nav_bar': has_nav_bar,
                'is_fullscreen': is_fullscreen,
                'estimated_nav_height': estimated_nav_height
            }

        except Exception as e:
            logger.warning(f"[NavInfo] Failed to get nav info: {e}")
            # Return safe defaults - assume nav bar exists
            return {
                'nav_mode': 0,
                'has_nav_bar': True,
                'is_fullscreen': False,
                'estimated_nav_height': 48
            }

    async def refresh_page(self, device_id: str, times: int = 3):
        """
        Refresh the page by swiping down from top (pull-to-refresh gesture).
        Many apps support this to refresh content.
        """
        try:
            # Get screen size
            img = await self.capture_screenshot_pil(device_id)
            if not img:
                return
            width, height = img.size

            for i in range(times):
                logger.debug(f"  Refresh {i+1}/{times}...")
                # Swipe DOWN from near top to middle (pull-to-refresh)
                swipe_x = width // 2
                swipe_start_y = int(height * 0.15)  # Start near top
                swipe_end_y = int(height * 0.60)    # End in middle

                await self.adb_bridge.swipe(
                    device_id,
                    swipe_x, swipe_start_y,
                    swipe_x, swipe_end_y,
                    duration=300
                )
                await asyncio.sleep(1.5)  # Wait for refresh animation

            logger.info(f"  Page refreshed {times} times")

        except Exception as e:
            logger.warning(f"  Page refresh failed: {e}")

    async def scroll_to_bottom(self, device_id: str, max_attempts: int = 5):
        """
        Scroll to the bottom of the current scrollable view.
        Uses multiple swipe up gestures until we can't scroll anymore.
        Matches stable stitcher behavior exactly.
        """
        try:
            for attempt in range(max_attempts):
                img_before = await self.capture_screenshot_pil(device_id)
                if not img_before:
                    break

                width, height = img_before.size
                swipe_x = width // 2
                # Swipe UP (finger moves up) to scroll DOWN
                swipe_start_y = int(height * 0.70)
                swipe_end_y = int(height * 0.30)

                await self.adb_bridge.swipe(device_id, swipe_x, swipe_start_y, swipe_x, swipe_end_y, duration=300)
                await asyncio.sleep(0.3)

                img_after = await self.capture_screenshot_pil(device_id)
                if not img_after:
                    break

                similarity = self._compare_images(img_before, img_after)
                if similarity > 0.98:
                    logger.debug(f"  Reached bottom after {attempt + 1} scroll(s)")
                    break

            logger.info(f"  Scroll to bottom complete")

        except Exception as e:
            logger.warning(f"  Scroll to bottom failed: {e}")

    async def scroll_to_top(self, device_id: str, max_attempts: int = 3):
        """
        Scroll to the top of the current scrollable view.
        Matches stable stitcher behavior exactly.
        """
        try:
            for attempt in range(max_attempts):
                # Capture before scroll
                img_before = await self.capture_screenshot_pil(device_id)
                if not img_before:
                    break

                # Swipe DOWN to scroll UP (opposite of normal scrolling)
                width, height = img_before.size
                swipe_x = width // 2
                swipe_start_y = int(height * 0.30)
                swipe_end_y = int(height * 0.70)

                await self.adb_bridge.swipe(
                    device_id,
                    swipe_x, swipe_start_y,
                    swipe_x, swipe_end_y,
                    duration=300
                )
                await asyncio.sleep(0.3)

                # Capture after scroll
                img_after = await self.capture_screenshot_pil(device_id)
                if not img_after:
                    break

                # Check if we actually scrolled (images different)
                similarity = self._compare_images(img_before, img_after)
                if similarity > 0.98:  # Images nearly identical = at top
                    logger.debug(f"  Reached top after {attempt + 1} scroll(s)")
                    break

            logger.info(f"  Scroll to top complete")

        except Exception as e:
            logger.warning(f"  Scroll to top failed: {e}, continuing anyway")

    async def capture_screenshot_pil(self, device_id: str) -> Optional[Image.Image]:
        """Capture screenshot and return as PIL Image"""
        try:
            screenshot_bytes = await self.adb_bridge.capture_screenshot(device_id)
            if not screenshot_bytes:
                return None

            return Image.open(io.BytesIO(screenshot_bytes))

        except Exception as e:
            logger.error(f"[DeviceController] Screenshot capture failed: {e}")
            return None

    async def get_ui_elements_with_retry(self, device_id: str, max_retries: int = 3) -> list:
        """
        Get UI elements with retry logic. uiautomator can be flaky,
        especially right after scrolling.

        Returns:
            List of UI elements, or empty list if all retries fail
        """
        # Initial delay to let screen stabilize after any scroll
        await asyncio.sleep(0.3)

        for attempt in range(max_retries):
            try:
                # Additional delay on retries
                if attempt > 0:
                    await asyncio.sleep(0.5)

                elements = await self.adb_bridge.get_ui_elements(device_id)

                if elements:  # Got elements successfully
                    return elements
                else:
                    logger.warning(f"  UI elements attempt {attempt + 1}: empty result")

            except Exception as e:
                logger.warning(f"  UI elements attempt {attempt + 1}/{max_retries} failed: {e}")

        logger.warning(f"  All UI element retries failed - using pixel-only stitching")
        return []

    async def get_scroll_position(self, device_id: str) -> Optional[int]:
        """
        Get current scroll position from UI hierarchy

        Returns Y-coordinate of scrollable view or None if unavailable
        """
        try:
            import re
            # Get UI hierarchy
            ui_elements = await self.adb_bridge.get_ui_elements(device_id)

            # Look for scrollable views
            for element in ui_elements:
                if element.get("scrollable") == "true":
                    bounds = element.get("bounds", "")
                    # Parse bounds format: "[x1,y1][x2,y2]"
                    if bounds:
                        # Extract Y coordinate as scroll position
                        match = re.search(r'\[(\d+),(\d+)\]', bounds)
                        if match:
                            return int(match.group(2))

            # Fallback: return None (can't detect position)
            return None

        except Exception as e:
            logger.warning(f"  Get scroll position failed: {e}")
            return None

    def find_safe_scroll_x(self, screen_width: int, elements: list) -> int:
        """
        Find a safe X coordinate for scrolling that avoids interactive elements.

        Analyzes the UI elements to find a vertical strip without clickable elements
        like buttons, links, inputs, etc.

        Args:
            screen_width: Width of the screen in pixels
            elements: List of UI elements from UI hierarchy

        Returns:
            Safe X coordinate for scrolling (defaults to 85% of width if no safe area found)
        """
        import re

        # Interactive element types that we want to avoid
        interactive_classes = [
            'button', 'edittext', 'checkbox', 'switch', 'radio',
            'imagebutton', 'spinner', 'seekbar', 'ratingbar',
            'compoundbutton', 'togglebutton', 'link'
        ]

        # Track which X ranges are occupied by interactive elements
        # We'll divide the screen into 20 columns and mark which are "dangerous"
        num_columns = 20
        column_width = screen_width // num_columns
        dangerous_columns = set()

        for elem in elements:
            # Check if this is an interactive element
            class_name = (elem.get('class', '') or '').lower()
            clickable = elem.get('clickable', False)
            focusable = elem.get('focusable', False)

            is_interactive = clickable or focusable
            for ic in interactive_classes:
                if ic in class_name:
                    is_interactive = True
                    break

            if not is_interactive:
                continue

            # Get element bounds
            bounds = elem.get('bounds', {})
            if isinstance(bounds, dict):
                x = bounds.get('x', 0)
                width = bounds.get('width', 0)
            elif isinstance(bounds, str):
                # Parse "[x1,y1][x2,y2]" format
                match = re.findall(r'\[(\d+),(\d+)\]', bounds)
                if len(match) >= 2:
                    x = int(match[0][0])
                    x2 = int(match[1][0])
                    width = x2 - x
                else:
                    continue
            else:
                continue

            # Mark columns covered by this element as dangerous
            start_col = max(0, x // column_width)
            end_col = min(num_columns - 1, (x + width) // column_width)
            for col in range(start_col, end_col + 1):
                dangerous_columns.add(col)

        # Find the safest column (preferring right side of screen)
        # Start from column 17 (85%) and work backwards, then forwards
        preferred_order = list(range(17, num_columns)) + list(range(16, -1, -1))

        for col in preferred_order:
            if col not in dangerous_columns:
                safe_x = col * column_width + column_width // 2
                logger.debug(f"  Safe scroll column {col} at x={safe_x}")
                return safe_x

        # If all columns are dangerous, use right edge (least likely to have buttons)
        safe_x = int(screen_width * 0.85)
        logger.debug(f"  No safe column found, using x={safe_x} (85%)")
        return safe_x

    def _compare_images(self, img1: Image.Image, img2: Image.Image) -> float:
        """
        Compare two images for similarity using structural comparison.

        Returns:
            Float between 0.0 (completely different) and 1.0 (identical)
        """
        try:
            # Convert to numpy arrays
            arr1 = np.array(img1)
            arr2 = np.array(img2)

            # Ensure same size
            if arr1.shape != arr2.shape:
                return 0.0

            # Convert to grayscale for comparison using PIL
            if len(arr1.shape) == 3:
                gray1 = np.array(img1.convert('L'))
                gray2 = np.array(img2.convert('L'))
            else:
                gray1, gray2 = arr1, arr2

            # Calculate Structural Similarity Index (SSIM-like)
            # Using normalized cross-correlation
            mean1 = np.mean(gray1)
            mean2 = np.mean(gray2)

            # Subtract means
            norm1 = gray1.astype(np.float64) - mean1
            norm2 = gray2.astype(np.float64) - mean2

            # Calculate correlation
            numerator = np.sum(norm1 * norm2)
            denominator = np.sqrt(np.sum(norm1**2) * np.sum(norm2**2))

            if denominator == 0:
                return 1.0 if numerator == 0 else 0.0

            correlation = numerator / denominator

            # Normalize to 0-1 range (correlation is -1 to 1)
            similarity = (correlation + 1) / 2

            return float(similarity)

        except Exception as e:
            logger.error(f"  Image comparison failed: {e}")
            return 0.0
