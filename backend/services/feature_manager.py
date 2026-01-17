"""
Feature Manager - Toggles for heavy dependencies and experimental features

This service manages feature flags for the Visual Mapper system.
It allows disabling heavy ML components (torch, tensorflow) for
resource-constrained environments (Basic Mode).

Core Features (via _flags):
- ML components (torch, tensorflow)
- Real app icons (cv2, extraction)
- Advanced navigation (q-learning)
- Performance monitoring
- Hybrid execution

Labs Features (via _labs):
- Experimental features exposed via HA addon config UI
- Opt-in, disabled by default
- Isolated from core functionality
- Environment variables prefixed with LABS_

Example Labs:
- flow_consolidation: Batches flows targeting same app
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
        # Default flags (core features)
        self._flags = {
            "ml_enabled": self._get_env_bool("ML_ENABLED", False),
            "ml_training": self._get_env_bool("ML_TRAINING", False),
            "real_icons_enabled": self._get_env_bool("ENABLE_REAL_ICONS", True),
            "advanced_navigation": self._get_env_bool("ADVANCED_NAVIGATION", False),
            "hybrid_execution": self._get_env_bool("HYBRID_EXECUTION", True),
            "performance_monitoring": self._get_env_bool(
                "PERFORMANCE_MONITORING", True
            ),
        }

        # Labs flags (experimental features - separate namespace)
        # Labs features are disabled by default and opt-in via HA addon config
        self._labs = {
            # Flow consolidation - batches flows targeting same app/screens
            # Env var: LABS_FLOW_CONSOLIDATION (with FLOW_CONSOLIDATION as fallback)
            "flow_consolidation": self._get_env_bool(
                "LABS_FLOW_CONSOLIDATION",
                self._get_env_bool("FLOW_CONSOLIDATION", False)  # Backward compat
            ),
        }

        # Labs-specific configuration
        self._labs_config = {
            "flow_consolidation": {
                "window_seconds": int(os.environ.get("LABS_CONSOLIDATION_WINDOW",
                                      os.environ.get("CONSOLIDATION_WINDOW_SECONDS", "30"))),
                "minimum_savings_threshold": int(os.environ.get("LABS_CONSOLIDATION_MIN_SAVINGS",
                                                 os.environ.get("MINIMUM_SAVINGS_THRESHOLD", "5"))),
                "max_batch_size": int(os.environ.get("LABS_CONSOLIDATION_MAX_BATCH",
                                      os.environ.get("MAX_CONSOLIDATION_BATCH", "10"))),
            },
        }

        # Log active flags
        active_features = [f for f, enabled in self._flags.items() if enabled]
        disabled_features = [f for f, enabled in self._flags.items() if not enabled]

        logger.info(f"[FeatureManager] Enabled features: {active_features}")
        if disabled_features:
            logger.info(f"[FeatureManager] Disabled features: {disabled_features}")

        # Log labs status
        enabled_labs = [k for k, v in self._labs.items() if v]
        if enabled_labs:
            logger.info(f"[FeatureManager] Labs enabled: {enabled_labs}")

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

    def is_lab_enabled(self, lab_name: str) -> bool:
        """Check if a labs feature is enabled"""
        return self._labs.get(lab_name, False)

    def get_lab_config(self, lab_name: str) -> Dict[str, Any]:
        """Get configuration for a labs feature"""
        return self._labs_config.get(lab_name, {}).copy()

    def get_all_labs(self) -> Dict[str, bool]:
        """Get all labs feature states"""
        return self._labs.copy()

    def get_consolidation_config(self) -> Dict[str, Any]:
        """Get flow consolidation configuration (legacy, use get_lab_config instead)"""
        return self.get_lab_config("flow_consolidation")


# Singleton instance
_feature_manager = None


def get_feature_manager() -> FeatureManager:
    """Get or create singleton FeatureManager"""
    global _feature_manager
    if _feature_manager is None:
        _feature_manager = FeatureManager()
    return _feature_manager
