"""
Visual Mapper - App Label Extractor (Phase 8 Enhancement)
Extracts real, human-readable app names from Android packages

Features:
- Uses dumpsys to get app labels
- Caches results for performance
- Fallback to package-based names
"""

import logging
import re
from typing import Optional, Dict
from pathlib import Path
import json

logger = logging.getLogger(__name__)


class AppLabelExtractor:
    """
    Extracts real app labels from Android devices

    Strategy:
    1. Use dumpsys package to get app label (fastest, no APK pull needed)
    2. Cache results locally
    3. Fallback to package-based name if extraction fails
    """

    def __init__(self, cache_dir: str = "data/app-labels", enable_extraction: bool = True):
        """
        Initialize label extractor

        Args:
            cache_dir: Directory to cache app labels
            enable_extraction: Enable real label extraction (if False, uses package-based names)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.enable_extraction = enable_extraction

        # In-memory cache for current session
        self.memory_cache: Dict[str, str] = {}

        # Load disk cache
        self._load_cache()

        logger.info(f"[AppLabelExtractor] Initialized (cache: {cache_dir}, enabled: {enable_extraction})")

    def _load_cache(self):
        """Load label cache from disk"""
        cache_file = self.cache_dir / "labels.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    self.memory_cache = json.load(f)
                logger.info(f"[AppLabelExtractor] Loaded {len(self.memory_cache)} cached labels")
            except Exception as e:
                logger.warning(f"[AppLabelExtractor] Failed to load cache: {e}")
                self.memory_cache = {}

    def _save_cache(self):
        """Save label cache to disk"""
        cache_file = self.cache_dir / "labels.json"
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.memory_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[AppLabelExtractor] Failed to save cache: {e}")

    async def get_label(self, shell_func, package_name: str) -> str:
        """
        Get app label (cached or extracted)

        Args:
            shell_func: Async function to execute shell commands (e.g., conn.shell)
            package_name: App package name

        Returns:
            Human-readable app label
        """
        if not self.enable_extraction:
            return self._fallback_label(package_name)

        # Check memory cache first
        if package_name in self.memory_cache:
            logger.debug(f"[AppLabelExtractor] Cache hit for {package_name}: {self.memory_cache[package_name]}")
            return self.memory_cache[package_name]

        # Extract from device
        try:
            label = await self._extract_label_from_dumpsys(shell_func, package_name)
            if label:
                # Save to cache
                self.memory_cache[package_name] = label
                self._save_cache()
                logger.info(f"[AppLabelExtractor] Extracted label for {package_name}: {label}")
                return label
        except Exception as e:
            logger.debug(f"[AppLabelExtractor] Failed to extract label for {package_name}: {e}")

        # Fallback to package-based name
        fallback = self._fallback_label(package_name)
        self.memory_cache[package_name] = fallback
        return fallback

    async def get_labels_batch(self, shell_func, package_names: list) -> Dict[str, str]:
        """
        Get app labels for multiple packages efficiently

        Args:
            shell_func: Async function to execute shell commands
            package_names: List of package names

        Returns:
            Dict mapping package_name -> label
        """
        results = {}

        # Use cmd package to get labels efficiently (Android 8+)
        # This is much faster than dumpsys for each package
        try:
            # Build a shell script that extracts all labels at once
            script = "for pkg in " + " ".join(package_names[:50]) + "; do "  # Batch first 50
            script += "label=$(cmd package resolve-activity --brief -c android.intent.category.LAUNCHER $pkg 2>/dev/null | head -1); "
            script += "[ -n \"$label\" ] && echo \"$pkg|$label\"; "
            script += "done"

            output = await shell_func(script)

            for line in output.strip().split('\n'):
                if '|' in line:
                    package, label = line.split('|', 1)
                    if label and label != package:
                        results[package.strip()] = label.strip()

        except Exception as e:
            logger.debug(f"[AppLabelExtractor] Batch extraction failed, falling back: {e}")

        # For packages without labels, try dumpsys individually (but limit to avoid slowdown)
        for package_name in package_names[:20]:  # Only try first 20 to avoid timeout
            if package_name not in results:
                label = await self._extract_label_from_dumpsys(shell_func, package_name)
                if label:
                    results[package_name] = label

        return results

    async def _extract_label_from_dumpsys(self, shell_func, package_name: str) -> Optional[str]:
        """
        Extract app label using dumpsys package

        Example output:
        Packages:
          Package [com.android.chrome] (abc123):
            userId=10123
            pkg=Package{...}
            versionName=120.0.6099.144
            applicationInfo=ApplicationInfo{...}
              labelRes=0x7f14001e label=Chrome
              ...
        """
        try:
            # Try faster method first: pm dump
            output = await shell_func(f"pm dump {package_name} | grep -E '(label=|versionName)' | head -5")

            if output:
                # Look for "label=" in output
                label_match = re.search(r'\blabel=([^\s\n]+)', output)
                if label_match:
                    label = label_match.group(1)
                    # Clean up label (remove quotes if present)
                    label = label.strip('"').strip("'")
                    if label and not label.startswith('0x'):  # Ignore resource references
                        return label

            return None

        except Exception as e:
            logger.debug(f"[AppLabelExtractor] dumpsys extraction failed: {e}")
            return None

    def _fallback_label(self, package_name: str) -> str:
        """
        Generate fallback label from package name

        Strategy:
        - Take the last segment of package name
        - Title case it
        - Handle common patterns (e.g., remove trailing numbers)

        Examples:
        - com.android.chrome -> Chrome
        - com.google.android.gms -> Gms
        - com.activitymanager -> Activitymanager
        """
        # Split by dots and take last segment
        segments = package_name.split('.')
        label = segments[-1] if segments else package_name

        # Title case
        label = label.title()

        return label

    def clear_cache(self, package_name: Optional[str] = None):
        """
        Clear label cache

        Args:
            package_name: Clear specific package (if None, clears all)
        """
        if package_name:
            if package_name in self.memory_cache:
                del self.memory_cache[package_name]
                self._save_cache()
                logger.info(f"[AppLabelExtractor] Cleared cache for {package_name}")
        else:
            # Clear all cached labels
            self.memory_cache.clear()
            self._save_cache()
            logger.info("[AppLabelExtractor] Cleared all label cache")

    def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        return {
            "total_labels": len(self.memory_cache),
            "cache_dir": str(self.cache_dir)
        }
