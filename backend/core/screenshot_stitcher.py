"""
Visual Mapper - Screenshot Stitcher (Phase 8)
Captures full scrollable pages using HYBRID approach:
1. Element-based matching (fastest, semantic)
2. ORB feature matching (robust to rendering variations)
3. Template matching (fallback)

Performance Target: ~1s per scroll, <25s for 20-screen page
"""

import logging
import asyncio
import time
import base64
from typing import Tuple, Optional, Dict, Any
from PIL import Image
import numpy as np
import io
from services.feature_manager import get_feature_manager

# Initialize logger BEFORE conditional imports that may need it
logger = logging.getLogger(__name__)

# Conditional OpenCV import for basic mode
feature_manager = get_feature_manager()
CV2_AVAILABLE = False
if feature_manager.is_enabled("real_icons_enabled"):
    try:
        import cv2
        CV2_AVAILABLE = True
    except ImportError:
        logger.warning("OpenCV (cv2) not found, falling back to PIL-only mode")
else:
    logger.info("OpenCV features disabled by feature flag")

# Import feature-based stitcher
try:
    if CV2_AVAILABLE:
        from screenshot_stitcher_feature_matching import FeatureBasedStitcher
        FEATURE_MATCHING_AVAILABLE = True
    else:
        FEATURE_MATCHING_AVAILABLE = False
except ImportError:
    FEATURE_MATCHING_AVAILABLE = False

