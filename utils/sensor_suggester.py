"""
Smart Sensor Suggester - AI-powered sensor detection from UI elements

This module analyzes Android UI elements and suggests Home Assistant sensors
based on pattern detection heuristics. It identifies common sensor types like
battery, temperature, humidity, binary sensors, and more.
"""

import re
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class SensorSuggester:
    """AI-powered sensor detection from UI elements"""

    # Pattern definitions for different sensor types
    # Order matters! More specific patterns should come first
    PATTERNS = {
        # Class-based auto-detection patterns (highest priority)
        'progressbar': {
            'keywords': [],
            'indicators': [],
            'classes': ['android.widget.ProgressBar', 'androidx.appcompat.widget.AppCompatProgressBar'],
            'device_class': 'none',
            'unit': '%',
            'icon': 'mdi:progress-clock',
            'confidence_base': 0.9,
            'value_range': (0, 100),
            'is_class_based': True
        },
        'seekbar': {
            'keywords': [],
            'indicators': [],
            'classes': ['android.widget.SeekBar', 'androidx.appcompat.widget.AppCompatSeekBar'],
            'device_class': 'none',
            'unit': None,
            'icon': 'mdi:tune',
            'confidence_base': 0.85,
            'is_class_based': True
        },
        'ratingbar': {
            'keywords': [],
            'indicators': [],
            'classes': ['android.widget.RatingBar'],
            'device_class': 'none',
            'unit': 'stars',
            'icon': 'mdi:star',
            'confidence_base': 0.9,
            'value_range': (0, 5),
            'is_class_based': True
        },
        # Specific patterns with strong keywords
        'temperature': {
            'keywords': ['temp', 'temperature'],
            'indicators': ['°f', '°c', '°', 'deg'],
            'device_class': 'temperature',
            'unit': None,  # Auto-detect from text
            'icon': 'mdi:thermometer',
            'confidence_base': 0.95,
            'value_range': (-50, 150)
        },
        'humidity': {
            'keywords': ['humidity', 'humid', 'rh', 'moisture'],
            'indicators': ['%'],
            'device_class': 'humidity',
            'unit': '%',
            'icon': 'mdi:water-percent',
            'confidence_base': 0.9,
            'value_range': (0, 100)
        },
        'illuminance': {
            'keywords': ['light', 'brightness', 'lux', 'illuminance'],
            'indicators': ['lux', 'lx'],
            'device_class': 'illuminance',
            'unit': 'lx',
            'icon': 'mdi:brightness-6',
            'confidence_base': 0.9,
            'value_range': (0, 100000)
        },
        'pressure': {
            'keywords': ['pressure', 'barometer', 'hpa', 'mbar', 'psi'],
            'indicators': ['hpa', 'mbar', 'psi', 'inhg'],
            'device_class': 'pressure',
            'unit': None,  # Auto-detect from text
            'icon': 'mdi:gauge',
            'confidence_base': 0.85,
            'value_range': (900, 1100)
        },
        'battery': {
            'keywords': ['battery', 'batt', 'charge', 'power'],
            'indicators': ['%'],
            'device_class': 'battery',
            'unit': '%',
            'icon': 'mdi:battery',
            'confidence_base': 0.9,
            'value_range': (0, 100)
        },
        'percentage': {
            'keywords': [],
            'indicators': ['%'],
            'device_class': 'none',
            'unit': '%',
            'icon': 'mdi:percent',
            'confidence_base': 0.65,  # Moderate confidence - % is a strong indicator
            'value_range': (0, 100)
        },
        'timestamp': {
            'keywords': ['updated', 'last', 'time', 'date', 'modified', 'refreshed', 'synced'],
            'indicators': [':', 'am', 'pm', 'ago', 'min', 'sec', 'hour'],
            'device_class': 'timestamp',
            'unit': None,
            'icon': 'mdi:clock',
            'confidence_base': 0.7,
            'is_timestamp': True
        },
        'binary': {
            'keywords': ['status', 'state', 'enabled', 'disabled', 'active'],
            'indicators': ['on', 'off', 'true', 'false', 'yes', 'no', 'enabled', 'disabled', 'active', 'inactive'],
            'device_class': 'none',
            'unit': None,
            'icon': 'mdi:toggle-switch',
            'confidence_base': 0.85,
            'is_binary': True
        }
    }

    def suggest_sensors(self, elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyze UI elements and suggest sensors

        Args:
            elements: List of UI element dicts from get_ui_elements()

        Returns:
            List of sensor suggestions with confidence scores
        """
        logger.info(f"[SensorSuggester] Analyzing {len(elements)} UI elements")
        suggestions = []
        seen_combinations = set()  # Avoid duplicate suggestions (resource_id + text combo)

        skipped_no_text = 0
        skipped_duplicate = 0
        analyzed = 0

        for element in elements:
            # Skip elements without any useful attributes
            text = element.get('text', '').strip()
            resource_id = element.get('resource_id', '')
            content_desc = element.get('content_desc', '')
            element_class = element.get('class', '')

            # Only skip if element has no useful info AND is a generic container
            if not text and not resource_id and not content_desc:
                # Check if element class is useful (not a generic container)
                if element_class in ['android.view.View', 'android.view.ViewGroup', '']:
                    skipped_no_text += 1
                    continue
                # Otherwise, analyze it (might have useful class info)

            analyzed += 1
            logger.debug(f"[SensorSuggester] Analyzing element: text='{text[:50] if text else '(none)'}', resource_id='{resource_id}'")

            # Try to match against each pattern
            matched_any = False
            for pattern_name, pattern in self.PATTERNS.items():
                match_result = self._matches_pattern(element, text, pattern)

                if match_result['matches']:
                    # Create unique key combining resource_id, text, and position
                    # This allows multiple sensors with same ID but different values (e.g., 4 tire pressures)
                    bounds = element.get('bounds', '')
                    unique_key = f"{resource_id}|{text}|{bounds}"

                    # Skip only if exact same element (same ID, text, AND position)
                    if unique_key in seen_combinations:
                        skipped_duplicate += 1
                        logger.debug(f"[SensorSuggester] Skipping duplicate element: {unique_key}")
                        break

                    suggestion = self._create_suggestion(
                        element=element,
                        pattern_name=pattern_name,
                        pattern=pattern,
                        confidence=match_result['confidence'],
                        extracted_value=match_result.get('value'),
                        extracted_unit=match_result.get('unit'),
                        all_elements=elements
                    )

                    suggestions.append(suggestion)
                    matched_any = True
                    logger.debug(f"[SensorSuggester] Matched pattern '{pattern_name}' with confidence {match_result['confidence']:.2f}")

                    # Mark this combination as seen
                    seen_combinations.add(unique_key)

                    # Only match first pattern (highest priority)
                    break

            if not matched_any:
                logger.debug(f"[SensorSuggester] No pattern matched for element: text='{text[:50] if text else '(none)'}'")

        # Sort by confidence (highest first)
        suggestions.sort(key=lambda x: x['confidence'], reverse=True)

        logger.info(f"[SensorSuggester] Generated {len(suggestions)} sensor suggestions from {len(elements)} elements")
        logger.info(f"[SensorSuggester] Stats: analyzed={analyzed}, skipped_no_text={skipped_no_text}, skipped_duplicate={skipped_duplicate}")
        return suggestions

    def _matches_pattern(
        self,
        element: Dict[str, Any],
        text: str,
        pattern: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Check if element matches a sensor pattern

        Returns:
            Dict with 'matches' (bool), 'confidence' (float), 'value', 'unit'
        """
        text_lower = text.lower()
        resource_id = element.get('resource_id', '').lower()
        content_desc = element.get('content_desc', '').lower()
        element_class = element.get('class', '')

        # Combine all searchable text
        searchable = f"{text_lower} {resource_id} {content_desc}"

        confidence = 0.0
        extracted_value = None
        extracted_unit = None

        # Check for class-based match (highest priority for class-based patterns)
        class_match = element_class in pattern.get('classes', [])

        if class_match and pattern.get('is_class_based'):
            # Class-based auto-detection - high confidence
            confidence = pattern['confidence_base']
            # Try to extract numeric value if available
            numeric_match = self._extract_numeric_value(text)
            if numeric_match:
                extracted_value = numeric_match['value']
                extracted_unit = numeric_match['unit']
            else:
                # For widgets like ProgressBar, use resource-id or text as value
                extracted_value = text or resource_id or element_class.split('.')[-1]

            return {
                'matches': True,
                'confidence': confidence,
                'value': extracted_value,
                'unit': extracted_unit or pattern.get('unit')
            }

        # Check for keywords
        keyword_match = any(kw in searchable for kw in pattern.get('keywords', []))

        # Check for indicators
        indicator_match = any(ind in text_lower for ind in pattern.get('indicators', []))

        # Special handling for binary sensors
        if pattern.get('is_binary'):
            if text_lower in pattern['indicators']:
                confidence = pattern['confidence_base']
                extracted_value = text_lower
                return {
                    'matches': True,
                    'confidence': confidence,
                    'value': extracted_value,
                    'unit': None
                }

        # Special handling for timestamps
        if pattern.get('is_timestamp'):
            if keyword_match or self._looks_like_timestamp(text):
                confidence = pattern['confidence_base']
                if self._looks_like_timestamp(text):
                    confidence += 0.1  # Bonus for matching time format
                return {
                    'matches': True,
                    'confidence': min(confidence, 1.0),
                    'value': text,
                    'unit': None
                }

        # Numeric value extraction
        numeric_match = self._extract_numeric_value(text)

        if numeric_match:
            extracted_value = numeric_match['value']
            extracted_unit = numeric_match['unit']

            # Check if value is in expected range
            value_range = pattern.get('value_range')
            in_range = True
            if value_range:
                try:
                    val_float = float(extracted_value)
                    in_range = value_range[0] <= val_float <= value_range[1]
                except:
                    in_range = False

            # Calculate confidence - RELAXED matching logic
            if keyword_match and indicator_match and in_range:
                # Perfect match: keyword + indicator + range
                confidence = pattern['confidence_base']
            elif keyword_match and indicator_match:
                # Strong match: keyword + indicator (no range check)
                confidence = pattern['confidence_base'] * 0.9
            elif keyword_match and in_range:
                # Good match: keyword + range (missing indicator)
                confidence = pattern['confidence_base'] * 0.85
            elif indicator_match and in_range:
                # Indicator + range match (works for both generic and keyword patterns)
                # Strong indicators (%, °, etc.) are sufficient even without keywords
                if pattern['confidence_base'] >= 0.6:
                    # High confidence pattern - indicator + range is good
                    confidence = pattern['confidence_base'] * 0.8
                else:
                    # Low confidence pattern - reduce confidence
                    confidence = pattern['confidence_base'] * 0.6
            elif indicator_match and not pattern.get('keywords'):
                # Generic pattern with indicator only (no range check needed)
                confidence = pattern['confidence_base'] * 0.7
            elif indicator_match and pattern['confidence_base'] >= 0.8:
                # Strong indicator for high-confidence pattern (%, °, humidity, etc.)
                # Allow match even without keyword or range
                confidence = pattern['confidence_base'] * 0.6
            elif keyword_match:
                # Keyword only - weak match, but allow for TextViews with numeric content
                is_textview = 'TextView' in element_class
                if is_textview and numeric_match:
                    confidence = pattern['confidence_base'] * 0.5
                else:
                    confidence = 0.0
            else:
                # No match
                confidence = 0.0

        # Match if confidence is above threshold (lowered from 0.5 to 0.3 for better detection)
        matches = confidence >= 0.3

        return {
            'matches': matches,
            'confidence': confidence,
            'value': extracted_value,
            'unit': extracted_unit or pattern.get('unit')
        }

    def _extract_numeric_value(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Extract numeric value and unit from text

        Examples:
            "85%" -> {value: 85, unit: "%"}
            "72°F" -> {value: 72, unit: "°F"}
            "3.14" -> {value: 3.14, unit: None}
        """
        # Pattern: optional number with decimal, followed by optional unit
        pattern = r'(-?\d+\.?\d*)\s*([°%a-zA-Z]+)?'
        match = re.search(pattern, text)

        if match:
            value = match.group(1)
            unit = match.group(2) if match.group(2) else None

            return {
                'value': value,
                'unit': unit
            }

        return None

    def _looks_like_timestamp(self, text: str) -> bool:
        """Check if text looks like a timestamp"""
        # Common timestamp patterns
        patterns = [
            r'\d{1,2}:\d{2}',  # HH:MM
            r'\d{1,2}:\d{2}:\d{2}',  # HH:MM:SS
            r'\d{1,2}:\d{2}\s*(am|pm)',  # 12-hour with AM/PM
            r'\d+ (min|sec|hour|day)s? ago',  # Relative time
            r'\d{4}-\d{2}-\d{2}',  # ISO date
        ]

        return any(re.search(pattern, text.lower()) for pattern in patterns)

    def _create_suggestion(
        self,
        element: Dict[str, Any],
        pattern_name: str,
        pattern: Dict[str, Any],
        confidence: float,
        extracted_value: Optional[str] = None,
        extracted_unit: Optional[str] = None,
        all_elements: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Create a sensor suggestion from element and pattern match
        """
        text = element.get('text', '').strip()
        resource_id = element.get('resource_id', '')

        # Generate sensor name (use spatial detection if available)
        name = self._generate_sensor_name(element, pattern_name, all_elements)

        # Generate entity ID
        entity_id = self._generate_entity_id(element, pattern_name)

        # Determine unit
        unit = extracted_unit or pattern.get('unit')

        return {
            'name': name,
            'entity_id': entity_id,
            'device_class': pattern.get('device_class'),
            'unit_of_measurement': unit,
            'icon': pattern.get('icon'),
            'confidence': round(confidence, 2),
            'pattern_type': pattern_name,
            'element': {
                'text': text,
                'resource-id': resource_id,
                'content-desc': element.get('content_desc', ''),
                'class': element.get('class', ''),
                'bounds': element.get('bounds', {})
            },
            'current_value': extracted_value,
            'suggested': True  # User hasn't confirmed yet
        }

    def _find_nearby_label(
        self,
        element: Dict[str, Any],
        elements: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Find label element spatially near this value element

        Detects label-value pairs like:
        - "Doors" (label above) + "Closed and locked" (value)
        - "Total mileage" (label above) + "18107km" (value)

        Args:
            element: The value element to find a label for
            elements: All UI elements to search through

        Returns:
            Label text if found, None otherwise
        """
        bounds = element.get('bounds', {})
        if not bounds or 'x' not in bounds or 'y' not in bounds:
            return None

        element_text = element.get('text', '').strip()

        # Look for elements above/beside this one
        nearby_labels = []

        for other in elements:
            # Skip self
            if other is element:
                continue

            other_bounds = other.get('bounds', {})
            if not other_bounds or 'x' not in other_bounds or 'y' not in other_bounds:
                continue

            other_text = other.get('text', '').strip()
            if not other_text:
                continue

            # Calculate spatial relationship
            x_distance = abs(other_bounds['x'] - bounds['x'])
            y_distance = bounds['y'] - other_bounds['y']  # Positive = other is above

            # Check if vertically aligned (same column, within 50px)
            if x_distance < 50:
                # Check if element is above (within 100px)
                if 0 < y_distance < 100:
                    # Check if other element looks like a label (text without numbers/units)
                    # Labels typically don't have numeric values or units
                    if not self._extract_numeric_value(other_text):
                        nearby_labels.append({
                            'text': other_text,
                            'distance': y_distance,
                            'element': other
                        })

            # Also check horizontally aligned (same row, to the left)
            y_distance_abs = abs(other_bounds['y'] - bounds['y'])
            x_distance_horiz = bounds['x'] - other_bounds['x']  # Positive = other is to left

            if y_distance_abs < 30:  # Same horizontal line
                if 0 < x_distance_horiz < 200:  # Within 200px to the left
                    if not self._extract_numeric_value(other_text):
                        nearby_labels.append({
                            'text': other_text,
                            'distance': x_distance_horiz,
                            'element': other
                        })

        # Return closest label if found
        if nearby_labels:
            closest = min(nearby_labels, key=lambda x: x['distance'])
            logger.debug(f"[SensorSuggester] Found nearby label '{closest['text']}' for value '{element_text}'")
            return closest['text']

        return None

    def _generate_sensor_name(
        self,
        element: Dict[str, Any],
        pattern_name: str,
        all_elements: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Generate human-readable sensor name"""
        text = element.get('text', '').strip()
        resource_id = element.get('resource_id', '')

        # Try to find a nearby label first (spatial detection)
        if all_elements:
            nearby_label = self._find_nearby_label(element, all_elements)
            if nearby_label:
                # Use nearby label as sensor name
                return nearby_label.title()

        # Try to extract meaningful name from resource-id
        if resource_id:
            # e.g., "com.example:id/battery_level" -> "Battery Level"
            parts = resource_id.split('/')
            if len(parts) > 1:
                id_part = parts[-1]
                # Convert snake_case to Title Case
                name = id_part.replace('_', ' ').title()
                return name

        # Fallback: use text if it's descriptive
        if text and len(text) < 30:
            # Remove numeric values, keep descriptive part
            name = re.sub(r'\d+\.?\d*\s*[°%a-zA-Z]*', '', text).strip()
            if name:
                return name.title()

        # Last resort: use pattern type
        return pattern_name.replace('_', ' ').title()

    def _generate_entity_id(self, element: Dict[str, Any], pattern_name: str) -> str:
        """Generate unique entity ID"""
        resource_id = element.get('resource_id', '')

        # Use resource-id if available
        if resource_id:
            # e.g., "com.example:id/battery_level" -> "sensor.battery_level"
            parts = resource_id.split('/')
            if len(parts) > 1:
                id_part = parts[-1]
                # Ensure valid entity ID format (lowercase, underscores)
                id_part = re.sub(r'[^a-z0-9_]', '_', id_part.lower())
                return f"sensor.{id_part}"

        # Fallback: use pattern name + hash of element
        element_hash = str(hash(str(element)))[-6:]
        entity_id = f"sensor.{pattern_name}_{element_hash}"
        entity_id = re.sub(r'[^a-z0-9_]', '_', entity_id.lower())

        return entity_id


# Singleton instance
_suggester = None

def get_sensor_suggester() -> SensorSuggester:
    """Get global sensor suggester instance"""
    global _suggester
    if _suggester is None:
        _suggester = SensorSuggester()
    return _suggester
