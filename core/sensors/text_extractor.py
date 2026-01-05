"""
Visual Mapper - Text Extraction Engine
Version: 0.0.4 (Phase 3)

Extracts and parses text from UI elements using various methods.
"""

import re
import logging
from typing import Optional, List, Dict, Any

from .sensor_models import TextExtractionRule, ExtractionMethod

logger = logging.getLogger(__name__)


class TextExtractor:
    """Extract and parse text from UI elements"""

    def extract(self, text: str, rule: TextExtractionRule) -> Optional[str]:
        """
        Extract text using extraction rule

        Args:
            text: Source text to extract from
            rule: Extraction rule

        Returns:
            Extracted text or None if extraction failed
        """
        if not text:
            logger.warning("[TextExtractor] Empty source text")
            return rule.fallback_value

        try:
            # If pipeline is defined, use multi-step extraction
            if rule.pipeline:
                return self._extract_pipeline(text, rule.pipeline, rule.fallback_value)

            # Otherwise, use single-step extraction
            # Apply extraction method
            if rule.method == ExtractionMethod.EXACT:
                result = self._extract_exact(text)
            elif rule.method == ExtractionMethod.REGEX:
                result = self._extract_regex(text, rule.regex_pattern)
            elif rule.method == ExtractionMethod.NUMERIC:
                result = self._extract_numeric(text)
            elif rule.method == ExtractionMethod.BEFORE:
                result = self._extract_before(text, rule.before_text)
            elif rule.method == ExtractionMethod.AFTER:
                result = self._extract_after(text, rule.after_text)
            elif rule.method == ExtractionMethod.BETWEEN:
                result = self._extract_between(text, rule.between_start, rule.between_end)
            else:
                logger.error(f"[TextExtractor] Unknown extraction method: {rule.method}")
                return rule.fallback_value

            # Post-processing
            if result and rule.extract_numeric:
                result = self._extract_numeric(result)

            if result and rule.remove_unit:
                result = self._remove_unit(result)

            return result if result else rule.fallback_value

        except Exception as e:
            logger.error(f"[TextExtractor] Extraction failed: {e}")
            return rule.fallback_value

    def _extract_pipeline(self, text: str, pipeline: List[Dict[str, Any]], fallback: Optional[str]) -> Optional[str]:
        """
        Execute multi-step extraction pipeline

        Args:
            text: Source text
            pipeline: List of extraction steps (each is a dict with method and params)
            fallback: Fallback value if any step fails

        Returns:
            Final extracted text or fallback
        """
        result = text

        for step_index, step in enumerate(pipeline):
            method = step.get("method")
            if not method:
                logger.error(f"[TextExtractor] Pipeline step {step_index} missing 'method'")
                return fallback

            try:
                # Apply extraction method for this step
                if method == "exact":
                    result = self._extract_exact(result)
                elif method == "regex":
                    result = self._extract_regex(result, step.get("regex_pattern"))
                elif method == "numeric":
                    result = self._extract_numeric(result)
                elif method == "before":
                    result = self._extract_before(result, step.get("before_text"))
                elif method == "after":
                    result = self._extract_after(result, step.get("after_text"))
                elif method == "between":
                    result = self._extract_between(result, step.get("between_start"), step.get("between_end"))
                else:
                    logger.error(f"[TextExtractor] Unknown pipeline method: {method}")
                    return fallback

                # If any step returns None, pipeline fails
                if result is None:
                    logger.warning(f"[TextExtractor] Pipeline step {step_index} ({method}) returned None")
                    return fallback

            except Exception as e:
                logger.error(f"[TextExtractor] Pipeline step {step_index} ({method}) failed: {e}")
                return fallback

        return result if result else fallback

    def _extract_exact(self, text: str) -> str:
        """Return text as-is"""
        return text.strip()

    def _extract_regex(self, text: str, pattern: Optional[str]) -> Optional[str]:
        """Extract text using regex pattern"""
        if not pattern:
            logger.warning("[TextExtractor] No regex pattern provided")
            return None

        try:
            match = re.search(pattern, text)
            if match:
                # If there are groups, return first group; otherwise return full match
                return match.group(1) if match.groups() else match.group(0)
            return None
        except re.error as e:
            logger.error(f"[TextExtractor] Invalid regex pattern '{pattern}': {e}")
            return None

    def _extract_numeric(self, text: str) -> Optional[str]:
        """Extract first numeric value from text"""
        # Match integer or decimal numbers (with optional negative sign)
        match = re.search(r'-?\d+\.?\d*', text)
        return match.group(0) if match else None

    def _extract_before(self, text: str, before_text: Optional[str]) -> Optional[str]:
        """Extract text before substring"""
        if not before_text:
            logger.warning("[TextExtractor] No before_text provided")
            return None

        index = text.find(before_text)
        if index == -1:
            return None

        return text[:index].strip()

    def _extract_after(self, text: str, after_text: Optional[str]) -> Optional[str]:
        """Extract text after substring"""
        if not after_text:
            logger.warning("[TextExtractor] No after_text provided")
            return None

        index = text.find(after_text)
        if index == -1:
            return None

        return text[index + len(after_text):].strip()

    def _extract_between(self, text: str, start: Optional[str], end: Optional[str]) -> Optional[str]:
        """Extract text between two substrings"""
        if not start or not end:
            logger.warning("[TextExtractor] Missing start or end text for BETWEEN method")
            return None

        start_index = text.find(start)
        if start_index == -1:
            return None

        start_index += len(start)
        end_index = text.find(end, start_index)
        if end_index == -1:
            return None

        return text[start_index:end_index].strip()

    def _remove_unit(self, text: str) -> str:
        """Remove unit suffix from numeric value"""
        # Remove common units: %, °C, °F, km/h, mph, V, A, W, etc.
        # Keep only numbers and decimal points
        match = re.match(r'(-?\d+\.?\d*)', text)
        return match.group(1) if match else text


