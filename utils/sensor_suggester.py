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
        # Specific patterns with strong keywords first
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
        },
        # Generic patterns last (lowest priority)
        'percentage': {
            'keywords': [],
            'indicators': ['%'],
            'device_class': 'none',
            'unit': '%',
            'icon': 'mdi:percent',
            'confidence_base': 0.5,  # Low confidence - generic
            'value_range': (0, 100)
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
        suggestions = []
        seen_resource_ids = set()  # Avoid duplicate suggestions

        for element in elements:
            # Skip elements without useful text or resource-id
            text = element.get('text', '').strip()
            resource_id = element.get('resource-id', '')

            if not text and not resource_id:
                continue

            # Try to match against each pattern
            for pattern_name, pattern in self.PATTERNS.items():
                match_result = self._matches_pattern(element, text, pattern)

                if match_result['matches']:
                    # Avoid duplicate suggestions for same resource-id
                    if resource_id and resource_id in seen_resource_ids:
                        continue

                    suggestion = self._create_suggestion(
                        element=element,
                        pattern_name=pattern_name,
                        pattern=pattern,
                        confidence=match_result['confidence'],
                        extracted_value=match_result.get('value'),
                        extracted_unit=match_result.get('unit')
                    )

                    suggestions.append(suggestion)

                    if resource_id:
                        seen_resource_ids.add(resource_id)

                    # Only match first pattern (highest priority)
                    break

        # Sort by confidence (highest first)
        suggestions.sort(key=lambda x: x['confidence'], reverse=True)

        logger.info(f"Generated {len(suggestions)} sensor suggestions from {len(elements)} elements")
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
        resource_id = element.get('resource-id', '').lower()
        content_desc = element.get('content-desc', '').lower()

        # Combine all searchable text
        searchable = f"{text_lower} {resource_id} {content_desc}"

        confidence = 0.0
        extracted_value = None
        extracted_unit = None

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

            # Calculate confidence
            if keyword_match and indicator_match and in_range:
                confidence = pattern['confidence_base']
            elif (keyword_match or indicator_match) and in_range:
                confidence = pattern['confidence_base'] * 0.8
            elif keyword_match or indicator_match:
                confidence = pattern['confidence_base'] * 0.6
            elif in_range and numeric_match:
                confidence = pattern['confidence_base'] * 0.5

        # Match if confidence is above threshold
        matches = confidence >= 0.4

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
        extracted_unit: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a sensor suggestion from element and pattern match
        """
        text = element.get('text', '').strip()
        resource_id = element.get('resource-id', '')

        # Generate sensor name
        name = self._generate_sensor_name(element, pattern_name)

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
                'content-desc': element.get('content-desc', ''),
                'class': element.get('class', ''),
                'bounds': element.get('bounds', {})
            },
            'current_value': extracted_value,
            'suggested': True  # User hasn't confirmed yet
        }

    def _generate_sensor_name(self, element: Dict[str, Any], pattern_name: str) -> str:
        """Generate human-readable sensor name"""
        text = element.get('text', '').strip()
        resource_id = element.get('resource-id', '')

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
        resource_id = element.get('resource-id', '')

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
