"""
Feature Manager - Toggles for heavy dependencies and experimental features

This service manages feature flags for the Visual Mapper system.
It allows disabling heavy ML components (torch, tensorflow) for
resource-constrained environments (Basic Mode).

Features:
- ML components (torch, tensorflow)
- Real app icons (cv2, extraction)
- Advanced navigation (q-learning)
- Flow consolidation (beta)
"""

import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class FeatureManager:
    """
    Manages feature flags for the application.
    Flags can be set via environment variables.
    """

    def __init__(self):
        # Default flags
        self._flags = {
            "ml_enabled": self._get_env_bool("ML_ENABLED", False),
            "ml_training": self._get_env_bool("ML_TRAINING", False),
            "real_icons_enabled": self._get_env_bool("ENABLE_REAL_ICONS", True),
            "advanced_navigation": self._get_env_bool("ADVANCED_NAVIGATION", False),
            "hybrid_execution": self._get_env_bool("HYBRID_EXECUTION", True),
            "performance_monitoring": self._get_env_bool(
                "PERFORMANCE_MONITORING", True
            ),
            # Flow consolidation (beta) - batches flows targeting same app/screens
            "flow_consolidation": self._get_env_bool("FLOW_CONSOLIDATION", False),
        }

        # Consolidation-specific configuration
        self._consolidation_config = {
            "window_seconds": int(os.environ.get("CONSOLIDATION_WINDOW_SECONDS", "30")),
            "minimum_savings_threshold": int(
                os.environ.get("MINIMUM_SAVINGS_THRESHOLD", "5")
            ),
            "max_batch_size": int(os.environ.get("MAX_CONSOLIDATION_BATCH", "10")),
        }

        # Log active flags
        active_features = [f for f, enabled in self._flags.items() if enabled]
        disabled_features = [f for f, enabled in self._flags.items() if not enabled]

        logger.info(f"[FeatureManager] Enabled features: {active_features}")
        if disabled_features:
            logger.info(f"[FeatureManager] Disabled features: {disabled_features}")

    def _get_env_bool(self, name: str, default: bool) -> bool:
        """Get boolean value from environment variable"""
        value = os.environ.get(name, str(default)).lower()
        return value in ("true", "1", "yes", "on")

    def is_enabled(self, feature_name: str) -> bool:
        """Check if a feature is enabled"""
        return self._flags.get(feature_name, False)

    def get_all_flags(self) -> Dict[str, bool]:
        """Get all feature flags"""
        return self._flags.copy()

    def get_consolidation_config(self) -> Dict[str, Any]:
        """Get flow consolidation configuration"""
        return self._consolidation_config.copy()


# Singleton instance
_feature_manager = None


def get_feature_manager() -> FeatureManager:
    """Get or create singleton FeatureManager"""
    global _feature_manager
    if _feature_manager is None:
        _feature_manager = FeatureManager()
    return _feature_manager
