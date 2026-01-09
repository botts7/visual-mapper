"""
Screenshot Stitcher Overlap Module

Contains overlap detection and image comparison methods:
- detect_fixed_top_height: Detect fixed header height
- detect_fixed_bottom_height: Detect fixed footer height
- find_overlap_by_image: Template matching for scroll detection
- find_overlap_offset: OpenCV-based template matching
- detect_overlap_between_captures: Multi-strip overlap validation
- compare_images: Structural similarity comparison
- compare_image_regions: Simple region comparison
"""

import logging
import numpy as np
from typing import Tuple, Optional
from PIL import Image

logger = logging.getLogger(__name__)

# Optional cv2 import - fall back to PIL-only methods if not available
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("OpenCV not available in overlap module, using PIL-only methods")


class OverlapDetector:
    """Detects overlap between screenshots for stitching."""

    def __init__(self, fixed_element_threshold: float = 0.98, match_threshold: float = 0.75):
        """
        Initialize overlap detector.

        Args:
            fixed_element_threshold: Similarity threshold for fixed element detection
            match_threshold: Minimum match quality threshold for template matching
        """
        self.fixed_element_threshold = fixed_element_threshold
        self.match_threshold = match_threshold

    def detect_fixed_top_height(self, img1: Image.Image, img2: Image.Image) -> int:
        """
        Detect the height of fixed top elements (like app headers, status bar)
        by comparing the top portions of two screenshots.

        Handles:
        - Regular apps with status bar + app header (~80-120px)
        - Minimal header apps (~24-50px, just status bar)
        - Fullscreen apps (0px fixed header)
        - Gesture navigation with thin hints

        Returns:
            Height in pixels of the fixed top element, or 0 if none detected
        """
        try:
            width, height = img1.size

            # Start small to detect fullscreen apps and minimal headers
            # Use smaller step size for precision
            step_size = 15
            last_similar_height = 0

            # Check top portions in increments starting from 10px
            for check_height in range(10, min(300, height // 4), step_size):
                # Extract top portions
                top1 = img1.crop((0, 0, width, check_height))
                top2 = img2.crop((0, 0, width, check_height))

                # Compare them
                similarity = self.compare_image_regions(top1, top2)

                if similarity >= self.fixed_element_threshold:
                    # This region is identical - it's part of fixed header
                    last_similar_height = check_height
                else:
                    # Found where content differs - fixed element ends here
                    if last_similar_height > 0:
                        logger.info(f"  Detected fixed top element: {last_similar_height}px")
                        return last_similar_height
                    else:
                        # Even first check was different - fullscreen app with no fixed header
                        logger.info(f"  No fixed top element detected (fullscreen app)")
                        return 0

            # If we checked all and they were all similar, use last known similar height
            if last_similar_height > 0:
                logger.info(f"  Detected fixed top element: {last_similar_height}px (max checked)")
                return last_similar_height

            # No fixed header detected
            return 0

        except Exception as e:
            logger.warning(f"  Fixed top element detection failed: {e}")
            return 0

    def detect_fixed_bottom_height(self, img1: Image.Image, img2: Image.Image) -> int:
        """
        Detect the height of fixed bottom elements (like navigation bars)
        by comparing the bottom portions of two screenshots.

        Handles:
        - Standard apps with nav bar (~48-150px)
        - Fullscreen apps (0px footer)
        - Gesture navigation (~20px hint bar)

        Returns:
            Height in pixels of the fixed bottom element, or 0 if none detected
        """
        try:
            width, height = img1.size

            # Use smaller step size for more accurate detection
            step_size = 10
            last_similar_height = 0

            # Check bottom portions in small increments
            # Start from VERY small (10px) to detect even gesture nav hint bars
            # This allows detecting fullscreen apps with 0px footer
            for check_height in range(10, min(300, height // 3), step_size):
                # Extract bottom portions
                bottom1 = img1.crop((0, height - check_height, width, height))
                bottom2 = img2.crop((0, height - check_height, width, height))

                # Compare them
                similarity = self.compare_image_regions(bottom1, bottom2)

                if similarity >= self.fixed_element_threshold:
                    # This region is still fixed (identical)
                    last_similar_height = check_height
                else:
                    # Found where content starts to differ
                    # Fixed footer is everything that was still similar
                    if last_similar_height > 0:
                        logger.info(f"  Detected fixed footer: {last_similar_height}px (diff at {check_height}px)")
                        return last_similar_height
                    else:
                        # No fixed footer at all - likely fullscreen app
                        logger.info(f"  No fixed footer detected (fullscreen app?)")
                        return 0

            # If we checked up to max and everything was similar, return a reasonable estimate
            # Add some buffer since we might have stopped just before the transition
            if last_similar_height > 0:
                result = min(last_similar_height + 20, 200)
                logger.info(f"  Fixed footer (all similar): {result}px")
                return result

            # Nothing was similar - fullscreen or dynamic content at bottom
            logger.info(f"  No fixed footer (dynamic bottom content)")
            return 0

        except Exception as e:
            logger.warning(f"  Fixed element detection failed: {e}")
            return 0  # Assume no footer on error - safer for fullscreen apps

    def find_overlap_by_image(self, img1: Image.Image, img2: Image.Image, screen_height: int) -> int:
        """
        Find scroll offset by matching the bottom of img1 with the top of img2.
        Uses template matching on a strip from img1's bottom.

        Returns:
            scroll_offset in pixels (how much content moved between captures)
        """
        try:
            width = img1.size[0]
            img1_height = img1.size[1]

            # Convert to numpy arrays and ensure RGB (not RGBA)
            arr1 = np.array(img1.convert('RGB'))
            arr2 = np.array(img2.convert('RGB'))

            # Take a strip from the MIDDLE portion of img1 (avoiding header and footer)
            # This strip should appear somewhere in img2 after scrolling
            strip_height = 100  # Use 100px strip for matching
            # For accumulated images, use middle of the LAST screen_height portion
            if img1_height > screen_height:
                # Use middle of the bottom screen-worth of content
                strip_start = img1_height - screen_height + int(screen_height * 0.4)
            else:
                # Single screen - use middle area
                strip_start = int(screen_height * 0.4)
            strip_start = max(200, min(strip_start, img1_height - 300))  # Bounds check
            strip_end = strip_start + strip_height

            strip = arr1[strip_start:strip_end, :, :]
            logger.info(f"  Template matching: strip from y={strip_start}-{strip_end} in img1")

            # Search for this strip in img2 (skip header area)
            search_start = 80  # Skip status bar
            search_end = screen_height - 100  # Leave room for search

            best_match_y = -1
            best_match_score = 0

            # Slide the template down img2 and find best match
            for y in range(search_start, search_end - strip_height, 10):  # Step by 10 for speed
                region = arr2[y:y + strip_height, :, :]

                # Calculate similarity (simple mean absolute difference)
                diff = np.abs(strip.astype(float) - region.astype(float))
                similarity = 1.0 - (np.mean(diff) / 255.0)

                if similarity > best_match_score:
                    best_match_score = similarity
                    best_match_y = y

            if best_match_score > 0.85:  # Good match threshold
                # scroll_offset = where strip was in img1 - where it is in img2
                scroll_offset = strip_start - best_match_y
                logger.info(f"  Template match found: y={best_match_y} in img2, score={best_match_score:.3f}")
                logger.info(f"  Calculated scroll_offset: {scroll_offset}px")

                if scroll_offset > 0:
                    return scroll_offset

            # Fallback: assume ~50% scroll based on typical swipe distance
            fallback = int(screen_height * 0.5)
            logger.warning(f"  Template matching failed (best score: {best_match_score:.3f}). Using fallback: {fallback}px")
            return fallback

        except Exception as e:
            logger.error(f"  Image-based overlap detection failed: {e}")
            return int(screen_height * 0.5)

    def find_overlap_offset(
        self,
        template: Image.Image,
        img2: Image.Image,
        search_height: int
    ) -> Tuple[Optional[int], Optional[float]]:
        """
        Find Y-offset where template appears in img2
        Uses OpenCV template matching with TM_CCOEFF_NORMED (if available)
        Falls back to simple sliding window comparison without cv2

        Args:
            template: Pre-cropped template strip to search for
            img2: Current screenshot to search in
            search_height: Height of region in img2 to search

        Returns:
            Tuple of (Y-offset in pixels, match quality) or (None, None) if no match
        """
        try:
            width2, height2 = img2.size
            template_width, template_height = template.size

            # Extract search region from img2
            actual_search_height = min(search_height, height2)
            search_region = img2.crop((0, 0, width2, actual_search_height))

            # Convert PIL to numpy arrays
            template_np = np.array(template.convert('RGB'))
            search_np = np.array(search_region.convert('RGB'))

            # Convert to grayscale for better matching (using PIL)
            template_gray = np.array(template.convert('L'))
            search_gray = np.array(search_region.convert('L'))

            if CV2_AVAILABLE:
                # Use OpenCV template matching
                result = cv2.matchTemplate(search_gray, template_gray, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                offset_y = max_loc[1]

                # Try REVERSE direction - swap template and search
                if max_val < 0.9 and template_height < search_gray.shape[0]:
                    reverse_template = search_gray[:template_height, :]
                    result_rev = cv2.matchTemplate(search_gray, reverse_template, cv2.TM_CCOEFF_NORMED)
                    _, rev_max_val, _, rev_max_loc = cv2.minMaxLoc(result_rev)

                    logger.info(f"  Reverse match: y={rev_max_loc[1]}, conf={rev_max_val:.3f} (forward was {max_val:.3f})")

                    if rev_max_val > max_val + 0.1 and rev_max_loc[1] > 50:
                        offset_y = rev_max_loc[1]
                        max_val = rev_max_val
                        logger.info(f"  Using reverse match (gradient-compensated)")

                # Try EDGE-BASED matching if still weak
                if max_val < 0.85:
                    template_edges = cv2.Canny(template_gray, 50, 150)
                    search_edges = cv2.Canny(search_gray, 50, 150)
                    result_edges = cv2.matchTemplate(search_edges, template_edges, cv2.TM_CCOEFF_NORMED)
                    _, edge_max_val, _, edge_max_loc = cv2.minMaxLoc(result_edges)
                    edge_y = edge_max_loc[1]

                    logger.info(f"  Edge-based match: y={edge_y}, conf={edge_max_val:.3f} (grayscale was {max_val:.3f})")

                    if edge_y > 50 and abs(edge_y - offset_y) < 200:
                        if edge_max_val > max_val or max_val < 0.7:
                            offset_y = edge_y
                            max_val = edge_max_val
                            logger.info(f"  Using edge-based detection (better for gradient backgrounds)")
                    else:
                        logger.info(f"  Edge result rejected (y={edge_y} too close to 0 or too different from grayscale={offset_y})")
            else:
                # PIL-only fallback: simple sliding window comparison
                logger.info("  Using PIL-only template matching (cv2 not available)")
                best_y = 0
                max_val = 0.0

                # Slide template down search region
                for y in range(0, actual_search_height - template_height, 5):
                    region = search_gray[y:y + template_height, :]
                    if region.shape != template_gray.shape:
                        continue

                    # Calculate normalized correlation
                    diff = np.abs(template_gray.astype(float) - region.astype(float))
                    similarity = 1.0 - (np.mean(diff) / 255.0)

                    if similarity > max_val:
                        max_val = similarity
                        best_y = y

                offset_y = best_y

            # Quality check
            if max_val < self.match_threshold:
                logger.warning(f"  Low match quality: {max_val:.3f} (threshold: {self.match_threshold})")

            logger.info(f"  Template match: y={offset_y}, confidence={max_val:.3f}")

            return offset_y, max_val

        except Exception as e:
            logger.error(f"  Template matching failed: {e}")
            import traceback
            traceback.print_exc()
            return None, None

    def detect_overlap_between_captures(
        self,
        img1: Image.Image,
        img2: Image.Image,
        screen_height: int,
        known_scroll: int
    ) -> Tuple[int, int]:
        """
        Detect where new content starts in img2 by template matching with img1.
        Both images should be RAW captures (same size as screen).

        The key insight: after scrolling DOWN by X pixels, content moves UP.
        So content at y=Y in img1 appears at y=Y-X in img2.
        The overlap region is: content at y=(screen-X) to y=screen in img1
        appears at y=0 to y=X in img2 (roughly, accounting for fixed elements).

        Returns:
            Tuple of (new_content_start, detected_footer)
            - new_content_start: Y position in img2 where new content starts
            - detected_footer: The detected fixed footer height for this app
        """
        try:
            width = img1.size[0]

            # Detect fixed footer by comparing bottom regions
            fixed_footer = self.detect_fixed_bottom_height(img1, img2)
            # Apply reasonable bounds based on what's possible:
            # - Fullscreen apps: 0px footer
            # - Gesture nav: ~20px (just hint bar)
            # - 3-button nav: ~48px
            # - Nav + app bar: ~100-150px
            # - Large footers (Netflix, etc): 150-220px
            # - Max: 250px (more is likely mis-detection)
            #
            # IMPORTANT: Don't enforce a minimum - fullscreen/gesture apps may have 0px footer
            if fixed_footer < 0:
                fixed_footer = 0
            elif fixed_footer > 250:
                logger.info(f"  Footer detection capped: {fixed_footer}px -> 250px (likely mis-detection)")
                fixed_footer = 250  # Cap to prevent over-cropping
            logger.info(f"  Using fixed_footer={fixed_footer}px (0=fullscreen/gesture possible)")

            # Detect fixed header
            fixed_header = self.detect_fixed_top_height(img1, img2)
            # Apply reasonable bounds for header
            # - Fullscreen apps: 0px header (no status bar)
            # - Normal apps: 24px status bar + 56px app bar = ~80px
            # - Max: 120px (more is likely mis-detection)
            #
            # IMPORTANT: Don't enforce large minimum - fullscreen apps may have small/no header
            if fixed_header < 0:
                fixed_header = 0
            elif fixed_header > 120:
                logger.info(f"  Header detection capped: {fixed_header}px -> 120px (likely mis-detection)")
                fixed_header = 120
            logger.info(f"  Detected fixed_header={fixed_header}px (0=fullscreen possible)")

            # SIMPLE CALCULATION based on scroll distance
            # After scrolling known_scroll pixels, the overlap is:
            # screen_height - known_scroll - fixed_header - fixed_footer (scrollable area that's still visible)
            # New content starts at: screen_height - known_scroll (approximately)

            # But we need to account for fixed header - content below header shifts
            # Actual new content start = screen_height - known_scroll
            # But since header is fixed, we take content starting from there

            # ROW-BY-ROW comparison to find EXACT overlap point
            # Take a strip from img1 (just above footer) and find it in img2

            scrollable_height = screen_height - fixed_header - fixed_footer
            logger.info(f"  Scrollable height: {scrollable_height}px (header={fixed_header}, footer={fixed_footer})")

            # QUICK CHECK: If images are very similar, page barely scrolled
            img_similarity = self.compare_images(img1, img2)
            logger.info(f"  OVERLAP: Full image similarity: {img_similarity:.3f}")
            if img_similarity > 0.90:
                # Images are very similar - page barely moved
                # Use a very conservative scroll estimate
                estimated_scroll = int(known_scroll * (1.0 - img_similarity) * 5)
                if estimated_scroll < 50:
                    estimated_scroll = 50  # At least 50px
                logger.info(f"  OVERLAP: Images very similar! Using conservative scroll: {estimated_scroll}px")
                new_content_start = screen_height - fixed_footer - estimated_scroll
                return (new_content_start, fixed_footer)

            # Convert images to numpy for fast comparison
            arr1 = np.array(img1.convert('RGB'))
            arr2 = np.array(img2.convert('RGB'))

            strip_height = 60  # Strip height for matching
            scrollable_start = fixed_header
            scrollable_end = screen_height - fixed_footer

            # MULTI-STRIP VALIDATION: Use multiple strips from the LOWER portion
            # of scrollable area (avoiding fixed headers/titles at top)
            strip_positions = [
                int(scrollable_height * 0.60),  # 60% down
                int(scrollable_height * 0.75),  # 75% down
                int(scrollable_height * 0.88),  # 88% down (near bottom)
            ]

            scroll_estimates = []
            for rel_pos in strip_positions:
                strip_y = scrollable_start + rel_pos
                strip_y = max(scrollable_start + 50, min(strip_y, scrollable_end - strip_height - 20))

                reference_strip = arr1[strip_y:strip_y + strip_height, :, :]

                # Search for this strip in img2
                # Use known_scroll to guide search range
                expected_y = strip_y - known_scroll if known_scroll > 0 else strip_y // 2

                # Search in full scrollable range if expected is out of bounds
                search_start = max(fixed_header, expected_y - 300)
                search_end = min(scrollable_end - strip_height, expected_y + 300)

                if expected_y < fixed_header or expected_y > scrollable_end:
                    search_start = fixed_header
                    search_end = min(scrollable_end - strip_height, fixed_header + 500)

                best_y = -1
                best_score = 0

                for y in range(search_start, search_end, 5):
                    candidate = arr2[y:y + strip_height, :, :]
                    diff = np.abs(reference_strip.astype(float) - candidate.astype(float))
                    similarity = 1.0 - (np.mean(diff) / 255.0)
                    if similarity > best_score:
                        best_score = similarity
                        best_y = y

                if best_score > 0.9 and best_y > 0:
                    detected_scroll = strip_y - best_y
                    scroll_estimates.append((strip_y, best_y, detected_scroll, best_score))

            # Analyze scroll estimates for consistency
            if len(scroll_estimates) >= 2:
                scrolls = [e[2] for e in scroll_estimates]
                scroll_range = max(scrolls) - min(scrolls)
                avg_scroll = sum(scrolls) / len(scrolls)

                logger.info(f"  MULTI-STRIP: {len(scroll_estimates)} strips, scrolls={scrolls}, range={scroll_range}px")

                # If strips disagree significantly (>100px range), match is unreliable
                if scroll_range > 100:
                    min_scroll = min(scrolls)
                    max_scroll = max(scrolls)
                    logger.info(f"  MULTI-STRIP: Inconsistent matches! min={min_scroll}, max={max_scroll}")

                    # Strategy: lower scroll -> higher new_content_start -> LESS content added
                    # To avoid duplicates, we want to add LESS content when unsure
                    # So use the MINIMUM scroll (most conservative)
                    #
                    # BUT: if some scrolls are consistent with previous captures (~530px)
                    # and others are much lower, the lower ones might be false matches
                    #
                    # Check if any scroll is close to previous captures' pattern
                    # Consistent = within 100px of commanded OR within 15% of previous captures (~530px)
                    # Use a tighter bound for consistency
                    expected_scroll = known_scroll if known_scroll > 0 else 450
                    consistent_scrolls = [s for s in scrolls if abs(s - expected_scroll) < 100 or (s >= 450 and s <= 600)]
                    low_scrolls = [s for s in scrolls if s < expected_scroll * 0.6]

                    if consistent_scrolls and low_scrolls:
                        # Mixed: some consistent, some low - this often happens at end of page
                        # Filter out values > commanded (likely false matches in repetitive content)
                        valid_scrolls = [s for s in scrolls if s <= known_scroll * 1.2]
                        if valid_scrolls:
                            # Use median of valid scrolls (more robust than min)
                            valid_scrolls.sort()
                            actual_scroll = valid_scrolls[len(valid_scrolls) // 2]
                            logger.info(f"  MULTI-STRIP: Mixed results, using median of valid: {actual_scroll}px (valid: {valid_scrolls}, all: {scrolls})")
                        else:
                            actual_scroll = min(scrolls)
                            logger.info(f"  MULTI-STRIP: No valid scrolls, using minimum: {actual_scroll}px (all: {scrolls})")
                    elif low_scrolls and not consistent_scrolls:
                        # All scrolls are low - page likely at bottom
                        actual_scroll = min(scrolls)
                        logger.info(f"  MULTI-STRIP: All low scrolls, page at bottom: {actual_scroll}px")
                    else:
                        # General inconsistency with mostly high values - use median
                        actual_scroll = int(sorted(scrolls)[len(scrolls)//2])
                        logger.info(f"  MULTI-STRIP: Using median: {actual_scroll}px")

                    best_match_y = -1
                    best_match_score = 0.5  # Mark as unreliable
                else:
                    # Use the median scroll estimate
                    actual_scroll = int(sorted(scrolls)[len(scrolls)//2])
                    best_match_y = scroll_estimates[0][1]
                    best_match_score = max(e[3] for e in scroll_estimates)
            elif len(scroll_estimates) == 1:
                actual_scroll = scroll_estimates[0][2]
                best_match_y = scroll_estimates[0][1]
                best_match_score = scroll_estimates[0][3]
            else:
                # No good matches found
                actual_scroll = known_scroll
                best_match_y = -1
                best_match_score = 0

            logger.info(f"  OVERLAP: Best match y={best_match_y}, similarity={best_match_score:.3f}")

            if best_match_score > 0.92:
                # Good match found - actual_scroll already calculated by multi-strip above
                logger.info(f"  OVERLAP: actual_scroll={actual_scroll}px (commanded: {known_scroll}px)")

                # SANITY CHECK: If actual_scroll is very different from known_scroll,
                # the page might have hit the bottom or the match might be wrong
                scroll_diff = abs(actual_scroll - known_scroll) if known_scroll > 0 else 0
                if known_scroll > 0 and actual_scroll > 0:
                    scroll_ratio = actual_scroll / known_scroll
                else:
                    scroll_ratio = 1.0

                # Check for suspicious results
                if scroll_diff > 100:
                    # More than 100px difference from commanded scroll - suspicious
                    logger.info(f"  SUSPICIOUS: actual_scroll={actual_scroll} differs from commanded={known_scroll} by {scroll_diff}px")

                    # If actual scroll is LESS than expected, page might have hit bottom
                    # OR the row matching found a wrong match in repetitive content
                    if actual_scroll < known_scroll * 0.75:
                        # Page scrolled less than 75% of commanded - likely at end of page
                        logger.info(f"  END-OF-PAGE: actual_scroll ({actual_scroll}) < 75% of commanded ({known_scroll})")

                        # Trust the actual scroll detection - it tells us exactly how much we scrolled
                        # new_content_start = where content in current capture starts being NEW
                        # If we scrolled X pixels, content at y=(screen_height - footer - X) is the boundary
                        new_content_start = screen_height - fixed_footer - actual_scroll

                        if new_content_start < fixed_header:
                            new_content_start = fixed_header
                        logger.info(f"  END-OF-PAGE: Using actual scroll, new_content_start={new_content_start}")
                        return (new_content_start, fixed_footer)

                    # If actual scroll is MORE than expected, match might be wrong
                    if actual_scroll > known_scroll * 1.5:
                        logger.warning(f"  MATCH possibly wrong: actual > 1.5x commanded, using commanded scroll")
                        # Use commanded scroll as fallback
                        new_content_start = screen_height - fixed_footer - known_scroll
                        if new_content_start < fixed_header:
                            new_content_start = fixed_header
                        logger.info(f"  Fallback new content starts at y={new_content_start}")
                        return (new_content_start, fixed_footer)

                # New content in img2 starts where img1's bottom content ends
                # img1 content ended at (screen_height - fixed_footer)
                # This appears at (screen_height - fixed_footer - actual_scroll) in img2's coordinate
                # So new content starts just after this point
                new_content_start = screen_height - fixed_footer - actual_scroll
                logger.info(f"  OVERLAP: new_content_start = {screen_height} - {fixed_footer} - {actual_scroll} = {new_content_start}")
                if new_content_start < fixed_header:
                    new_content_start = fixed_header
                    logger.info(f"  OVERLAP: Clamped to fixed_header={fixed_header}")
                return (new_content_start, fixed_footer)
            else:
                # best_match_score is low, but we might still have actual_scroll from multi-strip
                # Use actual_scroll if it was calculated, otherwise fall back to known_scroll
                if actual_scroll != known_scroll:
                    # Multi-strip gave us a value - use it
                    logger.info(f"  OVERLAP: Using multi-strip actual_scroll={actual_scroll} (score was low)")
                    new_content_start = screen_height - fixed_footer - actual_scroll
                    logger.info(f"  OVERLAP: new_content_start = {screen_height} - {fixed_footer} - {actual_scroll} = {new_content_start}")
                    if new_content_start < fixed_header:
                        new_content_start = fixed_header
                    return (new_content_start, fixed_footer)

                # Fallback to calculation
                logger.warning(f"  Row matching weak ({best_match_score:.3f}), using calculated fallback")
                overlap = scrollable_height - known_scroll
                if overlap < 0:
                    overlap = 0
                new_content_start = fixed_header + overlap
                logger.info(f"  Fallback new_content_start={new_content_start}")
                return (new_content_start, fixed_footer)

        except Exception as e:
            logger.error(f"  Overlap detection failed: {e}")
            import traceback
            traceback.print_exc()
            # Ultimate fallback - use 100px as safe footer estimate
            return (screen_height - known_scroll, 100)

    def compare_images(self, img1: Image.Image, img2: Image.Image) -> float:
        """
        Compare two images for similarity using structural comparison.

        Returns:
            Float between 0.0 (completely different) and 1.0 (identical)
        """
        try:
            # Convert to numpy arrays
            arr1 = np.array(img1)
            arr2 = np.array(img2)

            # Ensure same size
            if arr1.shape != arr2.shape:
                return 0.0

            # Convert to grayscale for comparison
            if len(arr1.shape) == 3:
                # Use PIL for grayscale conversion (works without cv2)
                gray1 = np.array(img1.convert('L'))
                gray2 = np.array(img2.convert('L'))
            else:
                gray1, gray2 = arr1, arr2

            # Calculate Structural Similarity Index (SSIM-like)
            # Using normalized cross-correlation
            mean1 = np.mean(gray1)
            mean2 = np.mean(gray2)

            # Subtract means
            norm1 = gray1.astype(np.float64) - mean1
            norm2 = gray2.astype(np.float64) - mean2

            # Calculate correlation
            numerator = np.sum(norm1 * norm2)
            denominator = np.sqrt(np.sum(norm1**2) * np.sum(norm2**2))

            if denominator == 0:
                return 1.0 if numerator == 0 else 0.0

            correlation = numerator / denominator

            # Normalize to 0-1 range (correlation is -1 to 1)
            similarity = (correlation + 1) / 2

            return float(similarity)

        except Exception as e:
            logger.error(f"  Image comparison failed: {e}")
            return 0.0

    def compare_image_regions(self, img1: Image.Image, img2: Image.Image) -> float:
        """Compare two image regions for similarity"""
        try:
            arr1 = np.array(img1)
            arr2 = np.array(img2)

            if arr1.shape != arr2.shape:
                return 0.0

            # Simple pixel comparison for regions
            diff = np.abs(arr1.astype(np.float64) - arr2.astype(np.float64))
            max_diff = 255.0 * arr1.size
            similarity = 1.0 - (np.sum(diff) / max_diff)

            return float(similarity)
        except:
            return 0.0
