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
        stored_bounds: Optional[Dict] = None
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

        # Strategy 1: Match by resource_id (most reliable)
        if resource_id:
            match = self._find_by_resource_id(ui_elements, resource_id)
            if match.found:
                return match

        # Strategy 2: Match by text + class
        if element_text and element_class:
            match = self._find_by_text_and_class(ui_elements, element_text, element_class)
            if match.found:
                return match

        # Strategy 3: Match by text only
        if element_text:
            match = self._find_by_text(ui_elements, element_text)
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
        resource_id: str
    ) -> ElementMatch:
        """Find element by exact resource_id match"""
        for elem in ui_elements:
            if elem.get('resource_id') == resource_id:
                bounds = self._extract_bounds(elem)
                logger.debug(f"[ElementFinder] Found by resource_id: {resource_id}")
                return ElementMatch(
                    found=True,
                    element=elem,
                    bounds=bounds,
                    confidence=self.CONFIDENCE_RESOURCE_ID,
                    method="resource_id",
                    message=f"Matched resource_id: {resource_id}"
                )
        return ElementMatch(found=False)

    def _find_by_text_and_class(
        self,
        ui_elements: List[Dict],
        text: str,
        element_class: str
    ) -> ElementMatch:
        """Find element by text content and class name"""
        for elem in ui_elements:
            elem_text = elem.get('text', '')
            elem_class = elem.get('class', '')

            if elem_text == text and elem_class == element_class:
                bounds = self._extract_bounds(elem)
                logger.debug(f"[ElementFinder] Found by text+class: '{text}' / {element_class}")
                return ElementMatch(
                    found=True,
                    element=elem,
                    bounds=bounds,
                    confidence=self.CONFIDENCE_TEXT_CLASS,
                    method="text_class",
                    message=f"Matched text '{text}' with class {element_class}"
                )
        return ElementMatch(found=False)

    def _find_by_text(
        self,
        ui_elements: List[Dict],
        text: str
    ) -> ElementMatch:
        """Find element by text content only"""
        matches = []
        for elem in ui_elements:
            elem_text = elem.get('text', '')
            if elem_text == text:
                matches.append(elem)

        if len(matches) == 1:
            # Unique match
            bounds = self._extract_bounds(matches[0])
            logger.debug(f"[ElementFinder] Found by text: '{text}'")
            return ElementMatch(
                found=True,
                element=matches[0],
                bounds=bounds,
                confidence=self.CONFIDENCE_TEXT_ONLY,
                method="text",
                message=f"Matched text '{text}'"
            )
        elif len(matches) > 1:
            # Multiple matches - use first but lower confidence
            bounds = self._extract_bounds(matches[0])
            logger.warning(f"[ElementFinder] Multiple text matches for '{text}', using first")
            return ElementMatch(
                found=True,
                element=matches[0],
                bounds=bounds,
                confidence=self.CONFIDENCE_TEXT_ONLY * 0.7,  # Lower confidence
                method="text_ambiguous",
                message=f"Multiple matches for '{text}', using first of {len(matches)}"
            )

        return ElementMatch(found=False)

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
