"""
Visual Mapper - Screenshot Stitcher (Phase 8)
Captures full scrollable pages using OpenCV template matching

Performance Target: ~1s per scroll, <25s for 20-screen page
"""

import logging
import asyncio
import time
import base64
from typing import Tuple, Optional, Dict, Any
from PIL import Image
import numpy as np
import cv2
import io

logger = logging.getLogger(__name__)


class ScreenshotStitcher:
    """
    Stitches multiple screenshots together to capture full scrollable pages
    Uses OpenCV template matching for pixel-perfect alignment
    """

    def __init__(self, adb_bridge):
        """
        Initialize screenshot stitcher

        Args:
            adb_bridge: ADB bridge instance for device communication
        """
        self.adb_bridge = adb_bridge

        # Configuration - TUNED VALUES based on testing
        self.scroll_ratio = 0.40  # Scroll 40% of screen height per swipe
        self.overlap_ratio = 0.30  # 30% overlap for reliable matching
        self.match_threshold = 0.8  # Template match quality threshold
        self.scroll_delay_ms = 1000  # Wait 1 second after scroll for animation to settle (was 600ms)
        self.max_scrolls = 20  # Safety limit
        self.duplicate_threshold = 0.95  # If images > 95% similar, we're not scrolling
        self.min_new_content_ratio = 0.05  # Need at least 5% new content to continue (was 15% - too strict)
        self.fixed_element_threshold = 0.98  # Threshold for detecting fixed UI elements

        # Element tracking for smart stitching
        self.use_element_tracking = True  # Use UI elements for precise stitching

        logger.info("[ScreenshotStitcher] Initialized")

    async def capture_scrolling_screenshot(
        self,
        device_id: str,
        max_scrolls: Optional[int] = None,
        scroll_ratio: Optional[float] = None,
        overlap_ratio: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Capture full scrollable page using BOOKEND strategy:
        1. Capture TOP screenshot
        2. Scroll to BOTTOM and capture
        3. Check if TOP/BOTTOM overlap (short page - just 2 screenshots needed)
        4. If no overlap, fill in the middle with incremental scrolls

        Returns:
            Dictionary with:
                - image: PIL Image of stitched screenshot
                - metadata: Capture statistics
                - debug_screenshots: List of individual captures for debugging
        """
        start_time = time.time()

        # Use provided values or defaults
        max_scrolls = max_scrolls or self.max_scrolls
        scroll_ratio = scroll_ratio or self.scroll_ratio
        overlap_ratio = overlap_ratio or self.overlap_ratio

        logger.info(f"[ScreenshotStitcher] Starting BOOKEND capture for {device_id}")

        try:
            # === STEP 0: Refresh page (optional but recommended) ===
            logger.info("  STEP 0: Refreshing page 3 times...")
            await self._refresh_page(device_id, times=3)

            # === STEP 1: Capture TOP ===
            logger.info("  STEP 1: Scrolling to TOP...")
            await self._scroll_to_top(device_id)
            await asyncio.sleep(0.5)

            img_top = await self._capture_screenshot_pil(device_id)
            if not img_top:
                raise RuntimeError("Failed to capture TOP screenshot")

            elements_top = await self._get_ui_elements_with_retry(device_id)
            width, height = img_top.size
            logger.info(f"  TOP: {len(elements_top)} UI elements, screen {width}x{height}")

            # Build fingerprint set for TOP
            fp_top = set()
            for elem in elements_top:
                fp = self._get_element_fingerprint(elem)
                if fp:
                    fp_top.add(fp)

            # === STEP 2: Scroll to BOTTOM and capture ===
            logger.info("  STEP 2: Scrolling to BOTTOM...")
            await self._scroll_to_bottom(device_id, max_attempts=5)
            await asyncio.sleep(0.5)

            img_bottom = await self._capture_screenshot_pil(device_id)
            if not img_bottom:
                raise RuntimeError("Failed to capture BOTTOM screenshot")

            elements_bottom = await self._get_ui_elements_with_retry(device_id)
            logger.info(f"  BOTTOM: {len(elements_bottom)} UI elements")

            # Build fingerprint set for BOTTOM
            fp_bottom = set()
            for elem in elements_bottom:
                fp = self._get_element_fingerprint(elem)
                if fp:
                    fp_bottom.add(fp)

            # === STEP 3: Check for overlap ===
            overlap = fp_top & fp_bottom
            logger.info(f"  OVERLAP CHECK: {len(overlap)} common elements between TOP and BOTTOM")

            # If TOP and BOTTOM share elements, we can stitch them directly
            if len(overlap) >= 3:
                # Short page - just 2 screenshots needed!
                logger.info("  Short page detected - using 2-screenshot stitch")
                overlap_end_y = self._find_overlap_end_y(elements_top, elements_bottom, height)
                logger.info(f"  Overlap ends at y={overlap_end_y} in BOTTOM screenshot")
                captures = [
                    (img_top, elements_top, 0),
                    (img_bottom, elements_bottom, overlap_end_y)  # Crop from where overlap ends
                ]
                scroll_count = 1  # We only did one scroll (to bottom)
            else:
                # Long page - need to capture middle content
                logger.info("  Long page - need to capture MIDDLE content")

                # Go back to top
                logger.info("  Scrolling back to TOP...")
                await self._scroll_to_top(device_id)
                await asyncio.sleep(0.5)

                # Re-capture top (it's our starting point)
                img_top = await self._capture_screenshot_pil(device_id)
                elements_top = await self._get_ui_elements_with_retry(device_id)

                # Track all seen elements
                seen_elements = {}
                for elem in elements_top:
                    fp = self._get_element_fingerprint(elem)
                    if fp:
                        seen_elements[fp] = self._get_element_y_center(elem)

                captures = [(img_top, elements_top, 0)]
                scroll_count = 0
                prev_img = img_top

                # Incremental scroll until we see elements from BOTTOM screenshot
                for i in range(max_scrolls):
                    logger.info(f"  MIDDLE scroll {i+1}/{max_scrolls}...")

                    # Perform scroll
                    swipe_x = width // 2
                    swipe_start_y = int(height * 0.70)
                    swipe_distance = int(height * scroll_ratio)
                    swipe_end_y = max(int(height * 0.15), swipe_start_y - swipe_distance)

                    logger.info(f"  >>> SWIPE: y={swipe_start_y}->{swipe_end_y} ({swipe_start_y - swipe_end_y}px)")

                    await self.adb_bridge.swipe(device_id, swipe_x, swipe_start_y, swipe_x, swipe_end_y, duration=600)
                    scroll_count += 1
                    await asyncio.sleep(self.scroll_delay_ms / 1000)

                    # Capture
                    img_mid = await self._capture_screenshot_pil(device_id)
                    if not img_mid:
                        break

                    elements_mid = await self._get_ui_elements_with_retry(device_id)

                    # Find new elements and check if we've reached bottom content
                    new_elements = []
                    first_new_y = height
                    reached_bottom_content = False

                    for elem in elements_mid:
                        fp = self._get_element_fingerprint(elem)
                        if fp:
                            y = self._get_element_y_center(elem)
                            if fp not in seen_elements:
                                new_elements.append((fp, y))
                                if y < first_new_y:
                                    first_new_y = y
                                seen_elements[fp] = y
                            # Check if this element is from the BOTTOM screenshot
                            if fp in fp_bottom:
                                reached_bottom_content = True

                    logger.info(f"  Scroll {i+1}: {len(new_elements)} new elements, reached_bottom={reached_bottom_content}")

                    if len(new_elements) > 0:
                        captures.append((img_mid, elements_mid, first_new_y))

                    # Stop if we've reached content from the bottom screenshot
                    if reached_bottom_content:
                        logger.info("  Reached BOTTOM content - adding final screenshot")
                        # Add the actual bottom screenshot as final
                        overlap_end = self._find_overlap_end_y(elements_mid, elements_bottom, height)
                        captures.append((img_bottom, elements_bottom, overlap_end))
                        break

                    # Check for image similarity (backup)
                    if self._compare_images(prev_img, img_mid) > self.duplicate_threshold:
                        logger.info("  Bottom detected by image similarity")
                        break

                    prev_img = img_mid

            # === STEP 4: Stitch ===
            logger.info(f"  Stitching {len(captures)} screenshots...")
            stitched = self._stitch_by_elements(captures, height)

            # === STEP 5: Build metadata ===
            duration_ms = int((time.time() - start_time) * 1000)
            final_width, final_height = stitched.size

            debug_screenshots = []
            for i, (img, elements, first_new_y) in enumerate(captures):
                img_buffer = io.BytesIO()
                img.save(img_buffer, format='PNG')
                img_buffer.seek(0)
                debug_screenshots.append({
                    'index': i,
                    'image': base64.b64encode(img_buffer.read()).decode('utf-8'),
                    'element_count': len(elements),
                    'first_new_y': first_new_y
                })

            metadata = {
                "scroll_count": scroll_count,
                "capture_count": len(captures),
                "final_width": final_width,
                "final_height": final_height,
                "original_height": height,
                "duration_ms": duration_ms,
                "bottom_reached": True,
                "avg_scroll_time_ms": duration_ms // max(1, scroll_count) if scroll_count > 0 else duration_ms,
                "strategy": "bookend" if len(overlap) >= 3 else "incremental"
            }

            logger.info(f"[ScreenshotStitcher] Complete: {final_width}x{final_height} in {duration_ms}ms")
            logger.info(f"  Strategy: {metadata['strategy']}, Scrolls: {scroll_count}, Captures: {len(captures)}")

            return {
                "image": stitched,
                "metadata": metadata,
                "debug_screenshots": debug_screenshots
            }

        except Exception as e:
            logger.error(f"[ScreenshotStitcher] Capture failed: {e}")
            raise

    def _find_overlap_end_y(self, elements_prev: list, elements_curr: list, height: int) -> int:
        """
        Find Y position where OVERLAP ENDS in current screenshot.
        PURELY element-based - finds the BOTTOM edge of the LOWEST common element.

        Logic:
        - Elements in PREV that also appear in CURR are "overlap" elements
        - Find the one that's LOWEST in CURR (highest Y value)
        - Return its bottom edge - that's where new content starts
        """
        # Build fingerprint -> element data for prev screenshot
        # Track elements that are in the "scrollable" area (not fixed header/footer)
        # Use Y position in PREV to identify scrollable content
        fp_prev_data = {}  # fingerprint -> (y_center, y_bottom) in prev
        for elem in elements_prev:
            fp = self._get_element_fingerprint(elem)
            if fp:
                y_center = self._get_element_y_center(elem)
                y_bottom = self._get_element_bottom(elem)
                fp_prev_data[fp] = (y_center, y_bottom)

        logger.debug(f"  PREV has {len(fp_prev_data)} fingerprinted elements")

        # Find common elements in CURR and track their positions
        common_elements = []  # List of (fingerprint, y_center_curr, y_bottom_curr, y_center_prev)
        for elem in elements_curr:
            fp = self._get_element_fingerprint(elem)
            if fp and fp in fp_prev_data:
                y_center_curr = self._get_element_y_center(elem)
                y_bottom_curr = self._get_element_bottom(elem)
                y_center_prev = fp_prev_data[fp][0]
                common_elements.append((fp, y_center_curr, y_bottom_curr, y_center_prev))

        if not common_elements:
            logger.warning(f"  No common elements found! Using default 30% overlap")
            return int(height * 0.3)

        # Sort by Y position in CURR (we want the LOWEST common element)
        common_elements.sort(key=lambda x: x[1], reverse=True)

        # Log all common elements for debugging
        logger.info(f"  Found {len(common_elements)} common elements:")
        for fp, y_curr, y_bottom, y_prev in common_elements[:5]:  # Show top 5
            logger.debug(f"    {fp[:40]}: prev_y={y_prev}, curr_y={y_curr}, curr_bottom={y_bottom}")

        # The LOWEST common element in CURR marks where overlap ends
        # But exclude elements near the very bottom (likely nav bar)
        nav_bar_threshold = int(height * 0.85)

        for fp, y_center_curr, y_bottom_curr, y_center_prev in common_elements:
            # Skip elements that are in the nav bar area (bottom 15%)
            if y_center_curr > nav_bar_threshold:
                continue

            # This element exists in both - its BOTTOM is where overlap ends
            logger.info(f"  Overlap element: '{fp[:40]}' at y={y_center_curr}, bottom={y_bottom_curr}")
            return y_bottom_curr + 5  # Small buffer

        # All common elements were in nav bar - use default
        logger.warning(f"  All common elements in nav bar area, using default")
        return int(height * 0.3)

    def _get_element_bottom(self, element: dict) -> int:
        """Get the bottom Y position of an element"""
        bounds = element.get('bounds', {})
        if isinstance(bounds, dict):
            return bounds.get('y', 0) + bounds.get('height', 0)
        elif isinstance(bounds, str):
            import re
            match = re.findall(r'\[(\d+),(\d+)\]', bounds)
            if len(match) >= 2:
                return int(match[1][1])  # y2 from [x1,y1][x2,y2]
        return self._get_element_y_center(element) + 50

    async def _refresh_page(self, device_id: str, times: int = 3):
        """
        Refresh the page by swiping down from top (pull-to-refresh gesture).
        Many apps support this to refresh content.
        """
        try:
            # Get screen size
            img = await self._capture_screenshot_pil(device_id)
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

    def _detect_fixed_top_height(self, img1: Image.Image, img2: Image.Image) -> int:
        """
        Detect the height of fixed top elements (like app headers, status bar)
        by comparing the top portions of two screenshots.

        Returns:
            Height in pixels of the fixed top element, or 0 if none detected
        """
        try:
            width, height = img1.size

            # Check top portions in increments
            for check_height in range(50, min(300, height // 4), 25):
                # Extract top portions
                top1 = img1.crop((0, 0, width, check_height))
                top2 = img2.crop((0, 0, width, check_height))

                # Compare them
                similarity = self._compare_image_regions(top1, top2)

                if similarity < self.fixed_element_threshold:
                    # Found where content differs - fixed element is above this
                    fixed_height = check_height - 25
                    if fixed_height > 30:
                        logger.info(f"  Detected fixed top element: {fixed_height}px")
                        return fixed_height
                    return 0

            # If large portion of top is identical, we have a fixed header
            if check_height >= 75:
                logger.info(f"  Detected fixed top element: ~{check_height - 25}px")
                return check_height - 50

            return 0

        except Exception as e:
            logger.warning(f"  Fixed top element detection failed: {e}")
            return 0

    async def _scroll_to_bottom(self, device_id: str, max_attempts: int = 5):
        """
        Scroll to the bottom of the current scrollable view.
        Uses multiple swipe up gestures until we can't scroll anymore.
        """
        try:
            for attempt in range(max_attempts):
                img_before = await self._capture_screenshot_pil(device_id)
                if not img_before:
                    break

                width, height = img_before.size
                swipe_x = width // 2
                # Swipe UP (finger moves up) to scroll DOWN
                swipe_start_y = int(height * 0.70)
                swipe_end_y = int(height * 0.30)

                await self.adb_bridge.swipe(device_id, swipe_x, swipe_start_y, swipe_x, swipe_end_y, duration=300)
                await asyncio.sleep(0.3)

                img_after = await self._capture_screenshot_pil(device_id)
                if not img_after:
                    break

                similarity = self._compare_images(img_before, img_after)
                if similarity > 0.98:
                    logger.debug(f"  Reached bottom after {attempt + 1} scroll(s)")
                    break

            logger.info(f"  Scroll to bottom complete")

        except Exception as e:
            logger.warning(f"  Scroll to bottom failed: {e}")

    def _get_element_fingerprint(self, element: dict) -> str:
        """Create a unique fingerprint for an element"""
        # Use resource_id if available, otherwise text + class
        resource_id = element.get('resource_id', '') or element.get('resource-id', '')
        text = element.get('text', '')
        class_name = element.get('class', '')

        if resource_id and resource_id != 'null':
            return f"id:{resource_id}"
        elif text:
            return f"text:{text[:50]}|{class_name}"
        else:
            return None  # Can't fingerprint this element

    def _get_element_y_center(self, element: dict) -> int:
        """Get the Y center position of an element"""
        bounds = element.get('bounds', {})
        if isinstance(bounds, dict):
            y = bounds.get('y', 0)
            height = bounds.get('height', 0)
            return y + height // 2
        elif isinstance(bounds, str):
            # Parse "[x1,y1][x2,y2]" format
            import re
            match = re.findall(r'\[(\d+),(\d+)\]', bounds)
            if len(match) >= 2:
                y1, y2 = int(match[0][1]), int(match[1][1])
                return (y1 + y2) // 2
        return 0

    def _calculate_scroll_from_elements(
        self,
        elements1: list,
        elements2: list,
        screen_height: int
    ) -> tuple:
        """
        Calculate scroll amount by comparing element positions across screenshots.

        Returns:
            (scroll_amount, confidence) - scroll_amount in pixels, confidence 0-1
        """
        # Build fingerprint -> y_position maps
        fp_to_y1 = {}
        fp_to_y2 = {}

        for elem in elements1:
            fp = self._get_element_fingerprint(elem)
            if fp:
                y = self._get_element_y_center(elem)
                # Only track elements in the middle portion (not fixed headers/footers)
                if screen_height * 0.1 < y < screen_height * 0.9:
                    fp_to_y1[fp] = y

        for elem in elements2:
            fp = self._get_element_fingerprint(elem)
            if fp:
                y = self._get_element_y_center(elem)
                if screen_height * 0.1 < y < screen_height * 0.9:
                    fp_to_y2[fp] = y

        # Find common elements
        common_fps = set(fp_to_y1.keys()) & set(fp_to_y2.keys())

        if not common_fps:
            logger.debug("  No common elements found between screenshots")
            return None, 0

        # Calculate scroll amounts from each common element
        scroll_amounts = []
        for fp in common_fps:
            y1 = fp_to_y1[fp]
            y2 = fp_to_y2[fp]
            scroll = y1 - y2  # Positive = scrolled down
            scroll_amounts.append(scroll)

        # Use median scroll amount (robust to outliers)
        scroll_amounts.sort()
        median_scroll = scroll_amounts[len(scroll_amounts) // 2]

        # Calculate confidence based on consistency
        consistent = sum(1 for s in scroll_amounts if abs(s - median_scroll) < 20)
        confidence = consistent / len(scroll_amounts)

        logger.info(f"  Element-based scroll: {median_scroll}px (confidence: {confidence:.2f}, {len(common_fps)} common elements)")

        return median_scroll, confidence

    def _find_new_content_boundary(
        self,
        elements1: list,
        elements2: list,
        scroll_amount: int,
        screen_height: int
    ) -> int:
        """
        Find where new content starts in screenshot2.

        Returns:
            Y position in screenshot2 where new (unseen) content begins
        """
        # Elements from screenshot1 that were near the bottom
        # will appear near the top of screenshot2 after scrolling

        # The boundary is where elements from screenshot1 end in screenshot2's coordinate system
        # If element was at y1 in screenshot1, it's at y1 - scroll_amount in screenshot2

        # Find the lowest element from screenshot1 that would still be visible
        max_y_in_screen2 = 0

        fp_to_y1 = {}
        for elem in elements1:
            fp = self._get_element_fingerprint(elem)
            if fp:
                y = self._get_element_y_center(elem)
                fp_to_y1[fp] = y

        for elem in elements2:
            fp = self._get_element_fingerprint(elem)
            if fp and fp in fp_to_y1:
                y2 = self._get_element_y_center(elem)
                # This element was in screenshot1, track its bottom in screenshot2
                bounds = elem.get('bounds', {})
                if isinstance(bounds, dict):
                    y_bottom = bounds.get('y', 0) + bounds.get('height', 0)
                else:
                    y_bottom = y2 + 50  # Estimate
                max_y_in_screen2 = max(max_y_in_screen2, y_bottom)

        # New content starts just after the last common element
        boundary = max_y_in_screen2 + 10  # Small buffer

        logger.debug(f"  New content boundary in screenshot2: y={boundary}")
        return boundary

    async def _get_ui_elements_with_retry(self, device_id: str, max_retries: int = 3) -> list:
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

    async def _scroll_to_top(self, device_id: str, max_attempts: int = 3):
        """
        Scroll to the top of the current scrollable view.
        Uses multiple swipe down gestures until we can't scroll anymore.
        """
        try:
            # Get screen dimensions for swipe coordinates
            # We'll swipe DOWN (finger moves down) to scroll UP
            for attempt in range(max_attempts):
                # Capture before scroll
                img_before = await self._capture_screenshot_pil(device_id)
                if not img_before:
                    break

                # Swipe DOWN to scroll UP (opposite of normal scrolling)
                # Start near top, swipe to bottom
                width, height = img_before.size
                swipe_x = width // 2
                swipe_start_y = int(height * 0.30)  # Start near top
                swipe_end_y = int(height * 0.70)    # End near bottom

                await self.adb_bridge.swipe(
                    device_id,
                    swipe_x, swipe_start_y,
                    swipe_x, swipe_end_y,
                    duration=300
                )

                await asyncio.sleep(0.3)  # Short wait

                # Capture after scroll
                img_after = await self._capture_screenshot_pil(device_id)
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

    async def _capture_screenshot_pil(self, device_id: str) -> Optional[Image.Image]:
        """Capture screenshot and return as PIL Image"""
        try:
            screenshot_bytes = await self.adb_bridge.capture_screenshot(device_id)
            if not screenshot_bytes:
                return None

            return Image.open(io.BytesIO(screenshot_bytes))

        except Exception as e:
            logger.error(f"[ScreenshotStitcher] Screenshot capture failed: {e}")
            return None

    def _detect_fixed_bottom_height(self, img1: Image.Image, img2: Image.Image) -> int:
        """
        Detect the height of fixed bottom elements (like navigation bars)
        by comparing the bottom portions of two screenshots.

        Returns:
            Height in pixels of the fixed bottom element, or 0 if none detected
        """
        try:
            width, height = img1.size

            # Check bottom portions in increments of 50px
            # Start from bottom and work up to find where content differs
            for check_height in range(50, min(400, height // 3), 25):
                # Extract bottom portions
                bottom1 = img1.crop((0, height - check_height, width, height))
                bottom2 = img2.crop((0, height - check_height, width, height))

                # Compare them
                similarity = self._compare_image_regions(bottom1, bottom2)

                if similarity < self.fixed_element_threshold:
                    # Found where content differs - fixed element is below this
                    fixed_height = check_height - 25  # Previous check was still fixed
                    if fixed_height > 50:  # Only count if substantial
                        logger.info(f"  Detected fixed bottom element: {fixed_height}px")
                        return fixed_height
                    return 0

            # If we got here, large portion of bottom is identical
            # Check if we found a fixed bar
            if check_height >= 100:
                logger.info(f"  Detected fixed bottom element: ~{check_height}px")
                return check_height - 50  # Conservative estimate

            return 0

        except Exception as e:
            logger.warning(f"  Fixed element detection failed: {e}")
            return 0

    def _compare_image_regions(self, img1: Image.Image, img2: Image.Image) -> float:
        """Compare two image regions for similarity"""
        try:
            arr1 = np.array(img1)
            arr2 = np.array(img2)

            if arr1.shape != arr2.shape:
                return 0.0

            # Simple pixel comparison for regions
            diff = np.abs(arr1.astype(np.float64) - arr2.astype(np.float64))
            max_diff = 255.0 * arr1.size
            similarity = 1.0 - (np.sum(diff) / max_diff)

            return float(similarity)
        except:
            return 0.0

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

            # Convert to grayscale for comparison
            if len(arr1.shape) == 3:
                gray1 = cv2.cvtColor(arr1, cv2.COLOR_RGB2GRAY)
                gray2 = cv2.cvtColor(arr2, cv2.COLOR_RGB2GRAY)
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

    async def _get_scroll_position(self, device_id: str) -> Optional[int]:
        """
        Get current scroll position from UI hierarchy

        Returns Y-coordinate of scrollable view or None if unavailable
        """
        try:
            # Get UI hierarchy
            ui_elements = await self.adb_bridge.get_ui_elements(device_id)

            # Look for scrollable views
            for element in ui_elements:
                if element.get("scrollable") == "true":
                    bounds = element.get("bounds", "")
                    # Parse bounds format: "[x1,y1][x2,y2]"
                    if bounds:
                        # Extract Y coordinate as scroll position
                        import re
                        match = re.search(r'\[(\d+),(\d+)\]', bounds)
                        if match:
                            return int(match.group(2))

            # Fallback: return None (can't detect position)
            return None

        except Exception as e:
            logger.debug(f"  Could not get scroll position: {e}")
            return None

    def _find_overlap_offset(
        self,
        img1: Image.Image,
        img2: Image.Image,
        overlap_height: int
    ) -> Tuple[Optional[int], Optional[float]]:
        """
        Find Y-offset where img1 bottom overlaps with img2 top
        Uses OpenCV template matching with TM_CCOEFF_NORMED

        Args:
            img1: Previous screenshot
            img2: Current screenshot
            overlap_height: Height of overlap region to search

        Returns:
            Tuple of (Y-offset in pixels, match quality) or (None, None) if no match
        """
        try:
            width1, height1 = img1.size
            width2, height2 = img2.size

            # 1. Extract template from bottom of img1
            template = img1.crop((0, height1 - overlap_height, width1, height1))

            # 2. Extract search region from top of img2 (search in 2x overlap)
            search_height = min(overlap_height * 2, height2)
            search_region = img2.crop((0, 0, width2, search_height))

            # 3. Convert PIL to numpy arrays
            template_np = np.array(template)
            search_np = np.array(search_region)

            # 4. Convert to grayscale for better matching
            template_gray = cv2.cvtColor(template_np, cv2.COLOR_RGB2GRAY)
            search_gray = cv2.cvtColor(search_np, cv2.COLOR_RGB2GRAY)

            # 5. Template matching
            result = cv2.matchTemplate(search_gray, template_gray, cv2.TM_CCOEFF_NORMED)

            # 6. Find best match
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            # max_loc = (x, y) of top-left corner of best match
            offset_y = max_loc[1]

            # 7. Quality check
            if max_val < self.match_threshold:
                logger.warning(f"  Low match quality: {max_val:.3f} (threshold: {self.match_threshold})")
                logger.warning(f"  May have alignment issues, proceeding anyway")
                # Still return offset, but log warning

            logger.debug(f"  Template match quality: {max_val:.3f}, offset_y={offset_y}")

            return offset_y, max_val

        except Exception as e:
            logger.error(f"  Template matching failed: {e}")
            return None, None

    def _stitch_by_elements(
        self,
        captures: list,  # List of (image, elements, _unused) tuples
        screen_height: int
    ) -> Image.Image:
        """
        TRACING PAPER method:
        1. Find a common element between captures
        2. Calculate offset: where element is in C1 vs C2
        3. C1 contributes: y=0 to y=offset (unique top content)
        4. C2 contributes: y=0 to y=height, placed at y=offset
        """
        if not captures:
            raise ValueError("No captures to stitch")

        if len(captures) == 1:
            return captures[0][0]

        img1, elements1, _ = captures[0]
        img2, elements2, _ = captures[1]
        width, height = img1.size

        logger.info(f"  === TRACING PAPER STITCHING ===")
        logger.info(f"  Screen: {width}x{height}")

        # Step 1: Build element position maps
        # fingerprint -> (y_center, y_top, y_bottom)
        elem1_positions = {}
        for elem in elements1:
            fp = self._get_element_fingerprint(elem)
            if fp:
                y_center = self._get_element_y_center(elem)
                y_bottom = self._get_element_bottom(elem)
                y_top = y_center - (y_bottom - y_center)  # Estimate top
                elem1_positions[fp] = (y_center, y_top, y_bottom)

        elem2_positions = {}
        for elem in elements2:
            fp = self._get_element_fingerprint(elem)
            if fp:
                y_center = self._get_element_y_center(elem)
                y_bottom = self._get_element_bottom(elem)
                y_top = y_center - (y_bottom - y_center)
                elem2_positions[fp] = (y_center, y_top, y_bottom)

        logger.info(f"  C1: {len(elem1_positions)} elements, C2: {len(elem2_positions)} elements")

        # Step 2: Find common elements (excluding fixed header/footer regions)
        # Header region: top 15% of screen
        # Footer region: bottom 20% of screen
        header_limit = height * 0.15
        footer_limit = height * 0.80

        common_elements = []
        for fp in elem1_positions:
            if fp in elem2_positions:
                y1_center = elem1_positions[fp][0]
                y2_center = elem2_positions[fp][0]

                # Element must be in scrollable region in BOTH captures
                # In C1: should be in middle-to-bottom (scrollable content)
                # In C2: should be in top-to-middle (scrolled up content)
                if y1_center > header_limit and y2_center < footer_limit:
                    offset = y1_center - y2_center
                    common_elements.append((fp, y1_center, y2_center, offset))
                    logger.info(f"    Common: '{fp[:35]}' C1_y={int(y1_center)}, C2_y={int(y2_center)}, offset={int(offset)}")

        if not common_elements:
            logger.warning("  No common elements found! Checking all elements...")
            # Try with looser constraints
            for fp in elem1_positions:
                if fp in elem2_positions:
                    y1 = elem1_positions[fp][0]
                    y2 = elem2_positions[fp][0]
                    offset = y1 - y2
                    # Only consider positive offsets (scrolled down)
                    if offset > 50:
                        common_elements.append((fp, y1, y2, offset))
                        logger.info(f"    Found: '{fp[:35]}' offset={int(offset)}")

        if not common_elements:
            logger.error("  Still no common elements! Using default 50% overlap")
            scroll_offset = int(height * 0.5)
        else:
            # IMPORTANT: Filter out elements with offset=0 or near 0
            # These are likely full-screen containers that don't move when scrolling
            meaningful_offsets = [c[3] for c in common_elements if c[3] > 100]

            if meaningful_offsets:
                # Use median of meaningful (non-zero) offsets
                meaningful_offsets.sort()
                scroll_offset = int(meaningful_offsets[len(meaningful_offsets) // 2])
                logger.info(f"  Median scroll offset: {scroll_offset}px (from {len(meaningful_offsets)} moving elements)")
            else:
                # All offsets are 0 - maybe no scrolling happened?
                logger.warning("  All elements have offset ~0! No scroll detected.")
                # Use max offset as fallback
                all_offsets = [c[3] for c in common_elements]
                scroll_offset = max(all_offsets) if all_offsets else int(height * 0.5)
                logger.info(f"  Using max offset: {scroll_offset}px")

        # Step 3: Detect fixed header height in C2 (status bar + app header)
        # Find elements that are at y=0 or very top - these are fixed headers
        fixed_header_height = 0
        for fp, (y_center, y_top, y_bottom) in elem2_positions.items():
            # Elements starting at y < 10 are likely fixed headers
            if y_top < 10 and y_bottom < height * 0.15:
                if y_bottom > fixed_header_height:
                    fixed_header_height = int(y_bottom)
                    logger.debug(f"    Header element: {fp[:30]} bottom={y_bottom}")

        # Also check by comparing top portions of both images (should be identical if fixed)
        if fixed_header_height < 50:
            # Use pixel comparison as fallback
            fixed_header_height = self._detect_fixed_top_height(img1, img2)

        # Ensure minimum header (at least status bar ~50px)
        fixed_header_height = max(fixed_header_height, 80)  # Android status + app bar minimum
        logger.info(f"  Fixed header height: {fixed_header_height}px")

        # Step 4: Stitch using tracing paper method
        # C1 contributes: y=0 to y=(scroll_offset + header) - the unique top portion
        # C2 contributes: y=fixed_header to y=height, placed at y=(scroll_offset + header)
        #
        # WHY add header to paste position?
        # - scroll_offset was calculated from FULL images (element y1 - element y2)
        # - But we're cutting header from C2, so C2's content shifts UP by header_height
        # - To compensate: paste C2 at (scroll_offset + header_height)

        c1_crop_top = 0
        c1_crop_bottom = scroll_offset + fixed_header_height  # Include more of C1 to match

        c2_crop_top = fixed_header_height  # CUT OFF the header!
        c2_crop_bottom = height
        c2_height_used = c2_crop_bottom - c2_crop_top

        c2_paste_y = scroll_offset + fixed_header_height  # Adjusted paste position

        total_height = c2_paste_y + c2_height_used

        logger.info(f"  C1: crop y={c1_crop_top}-{c1_crop_bottom} ({c1_crop_bottom}px), paste at y=0")
        logger.info(f"  C2: crop y={c2_crop_top}-{c2_crop_bottom} ({c2_height_used}px), paste at y={c2_paste_y}")
        logger.info(f"  Final size: {width}x{total_height}")

        # Create canvas and stitch
        stitched = Image.new('RGB', (width, total_height))

        # Paste C1's unique top portion
        if c1_crop_bottom > c1_crop_top:
            c1_cropped = img1.crop((0, c1_crop_top, width, c1_crop_bottom))
            stitched.paste(c1_cropped, (0, 0))
            logger.info(f"  Pasted C1 ({c1_cropped.size[1]}px) at y=0")

        # Paste C2 WITHOUT its header, at adjusted position
        c2_cropped = img2.crop((0, c2_crop_top, width, c2_crop_bottom))
        stitched.paste(c2_cropped, (0, c2_paste_y))
        logger.info(f"  Pasted C2 ({c2_cropped.size[1]}px) at y={c2_paste_y}")

        return stitched

    def _calculate_scroll_offset(self, elements_prev: list, elements_curr: list, height: int) -> int:
        """
        Calculate how many pixels were scrolled between two captures
        by comparing the Y positions of common elements.

        Returns:
            Scroll offset in pixels (positive = scrolled down)
        """
        # Build fingerprint -> y_position maps for ALL elements first
        fp_to_y_prev = {}
        fp_to_y_curr = {}

        logger.info(f"  === OFFSET CALCULATION ===")
        logger.info(f"  Screen height: {height}, Valid range: {int(height*0.10)}-{int(height*0.80)}")

        # Log ALL fingerprinted elements from PREV
        prev_all = {}
        for elem in elements_prev:
            fp = self._get_element_fingerprint(elem)
            if fp:
                y = self._get_element_y_center(elem)
                prev_all[fp] = y
                # Exclude elements in fixed header (top 10%) and footer (bottom 20%)
                if height * 0.10 < y < height * 0.80:
                    fp_to_y_prev[fp] = y

        logger.info(f"  PREV: {len(prev_all)} total fingerprinted, {len(fp_to_y_prev)} in valid Y range")

        # Log ALL fingerprinted elements from CURR
        curr_all = {}
        for elem in elements_curr:
            fp = self._get_element_fingerprint(elem)
            if fp:
                y = self._get_element_y_center(elem)
                curr_all[fp] = y
                if height * 0.10 < y < height * 0.80:
                    fp_to_y_curr[fp] = y

        logger.info(f"  CURR: {len(curr_all)} total fingerprinted, {len(fp_to_y_curr)} in valid Y range")

        # Find common elements
        common = set(fp_to_y_prev.keys()) & set(fp_to_y_curr.keys())

        # Also check ALL common elements (including fixed ones) for debugging
        all_common = set(prev_all.keys()) & set(curr_all.keys())
        logger.info(f"  Common elements: {len(common)} in valid range, {len(all_common)} total")

        # Log some example elements for debugging
        logger.info(f"  Sample PREV elements (in range):")
        for i, (fp, y) in enumerate(list(fp_to_y_prev.items())[:5]):
            logger.info(f"    {fp[:50]} @ y={y}")

        logger.info(f"  Sample CURR elements (in range):")
        for i, (fp, y) in enumerate(list(fp_to_y_curr.items())[:5]):
            logger.info(f"    {fp[:50]} @ y={y}")

        if not common:
            logger.warning("  NO COMMON ELEMENTS in valid Y range!")
            logger.info(f"  Checking ALL common elements...")
            for fp in list(all_common)[:5]:
                logger.info(f"    {fp[:50]}: prev_y={prev_all[fp]}, curr_y={curr_all[fp]}")
            return int(height * 0.5)  # Default: assume 50% scroll

        # Calculate offset from each common element
        offset_values = []
        logger.info(f"  Common elements with positions:")
        for fp in common:
            y_prev = fp_to_y_prev[fp]
            y_curr = fp_to_y_curr[fp]
            offset = y_prev - y_curr  # Positive if scrolled down
            offset_values.append(offset)
            logger.info(f"    {fp[:40]}: prev={y_prev}, curr={y_curr}, offset={offset}")

        # Use median offset (robust to outliers)
        offset_values.sort()
        median_offset = offset_values[len(offset_values) // 2]

        logger.info(f"  === RESULT: median offset = {median_offset}px ===")
        return median_offset

    def _stitch_images_smart(
        self,
        captures: list,  # List of (image, elements) tuples
        overlap_ratio: float,
        screen_height: int
    ) -> Image.Image:
        """
        Smart stitching using UI elements to determine exact crop boundaries.
        Falls back to pixel-based stitching if element tracking fails.
        """
        if not captures:
            raise ValueError("No captures to stitch")

        if len(captures) == 1:
            return captures[0][0]

        images = [c[0] for c in captures]
        width, height = images[0].size
        overlap_height = int(height * overlap_ratio)

        # Detect fixed bottom element
        fixed_bottom_height = 0
        if len(captures) >= 2:
            fixed_bottom_height = self._detect_fixed_bottom_height(images[0], images[1])

        # Track all seen element fingerprints and their Y positions in final image
        seen_elements = {}  # fingerprint -> max_y_in_final

        # Calculate crop regions using element tracking
        crop_regions = []  # (image, crop_top, crop_bottom)

        for i, (img, elements) in enumerate(captures):
            if i == 0:
                # First image: full content minus fixed footer
                crop_top = 0
                crop_bottom = height - fixed_bottom_height if fixed_bottom_height > 0 else height

                # Track all elements from first image
                for elem in elements:
                    fp = self._get_element_fingerprint(elem)
                    if fp:
                        y = self._get_element_y_center(elem)
                        if y < crop_bottom:  # Only track if above fixed footer
                            seen_elements[fp] = y
            else:
                # Subsequent images: find where new content starts
                prev_img, prev_elements = captures[i-1]

                # Use element-based calculation
                scroll_amount, confidence = self._calculate_scroll_from_elements(
                    prev_elements, elements, height
                )

                if scroll_amount and confidence > 0.3:
                    # Calculate crop_top based on element positions
                    crop_top = self._find_new_content_boundary(prev_elements, elements, scroll_amount, height)
                else:
                    # Fallback to pixel-based
                    offset_y, _ = self._find_overlap_offset(prev_img, img, overlap_height)
                    crop_top = (offset_y + overlap_height) if offset_y else overlap_height

                # Ensure we don't crop too much
                crop_top = max(0, min(crop_top, height - 100))

                # For non-final images, crop fixed footer
                if i < len(captures) - 1 and fixed_bottom_height > 0:
                    crop_bottom = height - fixed_bottom_height
                else:
                    crop_bottom = height

                # Track new elements
                for elem in elements:
                    fp = self._get_element_fingerprint(elem)
                    if fp and fp not in seen_elements:
                        y = self._get_element_y_center(elem)
                        if crop_top < y < crop_bottom:
                            seen_elements[fp] = y

            crop_regions.append((img, crop_top, crop_bottom))
            logger.debug(f"  Image {i}: crop {crop_top}-{crop_bottom} ({crop_bottom - crop_top}px)")

        # Calculate total height
        total_height = sum(cb - ct for _, ct, cb in crop_regions)
        logger.info(f"  Smart stitching {len(captures)} images -> {width}x{total_height}px (fixed bar: {fixed_bottom_height}px)")

        # Create canvas and stitch
        stitched = Image.new('RGB', (width, total_height))
        current_y = 0

        for i, (img, crop_top, crop_bottom) in enumerate(crop_regions):
            cropped = img.crop((0, crop_top, width, crop_bottom))
            stitched.paste(cropped, (0, current_y))
            current_y += cropped.size[1]

        return stitched

    def _stitch_images(
        self,
        images: list,
        overlap_ratio: float
    ) -> Image.Image:
        """
        Stitch multiple images together vertically by CROPPING overlapping portions.
        Also detects and removes fixed bottom elements (like nav bars) from non-final images.

        Args:
            images: List of PIL Images to stitch
            overlap_ratio: Overlap as ratio of height (for offset calculation)

        Returns:
            Single stitched PIL Image
        """
        if not images:
            raise ValueError("No images to stitch")

        if len(images) == 1:
            return images[0]

        first_img = images[0]
        width, height = first_img.size
        overlap_height = int(height * overlap_ratio)

        # Detect fixed bottom element height (nav bar, etc.)
        fixed_bottom_height = 0
        if len(images) >= 2:
            fixed_bottom_height = self._detect_fixed_bottom_height(images[0], images[1])

        # Calculate how much NEW content each image contributes
        # and store crop information
        crops = []  # List of (image, crop_top, crop_bottom)

        # First image: crop bottom if there's a fixed element
        first_crop_bottom = height - fixed_bottom_height if fixed_bottom_height > 0 else height
        crops.append((images[0], 0, first_crop_bottom))
        logger.debug(f"  Image 0: full height {height}, cropping bottom to {first_crop_bottom}")

        for i in range(1, len(images)):
            # Find where the overlap ends in this image
            offset_y, _ = self._find_overlap_offset(images[i-1], images[i], overlap_height)

            if offset_y is not None:
                # offset_y = where template (bottom of prev img) is found in this img
                # New content starts AFTER the template region
                crop_top = offset_y + overlap_height
                logger.debug(f"  Image {i}: template at y={offset_y}, crop top={crop_top}")
            else:
                # Fallback: assume overlap_height worth of overlap
                crop_top = overlap_height
                logger.debug(f"  Image {i}: no match, fallback crop top={crop_top}")

            # For non-final images, also crop the fixed bottom element
            if i < len(images) - 1 and fixed_bottom_height > 0:
                crop_bottom = height - fixed_bottom_height
            else:
                crop_bottom = height  # Last image: keep the nav bar

            crops.append((images[i], crop_top, crop_bottom))

        # Calculate total height
        total_height = 0
        for i, (img, crop_top, crop_bottom) in enumerate(crops):
            contribution = crop_bottom - crop_top
            total_height += contribution
            logger.debug(f"  Image {i}: contributes {contribution}px (crop {crop_top}-{crop_bottom})")

        logger.info(f"  Stitching {len(images)} images -> {width}x{total_height}px (fixed bar: {fixed_bottom_height}px)")

        # Create canvas and stitch
        stitched = Image.new('RGB', (width, total_height))
        current_y = 0

        for i, (img, crop_top, crop_bottom) in enumerate(crops):
            # Crop the image
            cropped = img.crop((0, crop_top, width, crop_bottom))

            # Paste at current position
            stitched.paste(cropped, (0, current_y))

            # Move position down
            current_y += cropped.size[1]

        return stitched