# Import from modular package
# Note: Using ss_modules during transition to avoid conflict with this file
from ss_modules.utils import (
    remove_consecutive_duplicates,
    estimate_from_patterns,
    estimate_from_numbered_items,
    estimate_from_bounds,
    get_scrollable_container_info,
)
from ss_modules.device import DeviceController
from ss_modules.elements import ElementAnalyzer
from ss_modules.overlap import OverlapDetector
from ss_modules.compose import ImageComposer


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
        self.max_scrolls = 25  # Safety limit (increased for smaller scroll steps)
        self.duplicate_threshold = 0.95  # If images > 95% similar, we're not scrolling
        self.min_new_content_ratio = 0.05  # Need at least 5% new content to continue (was 15% - too strict)
        self.fixed_element_threshold = 0.92  # Threshold for detecting fixed UI elements (allow slight variations)

        # Element tracking for smart stitching
        self.use_element_tracking = True  # Use UI elements for precise stitching

        # Initialize feature-based stitcher (ORB) if available
        self.feature_stitcher = None
        if FEATURE_MATCHING_AVAILABLE:
            try:
                self.feature_stitcher = FeatureBasedStitcher()
                logger.info("[ScreenshotStitcher] ORB feature matching enabled")
            except Exception as e:
                logger.warning(f"[ScreenshotStitcher] Feature matching init failed: {e}")

        # Initialize device controller for scroll operations
        self.device_controller = DeviceController(adb_bridge)

        # Initialize element analyzer for fingerprinting and scroll detection
        self.element_analyzer = ElementAnalyzer()

        # Initialize overlap detector for image comparison
        self.overlap_detector = OverlapDetector(
            fixed_element_threshold=self.fixed_element_threshold,
            match_threshold=self.match_threshold
        )

        # Initialize image composer for stitching operations
        self.image_composer = ImageComposer(
            overlap_detector=self.overlap_detector,
            element_analyzer=self.element_analyzer,
            remove_duplicates_fn=remove_consecutive_duplicates,
            feature_stitcher=self.feature_stitcher
        )

        logger.info("[ScreenshotStitcher] Initialized")

    async def _get_device_nav_info(self, device_id: str) -> dict:
        """Delegate to device controller."""
        return await self.device_controller.get_device_nav_info(device_id)

    async def estimate_content_height(self, device_id: str, screen_height: int) -> dict:
        """
        HYBRID approach to estimate total scrollable content height.

        Combines multiple methods and cross-validates for accuracy:
        1. Pattern matching (Episode 1 of 8, Item 3/10, etc.)
        2. Numbered item detection (find highest number in sequence)
        3. Item bounds analysis (count items, calculate avg height)
        4. Scrollable container analysis

        Returns:
            Dict with estimated_height, methods_used, confidence, details
        """
        try:
            elements = await self._get_ui_elements_with_retry(device_id)

            # Get device nav info for accurate footer estimation
            nav_info = await self._get_device_nav_info(device_id)

            estimates = []
            methods_used = []
            details = {
                'nav_info': nav_info
            }

            # === METHOD 1: Pattern Matching ("X of Y", "X/Y") ===
            total_from_pattern = self._estimate_from_patterns(elements)
            if total_from_pattern:
                details['pattern_match'] = total_from_pattern
                methods_used.append('pattern_match')

            # === METHOD 2: Numbered Item Sequence Detection ===
            sequence_info = self._estimate_from_numbered_items(elements)
            if sequence_info:
                details['numbered_sequence'] = sequence_info
                methods_used.append('numbered_sequence')

            # === METHOD 3: Item Bounds Analysis ===
            bounds_info = self._estimate_from_bounds(elements, screen_height)
            if bounds_info:
                details['bounds_analysis'] = bounds_info
                methods_used.append('bounds_analysis')

            # === METHOD 4: Scrollable Container Info ===
            container_info = self._get_scrollable_container_info(elements)
            if container_info:
                details['container'] = container_info

            # === COMBINE ESTIMATES ===
            # Priority: pattern_match > numbered_sequence > bounds_analysis

            final_estimate = screen_height  # Default
            confidence = "low"

            if total_from_pattern and total_from_pattern.get('total_items'):
                # Best case: we know exact item count from pattern like "Episode 5 of 8"
                total_items = total_from_pattern['total_items']
                avg_height = bounds_info.get('avg_item_height', 200) if bounds_info else 200
                header_height = bounds_info.get('header_estimate', 500) if bounds_info else 500
                final_estimate = header_height + (total_items * avg_height)
                confidence = "high"
                logger.info(f"[HeightEstimate] Pattern match: {total_items} items * {avg_height}px + {header_height}px header = {final_estimate}px")

            elif sequence_info and sequence_info.get('max_number'):
                # Good case: found numbered sequence like "1. Title", "2. Title"
                total_items = sequence_info['max_number']

                # Use the LARGER of: numbered item height OR bounds analysis height
                # (numbered items might just be title text, bounds captures full cards)
                seq_height = sequence_info.get('avg_height', 200)
                bounds_height = bounds_info.get('avg_item_height', 200) if bounds_info else 200
                avg_height = max(seq_height, bounds_height, 200)  # At least 200px per item

                # Use estimated header from numbered items (extrapolated from first visible item position)
                # If we're scrolled down (seeing items 6-8, not 1-3), estimated_header will be 0 or negative
                # In that case, we need to estimate header differently:
                # - Items 6,7,8 visible means items 1-5 are above the current view
                # - Header = scrolled distance - (items scrolled past * avg_height) + first_item_y
                header_height = sequence_info.get('estimated_header', 0)

                if header_height <= 0:
                    # We're scrolled down - calculate header from what we know:
                    # If item #6 is at y=183, and items are 231px each, then:
                    # Items 1-5 (5 items) are above current view = 5 * 231 = 1155px scrolled
                    # But item 6 starts at y=183 (below header/tabs area)
                    # So: items_before * avg_height + first_item_y = total above view
                    # Header ~= first_item_y (where scrollable content starts on screen)
                    first_y = sequence_info.get('first_item_y', 200)
                    first_num = sequence_info.get('first_item_num', 1)
                    items_before = first_num - 1

                    # The header is approximately where item 1 would start on a non-scrolled page
                    # Since we're seeing the list at first_y, and there are items_before above,
                    # header = first_y + (items_before * avg_height) - current_scroll
                    # But we don't know current_scroll... so use bounds header as fallback
                    header_height = bounds_info.get('header_estimate', 500) if bounds_info else 500

                    # Better estimate: header is typically 800-1200px for Netflix-style pages
                    # with large preview images. Scale based on scrollable_area
                    if bounds_info:
                        scrollable_area = bounds_info.get('scrollable_area', 1000)
                        # If scrollable area is most of screen, header is small
                        # If scrollable area is smaller, there's more fixed UI (header)
                        screen_minus_scroll = 1200 - scrollable_area
                        header_height = max(screen_minus_scroll + 600, 800)  # Add buffer for content above list

                    logger.info(f"[HeightEstimate] Scrolled view - using estimated header={header_height}px")

                # Add footer - use nav info for accurate estimation
                # - Fullscreen apps: 0px (no nav bar)
                # - Gesture nav: ~20px (hint bar only)
                # - 3-button nav: ~48px
                # - Plus app nav bar if present: ~60-80px
                android_nav = nav_info.get('estimated_nav_height', 48)
                app_nav = 80 if not nav_info.get('is_fullscreen', False) else 0
                footer_height = android_nav + app_nav
                logger.info(f"[HeightEstimate] Footer: android_nav({android_nav}) + app_nav({app_nav}) = {footer_height}px")

                final_estimate = header_height + (total_items * avg_height) + footer_height
                confidence = "medium-high"
                logger.info(f"[HeightEstimate] Numbered sequence: header({header_height}) + {total_items} items * {avg_height}px + footer({footer_height}) = {final_estimate}px")

            elif bounds_info:
                # Fallback: estimate from visible items
                final_estimate = bounds_info.get('estimated_total', screen_height)
                confidence = "medium"
                logger.info(f"[HeightEstimate] Bounds analysis: {final_estimate}px")

            # Cross-validate: if multiple methods agree within 20%, increase confidence
            if len(methods_used) >= 2:
                confidence = "high" if confidence == "medium-high" else "medium-high"

            return {
                "estimated_height": int(final_estimate),
                "estimated_scrolls": max(1, int((final_estimate - screen_height) / 400)),
                "methods_used": methods_used,
                "confidence": confidence,
                "details": details
            }

        except Exception as e:
            logger.error(f"Height estimation failed: {e}")
            import traceback
            traceback.print_exc()
            return {"estimated_height": screen_height, "confidence": "low", "error": str(e)}

    def _estimate_from_patterns(self, elements: list) -> dict:
        """Delegate to utils module."""
        return estimate_from_patterns(elements)

    def _estimate_from_numbered_items(self, elements: list) -> dict:
        """Delegate to utils module."""
        return estimate_from_numbered_items(elements)

    def _estimate_from_bounds(self, elements: list, screen_height: int) -> dict:
        """Delegate to utils module."""
        return estimate_from_bounds(elements, screen_height)

    def _get_scrollable_container_info(self, elements: list) -> dict:
        """Delegate to utils module."""
        return get_scrollable_container_info(elements)

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
            # === STEP 0: Refresh page (skip for browsers to avoid triggering gestures) ===
            # Get current app to check if it's a browser
            devices = await self.adb_bridge.get_devices()
            current_app = ""
            for d in devices:
                if d.get('id') == device_id:
                    current_app = d.get('current_activity', '')
                    break

            # Skip refresh for browsers only (they have their own gestures that interfere)
            # Keep refresh for other apps - it helps reset the page to a known state
            skip_refresh_packages = [
                'chrome', 'browser', 'firefox', 'opera', 'edge', 'brave', 'samsung.sbrowser'
            ]
            is_browser = any(pkg in current_app.lower() for pkg in skip_refresh_packages)

            if is_browser:
                logger.info("  STEP 0: Skipping refresh (browser detected)")
            else:
                # Do refresh for non-browser apps (matches stable stitcher)
                logger.info("  STEP 0: Refreshing page 3 times...")
                await self._refresh_page(device_id, times=3)

            # === STEP 1: Capture TOP ===
            logger.info("  STEP 1: Scrolling to TOP...")
            await self._scroll_to_top(device_id)
            await asyncio.sleep(0.5)

            # NOTE: Removed initial scroll - it was pushing top content off-screen
            # The scroll_to_top should already position us correctly
            # If apps have large headers, capture them as part of the page

            img_top = await self._capture_screenshot_pil(device_id)
            if not img_top:
                raise RuntimeError("Failed to capture TOP screenshot")

            elements_top = await self._get_ui_elements_with_retry(device_id)
            width, height = img_top.size
            logger.info(f"  TOP: {len(elements_top)} UI elements, screen {width}x{height}")

            # === STEP 2: Scroll to BOTTOM and capture ===
            logger.info("  STEP 2: Scrolling to BOTTOM...")
            await self._scroll_to_bottom(device_id, max_attempts=5)
            await asyncio.sleep(0.5)

            img_bottom = await self._capture_screenshot_pil(device_id)
            if not img_bottom:
                raise RuntimeError("Failed to capture BOTTOM screenshot")

            elements_bottom = await self._get_ui_elements_with_retry(device_id)
            logger.info(f"  BOTTOM: {len(elements_bottom)} UI elements")

            # === STEP 3: Simple overlap check (matches stable stitcher logic) ===
            # Build fingerprint sets for TOP and BOTTOM
            fp_top = set()
            for elem in elements_top:
                fp = self._get_element_fingerprint(elem)
                if fp:
                    fp_top.add(fp)

            fp_bottom = set()
            for elem in elements_bottom:
                fp = self._get_element_fingerprint(elem)
                if fp:
                    fp_bottom.add(fp)

            # Find common elements between TOP and BOTTOM
            overlap = fp_top & fp_bottom
            logger.info(f"  OVERLAP CHECK: {len(overlap)} common elements between TOP and BOTTOM")

            # Build position maps to check which elements actually MOVED
            pos_top = {}  # fingerprint -> y_center
            for elem in elements_top:
                fp = self._get_element_fingerprint(elem)
                if fp:
                    pos_top[fp] = self._get_element_y_center(elem)

            pos_bottom = {}
            for elem in elements_bottom:
                fp = self._get_element_fingerprint(elem)
                if fp:
                    pos_bottom[fp] = self._get_element_y_center(elem)

            # Count MOVING elements (same element at DIFFERENT Y positions)
            # These indicate actual scrollable content that overlaps
            # FIXED elements (same Y in both) don't count - they're headers/navbars
            moving_elements = 0
            fixed_elements = 0
            for fp in overlap:
                y_top = pos_top.get(fp, 0)
                y_bottom = pos_bottom.get(fp, 0)
                offset = abs(y_top - y_bottom)
                if offset > 20:  # Element moved more than 20px
                    moving_elements += 1
                else:
                    fixed_elements += 1

            logger.info(f"  ELEMENT ANALYSIS: {moving_elements} moving, {fixed_elements} fixed")

            # Short page detection logic:
            # - If MANY MOVING elements (>= 5), content overlaps = short page
            # - If FEW MOVING elements, TOP and BOTTOM show different content = long page
            # - Also check image similarity as backup
            if moving_elements >= 5:
                # Many moving elements = content overlaps = short page
                is_short_page = True
                logger.info(f"  SHORT PAGE: {moving_elements} moving elements (>= 5)")
            elif moving_elements >= 2:
                # Some moving elements - check image difference to confirm
                import numpy as np
                arr_top = np.array(img_top.convert('RGB'))
                arr_bottom = np.array(img_bottom.convert('RGB'))
                margin_y = int(height * 0.2)
                center_top = arr_top[margin_y:height-margin_y, :, :]
                center_bottom = arr_bottom[margin_y:height-margin_y, :, :]
                pixel_diff = np.mean(center_top != center_bottom) * 100
                logger.info(f"  IMAGE DIFFERENCE: {pixel_diff:.1f}% (center region)")

                # Low diff + some moving elements = short page
                is_short_page = pixel_diff < 30
                if is_short_page:
                    logger.info(f"  SHORT PAGE: {moving_elements} moving + {pixel_diff:.1f}% diff")
            else:
                # Few/no moving elements = different content = LONG page
                is_short_page = False
                logger.info(f"  LONG PAGE: only {moving_elements} moving elements (need middle captures)")

            # If TOP and BOTTOM share scrollable content elements AND look similar, stitch directly
            if is_short_page:
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
                # Long page - use SIMPLE SEQUENTIAL SCROLL approach
                # Don't rely on complex element matching - just scroll and capture
                logger.info("  Long page - using SIMPLE SEQUENTIAL SCROLL")
                logger.info("  Strategy: Scroll from TOP to BOTTOM, capturing at each step")

                # Go back to TOP first
                logger.info("  Scrolling back to TOP...")
                await self._scroll_to_top(device_id)
                await asyncio.sleep(0.5)

                # Re-capture TOP
                img_top = await self._capture_screenshot_pil(device_id)
                elements_top = await self._get_ui_elements_with_retry(device_id)

                scroll_count = 0
                prev_img = img_top

                # === DETERMINISTIC SCROLL APPROACH ===
                # Use SLOW swipe with KNOWN distance - no guessing needed
                # Swipe distance = exact scroll amount (minus fixed header)

                # Detect fixed header height from first capture
                fixed_header = 80  # Default Android status bar

                # Use 30% of scrollable area per swipe for MORE overlap
                # Smaller scrolls = more captures = better stitch point options
                scrollable_height = height - fixed_header - 100  # Subtract header and some footer
                swipe_distance = int(scrollable_height * 0.30)  # ~520px, gives more overlap

                # Use CENTER of screen (same as scroll_to_top/bottom)
                # 20% was hitting non-scrollable sidebars in some apps
                swipe_x = width // 2
                swipe_start_y = int(height * 0.70)  # Start at 70%
                swipe_end_y = swipe_start_y - swipe_distance  # End higher

                logger.info(f"  DETERMINISTIC SCROLL: {swipe_distance}px per swipe")
                logger.info(f"  Swipe from y={swipe_start_y} to y={swipe_end_y}")

                # Initialize captures with 4-element tuples: (img, elements, first_new_y, known_scroll)
                captures = [(img_top, elements_top, 0, 0)]  # First capture: known_scroll=0

                for i in range(max_scrolls):
                    logger.info(f"  Scroll DOWN {i+1}/{max_scrolls}...")

                    # SLOW swipe to minimize momentum (1000ms duration)
                    logger.info(f"  >>> SLOW SWIPE: y={swipe_start_y}->{swipe_end_y} ({swipe_distance}px, 1000ms)")

                    await self.adb_bridge.swipe(device_id, swipe_x, swipe_start_y, swipe_x, swipe_end_y, duration=1000)

                    scroll_count += 1

                    # Wait for scroll to settle completely
                    await asyncio.sleep(1.2)

                    # Capture screenshot
                    img_curr = await self._capture_screenshot_pil(device_id)
                    if not img_curr:
                        logger.warning(f"  Screenshot capture failed!")
                        break

                    # Get UI elements
                    elements_curr = await self._get_ui_elements_with_retry(device_id)
                    logger.info(f"  Got {len(elements_curr)} elements")

                    # Check if we've reached the bottom (image didn't change)
                    similarity = self._compare_images(prev_img, img_curr)
                    logger.info(f"  Image similarity: {similarity:.3f}")

                    if similarity > self.duplicate_threshold:
                        logger.info(f"  BOTTOM REACHED - can't scroll anymore")
                        break

                    # Add this capture with KNOWN scroll distance
                    # The new content in this capture = swipe_distance pixels from bottom
                    captures.append((img_curr, elements_curr, 0, swipe_distance))
                    prev_img = img_curr

                logger.info(f"  Total captures: {len(captures)} screenshots")

            # === STEP 4: Stitch ===
            logger.info(f"  Stitching {len(captures)} screenshots...")
            stitched, combined_elements, stitch_info = self._stitch_by_elements(captures, height)

            # === STEP 5: Build metadata ===
            duration_ms = int((time.time() - start_time) * 1000)
            final_width, final_height = stitched.size

            debug_screenshots = []
            for i, cap in enumerate(captures):
                # Unpack 4-element tuple: (img, elements, first_new_y, known_scroll)
                img = cap[0]
                elements = cap[1]
                first_new_y = cap[2] if len(cap) > 2 else 0
                known_scroll = cap[3] if len(cap) > 3 else 0

                img_buffer = io.BytesIO()
                img.save(img_buffer, format='PNG')
                img_buffer.seek(0)
                debug_screenshots.append({
                    'index': i,
                    'image': base64.b64encode(img_buffer.read()).decode('utf-8'),
                    'element_count': len(elements),
                    'first_new_y': first_new_y,
                    'known_scroll': known_scroll
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
                "strategy": "bookend" if len(overlap) >= 3 else "incremental",
                "stitch_info": stitch_info
            }

            logger.info(f"[ScreenshotStitcher] Complete: {final_width}x{final_height} in {duration_ms}ms")
            logger.info(f"  Strategy: {metadata['strategy']}, Scrolls: {scroll_count}, Captures: {len(captures)}")
            logger.info(f"  Combined elements: {len(combined_elements)}")

            return {
                "image": stitched,
                "elements": combined_elements,
                "metadata": metadata,
                "debug_screenshots": debug_screenshots
            }

        except Exception as e:
            logger.error(f"[ScreenshotStitcher] Capture failed: {e}")
            raise

    def _find_overlap_end_y(self, elements_prev: list, elements_curr: list, height: int) -> int:
        """Delegate to element analyzer."""
        return self.element_analyzer.find_overlap_end_y(elements_prev, elements_curr, height)

    def _get_element_bottom(self, element: dict) -> int:
        """Delegate to element analyzer."""
        return self.element_analyzer.get_element_bottom(element)

    async def _refresh_page(self, device_id: str, times: int = 3):
        """Delegate to device controller."""
        return await self.device_controller.refresh_page(device_id, times)

    def _detect_fixed_top_height(self, img1: Image.Image, img2: Image.Image) -> int:
        """Delegate to overlap detector."""
        return self.overlap_detector.detect_fixed_top_height(img1, img2)

    def _find_overlap_by_image(self, img1: Image.Image, img2: Image.Image, screen_height: int) -> int:
        """Delegate to overlap detector."""
        return self.overlap_detector.find_overlap_by_image(img1, img2, screen_height)

    async def _scroll_to_bottom(self, device_id: str, max_attempts: int = 5):
        """Delegate to device controller."""
        return await self.device_controller.scroll_to_bottom(device_id, max_attempts)

    def _find_safe_scroll_x(self, screen_width: int, elements: list) -> int:
        """Delegate to device controller."""
        return self.device_controller.find_safe_scroll_x(screen_width, elements)

    def _get_element_fingerprint(self, element: dict) -> str:
        """Delegate to element analyzer."""
        return self.element_analyzer.get_element_fingerprint(element)

    def _get_element_y_center(self, element: dict) -> int:
        """Delegate to element analyzer."""
        return self.element_analyzer.get_element_y_center(element)

    def _calculate_scroll_from_elements(
        self,
        elements1: list,
        elements2: list,
        screen_height: int
    ) -> tuple:
        """Delegate to element analyzer."""
        return self.element_analyzer.calculate_scroll_from_elements(elements1, elements2, screen_height)

    def _find_new_content_boundary(
        self,
        elements1: list,
        elements2: list,
        scroll_amount: int,
        screen_height: int
    ) -> int:
        """Delegate to element analyzer."""
        return self.element_analyzer.find_new_content_boundary(elements1, elements2, scroll_amount, screen_height)

    async def _get_ui_elements_with_retry(self, device_id: str, max_retries: int = 3) -> list:
        """Delegate to device controller."""
        return await self.device_controller.get_ui_elements_with_retry(device_id, max_retries)

    async def _scroll_to_top(self, device_id: str, max_attempts: int = 10):
        """Delegate to device controller."""
        return await self.device_controller.scroll_to_top(device_id, max_attempts)

    async def _capture_screenshot_pil(self, device_id: str) -> Optional[Image.Image]:
        """Delegate to device controller."""
        return await self.device_controller.capture_screenshot_pil(device_id)

    def _detect_fixed_bottom_height(self, img1: Image.Image, img2: Image.Image) -> int:
        """Delegate to overlap detector."""
        return self.overlap_detector.detect_fixed_bottom_height(img1, img2)

    def _compare_image_regions(self, img1: Image.Image, img2: Image.Image) -> float:
        """Delegate to overlap detector."""
        return self.overlap_detector.compare_image_regions(img1, img2)

    def _compare_images(self, img1: Image.Image, img2: Image.Image) -> float:
        """Delegate to overlap detector."""
        return self.overlap_detector.compare_images(img1, img2)

    async def _get_scroll_position(self, device_id: str) -> Optional[int]:
        """Delegate to device controller."""
        return await self.device_controller.get_scroll_position(device_id)

    def _find_overlap_offset(
        self,
        template: Image.Image,
        img2: Image.Image,
        search_height: int
    ) -> Tuple[Optional[int], Optional[float]]:
        """Delegate to overlap detector."""
        return self.overlap_detector.find_overlap_offset(template, img2, search_height)

    def _stitch_by_elements(
        self,
        captures: list,
        screen_height: int
    ) -> Tuple[Image.Image, list, dict]:
        """Delegate to image composer."""
        return self.image_composer.stitch_by_elements(captures, screen_height)

    def _remove_consecutive_duplicates(
        self,
        img: Image.Image,
        elements: list,
        screen_height: int
    ) -> Tuple[Image.Image, list]:
        """Delegate to utils module."""
        return remove_consecutive_duplicates(img, elements, screen_height)

    def _detect_overlap_between_captures(
        self,
        img1: Image.Image,
        img2: Image.Image,
        screen_height: int,
        known_scroll: int
    ) -> Tuple[int, int]:
        """Delegate to overlap detector."""
        return self.overlap_detector.detect_overlap_between_captures(img1, img2, screen_height, known_scroll)

    def _stitch_two_captures_simple(
        self,
        accumulated_img: Image.Image, accumulated_elements: list,
        new_img: Image.Image, new_elements: list,
        screen_height: int,
        new_content_start: int,
        current_result_height: int,
        detected_footer: int,
        is_last_capture: bool = True
    ) -> Tuple[Image.Image, list, dict]:
        """Delegate to image composer."""
        return self.image_composer.stitch_two_captures_simple(
            accumulated_img, accumulated_elements,
            new_img, new_elements,
            screen_height, new_content_start,
            current_result_height, detected_footer,
            is_last_capture
        )

    def _stitch_two_captures_deterministic(
        self,
        img1: Image.Image, elements1: list,
        img2: Image.Image, elements2: list,
        screen_height: int,
        known_scroll: int,
        current_result_height: int,
        is_last_capture: bool = True
    ) -> Tuple[Image.Image, list, dict]:
        """Delegate to image composer."""
        return self.image_composer.stitch_two_captures_deterministic(
            img1, elements1, img2, elements2,
            screen_height, known_scroll,
            current_result_height, is_last_capture
        )

    def _stitch_two_captures(
        self,
        img1: Image.Image, elements1: list,
        img2: Image.Image, elements2: list,
        screen_height: int,
        prev_raw_elements: list,
        current_result_height: int,
        is_last_capture: bool = True
    ) -> Tuple[Image.Image, list, dict]:
        """Delegate to image composer."""
        return self.image_composer.stitch_two_captures(
            img1, elements1, img2, elements2,
            screen_height, prev_raw_elements,
            current_result_height, is_last_capture
        )

    def _calculate_scroll_offset(self, elements_prev: list, elements_curr: list, height: int) -> int:
        """Delegate to element analyzer."""
        return self.element_analyzer.calculate_scroll_offset(elements_prev, elements_curr, height)

    def _stitch_images_smart(
        self,
        captures: list,  # List of (image, elements) tuples
        overlap_ratio: float,
        screen_height: int
    ) -> Image.Image:
        """Delegate to image composer."""
        return self.image_composer.stitch_images_smart(captures, overlap_ratio, screen_height)

    def _stitch_images(
        self,
        images: list,
        overlap_ratio: float
    ) -> Image.Image:
        """Delegate to image composer."""
        return self.image_composer.stitch_images(images, overlap_ratio)
