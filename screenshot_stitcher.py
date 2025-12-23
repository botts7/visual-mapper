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
import cv2
import io

# Import feature-based stitcher
try:
    from screenshot_stitcher_feature_matching import FeatureBasedStitcher
    FEATURE_MATCHING_AVAILABLE = True
except ImportError:
    FEATURE_MATCHING_AVAILABLE = False

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
        self.max_scrolls = 25  # Safety limit (increased for smaller scroll steps)
        self.duplicate_threshold = 0.95  # If images > 95% similar, we're not scrolling
        self.min_new_content_ratio = 0.05  # Need at least 5% new content to continue (was 15% - too strict)
        self.fixed_element_threshold = 0.95  # Threshold for detecting fixed UI elements (balanced - catches real fixed UI)

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

        logger.info("[ScreenshotStitcher] Initialized")

    async def _get_device_nav_info(self, device_id: str) -> dict:
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
            import subprocess
            import asyncio

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
        """
        Look for patterns like "Episode 5 of 8", "3/10", "Item 2 of 5"
        """
        import re

        patterns = [
            r'(\d+)\s*of\s*(\d+)',           # "5 of 8", "Episode 5 of 8"
            r'(\d+)\s*/\s*(\d+)',             # "5/8", "3/10"
            r'(\d+)\s*out of\s*(\d+)',        # "5 out of 8"
            r'Episode\s*(\d+).*?(\d+)\s*episodes',  # "Episode 5...8 episodes"
        ]

        for elem in elements:
            text = str(elem.get('text', '')) + ' ' + str(elem.get('content_desc', ''))

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    current = int(match.group(1))
                    total = int(match.group(2))
                    if 1 <= current <= total <= 1000:  # Sanity check
                        logger.info(f"[Pattern] Found '{match.group()}' -> {current} of {total}")
                        return {
                            'current_item': current,
                            'total_items': total,
                            'source_text': text[:50]
                        }

        return None

    def _estimate_from_numbered_items(self, elements: list) -> dict:
        """
        Find numbered items like "1. Title", "2. Another", "Episode 3"
        Track the sequence to find max number.
        Also track the Y position of the FIRST numbered item to estimate header height.

        IMPORTANT: Prefer content_desc over text as it usually refers to the FULL container
        with accurate height, while text is often just a small label.
        """
        import re

        numbered_items = []
        seen_numbers = set()  # Track which numbers we've seen to avoid duplicates

        # Patterns for numbered items
        patterns = [
            r'Episode\s*(\d+)',          # "Episode 5" - prioritize full episode containers
            r'Chapter\s*(\d+)',          # "Chapter 3"
            r'Item\s*(\d+)',             # "Item 7"
            r'^(\d+)\.\s+\w',           # "1. Title"
            r'^(\d+)\)\s+\w',           # "1) Title"
            r'^#(\d+)',                  # "#5"
        ]

        # FIRST PASS: Check content_desc (usually full containers with correct height)
        for elem in elements:
            content_desc = str(elem.get('content_desc', ''))
            bounds = elem.get('bounds', {})

            for pattern in patterns:
                match = re.search(pattern, content_desc, re.IGNORECASE)
                if match:
                    num = int(match.group(1))
                    if 1 <= num <= 1000 and num not in seen_numbers:
                        y_pos = bounds.get('y', 0) if isinstance(bounds, dict) else 0
                        height = bounds.get('height', 0) if isinstance(bounds, dict) else 0
                        # Only add if height is reasonable (full card, not just text)
                        if height > 100:
                            seen_numbers.add(num)
                            numbered_items.append({
                                'number': num,
                                'text': content_desc[:40],
                                'height': height,
                                'y': y_pos,
                                'source': 'content_desc'
                            })
                    break

        # SECOND PASS: Check text (fallback for apps without content_desc)
        for elem in elements:
            text = str(elem.get('text', ''))
            bounds = elem.get('bounds', {})

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    num = int(match.group(1))
                    if 1 <= num <= 1000 and num not in seen_numbers:
                        y_pos = bounds.get('y', 0) if isinstance(bounds, dict) else 0
                        height = bounds.get('height', 0) if isinstance(bounds, dict) else 0
                        seen_numbers.add(num)
                        numbered_items.append({
                            'number': num,
                            'text': text[:30],
                            'height': height,
                            'y': y_pos,
                            'source': 'text'
                        })
                    break

        if not numbered_items:
            return None

        # Find the highest number (likely total count)
        max_num = max(item['number'] for item in numbered_items)
        numbers_found = sorted(set(item['number'] for item in numbered_items))

        # Calculate average height of numbered items
        heights = [item['height'] for item in numbered_items if item['height'] > 50]
        avg_height = sum(heights) / len(heights) if heights else 200

        # Find the Y position of the FIRST visible numbered item
        # This helps estimate header height more accurately
        first_item = min(numbered_items, key=lambda x: x['number'])
        first_item_y = first_item.get('y', 0)
        first_item_num = first_item.get('number', 1)

        # Calculate where item #1 would start (extrapolate backward)
        # If we see item 6 at y=200, and items are ~230px each, then item 1 starts at y=200 - (5*230)
        estimated_item1_y = first_item_y - ((first_item_num - 1) * max(avg_height, 200))
        # Header is everything above where item 1 would be
        estimated_header = max(0, estimated_item1_y)

        logger.info(f"[Numbered] Found items: {numbers_found}, max={max_num}, avg_height={avg_height:.0f}px")
        logger.info(f"[Numbered] First visible: #{first_item_num} at y={first_item_y}, estimated header={estimated_header:.0f}px")

        return {
            'max_number': max_num,
            'numbers_found': numbers_found,
            'items_visible': len(numbered_items),
            'avg_height': int(avg_height),
            'first_item_y': first_item_y,
            'first_item_num': first_item_num,
            'estimated_header': int(estimated_header)
        }

    def _estimate_from_bounds(self, elements: list, screen_height: int) -> dict:
        """
        Analyze element bounds to estimate content structure.
        """
        # Find scrollable area
        scrollable_top = 0
        scrollable_bottom = screen_height

        for elem in elements:
            if elem.get('scrollable') == 'true' or elem.get('scrollable') == True:
                bounds = elem.get('bounds', {})
                if isinstance(bounds, dict):
                    scrollable_top = bounds.get('y', 0)
                    scrollable_bottom = scrollable_top + bounds.get('height', screen_height)
                    break

        scrollable_height = scrollable_bottom - scrollable_top

        # Find items within scrollable area
        items_in_scroll = []
        for elem in elements:
            bounds = elem.get('bounds', {})
            if isinstance(bounds, dict):
                y = bounds.get('y', 0)
                h = bounds.get('height', 0)
                # Items with reasonable height within scroll area
                if scrollable_top <= y < scrollable_bottom and 50 < h < 400:
                    items_in_scroll.append({'y': y, 'height': h})

        if not items_in_scroll:
            return None

        # Calculate stats
        heights = [item['height'] for item in items_in_scroll]
        avg_height = sum(heights) / len(heights)

        # Estimate header content (above scrollable area)
        header_estimate = scrollable_top + 400  # scrollable_top + some buffer for title/desc

        # Estimate total: visible items usually represent 30-50% of total
        # Use conservative 2.5x multiplier
        estimated_items = len(items_in_scroll) * 2.5
        estimated_total = header_estimate + (estimated_items * avg_height)

        return {
            'scrollable_area': scrollable_height,
            'scrollable_top': scrollable_top,
            'visible_items': len(items_in_scroll),
            'avg_item_height': int(avg_height),
            'header_estimate': header_estimate,
            'estimated_total': int(estimated_total)
        }

    def _get_scrollable_container_info(self, elements: list) -> dict:
        """
        Get info about the scrollable container.
        """
        for elem in elements:
            if elem.get('scrollable') == 'true' or elem.get('scrollable') == True:
                bounds = elem.get('bounds', {})
                if isinstance(bounds, dict):
                    return {
                        'class': elem.get('class', 'unknown'),
                        'bounds': bounds,
                        'resource_id': elem.get('resource_id', '')
                    }
        return None

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

            # === STEP 3: DYNAMICALLY detect fixed vs scrollable elements ===
            # Compare element positions between TOP and BOTTOM:
            # - Same fingerprint at SAME Y position = FIXED (header/footer/nav)
            # - Same fingerprint at DIFFERENT Y position = SCROLLABLE content that overlaps
            # - Fingerprint only in TOP or BOTTOM = SCROLLABLE content (no overlap)

            # Build position maps: fingerprint -> y_center
            fp_to_y_top = {}
            for elem in elements_top:
                fp = self._get_element_fingerprint(elem)
                if fp:
                    fp_to_y_top[fp] = self._get_element_y_center(elem)

            fp_to_y_bottom = {}
            for elem in elements_bottom:
                fp = self._get_element_fingerprint(elem)
                if fp:
                    fp_to_y_bottom[fp] = self._get_element_y_center(elem)

            # Categorize elements
            fixed_elements = set()      # Same position in both = fixed UI
            scrollable_overlap = set()  # Different position = scrollable content that overlaps
            y_tolerance = 20  # Allow small Y difference for "same position"

            for fp in fp_to_y_top:
                if fp in fp_to_y_bottom:
                    y_diff = abs(fp_to_y_top[fp] - fp_to_y_bottom[fp])
                    if y_diff <= y_tolerance:
                        fixed_elements.add(fp)
                    else:
                        scrollable_overlap.add(fp)

            # Elements only in TOP or only in BOTTOM are unique scrollable content
            fp_only_top = set(fp_to_y_top.keys()) - set(fp_to_y_bottom.keys())
            fp_only_bottom = set(fp_to_y_bottom.keys()) - set(fp_to_y_top.keys())

            logger.info(f"  DYNAMIC DETECTION:")
            logger.info(f"    Fixed elements (same Y): {len(fixed_elements)}")
            logger.info(f"    Scrollable overlap (different Y): {len(scrollable_overlap)}")
            logger.info(f"    Only in TOP: {len(fp_only_top)}")
            logger.info(f"    Only in BOTTOM: {len(fp_only_bottom)}")

            # Content overlap = elements that exist in BOTH but at DIFFERENT positions
            overlap = scrollable_overlap
            logger.info(f"  CONTENT OVERLAP CHECK: {len(overlap)} scrollable elements overlap")

            # Build fp_bottom set for later use (checking if we reached bottom content)
            fp_bottom = set(fp_to_y_bottom.keys())

            # If TOP and BOTTOM share scrollable content elements, we can stitch them directly
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

                # Use 45% of scrollable area per swipe for good overlap
                scrollable_height = height - fixed_header - 100  # Subtract header and some footer
                swipe_distance = int(scrollable_height * 0.45)  # ~450px on 1200px screen

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

        Handles:
        - Regular apps with status bar + app header (~80-120px)
        - Minimal header apps (~24-50px, just status bar)
        - Fullscreen apps (0px fixed header)
        - Gesture navigation with thin hints

        Returns:
            Height in pixels of the fixed top element, or 0 if none detected
        """
        try:
            width, height = img1.size

            # Start small to detect fullscreen apps and minimal headers
            # Use smaller step size for precision
            step_size = 15
            last_similar_height = 0

            # Check top portions in increments starting from 10px
            for check_height in range(10, min(300, height // 4), step_size):
                # Extract top portions
                top1 = img1.crop((0, 0, width, check_height))
                top2 = img2.crop((0, 0, width, check_height))

                # Compare them
                similarity = self._compare_image_regions(top1, top2)

                if similarity >= self.fixed_element_threshold:
                    # This region is identical - it's part of fixed header
                    last_similar_height = check_height
                else:
                    # Found where content differs - fixed element ends here
                    if last_similar_height > 0:
                        logger.info(f"  Detected fixed top element: {last_similar_height}px")
                        return last_similar_height
                    else:
                        # Even first check was different - fullscreen app with no fixed header
                        logger.info(f"  No fixed top element detected (fullscreen app)")
                        return 0

            # If we checked all and they were all similar, use last known similar height
            if last_similar_height > 0:
                logger.info(f"  Detected fixed top element: {last_similar_height}px (max checked)")
                return last_similar_height

            # No fixed header detected
            return 0

        except Exception as e:
            logger.warning(f"  Fixed top element detection failed: {e}")
            return 0

    def _find_overlap_by_image(self, img1: Image.Image, img2: Image.Image, screen_height: int) -> int:
        """
        Find scroll offset by matching the bottom of img1 with the top of img2.
        Uses template matching on a strip from img1's bottom.

        Returns:
            scroll_offset in pixels (how much content moved between captures)
        """
        try:
            import numpy as np

            width = img1.size[0]
            img1_height = img1.size[1]

            # Convert to numpy arrays and ensure RGB (not RGBA)
            arr1 = np.array(img1.convert('RGB'))
            arr2 = np.array(img2.convert('RGB'))

            # Take a strip from the MIDDLE portion of img1 (avoiding header and footer)
            # This strip should appear somewhere in img2 after scrolling
            strip_height = 100  # Use 100px strip for matching
            # For accumulated images, use middle of the LAST screen_height portion
            if img1_height > screen_height:
                # Use middle of the bottom screen-worth of content
                strip_start = img1_height - screen_height + int(screen_height * 0.4)
            else:
                # Single screen - use middle area
                strip_start = int(screen_height * 0.4)
            strip_start = max(200, min(strip_start, img1_height - 300))  # Bounds check
            strip_end = strip_start + strip_height

            strip = arr1[strip_start:strip_end, :, :]
            logger.info(f"  Template matching: strip from y={strip_start}-{strip_end} in img1")

            # Search for this strip in img2 (skip header area)
            search_start = 80  # Skip status bar
            search_end = screen_height - 100  # Leave room for search

            best_match_y = -1
            best_match_score = 0

            # Slide the template down img2 and find best match
            for y in range(search_start, search_end - strip_height, 10):  # Step by 10 for speed
                region = arr2[y:y + strip_height, :, :]

                # Calculate similarity (simple mean absolute difference)
                diff = np.abs(strip.astype(float) - region.astype(float))
                similarity = 1.0 - (np.mean(diff) / 255.0)

                if similarity > best_match_score:
                    best_match_score = similarity
                    best_match_y = y

            if best_match_score > 0.85:  # Good match threshold
                # scroll_offset = where strip was in img1 - where it is in img2
                scroll_offset = strip_start - best_match_y
                logger.info(f"  Template match found: y={best_match_y} in img2, score={best_match_score:.3f}")
                logger.info(f"  Calculated scroll_offset: {scroll_offset}px")

                if scroll_offset > 0:
                    return scroll_offset

            # Fallback: assume ~50% scroll based on typical swipe distance
            fallback = int(screen_height * 0.5)
            logger.warning(f"  Template matching failed (best score: {best_match_score:.3f}). Using fallback: {fallback}px")
            return fallback

        except Exception as e:
            logger.error(f"  Image-based overlap detection failed: {e}")
            return int(screen_height * 0.5)

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

        Handles:
        - Standard apps with nav bar (~48-150px)
        - Fullscreen apps (0px footer)
        - Gesture navigation (~20px hint bar)

        Returns:
            Height in pixels of the fixed bottom element, or 0 if none detected
        """
        try:
            width, height = img1.size

            # Use smaller step size for more accurate detection
            step_size = 10
            last_similar_height = 0

            # Check bottom portions in small increments
            # Start from VERY small (10px) to detect even gesture nav hint bars
            # This allows detecting fullscreen apps with 0px footer
            for check_height in range(10, min(300, height // 3), step_size):
                # Extract bottom portions
                bottom1 = img1.crop((0, height - check_height, width, height))
                bottom2 = img2.crop((0, height - check_height, width, height))

                # Compare them
                similarity = self._compare_image_regions(bottom1, bottom2)

                if similarity >= self.fixed_element_threshold:
                    # This region is still fixed (identical)
                    last_similar_height = check_height
                else:
                    # Found where content starts to differ
                    # Fixed footer is everything that was still similar
                    if last_similar_height > 0:
                        logger.info(f"  Detected fixed footer: {last_similar_height}px (diff at {check_height}px)")
                        return last_similar_height
                    else:
                        # No fixed footer at all - likely fullscreen app
                        logger.info(f"  No fixed footer detected (fullscreen app?)")
                        return 0

            # If we checked up to max and everything was similar, return a reasonable estimate
            # Add some buffer since we might have stopped just before the transition
            if last_similar_height > 0:
                result = min(last_similar_height + 20, 200)
                logger.info(f"  Fixed footer (all similar): {result}px")
                return result

            # Nothing was similar - fullscreen or dynamic content at bottom
            logger.info(f"  No fixed footer (dynamic bottom content)")
            return 0

        except Exception as e:
            logger.warning(f"  Fixed element detection failed: {e}")
            return 0  # Assume no footer on error - safer for fullscreen apps

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
        template: Image.Image,
        img2: Image.Image,
        search_height: int
    ) -> Tuple[Optional[int], Optional[float]]:
        """
        Find Y-offset where template appears in img2
        Uses OpenCV template matching with TM_CCOEFF_NORMED

        Args:
            template: Pre-cropped template strip to search for
            img2: Current screenshot to search in
            search_height: Height of region in img2 to search

        Returns:
            Tuple of (Y-offset in pixels, match quality) or (None, None) if no match
        """
        try:
            width2, height2 = img2.size
            template_width, template_height = template.size

            # Extract search region from img2
            actual_search_height = min(search_height, height2)
            search_region = img2.crop((0, 0, width2, actual_search_height))

            # Convert PIL to numpy arrays
            template_np = np.array(template.convert('RGB'))
            search_np = np.array(search_region.convert('RGB'))

            # Convert to grayscale for better matching
            template_gray = cv2.cvtColor(template_np, cv2.COLOR_RGB2GRAY)
            search_gray = cv2.cvtColor(search_np, cv2.COLOR_RGB2GRAY)

            # Template matching
            result = cv2.matchTemplate(search_gray, template_gray, cv2.TM_CCOEFF_NORMED)

            # Find best match
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            # max_loc = (x, y) of top-left corner of best match
            offset_y = max_loc[1]

            # Quality check
            if max_val < self.match_threshold:
                logger.warning(f"  Low match quality: {max_val:.3f} (threshold: {self.match_threshold})")

            logger.info(f"  Template match: y={offset_y}, confidence={max_val:.3f}")

            return offset_y, max_val

        except Exception as e:
            logger.error(f"  Template matching failed: {e}")
            import traceback
            traceback.print_exc()
            return None, None

    def _stitch_by_elements(
        self,
        captures: list,  # List of (image, elements, _unused, known_scroll) tuples
        screen_height: int
    ) -> Tuple[Image.Image, list, dict]:
        """
        DETERMINISTIC STITCH method - uses KNOWN scroll distances:
        For each capture after the first:
        1. We know exactly how much was scrolled (known_scroll)
        2. New content = bottom portion of new capture (height - overlap)
        3. Overlap = screen_height - known_scroll - fixed_header

        Returns:
            Tuple of (stitched_image, combined_elements, stitch_info)
            - combined_elements: All elements with adjusted Y positions for the stitched image
            - stitch_info: Dict with scroll_offset, header_height, footer_height, etc.
        """
        if not captures:
            raise ValueError("No captures to stitch")

        # Handle different tuple lengths (3 or 4 elements)
        def unpack_capture(cap):
            if len(cap) >= 4:
                return cap[0], cap[1], cap[2], cap[3]
            else:
                return cap[0], cap[1], cap[2] if len(cap) > 2 else 0, 0

        if len(captures) == 1:
            img, elements, _, _ = unpack_capture(captures[0])
            return img, elements, {"scroll_offset": 0, "header_height": 0, "footer_height": 0}

        # For 2+ captures, stitch iteratively
        # Start with first capture as base
        img, elements, _, _ = unpack_capture(captures[0])
        result_img = img
        result_elements = elements
        width, height = result_img.size
        total_stitch_info = {
            "scroll_offset": 0,
            "header_height": 0,
            "footer_height": 0,
            "stitch_count": len(captures) - 1
        }

        # Track the LAST RAW capture for template matching
        prev_raw_img = img
        prev_raw_elements = result_elements
        current_result_height = height

        # Stitch each subsequent capture to the result
        for i in range(1, len(captures)):
            img_next, elements_next, _, known_scroll = unpack_capture(captures[i])
            is_last = (i == len(captures) - 1)

            logger.info(f"  === IMAGE-BASED STITCHING: Capture {i}/{len(captures)-1} ===")

            # Do template matching between consecutive RAW captures
            # This gives us the actual overlap AND the detected footer height
            detected_new_content_start, detected_footer = self._detect_overlap_between_captures(
                prev_raw_img, img_next, height, known_scroll
            )
            logger.info(f"  Detected new content starts at y={detected_new_content_start}, footer={detected_footer}px")

            result_img, result_elements, stitch_info = self._stitch_two_captures_simple(
                result_img, result_elements,
                img_next, elements_next,
                screen_height,
                detected_new_content_start,  # Use detected position
                current_result_height,
                detected_footer,  # Pass detected footer - no hardcoding!
                is_last_capture=is_last
            )

            # Update for next iteration
            prev_raw_img = img_next
            prev_raw_elements = elements_next
            current_result_height = result_img.size[1]

            # Accumulate stitch info
            total_stitch_info["scroll_offset"] += stitch_info.get("scroll_offset", 0)
            if is_last:
                total_stitch_info["header_height"] = stitch_info.get("header_height", 0)
                total_stitch_info["footer_height"] = stitch_info.get("footer_height", 0)

        # Final summary
        final_w, final_h = result_img.size
        logger.info(f"  === STITCH SUMMARY ===")
        logger.info(f"  Final image: {final_w}x{final_h}px from {len(captures)} captures")
        logger.info(f"  Total elements: {len(result_elements)}")

        return result_img, result_elements, total_stitch_info

    def _detect_overlap_between_captures(
        self,
        img1: Image.Image,
        img2: Image.Image,
        screen_height: int,
        known_scroll: int
    ) -> Tuple[int, int]:
        """
        Detect where new content starts in img2 by template matching with img1.
        Both images should be RAW captures (same size as screen).

        The key insight: after scrolling DOWN by X pixels, content moves UP.
        So content at y=Y in img1 appears at y=Y-X in img2.
        The overlap region is: content at y=(screen-X) to y=screen in img1
        appears at y=0 to y=X in img2 (roughly, accounting for fixed elements).

        Returns:
            Tuple of (new_content_start, detected_footer)
            - new_content_start: Y position in img2 where new content starts
            - detected_footer: The detected fixed footer height for this app
        """
        try:
            width = img1.size[0]

            # Detect fixed footer by comparing bottom regions
            fixed_footer = self._detect_fixed_bottom_height(img1, img2)
            # Apply reasonable bounds based on what's possible:
            # - Fullscreen apps: 0px footer
            # - Gesture nav: ~20px (just hint bar)
            # - 3-button nav: ~48px
            # - Nav + app bar: ~100-150px
            # - Max: 150px (more is likely mis-detection)
            #
            # IMPORTANT: Don't enforce a minimum - fullscreen/gesture apps may have 0px footer
            if fixed_footer < 0:
                fixed_footer = 0
            elif fixed_footer > 150:
                logger.info(f"  Footer detection capped: {fixed_footer}px -> 150px (likely mis-detection)")
                fixed_footer = 150  # Cap to prevent over-cropping
            logger.info(f"  Using fixed_footer={fixed_footer}px (0=fullscreen/gesture possible)")

            # Detect fixed header
            fixed_header = self._detect_fixed_top_height(img1, img2)
            # Apply reasonable bounds for header
            # - Fullscreen apps: 0px header (no status bar)
            # - Normal apps: 24px status bar + 56px app bar = ~80px
            # - Max: 120px (more is likely mis-detection)
            #
            # IMPORTANT: Don't enforce large minimum - fullscreen apps may have small/no header
            if fixed_header < 0:
                fixed_header = 0
            elif fixed_header > 120:
                logger.info(f"  Header detection capped: {fixed_header}px -> 120px (likely mis-detection)")
                fixed_header = 120
            logger.info(f"  Detected fixed_header={fixed_header}px (0=fullscreen possible)")

            # SIMPLE CALCULATION based on scroll distance
            # After scrolling known_scroll pixels, the overlap is:
            # screen_height - known_scroll - fixed_header - fixed_footer (scrollable area that's still visible)
            # New content starts at: screen_height - known_scroll (approximately)

            # But we need to account for fixed header - content below header shifts
            # Actual new content start = screen_height - known_scroll
            # But since header is fixed, we take content starting from there

            # Simple approach: new content starts at approximately (header + overlap)
            scrollable_height = screen_height - fixed_header - fixed_footer
            overlap = scrollable_height - known_scroll
            if overlap < 0:
                overlap = 0

            new_content_start = fixed_header + overlap
            logger.info(f"  Calculated: scrollable={scrollable_height}, overlap={overlap}, new_start={new_content_start}")

            # VERIFY with template matching
            # Take template from middle of img1's scrollable area
            template_height = 80
            # Use content from around 40% from top of scrollable area
            template_top = fixed_header + int(scrollable_height * 0.4)
            template_bottom = template_top + template_height

            template = img1.crop((0, template_top, width, template_bottom))
            logger.info(f"  Verification template: y={template_top}-{template_bottom}")

            # This template should appear at template_top - known_scroll in img2
            expected_match_y = template_top - known_scroll
            logger.info(f"  Expected match at y={expected_match_y}")

            # Search in img2
            match_y, confidence = self._find_overlap_offset(template, img2, screen_height - fixed_footer)

            if match_y is not None and confidence and confidence > 0.8:
                logger.info(f"  Actual match at y={match_y} (conf={confidence:.3f})")
                # Calculate actual scroll from match
                actual_scroll = template_top - match_y
                logger.info(f"  Implied actual scroll: {actual_scroll}px (commanded: {known_scroll}px)")

                # If actual scroll differs significantly from known, adjust
                if abs(actual_scroll - known_scroll) < 100:
                    # Use calculated value since match confirms it's close
                    logger.info(f"  Match confirms calculation, using new_content_start={new_content_start}")
                    return (new_content_start, fixed_footer)
                else:
                    # Match found but scroll different - use match-based calculation
                    adjusted_overlap = scrollable_height - actual_scroll
                    adjusted_new_start = fixed_header + max(0, adjusted_overlap)
                    logger.info(f"  Adjusting based on match: new_content_start={adjusted_new_start}")
                    return (adjusted_new_start, fixed_footer)
            else:
                logger.warning(f"  Template match weak (conf={confidence}), using calculated value")
                return (new_content_start, fixed_footer)

        except Exception as e:
            logger.error(f"  Overlap detection failed: {e}")
            import traceback
            traceback.print_exc()
            # Ultimate fallback - use 100px as safe footer estimate
            return (screen_height - known_scroll, 100)

    def _stitch_two_captures_simple(
        self,
        accumulated_img: Image.Image, accumulated_elements: list,
        new_img: Image.Image, new_elements: list,
        screen_height: int,
        new_content_start: int,  # Where new content starts in new_img
        current_result_height: int,
        detected_footer: int,  # Dynamically detected footer height
        is_last_capture: bool = True
    ) -> Tuple[Image.Image, list, dict]:
        """
        Simple stitch - just paste new content at the detected position.
        new_content_start is already determined by template matching.
        detected_footer is dynamically detected from image comparison.
        """
        width = accumulated_img.size[0]
        acc_height = accumulated_img.size[1]

        # Use the dynamically detected footer - no hardcoding!
        fixed_footer = detected_footer
        logger.info(f"  Using dynamically detected footer: {fixed_footer}px")

        # Where to stop in new_img
        new_content_end = screen_height if is_last_capture else (screen_height - fixed_footer)
        new_content_height = new_content_end - new_content_start

        if new_content_height <= 0:
            logger.warning(f"  No new content! height={new_content_height}")
            return accumulated_img, accumulated_elements, {"scroll_offset": 0}

        # For first stitch, we need to crop footer from accumulated image
        if acc_height == screen_height and not is_last_capture:
            paste_y = acc_height - fixed_footer
        else:
            paste_y = acc_height

        # Total height
        total_height = paste_y + new_content_height

        logger.info(f"  Stitching: new content y={new_content_start}-{new_content_end} ({new_content_height}px)")
        logger.info(f"  Paste at y={paste_y}, total height={total_height}px")

        # Create stitched image
        stitched = Image.new('RGB', (width, total_height))

        # Paste accumulated image (crop footer if first stitch)
        if acc_height == screen_height and not is_last_capture:
            cropped_acc = accumulated_img.crop((0, 0, width, paste_y))
            stitched.paste(cropped_acc, (0, 0))
        else:
            stitched.paste(accumulated_img, (0, 0))

        # Paste new content
        new_content = new_img.crop((0, new_content_start, width, new_content_end))
        stitched.paste(new_content, (0, paste_y))

        # === Combine elements ===
        combined_elements = []

        # Elements from accumulated image (filter out footer area if first stitch)
        for elem in accumulated_elements:
            y_center = self._get_element_y_center(elem)
            if y_center <= paste_y:
                combined_elements.append(elem.copy())

        # Elements from new image (only in new content region)
        y_adjustment = paste_y - new_content_start
        for elem in new_elements:
            y_center = self._get_element_y_center(elem)
            if new_content_start <= y_center <= new_content_end:
                adjusted_elem = elem.copy()
                bounds = adjusted_elem.get('bounds', {})
                if isinstance(bounds, dict):
                    adjusted_elem['bounds'] = {
                        'x': bounds.get('x', 0),
                        'y': bounds.get('y', 0) + y_adjustment,
                        'width': bounds.get('width', 0),
                        'height': bounds.get('height', 0)
                    }
                combined_elements.append(adjusted_elem)

        return stitched, combined_elements, {"scroll_offset": new_content_start}

    def _stitch_two_captures_deterministic(
        self,
        img1: Image.Image, elements1: list,
        img2: Image.Image, elements2: list,
        screen_height: int,
        known_scroll: int,  # KNOWN scroll distance from swipe (used as fallback)
        current_result_height: int,
        is_last_capture: bool = True
    ) -> Tuple[Image.Image, list, dict]:
        """
        IMAGE-BASED stitch using visual template matching.
        Works for ANY app by detecting actual overlap visually.

        Logic:
        1. Detect fixed footer by comparing bottom regions of img1 and img2
        2. Detect fixed header by comparing top regions
        3. Extract template strip from img1 (above footer)
        4. Find where this template appears in img2 using template matching
        5. New content starts AFTER the matched region
        """
        width = img1.size[0]
        img1_height = img1.size[1]

        logger.info(f"  IMAGE-BASED STITCH: screen={screen_height}, result={img1_height}, is_last={is_last_capture}")

        # === STEP 1: Detect fixed header by comparing top regions ===
        fixed_header = self._detect_fixed_top_height(img1, img2) if img1_height == screen_height else 0
        if fixed_header < 50:
            fixed_header = 50  # Minimum header (status bar)
        logger.info(f"  Detected fixed header: {fixed_header}px")

        # === STEP 2: Detect fixed footer by comparing bottom regions ===
        # Only detect for raw screenshots (not accumulated images)
        if img1_height == screen_height:
            fixed_footer = self._detect_fixed_bottom_height(img1, img2)
            if fixed_footer < 50:
                fixed_footer = 100  # Minimum footer (nav bar)
        else:
            fixed_footer = 100  # Use reasonable default for accumulated images

        effective_footer = 0 if is_last_capture else fixed_footer
        logger.info(f"  Detected fixed footer: {fixed_footer}px, effective={effective_footer}px")

        # === STEP 3: Find actual overlap using template matching ===
        # Extract a template strip from img1 (above the footer area)
        template_height = 80  # Use 80px strip for reliable matching

        # For accumulated images, get template from the bottom portion
        if img1_height > screen_height:
            # Use content from the last screen-worth, avoiding footer
            template_top = img1_height - fixed_footer - template_height - 30
        else:
            # For first image, use content above footer
            template_top = screen_height - fixed_footer - template_height - 30

        template_top = max(fixed_header + 50, template_top)  # Ensure we're below header
        template_bottom = template_top + template_height

        logger.info(f"  Template extraction: y={template_top}-{template_bottom} ({template_height}px)")

        # Extract template from img1
        template = img1.crop((0, template_top, width, template_bottom))

        # Search for template in img2
        match_y, confidence = self._find_overlap_offset(
            template,
            img2,
            screen_height - fixed_header  # Search in most of img2
        )

        # Calculate new_content_start based on match
        if match_y is not None and confidence and confidence > 0.7:
            # Good match found - new content starts after the matched region
            new_content_start = match_y + template_height
            logger.info(f"  Template matched at y={match_y} (confidence={confidence:.3f})")
            logger.info(f"  New content starts at y={new_content_start} (from image matching)")
        else:
            # Fallback to calculated overlap
            logger.warning(f"  Template match failed (conf={confidence}), using calculated fallback")
            scrollable_height = screen_height - fixed_header - fixed_footer
            overlap = max(0, scrollable_height - known_scroll)
            new_content_start = fixed_header + overlap
            logger.info(f"  Fallback: new_content_start={new_content_start} (calculated)")

        # Where to stop - include footer only on last capture
        new_content_end = screen_height if is_last_capture else (screen_height - effective_footer)
        new_content_height = new_content_end - new_content_start

        if new_content_height <= 0:
            logger.warning(f"  No new content! new_content_height={new_content_height}")
            return img1, elements1, {"scroll_offset": known_scroll, "header_height": fixed_header, "footer_height": effective_footer}

        # Calculate paste position: bottom of img1
        # On first stitch, crop footer from img1 too
        if img1_height == screen_height and not is_last_capture:
            paste_y = img1_height - fixed_footer  # First image - remove its footer
        else:
            paste_y = img1_height  # Accumulated image - footer already removed

        # Total height of stitched image
        total_height = paste_y + new_content_height

        logger.info(f"  New content: y={new_content_start}-{new_content_end} ({new_content_height}px)")
        logger.info(f"  Paste at y={paste_y}, Total height={total_height}px")
        logger.info(f"  DEBUG: img1 crop y=0-{paste_y}, img2 crop y={new_content_start}-{new_content_end}")
        logger.info(f"  DEBUG: Strip {1 if img1_height == screen_height else 'N'} contributes {paste_y}px from img1, {new_content_height}px from img2")

        # Create canvas and stitch
        stitched = Image.new('RGB', (width, total_height))

        # Paste img1 (crop footer on first stitch, except if it's also the last)
        if img1_height == screen_height and fixed_footer > 0 and not is_last_capture:
            # First image - crop out its footer
            img1_cropped = img1.crop((0, 0, width, img1_height - fixed_footer))
            stitched.paste(img1_cropped, (0, 0))
            logger.info(f"  Pasted img1 cropped (removed {fixed_footer}px footer)")
        else:
            stitched.paste(img1, (0, 0))
            logger.info(f"  Pasted img1 full ({img1_height}px)")

        # Paste new content from img2
        new_content = img2.crop((0, new_content_start, width, new_content_end))
        stitched.paste(new_content, (0, paste_y))

        logger.info(f"  Pasted img1 at y=0, new content ({new_content_height}px) at y={paste_y}")

        # === BUILD COMBINED ELEMENTS ===
        combined_elements = []
        fingerprint_y_positions = {}

        # Determine the crop boundary for img1 elements
        # If we cropped the footer from img1, exclude elements in that region
        img1_crop_bottom = paste_y  # Elements above this Y are included

        # Add elements from img1 (only those within the included region)
        img1_included = 0
        img1_excluded = 0
        for elem in elements1:
            y_center = self._get_element_y_center(elem)

            # Skip elements that are in the cropped footer region
            if y_center > img1_crop_bottom:
                img1_excluded += 1
                continue

            fp = self._get_element_fingerprint(elem)
            combined_elements.append(elem.copy())
            img1_included += 1
            if fp:
                if fp not in fingerprint_y_positions:
                    fingerprint_y_positions[fp] = []
                fingerprint_y_positions[fp].append(y_center)

        logger.info(f"  Elements from img1: {img1_included} included, {img1_excluded} excluded (in footer)")

        # Add NEW elements from img2 (only those in the new content region)
        y_adjustment = paste_y - new_content_start
        added_count = 0

        for elem in elements2:
            fp = self._get_element_fingerprint(elem)
            y_center = self._get_element_y_center(elem)

            # Only include elements in the NEW content region
            if y_center < new_content_start or y_center > new_content_end:
                continue

            # Check for position-aware duplicates
            adjusted_y = y_center + y_adjustment
            if fp and fp in fingerprint_y_positions:
                is_dup = any(abs(existing_y - adjusted_y) < 100 for existing_y in fingerprint_y_positions[fp])
                if is_dup:
                    continue

            # Create adjusted element
            adjusted_elem = elem.copy()
            bounds = adjusted_elem.get('bounds', {})
            if isinstance(bounds, dict):
                adjusted_elem['bounds'] = {
                    'x': bounds.get('x', 0),
                    'y': bounds.get('y', 0) + y_adjustment,
                    'width': bounds.get('width', 0),
                    'height': bounds.get('height', 0)
                }
            elif isinstance(bounds, str):
                import re
                match = re.findall(r'\[(\d+),(\d+)\]', bounds)
                if len(match) >= 2:
                    x1, y1 = int(match[0][0]), int(match[0][1])
                    x2, y2 = int(match[1][0]), int(match[1][1])
                    adjusted_elem['bounds'] = f"[{x1},{y1 + y_adjustment}][{x2},{y2 + y_adjustment}]"

            combined_elements.append(adjusted_elem)
            added_count += 1
            if fp:
                if fp not in fingerprint_y_positions:
                    fingerprint_y_positions[fp] = []
                fingerprint_y_positions[fp].append(adjusted_y)

        logger.info(f"  Combined: {len(combined_elements)} elements (added {added_count} from img2)")
        logger.info(f"  DEBUG: Element Y adjustment = {y_adjustment}px (paste_y={paste_y} - crop_top={new_content_start})")

        # Log sample element bounds for debugging
        if added_count > 0 and combined_elements:
            sample = combined_elements[-1]  # Last added element
            sample_bounds = sample.get('bounds', {})
            sample_text = sample.get('text', '')[:30]
            logger.info(f"  DEBUG: Sample element '{sample_text}' bounds={sample_bounds}")

        stitch_info = {
            "scroll_offset": known_scroll,
            "header_height": fixed_header,
            "footer_height": effective_footer,
            "new_content_start": new_content_start,
            "paste_y": paste_y,
            "is_last": is_last_capture
        }

        return stitched, combined_elements, stitch_info

    def _stitch_two_captures(
        self,
        img1: Image.Image, elements1: list,
        img2: Image.Image, elements2: list,
        screen_height: int,
        prev_raw_elements: list,  # Raw elements from previous capture for scroll offset calc
        current_result_height: int,  # Current height of accumulated result
        is_last_capture: bool = True
    ) -> Tuple[Image.Image, list, dict]:
        """
        Stitch two captures together using the tracing paper method.
        img1 is the accumulated result (may be taller than screen_height)
        img2 is the new capture (screen_height tall)
        prev_raw_elements are the RAW elements from the previous capture (for scroll offset calc)
        """
        width = img1.size[0]
        height = screen_height  # Use screen height for calculations
        img1_height = img1.size[1]

        logger.info(f"  Screen: {width}x{height}, Accumulated: {img1_height}px")

        # Step 0: Detect fixed footer using two raw screen-height images
        # For iterative stitching, we need to crop img1 to bottom screen_height pixels
        if img1_height > height:
            # Get bottom portion of accumulated image for footer detection
            img1_bottom = img1.crop((0, img1_height - height, width, img1_height))
            fixed_footer_height = self._detect_fixed_bottom_height(img1_bottom, img2)
        else:
            fixed_footer_height = self._detect_fixed_bottom_height(img1, img2)
        logger.info(f"  Fixed footer height: {fixed_footer_height}px")

        # Step 1: Build element position maps using RAW elements for scroll offset calculation
        # Use prev_raw_elements (RAW positions) instead of elements1 (which may be adjusted)
        # fingerprint -> (y_center, y_top, y_bottom)
        prev_positions = {}
        for elem in prev_raw_elements:
            fp = self._get_element_fingerprint(elem)
            if fp:
                y_center = self._get_element_y_center(elem)
                y_bottom = self._get_element_bottom(elem)
                y_top = y_center - (y_bottom - y_center)  # Estimate top
                prev_positions[fp] = (y_center, y_top, y_bottom)

        elem2_positions = {}
        for elem in elements2:
            fp = self._get_element_fingerprint(elem)
            if fp:
                y_center = self._get_element_y_center(elem)
                y_bottom = self._get_element_bottom(elem)
                y_top = y_center - (y_bottom - y_center)
                elem2_positions[fp] = (y_center, y_top, y_bottom)

        logger.info(f"  Prev: {len(prev_positions)} elements, New: {len(elem2_positions)} elements")

        # Step 2: Find common elements (excluding fixed header/footer regions)
        # Header region: top 15% of screen
        # Footer region: bottom 20% of screen
        header_limit = height * 0.15
        footer_limit = height * 0.80

        common_elements = []
        for fp in prev_positions:
            if fp in elem2_positions:
                y1_center = prev_positions[fp][0]
                y2_center = elem2_positions[fp][0]

                # Element must be in scrollable region in BOTH captures
                # In prev: should be in middle-to-bottom (scrollable content)
                # In new: should be in top-to-middle (scrolled up content)
                if y1_center > header_limit and y2_center < footer_limit:
                    offset = y1_center - y2_center
                    common_elements.append((fp, y1_center, y2_center, offset))
                    logger.info(f"    Common: '{fp[:35]}' prev_y={int(y1_center)}, new_y={int(y2_center)}, offset={int(offset)}")

        if not common_elements:
            logger.warning("  No common elements found! Checking all elements...")
            # Try with looser constraints
            for fp in prev_positions:
                if fp in elem2_positions:
                    y1 = prev_positions[fp][0]
                    y2 = elem2_positions[fp][0]
                    offset = y1 - y2
                    # Only consider positive offsets (scrolled down)
                    if offset > 50:
                        common_elements.append((fp, y1, y2, offset))
                        logger.info(f"    Found: '{fp[:35]}' offset={int(offset)}")

        # === HYBRID APPROACH: 3 methods, cross-validate ===
        # 1. Element-based (fastest, semantic)
        # 2. ORB feature matching (robust to rendering variations)
        # 3. Template matching (fallback)

        element_offset = None
        feature_offset = None
        template_offset = None

        # Method 1: Element-based offset
        if common_elements:
            meaningful_offsets = [c[3] for c in common_elements if 100 < c[3] < height]
            if meaningful_offsets:
                meaningful_offsets.sort()
                element_offset = int(meaningful_offsets[len(meaningful_offsets) // 2])
                logger.info(f"  [1] Element-based offset: {element_offset}px (from {len(meaningful_offsets)} elements)")

        # Method 2: ORB Feature matching
        if self.feature_stitcher:
            try:
                offset, confidence, debug = self.feature_stitcher.find_overlap_offset_features(
                    img1, img2, height
                )
                if offset and confidence > 0.5:
                    feature_offset = offset
                    logger.info(f"  [2] ORB feature offset: {feature_offset}px (confidence: {confidence:.2f})")
                else:
                    logger.info(f"  [2] ORB feature matching: low confidence ({confidence:.2f})")
            except Exception as e:
                logger.warning(f"  [2] ORB feature matching failed: {e}")

        # Method 3: Template matching
        template_offset = self._find_overlap_by_image(img1, img2, height)
        logger.info(f"  [3] Template offset: {template_offset}px")

        # Cross-validate and pick best result
        # Lower minimum to accept smaller scrolls (device may scroll less than expected)
        min_valid = int(height * 0.08)  # At least 8% scroll (~100px on 1200px screen)
        max_valid = int(height * 0.85)  # At most 85% scroll

        valid_offsets = []
        if element_offset and min_valid < element_offset < max_valid:
            valid_offsets.append(('element', element_offset))
        if feature_offset and min_valid < feature_offset < max_valid:
            valid_offsets.append(('feature', feature_offset))
        if template_offset and min_valid < template_offset < max_valid:
            valid_offsets.append(('template', template_offset))

        logger.info(f"  Valid offsets: {valid_offsets}")

        if len(valid_offsets) >= 2:
            # Multiple methods gave valid results - find consensus
            offsets_values = [v[1] for v in valid_offsets]

            # Check if at least 2 methods agree (within 150px for more tolerance)
            agreeing = []
            for i, (name1, val1) in enumerate(valid_offsets):
                for name2, val2 in valid_offsets[i+1:]:
                    if abs(val1 - val2) < 150:
                        agreeing.append((name1, val1))
                        agreeing.append((name2, val2))

            if agreeing:
                # Use average of agreeing methods
                avg_offset = sum(v[1] for v in agreeing) // len(agreeing)
                scroll_offset = avg_offset
                names = list(set(v[0] for v in agreeing))
                logger.info(f"  HYBRID: {names} agree! Using average: {scroll_offset}px")
            else:
                # No agreement - prefer element-based if available (most semantic)
                element_result = next((v for v in valid_offsets if v[0] == 'element'), None)
                feature_result = next((v for v in valid_offsets if v[0] == 'feature'), None)

                if element_result:
                    scroll_offset = element_result[1]
                    logger.info(f"  HYBRID: No consensus, preferring element-based: {scroll_offset}px")
                elif feature_result:
                    scroll_offset = feature_result[1]
                    logger.info(f"  HYBRID: No consensus, preferring feature-based: {scroll_offset}px")
                else:
                    # Use median as last resort
                    offsets_values.sort()
                    scroll_offset = offsets_values[len(offsets_values) // 2]
                    logger.warning(f"  HYBRID: No consensus, using median: {scroll_offset}px")
        elif len(valid_offsets) == 1:
            scroll_offset = valid_offsets[0][1]
            logger.info(f"  HYBRID: Only {valid_offsets[0][0]} valid: {scroll_offset}px")
        else:
            # No method gave valid result - check if element offset exists but was filtered
            if element_offset and element_offset > 50:
                scroll_offset = element_offset
                logger.warning(f"  HYBRID: Using element offset outside normal range: {scroll_offset}px")
            else:
                # Use safe default based on swipe distance
                scroll_offset = int(height * 0.35)  # ~420px, closer to actual scroll
                logger.warning(f"  HYBRID: No valid offset! Using default 35%: {scroll_offset}px")

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
        # For iterative stitching, img1 may be taller than screen_height (accumulated result)
        #
        # scroll_offset = how much content moved between prev and new captures
        # Content at prev_y=Y appears at new_y=(Y - scroll_offset)
        #
        # Logic:
        # - Keep ALL of img1 (the accumulated result)
        # - Calculate the overlap region in img2 (content that's already in img1)
        # - Append ONLY the NEW (non-overlapping) content from img2

        c2_crop_top = fixed_header_height  # CUT OFF the header from img2

        # For img2, the overlap ends at approximately (height - scroll_offset)
        # So new content starts at around that point
        # But we already cropped the header, so adjust accordingly
        #
        # The "overlap zone" in img2 is content that was in the BOTTOM of prev capture
        # After scrolling, that content moved UP by scroll_offset pixels
        # So in img2: overlap is from fixed_header_height to (height - scroll_offset)
        # New content is from (height - scroll_offset) to (height - fixed_footer if not last)

        # Calculate where to paste img2's content
        # The paste position = img1_height - (overlap height in img2)
        # overlap_height_in_img2 = (height - scroll_offset) - fixed_header_height
        # = height - scroll_offset - fixed_header_height
        overlap_in_img2 = height - scroll_offset - fixed_header_height
        if overlap_in_img2 < 0:
            overlap_in_img2 = 0  # No overlap (big scroll)

        c2_paste_y = img1_height - fixed_footer_height  # Paste at bottom of img1 (before footer)

        c2_crop_bottom = height if is_last_capture else height - fixed_footer_height
        c2_height_used = c2_crop_bottom - c2_crop_top

        # New content starts after the overlap
        new_content_start = c2_crop_top + overlap_in_img2
        if new_content_start < c2_crop_top:
            new_content_start = c2_crop_top

        # For simplicity: paste full img2 content (minus header) starting where overlap begins
        # This means some content overlaps, but that's OK - it's the same content
        # The key is to get the paste position right

        # SAFETY: If scroll_offset is 0 or very small, the captures don't actually overlap
        # This can happen if we're stitching non-adjacent captures. Use minimum scroll distance.
        min_scroll = int(height * 0.3)  # Expect at least 30% scroll between adjacent captures
        if scroll_offset < min_scroll:
            logger.warning(f"  Low scroll_offset ({scroll_offset}px < {min_scroll}px) - captures may not overlap!")
            logger.warning(f"  Using minimum scroll_offset to prevent shrinkage")
            scroll_offset = min_scroll
            overlap_in_img2 = height - scroll_offset - fixed_header_height

        # Calculate paste position
        if img1_height == height:
            # First stitch
            c2_paste_y = scroll_offset + fixed_header_height
        else:
            # Iterative stitch - paste at bottom of img1 minus overlap
            c2_paste_y = img1_height - overlap_in_img2 - fixed_footer_height
            if c2_paste_y < img1_height - height:
                c2_paste_y = img1_height - height  # Safety: don't paste too high

        # Ensure paste position is never negative
        if c2_paste_y < 0:
            logger.warning(f"  Negative paste position {c2_paste_y}px! Adjusting to 0")
            c2_paste_y = 0

        # Calculate total height - must be at least as tall as img1
        total_height = max(img1_height, c2_paste_y + c2_height_used)

        logger.info(f"  Img1 height: {img1_height}px, scroll_offset: {scroll_offset}px")
        logger.info(f"  Overlap in img2: {overlap_in_img2}px")
        logger.info(f"  C2: crop y={c2_crop_top}-{c2_crop_bottom} ({c2_height_used}px), paste at y={c2_paste_y}")
        logger.info(f"  Final size: {width}x{total_height}")

        # Create canvas and stitch
        stitched = Image.new('RGB', (width, total_height))

        # Paste ALL of img1 (the accumulated result)
        stitched.paste(img1, (0, 0))
        logger.info(f"  Pasted Img1 ({img1_height}px) at y=0")

        # Paste img2 content (minus header) at calculated position
        c2_cropped = img2.crop((0, c2_crop_top, width, c2_crop_bottom))
        stitched.paste(c2_cropped, (0, c2_paste_y))
        logger.info(f"  Pasted Img2 ({c2_cropped.size[1]}px) at y={c2_paste_y}")

        # === BUILD COMBINED ELEMENTS WITH ADJUSTED Y POSITIONS ===
        # Elements from img1: keep ALL (they're already at correct positions)
        # Elements from img2: adjust Y by (c2_paste_y - c2_crop_top), skip header/close duplicates
        combined_elements = []
        # Track fingerprint -> list of Y positions (for position-aware deduplication)
        fingerprint_y_positions = {}  # fp -> list of (y_center_adjusted)

        # Add ALL elements from img1 (accumulated result)
        # For iterative stitching, elements1 already has correct Y positions
        for elem in elements1:
            fp = self._get_element_fingerprint(elem)
            combined_elements.append(elem.copy())
            if fp:
                y_center = self._get_element_y_center(elem)
                if fp not in fingerprint_y_positions:
                    fingerprint_y_positions[fp] = []
                fingerprint_y_positions[fp].append(y_center)

        # Add elements from img2 (adjust Y positions, skip header/close duplicates)
        y_adjustment = c2_paste_y - c2_crop_top  # How much to shift img2 elements
        added_count = 0
        skipped_header = 0
        skipped_footer = 0
        skipped_duplicate = 0

        for elem in elements2:
            fp = self._get_element_fingerprint(elem)
            y_center = self._get_element_y_center(elem)

            # Skip elements in header region (they were cropped)
            if y_center < c2_crop_top:
                skipped_header += 1
                continue

            # Skip footer elements from img2 if we're not at the last capture
            if not is_last_capture and y_center > (height - fixed_footer_height):
                skipped_footer += 1
                continue

            # Calculate adjusted Y position
            adjusted_y_center = y_center + y_adjustment

            # Position-aware deduplication: skip only if there's an element
            # with same fingerprint at CLOSE Y position (within 100px)
            if fp and fp in fingerprint_y_positions:
                is_duplicate = False
                for existing_y in fingerprint_y_positions[fp]:
                    if abs(existing_y - adjusted_y_center) < 100:
                        is_duplicate = True
                        break
                if is_duplicate:
                    skipped_duplicate += 1
                    continue

            # Create adjusted element
            adjusted_elem = elem.copy()
            bounds = adjusted_elem.get('bounds', {})
            if isinstance(bounds, dict):
                adjusted_elem['bounds'] = {
                    'x': bounds.get('x', 0),
                    'y': bounds.get('y', 0) + y_adjustment,
                    'width': bounds.get('width', 0),
                    'height': bounds.get('height', 0)
                }
            elif isinstance(bounds, str):
                # Parse and adjust "[x1,y1][x2,y2]" format
                import re
                match = re.findall(r'\[(\d+),(\d+)\]', bounds)
                if len(match) >= 2:
                    x1, y1 = int(match[0][0]), int(match[0][1])
                    x2, y2 = int(match[1][0]), int(match[1][1])
                    adjusted_elem['bounds'] = f"[{x1},{y1 + y_adjustment}][{x2},{y2 + y_adjustment}]"

            combined_elements.append(adjusted_elem)
            added_count += 1
            if fp:
                if fp not in fingerprint_y_positions:
                    fingerprint_y_positions[fp] = []
                fingerprint_y_positions[fp].append(adjusted_y_center)

        logger.info(f"  Combined elements: {len(combined_elements)} (Img1: {len(elements1)}, Img2 added: {added_count})")
        logger.info(f"  Img2 skipped: header={skipped_header}, footer={skipped_footer}, duplicate={skipped_duplicate}")

        # Build stitch info
        stitch_info = {
            "scroll_offset": scroll_offset,
            "header_height": fixed_header_height,
            "footer_height": fixed_footer_height,
            "c2_crop_top": c2_crop_top,
            "c2_paste_y": c2_paste_y,
            "y_adjustment": y_adjustment
        }

        return stitched, combined_elements, stitch_info

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
