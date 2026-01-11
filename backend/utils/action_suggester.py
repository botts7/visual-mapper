"""
Smart Action Suggester - AI-powered action detection from UI elements

This module analyzes Android UI elements and suggests Home Assistant actions
based on pattern detection heuristics. It identifies common action types like
buttons, switches, toggles, input fields, and more.

Enhanced to reduce false positives by:
- Distinguishing clickable from focusable elements
- Filtering out sensor-like elements (numeric values with units)
- Filtering out wrapper/container elements without actionable content
"""

import re
import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


class ActionSuggester:
    """AI-powered action detection from UI elements"""

    # Pattern definitions for different action types
    # Order matters! More specific patterns should come first
    # Class-specific patterns (Switch, CheckBox, EditText, SeekBar) before generic button patterns
    PATTERNS = {
        # Most specific: unique widget classes first
        'switch_toggle': {
            'keywords': ['enable', 'disable', 'toggle', 'switch'],
            'classes': ['android.widget.Switch', 'android.widget.ToggleButton', 'androidx.appcompat.widget.SwitchCompat'],
            'action_type': 'toggle',
            'icon': 'mdi:toggle-switch',
            'confidence_base': 0.95
        },
        'checkbox': {
            'keywords': ['check', 'select', 'agree'],
            'classes': ['android.widget.CheckBox', 'androidx.appcompat.widget.AppCompatCheckBox'],
            'action_type': 'toggle',
            'icon': 'mdi:checkbox-marked',
            'confidence_base': 0.9
        },
        'input_text': {
            'keywords': ['search', 'enter', 'type', 'input', 'name', 'email', 'password'],
            'classes': ['android.widget.EditText', 'androidx.appcompat.widget.AppCompatEditText'],
            'action_type': 'input_text',
            'icon': 'mdi:form-textbox',
            'confidence_base': 0.9
        },
        'slider': {
            'keywords': ['volume', 'brightness', 'slider', 'seekbar'],
            'classes': ['android.widget.SeekBar', 'androidx.appcompat.widget.AppCompatSeekBar'],
            'action_type': 'swipe',
            'icon': 'mdi:tune-vertical',
            'confidence_base': 0.85
        },
        # Button patterns with specific keywords (after unique widget classes)
        'button_submit': {
            'keywords': ['submit', 'send', 'confirm', 'ok', 'apply', 'save', 'done'],
            'classes': ['android.widget.Button', 'android.widget.ImageButton'],
            'action_type': 'tap',
            'icon': 'mdi:gesture-tap-button',
            'confidence_base': 0.95
        },
        'button_refresh': {
            'keywords': ['refresh', 'reload', 'update', 'sync'],
            'classes': ['android.widget.Button', 'android.widget.ImageButton'],
            'action_type': 'tap',
            'icon': 'mdi:refresh',
            'confidence_base': 0.95
        },
        'button_navigation': {
            'keywords': ['back', 'next', 'previous', 'forward', 'close', 'cancel', 'menu'],
            'classes': ['android.widget.Button', 'android.widget.ImageButton'],
            'action_type': 'tap',
            'icon': 'mdi:navigation',
            'confidence_base': 0.9
        },
        # Generic actionable patterns last (lowest priority)
        'generic_button': {
            'keywords': [],
            'classes': ['android.widget.Button', 'android.widget.ImageButton',
                       'android.widget.FloatingActionButton', 'com.google.android.material.button.MaterialButton'],
            'action_type': 'tap',
            'icon': 'mdi:gesture-tap',
            'confidence_base': 0.75,  # Increased from 0.7 - buttons are highly actionable
            'is_class_based': True  # Mark as class-based for auto-detection
        },
        'generic_clickable': {
            'keywords': [],
            'classes': [],  # Any clickable element
            'action_type': 'tap',
            'icon': 'mdi:cursor-default-click',
            'confidence_base': 0.6,  # Increased from 0.5 - clickable is a strong signal
            'is_generic': True
        }
    }

    def suggest_actions(self, elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyze UI elements and suggest actions

        Args:
            elements: List of UI element dicts from get_ui_elements()

        Returns:
            List of action suggestions with confidence scores
        """
        logger.info(f"[ActionSuggester] Analyzing {len(elements)} UI elements")
        suggestions = []
        seen_combinations = set()  # Avoid duplicate suggestions (resource_id + text + bounds)

        skipped_non_interactive = 0
        skipped_duplicate = 0
        analyzed = 0

        skipped_sensor_like = 0
        skipped_wrapper = 0

        for element in elements:
            # Skip elements without useful identifiers
            text = element.get('text', '').strip()
            resource_id = element.get('resource_id', '')
            content_desc = element.get('content_desc', '')
            element_class = element.get('class', '')

            # FILTER 1: Skip sensor-like elements (numeric values with units, status words)
            if self._looks_like_sensor(element):
                skipped_sensor_like += 1
                continue

            # FILTER 2: Skip wrapper/container elements without content
            if self._is_wrapper_element(element):
                skipped_wrapper += 1
                continue

            # FILTER 3: Check if truly interactive (not just focusable)
            is_interactive = self._is_truly_interactive(element)

            # Only skip non-interactive elements if they have no useful attributes
            if not is_interactive and not text and not resource_id and not content_desc:
                # Check if element class is actionable (Button, Switch, etc.)
                actionable_classes = ['Button', 'Switch', 'CheckBox', 'EditText', 'SeekBar']
                if not any(cls in element_class for cls in actionable_classes):
                    skipped_non_interactive += 1
                    continue
                # Otherwise, analyze it (might have useful class info)

            analyzed += 1
            logger.debug(f"[ActionSuggester] Analyzing element: text='{text[:50] if text else '(none)'}', class='{element_class}', interactive={is_interactive}")

            # Try to match against each pattern
            matched_any = False
            for pattern_name, pattern in self.PATTERNS.items():
                match_result = self._matches_pattern(element, text, pattern)

                if match_result['matches']:
                    # Create unique key combining resource_id, text, and position
                    # This allows multiple actions with same ID but different text/positions
                    bounds = element.get('bounds', '')
                    unique_key = f"{resource_id}|{text}|{bounds}"

                    # Skip only if exact same element (same ID, text, AND position)
                    if unique_key in seen_combinations:
                        skipped_duplicate += 1
                        logger.debug(f"[ActionSuggester] Skipping duplicate element: {unique_key}")
                        break

                    suggestion = self._create_suggestion(
                        element=element,
                        pattern_name=pattern_name,
                        pattern=pattern,
                        confidence=match_result['confidence']
                    )

                    suggestions.append(suggestion)
                    matched_any = True
                    logger.debug(f"[ActionSuggester] Matched pattern '{pattern_name}' with confidence {match_result['confidence']:.2f}")

                    # Mark this combination as seen
                    seen_combinations.add(unique_key)

                    # Only match first pattern (highest priority)
                    break

            if not matched_any:
                logger.debug(f"[ActionSuggester] No pattern matched for element: text='{text[:50] if text else '(none)'}', class='{element_class}'")

        # Sort by confidence (highest first)
        suggestions.sort(key=lambda x: x['confidence'], reverse=True)

        logger.info(f"[ActionSuggester] Generated {len(suggestions)} action suggestions from {len(elements)} elements")
        logger.info(f"[ActionSuggester] Stats: analyzed={analyzed}, skipped_non_interactive={skipped_non_interactive}, skipped_duplicate={skipped_duplicate}, skipped_sensor_like={skipped_sensor_like}, skipped_wrapper={skipped_wrapper}")
        return suggestions

    def _matches_pattern(
        self,
        element: Dict[str, Any],
        text: str,
        pattern: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Check if element matches an action pattern

        Returns:
            Dict with 'matches' (bool), 'confidence' (float)
        """
        text_lower = text.lower()
        resource_id = element.get('resource_id', '').lower()
        content_desc = element.get('content_desc', '').lower()
        element_class = element.get('class', '')

        # Use truly interactive check (distinguishes clickable from just focusable)
        is_interactive = self._is_truly_interactive(element)
        clickable = element.get('clickable', False)  # Keep for specific checks

        # Combine all searchable text
        searchable = f"{text_lower} {resource_id} {content_desc}"

        confidence = 0.0

        # Check for class match
        class_match = element_class in pattern.get('classes', [])

        # Check for keywords
        keyword_match = any(kw in searchable for kw in pattern.get('keywords', []))

        # Calculate confidence based on matches
        is_button_class = 'Button' in element_class  # More flexible check
        is_class_based = pattern.get('is_class_based', False)

        # Specific widget classes (Switch, CheckBox, EditText, etc.) are strong indicators
        # even without keyword matches, unlike generic Button classes
        is_specific_widget = class_match and element_class in [
            'android.widget.Switch', 'android.widget.ToggleButton',
            'android.widget.CheckBox', 'android.widget.EditText',
            'android.widget.SeekBar', 'androidx.appcompat.widget.SwitchCompat'
        ]

        # Class-based auto-detection (generic_button pattern)
        if is_class_based and class_match and is_interactive:
            # Button widget + interactive is very strong signal
            confidence = pattern['confidence_base'] * 0.95
        # Perfect match: class + keyword + interactive
        elif class_match and keyword_match and is_interactive:
            confidence = pattern['confidence_base']
        # Strong match: class + keyword (even without interactive)
        elif class_match and keyword_match:
            confidence = pattern['confidence_base'] * 0.9
        # Good match: specific widget class + interactive (Switch, CheckBox, etc.)
        elif is_specific_widget and is_interactive:
            confidence = pattern['confidence_base'] * 0.9
        # Good match: class + interactive (Button + clickable)
        elif class_match and is_interactive:
            if is_button_class:
                confidence = pattern['confidence_base'] * 0.8
            else:
                confidence = pattern['confidence_base'] * 0.85
        # Medium match: keyword + interactive
        elif keyword_match and is_interactive:
            confidence = pattern['confidence_base'] * 0.7
        # For generic patterns, accept clickable alone (must be truly clickable, not just focusable)
        elif pattern.get('is_generic') and clickable and not text_lower.startswith('android'):
            confidence = pattern['confidence_base'] * 0.9
        # Weak match: specific widget class only
        elif is_specific_widget:
            confidence = pattern['confidence_base'] * 0.6
        # Weak match: class only (no keywords or not interactive)
        elif class_match:
            confidence = pattern['confidence_base'] * 0.4
        # Very weak match: keyword only
        elif keyword_match:
            confidence = pattern['confidence_base'] * 0.3

        # Match if confidence is above threshold (raised to 0.5 for better quality)
        matches = confidence >= 0.5

        return {
            'matches': matches,
            'confidence': confidence
        }

    def _create_suggestion(
        self,
        element: Dict[str, Any],
        pattern_name: str,
        pattern: Dict[str, Any],
        confidence: float
    ) -> Dict[str, Any]:
        """
        Create an action suggestion from element and pattern match
        """
        text = element.get('text', '').strip()
        resource_id = element.get('resource_id', '')
        element_class = element.get('class', '')

        # Generate action name
        name = self._generate_action_name(element, pattern_name)

        # Generate entity ID
        entity_id = self._generate_entity_id(element, pattern_name)

        return {
            'name': name,
            'entity_id': entity_id,
            'action_type': pattern.get('action_type'),
            'icon': pattern.get('icon'),
            'confidence': round(confidence, 2),
            'pattern_type': pattern_name,
            'element': {
                'text': text,
                'resource_id': resource_id,
                'content_desc': element.get('content_desc', ''),
                'class': element_class,
                'bounds': element.get('bounds', {}),
                'clickable': element.get('clickable', False)
            },
            'suggested': True  # User hasn't confirmed yet
        }

    def _generate_action_name(self, element: Dict[str, Any], pattern_name: str) -> str:
        """Generate human-readable action name"""
        text = element.get('text', '').strip()
        resource_id = element.get('resource_id', '')

        # Try to extract meaningful name from text first
        if text and len(text) < 30 and not text.startswith('android'):
            return text.title()

        # Try to extract meaningful name from resource-id
        if resource_id:
            # e.g., "com.example:id/refresh_button" -> "Refresh Button"
            parts = resource_id.split('/')
            if len(parts) > 1:
                id_part = parts[-1]
                # Convert snake_case to Title Case
                name = id_part.replace('_', ' ').title()
                return name

        # Fallback: use pattern type
        return pattern_name.replace('_', ' ').title()

    def _generate_entity_id(self, element: Dict[str, Any], pattern_name: str) -> str:
        """Generate unique entity ID"""
        resource_id = element.get('resource_id', '')

        # Use resource-id if available
        if resource_id:
            # e.g., "com.example:id/refresh_button" -> "button.refresh_button"
            parts = resource_id.split('/')
            if len(parts) > 1:
                id_part = parts[-1]
                # Ensure valid entity ID format (lowercase, underscores)
                id_part = re.sub(r'[^a-z0-9_]', '_', id_part.lower())
                return f"button.{id_part}"

        # Fallback: use pattern name + hash of element
        element_hash = str(hash(str(element)))[-6:]
        entity_id = f"button.{pattern_name}_{element_hash}"
        entity_id = re.sub(r'[^a-z0-9_]', '_', entity_id.lower())

        return entity_id

    def _looks_like_sensor(self, element: Dict[str, Any]) -> bool:
        """
        Check if element looks like a sensor value (should not be an action)

        Filters out:
        - Numeric values with units (e.g., "71%", "25°C", "100km")
        - Status words that are state indicators, not buttons
        """
        text = element.get('text', '').strip()
        if not text:
            return False

        text_lower = text.lower()

        # Numeric value with unit pattern - very likely a sensor
        sensor_unit_pattern = r'\d+\.?\d*\s*(%|°[cfCF]?|km|mi|mph|km/h|v|a|w|kw|kwh|db|dbm|ppm|hz|mhz|gb|mb|kb|lux|hpa|psi)'
        if re.search(sensor_unit_pattern, text, re.IGNORECASE):
            logger.debug(f"[ActionSuggester] Skipping sensor-like element: '{text}'")
            return True

        # Pure percentage value (just number with %)
        if re.match(r'^\d+\.?\d*\s*%$', text):
            return True

        # Pure status words that are state indicators, not buttons
        status_indicators = [
            'on', 'off', 'open', 'closed', 'locked', 'unlocked',
            'connected', 'disconnected', 'charging', 'charged',
            'online', 'offline', 'active', 'inactive', 'enabled', 'disabled',
            'home', 'away', 'armed', 'disarmed', 'running', 'stopped'
        ]

        # Only filter if text is EXACTLY a status word (not containing action verbs)
        if text_lower in status_indicators:
            # Check if element is not a button/switch class
            element_class = element.get('class', '')
            if 'Button' not in element_class and 'Switch' not in element_class:
                logger.debug(f"[ActionSuggester] Skipping status indicator: '{text}'")
                return True

        return False

    def _is_wrapper_element(self, element: Dict[str, Any]) -> bool:
        """
        Check if element is a container/wrapper without actionable content

        Filters out:
        - FrameLayout, LinearLayout, etc. without text/content_desc
        - ViewGroups that are just containers for other elements
        """
        element_class = element.get('class', '')
        text = element.get('text', '').strip()
        content_desc = element.get('content_desc', '').strip()

        # List of wrapper/container classes that shouldn't be actions by themselves
        wrapper_classes = [
            'android.widget.FrameLayout',
            'android.widget.LinearLayout',
            'android.widget.RelativeLayout',
            'android.view.ViewGroup',
            'androidx.constraintlayout.widget.ConstraintLayout',
            'androidx.cardview.widget.CardView',
            'android.widget.ScrollView',
            'android.widget.HorizontalScrollView',
            'androidx.recyclerview.widget.RecyclerView',
            'android.widget.ListView'
        ]

        # If it's a wrapper class without text/content_desc, skip it
        if element_class in wrapper_classes:
            if not text and not content_desc:
                logger.debug(f"[ActionSuggester] Skipping wrapper element: '{element_class}'")
                return True

        return False

    def _is_truly_interactive(self, element: Dict[str, Any]) -> bool:
        """
        Check if element is truly interactive (not just focusable)

        Focusable alone doesn't mean clickable - many text elements are focusable
        for accessibility but aren't meant to be tapped as actions.
        """
        clickable = element.get('clickable', False)
        focusable = element.get('focusable', False)
        element_class = element.get('class', '')

        # Clickable is always interactive
        if clickable:
            return True

        # Focusable is only interactive if it's a known interactive widget class
        interactive_classes = [
            'Button', 'ImageButton', 'Switch', 'CheckBox', 'ToggleButton',
            'EditText', 'SeekBar', 'Spinner', 'RadioButton', 'FloatingActionButton'
        ]

        if focusable:
            for cls in interactive_classes:
                if cls in element_class:
                    return True

        return False


# Singleton instance
_suggester = None

def get_action_suggester() -> ActionSuggester:
    """Get global action suggester instance"""
    global _suggester
    if _suggester is None:
        _suggester = ActionSuggester()
    return _suggester