class ElementTextExtractor:
    """Extract text from UI element hierarchy"""

    def __init__(self, extractor: TextExtractor):
        self.extractor = extractor

    def extract_from_element(
        self,
        elements: List[Dict[str, Any]],
        element_index: int,
        rule: TextExtractionRule
    ) -> Optional[str]:
        """
        Extract text from UI element

        Args:
            elements: UI element hierarchy list
            element_index: Index of element to extract from
            rule: Extraction rule

        Returns:
            Extracted text or None
        """
        if not elements or element_index < 0 or element_index >= len(elements):
            logger.warning(f"[ElementTextExtractor] Invalid element index {element_index}")
            return rule.fallback_value

        element = elements[element_index]
        text = element.get('text', '')

        if not text:
            logger.warning(f"[ElementTextExtractor] Element {element_index} has no text")
            return rule.fallback_value

        return self.extractor.extract(text, rule)

    def extract_from_bounds(
        self,
        elements: List[Dict[str, Any]],
        bounds: Dict[str, int],
        rule: TextExtractionRule
    ) -> Optional[str]:
        """
        Extract text from all elements within bounds

        Args:
            elements: UI element hierarchy list
            bounds: Bounds dict with x, y, width, height
            rule: Extraction rule

        Returns:
            Extracted text or None
        """
        # Find all elements within bounds
        matching_elements = []
        for element in elements:
            elem_bounds = element.get('bounds', {})
            if self._is_within_bounds(elem_bounds, bounds):
                if element.get('text'):
                    matching_elements.append(element)

        if not matching_elements:
            logger.warning("[ElementTextExtractor] No elements found within bounds")
            return rule.fallback_value

        # Concatenate text from all matching elements
        combined_text = ' '.join(elem.get('text', '') for elem in matching_elements)

        return self.extractor.extract(combined_text, rule)

    def _is_within_bounds(
        self,
        elem_bounds: Dict[str, int],
        target_bounds: Dict[str, int],
        tolerance: int = 5
    ) -> bool:
        """Check if element bounds are within target bounds"""
        if not elem_bounds:
            return False

        ex, ey = elem_bounds.get('x', 0), elem_bounds.get('y', 0)
        ew, eh = elem_bounds.get('width', 0), elem_bounds.get('height', 0)

        tx, ty = target_bounds.get('x', 0), target_bounds.get('y', 0)
        tw, th = target_bounds.get('width', 0), target_bounds.get('height', 0)

        # Check if element center is within target bounds (with tolerance)
        elem_center_x = ex + ew // 2
        elem_center_y = ey + eh // 2

        return (
            tx - tolerance <= elem_center_x <= tx + tw + tolerance and
            ty - tolerance <= elem_center_y <= ty + th + tolerance
        )
