"""
Smart Element Finder - Dynamic element location for flow execution

Provides intelligent element detection that handles:
- Layout changes (element moved to different coordinates)
- App updates (resource IDs changed)
- Screen size differences

Detection strategies (in order of reliability):
1. resource_id match (most stable)
2. text + class match
3. text match only
4. class + approximate bounds match
5. Fall back to stored bounds
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ElementMatch:
    """Result of smart element detection"""
    found: bool
    element: Optional[Dict] = None
    bounds: Optional[Dict] = None  # {x, y, width, height}
    confidence: float = 0.0  # 0-1, how confident we are in the match
    method: str = "none"  # How the element was found
    message: str = ""


class SmartElementFinder:
    """
    Intelligently finds UI elements using multiple strategies.
    Handles cases where elements have moved or changed.
    """

    # Confidence scores for different match methods
    CONFIDENCE_RESOURCE_ID = 1.0  # Exact resource_id match
    CONFIDENCE_PATH = 0.95  # Exact hierarchy path match
    CONFIDENCE_TEXT_CLASS = 0.9   # Text + class match
    CONFIDENCE_TEXT_ONLY = 0.7    # Text match only
    CONFIDENCE_CLASS_BOUNDS = 0.5  # Class + approximate bounds
    CONFIDENCE_STORED_BOUNDS = 0.3  # Fall back to stored bounds

    # How close bounds need to be for approximate match (pixels)
    BOUNDS_TOLERANCE = 50

    def find_element(
        self,
        ui_elements: List[Dict],
        resource_id: Optional[str] = None,
        element_text: Optional[str] = None,
        element_class: Optional[str] = None,
        stored_bounds: Optional[Dict] = None,
        element_path: Optional[str] = None,
        parent_path: Optional[str] = None
    ) -> ElementMatch:
        """
        Find element using multiple strategies.

        Args:
            ui_elements: List of current UI elements from screen
            resource_id: Android resource ID (e.g., 'com.app:id/temp')
            element_text: Expected text content
            element_class: Android class (e.g., 'android.widget.TextView')
            stored_bounds: Previously stored bounds {x, y, width, height}

        Returns:
            ElementMatch with found element and confidence score
        """
        if not ui_elements:
            return ElementMatch(
                found=False,
                message="No UI elements available"
            )

        # Strategy 0: Match by hierarchy path (most reliable when available)
        if element_path:
            match = self._find_by_path(ui_elements, element_path)
            if match.found:
                return match

        # Strategy 1: Match by resource_id (most reliable)
        if resource_id:
            match = self._find_by_resource_id(ui_elements, resource_id, stored_bounds, parent_path)
            if match.found:
                return match

        # Strategy 2: Match by text + class
        if element_text and element_class:
            match = self._find_by_text_and_class(ui_elements, element_text, element_class, stored_bounds, parent_path)
            if match.found:
                return match

        # Strategy 3: Match by text only
        if element_text:
            match = self._find_by_text(ui_elements, element_text, stored_bounds, parent_path)
            if match.found:
                return match

        # Strategy 4: Match by class + approximate bounds
        if element_class and stored_bounds:
            match = self._find_by_class_and_bounds(
                ui_elements, element_class, stored_bounds
            )
            if match.found:
                return match

        # Strategy 5: Fall back to stored bounds
        if stored_bounds:
            return ElementMatch(
                found=True,
                bounds=stored_bounds,
                confidence=self.CONFIDENCE_STORED_BOUNDS,
                method="stored_bounds",
                message="Using stored bounds (element not dynamically found)"
            )

        return ElementMatch(
            found=False,
            message="Could not locate element with any strategy"
        )

    def _find_by_resource_id(
        self,
        ui_elements: List[Dict],
        resource_id: str,
        stored_bounds: Optional[Dict] = None,
        parent_path: Optional[str] = None
    ) -> ElementMatch:
        """Find element by exact resource_id match (prefer closest to stored bounds if ambiguous)"""
        matches = []
        for elem in ui_elements:
            if elem.get('resource_id') == resource_id:
                bounds = self._extract_bounds(elem)
                matches.append((elem, bounds))

        if not matches:
            return ElementMatch(found=False)

        if parent_path:
            parent_matches = [
                (elem, bounds) for elem, bounds in matches
                if elem.get('parent_path') == parent_path
            ]
            if parent_matches:
                matches = parent_matches

        if len(matches) == 1 or not stored_bounds:
            elem, bounds = matches[0]
            if len(matches) > 1:
                logger.warning(f"[ElementFinder] Multiple resource_id matches for '{resource_id}', using first")
            logger.debug(f"[ElementFinder] Found by resource_id: {resource_id}")
            return ElementMatch(
                found=True,
                element=elem,
                bounds=bounds,
                confidence=self.CONFIDENCE_RESOURCE_ID,
                method="resource_id",
                message=f"Matched resource_id: {resource_id}"
            )

        best = self._pick_closest_by_bounds(matches, stored_bounds)
        logger.debug(f"[ElementFinder] Found by resource_id+bounds: {resource_id}")
        return ElementMatch(
            found=True,
            element=best[0],
            bounds=best[1],
            confidence=self.CONFIDENCE_RESOURCE_ID,
            method="resource_id_bounds",
            message=f"Matched resource_id '{resource_id}' using stored bounds"
        )

    def _find_by_text_and_class(
        self,
        ui_elements: List[Dict],
        text: str,
        element_class: str,
        stored_bounds: Optional[Dict] = None,
        parent_path: Optional[str] = None
    ) -> ElementMatch:
        """Find element by text content and class name (prefer closest to stored bounds if ambiguous)"""
        matches = []
        for elem in ui_elements:
            elem_text = elem.get('text', '')
            elem_class_value = elem.get('class', '')

            if elem_text == text and elem_class_value == element_class:
                bounds = self._extract_bounds(elem)
                matches.append((elem, bounds))

        if not matches:
            return ElementMatch(found=False)

        if parent_path:
            parent_matches = [
                (elem, bounds) for elem, bounds in matches
                if elem.get('parent_path') == parent_path
            ]
            if parent_matches:
                matches = parent_matches

        if len(matches) == 1 or not stored_bounds:
            elem, bounds = matches[0]
            if len(matches) > 1:
                logger.warning(f"[ElementFinder] Multiple text+class matches for '{text}', using first")
            logger.debug(f"[ElementFinder] Found by text+class: '{text}' / {element_class}")
            return ElementMatch(
                found=True,
                element=elem,
                bounds=bounds,
                confidence=self.CONFIDENCE_TEXT_CLASS,
                method="text_class",
                message=f"Matched text '{text}' with class {element_class}"
            )

        best = self._pick_closest_by_bounds(matches, stored_bounds)
        logger.debug(f"[ElementFinder] Found by text+class+bounds: '{text}' / {element_class}")
        return ElementMatch(
            found=True,
            element=best[0],
            bounds=best[1],
            confidence=self.CONFIDENCE_TEXT_CLASS,
            method="text_class_bounds",
            message=f"Matched text '{text}' with class {element_class} using stored bounds"
        )

    def _find_by_text(
        self,
        ui_elements: List[Dict],
        text: str,
        stored_bounds: Optional[Dict] = None,
        parent_path: Optional[str] = None
    ) -> ElementMatch:
        """Find element by text content only (prefer closest to stored bounds if ambiguous)"""
        matches = []
        for elem in ui_elements:
            elem_text = elem.get('text', '')
            if elem_text == text:
                bounds = self._extract_bounds(elem)
                matches.append((elem, bounds))

        if not matches:
            return ElementMatch(found=False)

        if parent_path:
            parent_matches = [
                (elem, bounds) for elem, bounds in matches
                if elem.get('parent_path') == parent_path
            ]
            if parent_matches:
                matches = parent_matches

        if len(matches) == 1 or not stored_bounds:
            elem, bounds = matches[0]
            if len(matches) > 1:
                logger.warning(f"[ElementFinder] Multiple text matches for '{text}', using first")
            logger.debug(f"[ElementFinder] Found by text: '{text}'")
            return ElementMatch(
                found=True,
                element=elem,
                bounds=bounds,
                confidence=self.CONFIDENCE_TEXT_ONLY,
                method="text",
                message=f"Matched text '{text}'"
            )

        best = self._pick_closest_by_bounds(matches, stored_bounds)
        logger.debug(f"[ElementFinder] Found by text+bounds: '{text}'")
        return ElementMatch(
            found=True,
            element=best[0],
            bounds=best[1],
            confidence=self.CONFIDENCE_TEXT_ONLY,
            method="text_bounds",
            message=f"Matched text '{text}' using stored bounds"
        )

    def _pick_closest_by_bounds(
        self,
        matches: List[Tuple[Dict, Optional[Dict]]],
        stored_bounds: Dict
    ) -> Tuple[Dict, Optional[Dict]]:
        """Pick the match closest to stored bounds center."""
        best_match = matches[0]
        best_distance = float('inf')
        for elem, bounds in matches:
            distance = self._bounds_center_distance(bounds, stored_bounds)
            if distance < best_distance:
                best_distance = distance
                best_match = (elem, bounds)
        return best_match

    def _bounds_center_distance(self, bounds1: Optional[Dict], bounds2: Dict) -> float:
        """Compute center-to-center distance between bounds."""
        if not bounds1 or not bounds2:
            return float('inf')
        x1 = bounds1.get('x', 0) + (bounds1.get('width', 0) / 2)
        y1 = bounds1.get('y', 0) + (bounds1.get('height', 0) / 2)
        x2 = bounds2.get('x', 0) + (bounds2.get('width', 0) / 2)
        y2 = bounds2.get('y', 0) + (bounds2.get('height', 0) / 2)
        return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5

    def _find_by_class_and_bounds(
        self,
        ui_elements: List[Dict],
        element_class: str,
        stored_bounds: Dict
    ) -> ElementMatch:
        """Find element by class and approximate bounds location"""
        stored_x = stored_bounds.get('x', 0)
        stored_y = stored_bounds.get('y', 0)

        best_match = None
        best_distance = float('inf')

        for elem in ui_elements:
            if elem.get('class') != element_class:
                continue

            bounds = self._extract_bounds(elem)
            if not bounds:
                continue

            # Calculate distance from stored position
            dx = abs(bounds['x'] - stored_x)
            dy = abs(bounds['y'] - stored_y)
            distance = (dx * dx + dy * dy) ** 0.5

            if distance < best_distance and distance <= self.BOUNDS_TOLERANCE:
                best_distance = distance
                best_match = (elem, bounds)

        if best_match:
            elem, bounds = best_match
            logger.debug(f"[ElementFinder] Found by class+bounds: {element_class} (distance: {best_distance:.1f}px)")
            return ElementMatch(
                found=True,
                element=elem,
                bounds=bounds,
                confidence=self.CONFIDENCE_CLASS_BOUNDS,
                method="class_bounds",
                message=f"Matched {element_class} within {best_distance:.1f}px of stored location"
            )

        return ElementMatch(found=False)

    def _find_by_path(
        self,
        ui_elements: List[Dict],
        element_path: str
    ) -> ElementMatch:
        """Find element by exact hierarchy path"""
        for elem in ui_elements:
            if elem.get('path') == element_path:
                bounds = self._extract_bounds(elem)
                logger.debug(f"[ElementFinder] Found by path: {element_path}")
                return ElementMatch(
                    found=True,
                    element=elem,
                    bounds=bounds,
                    confidence=self.CONFIDENCE_PATH,
                    method="path",
                    message=f"Matched hierarchy path: {element_path}"
                )
        return ElementMatch(found=False)

    def _extract_bounds(self, element: Dict) -> Optional[Dict]:
        """Extract bounds dict from element"""
        bounds = element.get('bounds')
        if not bounds:
            return None

        # Handle different bounds formats
        if isinstance(bounds, dict):
            return {
                'x': bounds.get('x', bounds.get('left', 0)),
                'y': bounds.get('y', bounds.get('top', 0)),
                'width': bounds.get('width', bounds.get('right', 0) - bounds.get('left', 0)),
                'height': bounds.get('height', bounds.get('bottom', 0) - bounds.get('top', 0))
            }
        elif isinstance(bounds, (list, tuple)) and len(bounds) == 4:
            # [left, top, right, bottom] format
            return {
                'x': bounds[0],
                'y': bounds[1],
                'width': bounds[2] - bounds[0],
                'height': bounds[3] - bounds[1]
            }
        elif isinstance(bounds, str):
            # Android-style "[x1,y1][x2,y2]" or "(x,y) WxH" formats
            try:
                import re
                if '[' in bounds and ']' in bounds:
                    nums = [int(n) for n in re.findall(r"\d+", bounds)]
                    if len(nums) >= 4:
                        return {
                            'x': nums[0],
                            'y': nums[1],
                            'width': nums[2] - nums[0],
                            'height': nums[3] - nums[1]
                        }
                nums = [int(n) for n in re.findall(r"\d+", bounds)]
                if len(nums) == 4:
                    return {
                        'x': nums[0],
                        'y': nums[1],
                        'width': nums[2],
                        'height': nums[3]
                    }
            except Exception:
                return None

        return None

    def compare_bounds(
        self,
        bounds1: Dict,
        bounds2: Dict
    ) -> Tuple[bool, float]:
        """
        Compare two bounds and return if they're similar and the distance.

        Returns:
            (is_similar, distance_in_pixels)
        """
        if not bounds1 or not bounds2:
            return False, float('inf')

        dx = abs(bounds1.get('x', 0) - bounds2.get('x', 0))
        dy = abs(bounds1.get('y', 0) - bounds2.get('y', 0))
        distance = (dx * dx + dy * dy) ** 0.5

        return distance <= self.BOUNDS_TOLERANCE, distance


# Singleton instance
element_finder = SmartElementFinder()
