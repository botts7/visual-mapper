"""
Screenshot Stitcher Elements Module

Contains element fingerprinting and analysis methods:
- get_element_fingerprint: Create unique fingerprint for element
- get_element_y_center: Get Y center position
- get_element_bottom: Get bottom Y position
- calculate_scroll_from_elements: Calculate scroll amount from element positions
- find_new_content_boundary: Find where new content starts
- find_overlap_end_y: Find where overlap ends
- calculate_scroll_offset: Calculate scroll offset between captures
"""

import logging
import re
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class ElementAnalyzer:
    """Analyzes UI elements for scroll detection and stitching."""

    def get_element_fingerprint(self, element: dict) -> Optional[str]:
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

    def get_element_y_center(self, element: dict) -> int:
        """Get the Y center position of an element"""
        bounds = element.get('bounds', {})
        if isinstance(bounds, dict):
            y = bounds.get('y', 0)
            height = bounds.get('height', 0)
            return y + height // 2
        elif isinstance(bounds, str):
            # Parse "[x1,y1][x2,y2]" format
            match = re.findall(r'\[(\d+),(\d+)\]', bounds)
            if len(match) >= 2:
                y1, y2 = int(match[0][1]), int(match[1][1])
                return (y1 + y2) // 2
        return 0

    def get_element_bottom(self, element: dict) -> int:
        """Get the bottom Y position of an element"""
        bounds = element.get('bounds', {})
        if isinstance(bounds, dict):
            return bounds.get('y', 0) + bounds.get('height', 0)
        elif isinstance(bounds, str):
            # Parse "[x1,y1][x2,y2]" format
            match = re.findall(r'\[(\d+),(\d+)\]', bounds)
            if len(match) >= 2:
                return int(match[1][1])  # y2 from [x1,y1][x2,y2]
        return self.get_element_y_center(element) + 50

    def calculate_scroll_from_elements(
        self,
        elements1: list,
        elements2: list,
        screen_height: int
    ) -> Tuple[Optional[int], float]:
        """
        Calculate scroll amount by comparing element positions across screenshots.

        Returns:
            (scroll_amount, confidence) - scroll_amount in pixels, confidence 0-1
        """
        # Build fingerprint -> y_position maps
        fp_to_y1 = {}
        fp_to_y2 = {}

        for elem in elements1:
            fp = self.get_element_fingerprint(elem)
            if fp:
                y = self.get_element_y_center(elem)
                # Only track elements in the middle portion (not fixed headers/footers)
                if screen_height * 0.1 < y < screen_height * 0.9:
                    fp_to_y1[fp] = y

        for elem in elements2:
            fp = self.get_element_fingerprint(elem)
            if fp:
                y = self.get_element_y_center(elem)
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

    def find_new_content_boundary(
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
            fp = self.get_element_fingerprint(elem)
            if fp:
                y = self.get_element_y_center(elem)
                fp_to_y1[fp] = y

        for elem in elements2:
            fp = self.get_element_fingerprint(elem)
            if fp and fp in fp_to_y1:
                y2 = self.get_element_y_center(elem)
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

    def find_overlap_end_y(self, elements_prev: list, elements_curr: list, height: int) -> int:
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
            fp = self.get_element_fingerprint(elem)
            if fp:
                y_center = self.get_element_y_center(elem)
                y_bottom = self.get_element_bottom(elem)
                fp_prev_data[fp] = (y_center, y_bottom)

        logger.debug(f"  PREV has {len(fp_prev_data)} fingerprinted elements")

        # Find common elements in CURR and track their positions
        # SKIP full-screen containers and very large elements
        common_elements = []  # List of (fingerprint, y_center_curr, y_bottom_curr, y_center_prev, elem_height)
        for elem in elements_curr:
            fp = self.get_element_fingerprint(elem)
            if fp and fp in fp_prev_data:
                bounds = elem.get('bounds', {})
                elem_height = bounds.get('height', 0) if isinstance(bounds, dict) else 0
                elem_y = bounds.get('y', 0) if isinstance(bounds, dict) else 0

                # Skip full-screen containers (y near 0, height near screen height)
                if elem_y < 50 and elem_height > height * 0.8:
                    continue

                # Skip very large elements (likely containers, not content)
                if elem_height > height * 0.5:
                    continue

                y_center_curr = self.get_element_y_center(elem)
                y_bottom_curr = self.get_element_bottom(elem)
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

    def calculate_scroll_offset(self, elements_prev: list, elements_curr: list, height: int) -> int:
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
            fp = self.get_element_fingerprint(elem)
            if fp:
                y = self.get_element_y_center(elem)
                prev_all[fp] = y
                # Exclude elements in fixed header (top 10%) and footer (bottom 20%)
                if height * 0.10 < y < height * 0.80:
                    fp_to_y_prev[fp] = y

        logger.info(f"  PREV: {len(prev_all)} total fingerprinted, {len(fp_to_y_prev)} in valid Y range")

        # Log ALL fingerprinted elements from CURR
        curr_all = {}
        for elem in elements_curr:
            fp = self.get_element_fingerprint(elem)
            if fp:
                y = self.get_element_y_center(elem)
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
