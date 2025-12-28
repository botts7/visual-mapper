"""
Smart Action Suggester - AI-powered action detection from UI elements

This module analyzes Android UI elements and suggests Home Assistant actions
based on pattern detection heuristics. It identifies common action types like
buttons, switches, toggles, input fields, and more.
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

        for element in elements:
            # Skip elements without useful identifiers
            text = element.get('text', '').strip()
            resource_id = element.get('resource_id', '')
            content_desc = element.get('content_desc', '')
            element_class = element.get('class', '')
            clickable = element.get('clickable', False)

            # Only skip non-interactive elements if they have no useful attributes
            if not clickable and not text and not resource_id and not content_desc:
                # Check if element class is actionable (Button, Switch, etc.)
                actionable_classes = ['Button', 'Switch', 'CheckBox', 'EditText', 'SeekBar']
                if not any(cls in element_class for cls in actionable_classes):
                    skipped_non_interactive += 1
                    continue
                # Otherwise, analyze it (might have useful class info)

            analyzed += 1
            logger.debug(f"[ActionSuggester] Analyzing element: text='{text[:50] if text else '(none)'}', class='{element_class}', clickable={clickable}")

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
        logger.info(f"[ActionSuggester] Stats: analyzed={analyzed}, skipped_non_interactive={skipped_non_interactive}, skipped_duplicate={skipped_duplicate}")
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
        clickable = element.get('clickable', False)
        focusable = element.get('focusable', False)

        # Combine all searchable text
        searchable = f"{text_lower} {resource_id} {content_desc}"

        confidence = 0.0

        # Check for class match
        class_match = element_class in pattern.get('classes', [])

        # Check for keywords
        keyword_match = any(kw in searchable for kw in pattern.get('keywords', []))

        # Calculate confidence based on matches - RELAXED logic
        has_keywords = len(pattern.get('keywords', [])) > 0
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
        if is_class_based and class_match and (clickable or focusable):
            # Button widget + clickable is very strong signal, even without keywords
            confidence = pattern['confidence_base'] * 0.95
        # Perfect match: class + keyword + clickable
        elif class_match and keyword_match and (clickable or focusable):
            confidence = pattern['confidence_base']
        # Strong match: class + keyword
        elif class_match and keyword_match:
            confidence = pattern['confidence_base'] * 0.95
        # Good match: specific widget class + clickable (Switch, CheckBox, etc.)
        elif is_specific_widget and (clickable or focusable):
            confidence = pattern['confidence_base'] * 0.9
        # Good match: class + clickable (Button + clickable, even with keywords defined)
        elif class_match and (clickable or focusable):
            if is_button_class:
                # Button + clickable is strong even without keyword match
                confidence = pattern['confidence_base'] * 0.8  # Boosted from 0.3
            else:
                confidence = pattern['confidence_base'] * 0.9
        # Medium match: keyword + clickable (for patterns where class doesn't match)
        elif keyword_match and (clickable or focusable):
            confidence = pattern['confidence_base'] * 0.7
        # For generic patterns, accept clickable alone
        elif pattern.get('is_generic') and clickable and not text_lower.startswith('android'):
            confidence = pattern['confidence_base']  # Use full base confidence
        # Weak match: specific widget class only
        elif is_specific_widget:
            confidence = pattern['confidence_base'] * 0.7
        # Weak match: class only (no keywords or not clickable)
        elif class_match:
            confidence = pattern['confidence_base'] * 0.5
        # Very weak match: keyword only
        elif keyword_match:
            confidence = pattern['confidence_base'] * 0.4

        # Match if confidence is above threshold (lowered from 0.5 to 0.3 for better detection)
        matches = confidence >= 0.3

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
                'resource-id': resource_id,
                'content-desc': element.get('content_desc', ''),
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


# Singleton instance
_suggester = None

def get_action_suggester() -> ActionSuggester:
    """Get global action suggester instance"""
    global _suggester
    if _suggester is None:
        _suggester = ActionSuggester()
    return _suggester
