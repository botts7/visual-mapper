"""
Smart Sensor Suggester - AI-powered sensor detection from UI elements

This module analyzes Android UI elements and suggests Home Assistant sensors
based on pattern detection heuristics. It identifies common sensor types like
battery, temperature, humidity, binary sensors, and more.

Enhanced with flexible pattern matching, fuzzy matching, and support for
40+ Home Assistant device classes.
"""

import re
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class SensorSuggester:
    """AI-powered sensor detection from UI elements"""

    # Pattern definitions for different sensor types
    # Order matters! More specific patterns should come first
    PATTERNS = {
        # =====================================================================
        # Class-based auto-detection patterns (highest priority)
        # =====================================================================
        "progressbar": {
            "keywords": [],
            "indicators": [],
            "classes": [
                "android.widget.ProgressBar",
                "androidx.appcompat.widget.AppCompatProgressBar",
            ],
            "device_class": "none",
            "unit": "%",
            "icon": "mdi:progress-clock",
            "confidence_base": 0.9,
            "value_range": (0, 100),
            "is_class_based": True,
        },
        "seekbar": {
            "keywords": [],
            "indicators": [],
            "classes": [
                "android.widget.SeekBar",
                "androidx.appcompat.widget.AppCompatSeekBar",
            ],
            "device_class": "none",
            "unit": None,
            "icon": "mdi:tune",
            "confidence_base": 0.85,
            "is_class_based": True,
        },
        "ratingbar": {
            "keywords": [],
            "indicators": [],
            "classes": ["android.widget.RatingBar"],
            "device_class": "none",
            "unit": "stars",
            "icon": "mdi:star",
            "confidence_base": 0.9,
            "value_range": (0, 5),
            "is_class_based": True,
        },
        # =====================================================================
        # Specific patterns with strong keywords (ordered by specificity)
        # =====================================================================
        "temperature": {
            "keywords": ["temp", "temperature", "celsius", "fahrenheit", "thermometer"],
            "indicators": ["°f", "°c", "°", "deg", "℃", "℉"],
            "device_class": "temperature",
            "unit": None,  # Auto-detect from text
            "icon": "mdi:thermometer",
            "confidence_base": 0.95,
            "value_range": (-50, 150),
        },
        "humidity": {
            "keywords": ["humidity", "humid", "rh", "moisture", "dampness"],
            "indicators": ["%"],
            "device_class": "humidity",
            "unit": "%",
            "icon": "mdi:water-percent",
            "confidence_base": 0.9,
            "value_range": (0, 100),
        },
        "battery": {
            "keywords": ["battery", "batt", "charge", "soc", "state of charge"],
            "indicators": ["%"],
            "device_class": "battery",
            "unit": "%",
            "icon": "mdi:battery",
            "confidence_base": 0.9,
            "value_range": (0, 100),
        },
        # =====================================================================
        # NEW: Energy & Power patterns
        # =====================================================================
        "voltage": {
            "keywords": ["volt", "voltage", "potential"],
            "indicators": ["v", "mv", "kv", "volts"],
            "device_class": "voltage",
            "unit": "V",
            "icon": "mdi:lightning-bolt",
            "confidence_base": 0.9,
            "value_range": (0, 500),
        },
        "current": {
            "keywords": ["current", "amp", "ampere", "amps", "amperage"],
            "indicators": ["a", "ma", "amp", "amps"],
            "device_class": "current",
            "unit": "A",
            "icon": "mdi:current-ac",
            "confidence_base": 0.9,
            "value_range": (0, 100),
        },
        "power": {
            "keywords": ["power", "watt", "watts", "load", "consumption"],
            "indicators": ["w", "kw", "mw", "watts"],
            "device_class": "power",
            "unit": "W",
            "icon": "mdi:flash",
            "confidence_base": 0.9,
            "value_range": (0, 100000),
        },
        "energy": {
            "keywords": ["energy", "kwh", "wh", "consumption", "usage"],
            "indicators": ["wh", "kwh", "mwh"],
            "device_class": "energy",
            "unit": "kWh",
            "icon": "mdi:lightning-bolt-circle",
            "confidence_base": 0.9,
            "value_range": (0, 100000),
        },
        # =====================================================================
        # NEW: Speed & Distance patterns
        # =====================================================================
        "speed": {
            "keywords": ["speed", "velocity", "pace"],
            "indicators": ["mph", "km/h", "kmh", "kph", "m/s", "knots"],
            "device_class": "speed",
            "unit": None,  # Auto-detect
            "icon": "mdi:speedometer",
            "confidence_base": 0.9,
            "value_range": (0, 500),
        },
        "distance": {
            "keywords": [
                "distance",
                "range",
                "mileage",
                "odometer",
                "miles",
                "kilometers",
                "total mileage",
            ],
            "indicators": ["km", "mi", "miles", "meters", "m"],
            "device_class": "distance",
            "unit": None,  # Auto-detect
            "icon": "mdi:map-marker-distance",
            "confidence_base": 0.9,
            "value_range": (0, 1000000),
        },
        # =====================================================================
        # NEW: Signal & Connectivity patterns
        # =====================================================================
        "signal_strength": {
            "keywords": [
                "signal",
                "wifi",
                "bars",
                "rssi",
                "cellular",
                "reception",
                "network",
            ],
            "indicators": ["dbm", "db", "bars"],
            "device_class": "signal_strength",
            "unit": "dBm",
            "icon": "mdi:signal",
            "confidence_base": 0.85,
            "value_range": (-120, 0),
        },
        "data_rate": {
            "keywords": ["download", "upload", "bandwidth", "transfer", "speed"],
            "indicators": ["mbps", "kbps", "gbps", "mb/s", "kb/s"],
            "device_class": "data_rate",
            "unit": "Mbps",
            "icon": "mdi:download",
            "confidence_base": 0.85,
            "value_range": (0, 10000),
        },
        "data_size": {
            "keywords": [
                "storage",
                "memory",
                "disk",
                "space",
                "available",
                "free",
                "used",
            ],
            "indicators": ["gb", "mb", "kb", "tb", "bytes"],
            "device_class": "data_size",
            "unit": "GB",
            "icon": "mdi:database",
            "confidence_base": 0.85,
            "value_range": (0, 10000),
        },
        # =====================================================================
        # NEW: Environmental patterns
        # =====================================================================
        "illuminance": {
            "keywords": ["light", "brightness", "lux", "illuminance", "luminance"],
            "indicators": ["lux", "lx", "lumens"],
            "device_class": "illuminance",
            "unit": "lx",
            "icon": "mdi:brightness-6",
            "confidence_base": 0.9,
            "value_range": (0, 100000),
        },
        "pressure": {
            "keywords": ["pressure", "barometer", "hpa", "mbar", "psi", "atmospheric"],
            "indicators": ["hpa", "mbar", "psi", "inhg", "pa", "kpa"],
            "device_class": "pressure",
            "unit": None,  # Auto-detect from text
            "icon": "mdi:gauge",
            "confidence_base": 0.85,
            "value_range": (0, 2000),
        },
        "co2": {
            "keywords": ["co2", "carbon dioxide", "carbon"],
            "indicators": ["ppm", "co2"],
            "device_class": "carbon_dioxide",
            "unit": "ppm",
            "icon": "mdi:molecule-co2",
            "confidence_base": 0.9,
            "value_range": (0, 10000),
        },
        "aqi": {
            "keywords": [
                "aqi",
                "air quality",
                "pm2.5",
                "pm10",
                "pollution",
                "particulate",
            ],
            "indicators": ["aqi", "pm", "µg/m³"],
            "device_class": "aqi",
            "unit": None,
            "icon": "mdi:air-filter",
            "confidence_base": 0.9,
            "value_range": (0, 500),
        },
        # =====================================================================
        # NEW: Physical measurement patterns
        # =====================================================================
        "weight": {
            "keywords": ["weight", "mass", "heavy", "load"],
            "indicators": ["kg", "lb", "lbs", "g", "oz", "pounds", "kilograms"],
            "device_class": "weight",
            "unit": "kg",
            "icon": "mdi:weight",
            "confidence_base": 0.85,
            "value_range": (0, 10000),
        },
        "volume": {
            "keywords": ["volume", "capacity", "liters", "gallons", "tank", "fuel"],
            "indicators": ["l", "gal", "ml", "liters", "gallons"],
            "device_class": "volume",
            "unit": "L",
            "icon": "mdi:cup-water",
            "confidence_base": 0.85,
            "value_range": (0, 10000),
        },
        "frequency": {
            "keywords": ["frequency", "rpm", "hertz", "cycle"],
            "indicators": ["hz", "khz", "mhz", "ghz", "rpm"],
            "device_class": "frequency",
            "unit": "Hz",
            "icon": "mdi:sine-wave",
            "confidence_base": 0.85,
            "value_range": (0, 100000),
        },
        # =====================================================================
        # NEW: Financial & Duration patterns
        # =====================================================================
        "monetary": {
            "keywords": [
                "price",
                "cost",
                "balance",
                "amount",
                "total",
                "payment",
                "fee",
            ],
            "indicators": ["$", "€", "£", "¥", "usd", "eur"],
            "device_class": "monetary",
            "unit": None,
            "icon": "mdi:currency-usd",
            "confidence_base": 0.85,
            "value_range": (0, 1000000),
        },
        "duration": {
            "keywords": [
                "remaining",
                "elapsed",
                "eta",
                "time left",
                "duration",
                "countdown",
            ],
            "indicators": ["min", "hr", "hrs", "mins", "sec", "secs"],
            "device_class": "duration",
            "unit": None,
            "icon": "mdi:timer",
            "confidence_base": 0.8,
            "value_range": (0, 100000),
        },
        # =====================================================================
        # Generic fallback patterns (lower priority)
        # =====================================================================
        "percentage": {
            "keywords": [],
            "indicators": ["%"],
            "device_class": "none",
            "unit": "%",
            "icon": "mdi:percent",
            "confidence_base": 0.65,  # Moderate confidence - % is a strong indicator
            "value_range": (0, 100),
        },
        "timestamp": {
            "keywords": [
                "updated",
                "last",
                "time",
                "date",
                "modified",
                "refreshed",
                "synced",
                "at",
            ],
            "indicators": [":", "am", "pm", "ago", "min", "sec", "hour"],
            "device_class": "timestamp",
            "unit": None,
            "icon": "mdi:clock",
            "confidence_base": 0.7,
            "is_timestamp": True,
        },
        "binary": {
            "keywords": [
                "status",
                "state",
                "enabled",
                "disabled",
                "active",
                "mode",
                "locked",
                "door",
                "window",
            ],
            "indicators": [
                "on",
                "off",
                "true",
                "false",
                "yes",
                "no",
                "enabled",
                "disabled",
                "active",
                "inactive",
                "online",
                "offline",
                "connected",
                "disconnected",
                "locked",
                "unlocked",
                "open",
                "closed",
                "opened",
                "armed",
                "disarmed",
                "running",
                "stopped",
                "charging",
                "ready",
                "ok",
                "error",
                "good",
                "bad",
                "home",
                "away",
                "present",
                "absent",
                "occupied",
                "vacant",
            ],
            "device_class": "none",
            "unit": None,
            "icon": "mdi:toggle-switch",
            "confidence_base": 0.85,
            "is_binary": True,
        },
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
        seen_combinations = (
            set()
        )  # Avoid duplicate suggestions (resource_id + text combo)

        skipped_no_text = 0
        skipped_duplicate = 0
        analyzed = 0

        for element in elements:
            # Skip elements without any useful attributes
            text = element.get("text", "").strip()
            resource_id = element.get("resource_id", "")
            content_desc = element.get("content_desc", "")
            element_class = element.get("class", "")

            # Only skip if element has no useful info AND is a generic container
            if not text and not resource_id and not content_desc:
                # Check if element class is useful (not a generic container)
                if element_class in ["android.view.View", "android.view.ViewGroup", ""]:
                    skipped_no_text += 1
                    continue
                # Otherwise, analyze it (might have useful class info)

            analyzed += 1
            logger.debug(
                f"[SensorSuggester] Analyzing element: text='{text[:50] if text else '(none)'}', resource_id='{resource_id}'"
            )

            # Try to match against each pattern
            matched_any = False
            for pattern_name, pattern in self.PATTERNS.items():
                match_result = self._matches_pattern(element, text, pattern)

                if match_result["matches"]:
                    # Create unique key combining resource_id, text, and position
                    # This allows multiple sensors with same ID but different values (e.g., 4 tire pressures)
                    bounds = element.get("bounds", "")
                    unique_key = f"{resource_id}|{text}|{bounds}"

                    # Skip only if exact same element (same ID, text, AND position)
                    if unique_key in seen_combinations:
                        skipped_duplicate += 1
                        logger.debug(
                            f"[SensorSuggester] Skipping duplicate element: {unique_key}"
                        )
                        break

                    suggestion = self._create_suggestion(
                        element=element,
                        pattern_name=pattern_name,
                        pattern=pattern,
                        confidence=match_result["confidence"],
                        extracted_value=match_result.get("value"),
                        extracted_unit=match_result.get("unit"),
                        all_elements=elements,
                    )

                    suggestions.append(suggestion)
                    matched_any = True
                    logger.debug(
                        f"[SensorSuggester] Matched pattern '{pattern_name}' with confidence {match_result['confidence']:.2f}"
                    )

                    # Mark this combination as seen
                    seen_combinations.add(unique_key)

                    # Only match first pattern (highest priority)
                    break

            if not matched_any:
                logger.debug(
                    f"[SensorSuggester] No pattern matched for element: text='{text[:50] if text else '(none)'}'"
                )

        # Sort by confidence (highest first)
        suggestions.sort(key=lambda x: x["confidence"], reverse=True)

        logger.info(
            f"[SensorSuggester] Generated {len(suggestions)} sensor suggestions from {len(elements)} elements"
        )
        logger.info(
            f"[SensorSuggester] Stats: analyzed={analyzed}, skipped_no_text={skipped_no_text}, skipped_duplicate={skipped_duplicate}"
        )
        return suggestions

    def _matches_pattern(
        self, element: Dict[str, Any], text: str, pattern: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Check if element matches a sensor pattern

        Returns:
            Dict with 'matches' (bool), 'confidence' (float), 'value', 'unit'
        """
        text_lower = text.lower()
        resource_id = element.get("resource_id", "").lower()
        content_desc = element.get("content_desc", "").lower()
        element_class = element.get("class", "")

        # Combine all searchable text
        searchable = f"{text_lower} {resource_id} {content_desc}"

        confidence = 0.0
        extracted_value = None
        extracted_unit = None

        # Check for class-based match (highest priority for class-based patterns)
        class_match = element_class in pattern.get("classes", [])

        if class_match and pattern.get("is_class_based"):
            # Class-based auto-detection - high confidence
            confidence = pattern["confidence_base"]
            # Try to extract numeric value if available
            numeric_match = self._extract_numeric_value(text)
            if numeric_match:
                extracted_value = numeric_match["value"]
                extracted_unit = numeric_match["unit"]
            else:
                # For widgets like ProgressBar, use resource-id or text as value
                extracted_value = text or resource_id or element_class.split(".")[-1]

            return {
                "matches": True,
                "confidence": confidence,
                "value": extracted_value,
                "unit": extracted_unit or pattern.get("unit"),
            }

        # Check for keywords (using fuzzy matching for flexibility)
        keywords = pattern.get("keywords", [])
        keyword_match = self._fuzzy_match(searchable, keywords) if keywords else False

        # Check for indicators
        # Short indicators (≤2 chars like "a", "ma") require word boundaries
        # to prevent false positives like "sealion" matching "a" for amperes
        indicator_match = False
        for ind in pattern.get("indicators", []):
            if len(ind) <= 2:
                # Short indicators must be standalone (after digit/space, before non-letter)
                # Matches: "7 A", "7A", "50 ma" but NOT "sealion", "drama"
                if re.search(
                    rf"(?:^|\s|\d){re.escape(ind)}(?:$|\s|[^a-z])", text_lower
                ):
                    indicator_match = True
                    break
            else:
                # Longer indicators can use substring match
                if ind in text_lower:
                    indicator_match = True
                    break

        # Special handling for binary sensors
        if pattern.get("is_binary"):
            if text_lower in pattern["indicators"]:
                confidence = pattern["confidence_base"]
                extracted_value = text_lower
                return {
                    "matches": True,
                    "confidence": confidence,
                    "value": extracted_value,
                    "unit": None,
                }

        # Special handling for timestamps
        if pattern.get("is_timestamp"):
            if keyword_match or self._looks_like_timestamp(text):
                confidence = pattern["confidence_base"]
                if self._looks_like_timestamp(text):
                    confidence += 0.1  # Bonus for matching time format
                return {
                    "matches": True,
                    "confidence": min(confidence, 1.0),
                    "value": text,
                    "unit": None,
                }

        # Numeric value extraction
        numeric_match = self._extract_numeric_value(text)

        if numeric_match:
            extracted_value = numeric_match["value"]
            extracted_unit = numeric_match["unit"]

            # Check if value is in expected range
            value_range = pattern.get("value_range")
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
                confidence = pattern["confidence_base"]
            elif keyword_match and indicator_match:
                # Strong match: keyword + indicator (no range check)
                confidence = pattern["confidence_base"] * 0.9
            elif keyword_match and in_range:
                # Good match: keyword + range (missing indicator)
                confidence = pattern["confidence_base"] * 0.85
            elif indicator_match and in_range:
                # Indicator + range match (works for both generic and keyword patterns)
                # Strong indicators (%, °, etc.) are sufficient even without keywords
                if pattern["confidence_base"] >= 0.6:
                    # High confidence pattern - indicator + range is good
                    confidence = pattern["confidence_base"] * 0.8
                else:
                    # Low confidence pattern - reduce confidence
                    confidence = pattern["confidence_base"] * 0.6
            elif indicator_match and not pattern.get("keywords"):
                # Generic pattern with indicator only (no range check needed)
                confidence = pattern["confidence_base"] * 0.7
            elif indicator_match and pattern["confidence_base"] >= 0.8:
                # Strong indicator for high-confidence pattern (%, °, humidity, etc.)
                # Allow match even without keyword or range
                confidence = pattern["confidence_base"] * 0.6
            elif keyword_match:
                # Keyword only - weak match, but allow for TextViews with numeric content
                is_textview = "TextView" in element_class
                if is_textview and numeric_match:
                    confidence = pattern["confidence_base"] * 0.5
                else:
                    confidence = 0.0
            else:
                # No match
                confidence = 0.0

        # Match if confidence is above threshold (raised to 0.45 for better quality)
        matches = confidence >= 0.45

        # Only apply pattern's default unit if:
        # 1. We actually extracted a unit from the text, OR
        # 2. There was a strong indicator match (not a false positive from single-letter)
        # This prevents "BYD SEALION 7" from becoming "7 A"
        final_unit = extracted_unit
        if not final_unit and indicator_match and confidence >= 0.5:
            # Only apply default unit for confident matches with real indicator
            final_unit = pattern.get("unit")

        return {
            "matches": matches,
            "confidence": confidence,
            "value": extracted_value,
            "unit": final_unit,
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
        pattern = r"(-?\d+\.?\d*)\s*([°%a-zA-Z]+)?"
        match = re.search(pattern, text)

        if match:
            value = match.group(1)
            unit = match.group(2) if match.group(2) else None

            return {"value": value, "unit": unit}

        return None

    def _looks_like_timestamp(self, text: str) -> bool:
        """Check if text looks like a timestamp"""
        # Common timestamp patterns
        patterns = [
            r"\d{1,2}:\d{2}",  # HH:MM
            r"\d{1,2}:\d{2}:\d{2}",  # HH:MM:SS
            r"\d{1,2}:\d{2}\s*(am|pm)",  # 12-hour with AM/PM
            r"\d+ (min|sec|hour|day)s? ago",  # Relative time
            r"\d{4}-\d{2}-\d{2}",  # ISO date
        ]

        return any(re.search(pattern, text.lower()) for pattern in patterns)

    def _fuzzy_match(
        self, text: str, keywords: List[str], threshold: float = 0.8
    ) -> bool:
        """
        Check if text fuzzy-matches any keyword

        Supports:
        - Exact substring match (fastest)
        - Fuzzy matching using SequenceMatcher for typos/variations

        Args:
            text: Text to search in
            keywords: List of keywords to match
            threshold: Minimum similarity ratio (0.0-1.0) for fuzzy match

        Returns:
            True if any keyword matches
        """
        text_lower = text.lower()

        for keyword in keywords:
            # Exact substring match (fast path)
            if keyword in text_lower:
                return True

            # Fuzzy match each word in the text
            for word in text_lower.split():
                # Skip very short words for fuzzy matching
                if len(word) < 3 or len(keyword) < 3:
                    continue

                ratio = SequenceMatcher(None, keyword, word).ratio()
                if ratio >= threshold:
                    logger.debug(
                        f"[SensorSuggester] Fuzzy match: '{keyword}' ~ '{word}' ({ratio:.2f})"
                    )
                    return True

        return False

    def _create_suggestion(
        self,
        element: Dict[str, Any],
        pattern_name: str,
        pattern: Dict[str, Any],
        confidence: float,
        extracted_value: Optional[str] = None,
        extracted_unit: Optional[str] = None,
        all_elements: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Create a sensor suggestion from element and pattern match.
        Includes alternative name suggestions for user to choose from.
        """
        text = element.get("text", "").strip()
        resource_id = element.get("resource_id", "")

        # Find nearby label candidates (up to 3)
        label_candidates = []
        if all_elements:
            label_candidates = self._find_nearby_labels(
                element, all_elements, max_candidates=3
            )

        # Generate primary sensor name (use best label candidate if available)
        if label_candidates:
            name = label_candidates[0]["text"].title()
        else:
            name = self._generate_sensor_name(element, pattern_name, None)

        # Build alternative names list
        alternative_names = []
        for i, candidate in enumerate(label_candidates):
            alt_name = candidate["text"].title()
            if alt_name.lower() != name.lower():  # Don't include primary name
                alternative_names.append(
                    {
                        "name": alt_name,
                        "location": candidate.get("location", "unknown"),
                        "score": round(candidate.get("score", 0), 1),
                    }
                )

        # Also add resource-id based name as alternative if different
        if resource_id:
            parts = resource_id.split("/")
            if len(parts) > 1:
                resource_name = parts[-1].replace("_", " ").title()
                if resource_name.lower() != name.lower():
                    # Check if not already in alternatives
                    if not any(
                        alt["name"].lower() == resource_name.lower()
                        for alt in alternative_names
                    ):
                        alternative_names.append(
                            {
                                "name": resource_name,
                                "location": "resource_id",
                                "score": 50,  # Medium priority
                            }
                        )

        # Add pattern-based name as fallback alternative
        pattern_based_name = pattern_name.replace("_", " ").title()
        if pattern_based_name.lower() != name.lower():
            if not any(
                alt["name"].lower() == pattern_based_name.lower()
                for alt in alternative_names
            ):
                alternative_names.append(
                    {
                        "name": pattern_based_name,
                        "location": "pattern",
                        "score": 25,  # Lower priority
                    }
                )

        # Generate entity ID
        entity_id = self._generate_entity_id(element, pattern_name)

        # Determine unit
        unit = extracted_unit or pattern.get("unit")

        return {
            "name": name,
            "alternative_names": alternative_names,  # NEW: List of alternative name suggestions
            "entity_id": entity_id,
            "device_class": pattern.get("device_class"),
            "unit_of_measurement": unit,
            "icon": pattern.get("icon"),
            "confidence": round(confidence, 2),
            "pattern_type": pattern_name,
            "element": {
                "text": text,
                "resource_id": resource_id,
                "content_desc": element.get("content_desc", ""),
                "class": element.get("class", ""),
                "bounds": element.get("bounds", {}),
            },
            "current_value": extracted_value,
            "suggested": True,  # User hasn't confirmed yet
        }

    def _find_nearby_labels(
        self,
        element: Dict[str, Any],
        elements: List[Dict[str, Any]],
        max_candidates: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Find label elements spatially near this value element.
        Returns multiple candidates ranked by likelihood.

        Detects label-value pairs like:
        - "Cumulative AEC" (label above) + "17.7kWh/100km" (value)
        - "Doors" (label above) + "Closed and locked" (value)
        - "Total mileage" (label above) + "18107km" (value)
        - "Battery:" (label left) + "85%" (value)

        Args:
            element: The value element to find a label for
            elements: All UI elements to search through
            max_candidates: Maximum number of label candidates to return

        Returns:
            List of label candidates with text and score, sorted by score (best first)
        """
        bounds = element.get("bounds", {})
        if not bounds or "x" not in bounds or "y" not in bounds:
            return []

        element_text = element.get("text", "").strip()
        element_width = bounds.get("width", 200)
        element_height = bounds.get("height", 50)
        element_center_x = bounds["x"] + element_width / 2
        element_center_y = bounds["y"] + element_height / 2

        # Candidates grouped by location type
        above_labels = []
        below_labels = []
        left_labels = []
        content_desc_labels = []

        for other in elements:
            # Skip self
            if other is element:
                continue

            other_bounds = other.get("bounds", {})
            if not other_bounds or "x" not in other_bounds or "y" not in other_bounds:
                continue

            other_text = other.get("text", "").strip()
            other_content_desc = other.get("content_desc", "").strip()

            # Skip if no text content
            if not other_text and not other_content_desc:
                continue

            other_width = other_bounds.get("width", 200)
            other_height = other_bounds.get("height", 50)
            other_center_x = other_bounds["x"] + other_width / 2
            other_center_y = other_bounds["y"] + other_height / 2

            # Calculate center distances
            x_center_distance = abs(other_center_x - element_center_x)
            y_distance = element_center_y - other_center_y  # Positive = other is above

            # Use the text or content description
            label_text = other_text or other_content_desc

            # Check if this looks like a label (not a numeric value)
            if self._looks_like_label(label_text):
                # Check vertical alignment (within 100px horizontally, or overlapping x-axis)
                is_vertically_aligned = x_center_distance < 100 or (
                    other_bounds["x"] < bounds["x"] + element_width
                    and other_bounds["x"] + other_width > bounds["x"]
                )

                # Check horizontal alignment (within 40px vertically)
                is_horizontally_aligned = abs(y_distance) < 40

                # Element is ABOVE (y_distance > 0, within 150px)
                if is_vertically_aligned and 0 < y_distance < 150:
                    above_labels.append(
                        {
                            "text": label_text,
                            "distance": y_distance,
                            "x_offset": x_center_distance,
                            "priority": 1,
                        }
                    )

                # Element is BELOW (y_distance < 0, within 100px)
                elif is_vertically_aligned and -100 < y_distance < 0:
                    below_labels.append(
                        {
                            "text": label_text,
                            "distance": abs(y_distance),
                            "x_offset": x_center_distance,
                            "priority": 2,
                        }
                    )

                # Element is to the LEFT on same row
                elif is_horizontally_aligned:
                    x_left_distance = bounds["x"] - (other_bounds["x"] + other_width)
                    if 0 < x_left_distance < 250:  # To the left, within 250px
                        left_labels.append(
                            {
                                "text": label_text,
                                "distance": x_left_distance,
                                "x_offset": 0,
                                "priority": 3,
                            }
                        )

            # Also check content description even if element has numeric text
            # (some elements have descriptive content_desc)
            if other_content_desc and other_content_desc != other_text:
                if self._looks_like_label(other_content_desc):
                    if x_center_distance < 50 and abs(y_distance) < 30:
                        content_desc_labels.append(
                            {
                                "text": other_content_desc,
                                "distance": abs(y_distance) + x_center_distance / 10,
                                "x_offset": x_center_distance,
                                "priority": 4,
                            }
                        )

        # Collect all candidates and score them
        all_candidates = []

        # Score calculation: lower distance = higher score, priority as tiebreaker
        def calculate_score(item):
            # Base score from priority (above=1 is best)
            priority_score = (5 - item["priority"]) * 100  # 400, 300, 200, 100
            # Distance penalty (closer = higher score)
            distance_penalty = min(item["distance"], 200)  # Cap penalty
            # X-offset penalty (more centered = higher score)
            offset_penalty = min(item["x_offset"] / 2, 50)
            return priority_score - distance_penalty - offset_penalty

        for label in above_labels + below_labels + left_labels + content_desc_labels:
            label["score"] = calculate_score(label)
            label["location"] = {
                1: "above",
                2: "below",
                3: "left",
                4: "content_desc",
            }.get(label["priority"], "unknown")
            all_candidates.append(label)

        # Sort by score (highest first) and remove duplicates
        all_candidates.sort(key=lambda x: x["score"], reverse=True)

        # Remove duplicate texts (keep highest scored)
        seen_texts = set()
        unique_candidates = []
        for candidate in all_candidates:
            text_lower = candidate["text"].lower().strip()
            if text_lower not in seen_texts:
                seen_texts.add(text_lower)
                unique_candidates.append(candidate)

        # Return top candidates
        result = unique_candidates[:max_candidates]

        if result:
            logger.debug(
                f"[SensorSuggester] Found {len(result)} label candidates for value '{element_text}': {[c['text'] for c in result]}"
            )

        return result

    def _find_nearby_label(
        self, element: Dict[str, Any], elements: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Find the best label element spatially near this value element.
        Wrapper for _find_nearby_labels that returns just the top result.
        """
        candidates = self._find_nearby_labels(element, elements, max_candidates=1)
        if candidates:
            return candidates[0]["text"]
        return None

    def _looks_like_label(self, text: str) -> bool:
        """
        Check if text looks like a label rather than a value

        Labels typically:
        - Don't contain numeric values with units
        - Are shorter, descriptive text
        - Don't look like binary states (on/off)
        - May end with colon (:)
        """
        if not text:
            return False

        text_lower = text.lower().strip()

        # Labels ending with colon are definitely labels
        if text.endswith(":"):
            return True

        # Skip if it looks like a pure numeric value with unit
        # e.g., "85%", "72°F", "17.7kWh/100km"
        if re.match(r"^-?\d+\.?\d*\s*[°%a-zA-Z\/]+$", text.strip()):
            return False

        # Skip binary state values
        binary_values = [
            "on",
            "off",
            "true",
            "false",
            "yes",
            "no",
            "enabled",
            "disabled",
            "active",
            "inactive",
            "online",
            "offline",
            "connected",
            "disconnected",
            "open",
            "closed",
            "locked",
            "unlocked",
            "charging",
            "ready",
            "ok",
            "error",
        ]
        if text_lower in binary_values:
            return False

        # Skip very long text (probably not a label)
        if len(text) > 50:
            return False

        # Skip if text is mostly numeric
        digits = sum(c.isdigit() for c in text)
        if len(text) > 0 and digits / len(text) > 0.5:
            return False

        # Looks like a label
        return True

    def _generate_sensor_name(
        self,
        element: Dict[str, Any],
        pattern_name: str,
        all_elements: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Generate human-readable sensor name"""
        text = element.get("text", "").strip()
        resource_id = element.get("resource_id", "")

        # Try to find a nearby label first (spatial detection)
        if all_elements:
            nearby_label = self._find_nearby_label(element, all_elements)
            if nearby_label:
                # Use nearby label as sensor name
                return nearby_label.title()

        # Try to extract meaningful name from resource-id
        if resource_id:
            # e.g., "com.example:id/battery_level" -> "Battery Level"
            parts = resource_id.split("/")
            if len(parts) > 1:
                id_part = parts[-1]
                # Convert snake_case to Title Case
                name = id_part.replace("_", " ").title()
                return name

        # Fallback: use text if it's descriptive
        if text and len(text) < 30:
            # Remove numeric values, keep descriptive part
            name = re.sub(r"\d+\.?\d*\s*[°%a-zA-Z]*", "", text).strip()
            if name:
                return name.title()

        # Last resort: use pattern type
        return pattern_name.replace("_", " ").title()

    def _generate_entity_id(self, element: Dict[str, Any], pattern_name: str) -> str:
        """Generate unique entity ID"""
        resource_id = element.get("resource_id", "")

        # Use resource-id if available
        if resource_id:
            # e.g., "com.example:id/battery_level" -> "sensor.battery_level"
            parts = resource_id.split("/")
            if len(parts) > 1:
                id_part = parts[-1]
                # Ensure valid entity ID format (lowercase, underscores)
                id_part = re.sub(r"[^a-z0-9_]", "_", id_part.lower())
                return f"sensor.{id_part}"

        # Fallback: use pattern name + hash of element
        element_hash = str(hash(str(element)))[-6:]
        entity_id = f"sensor.{pattern_name}_{element_hash}"
        entity_id = re.sub(r"[^a-z0-9_]", "_", entity_id.lower())

        return entity_id


# Singleton instance
_suggester = None


def get_sensor_suggester() -> SensorSuggester:
    """Get global sensor suggester instance"""
    global _suggester
    if _suggester is None:
        _suggester = SensorSuggester()
    return _suggester
