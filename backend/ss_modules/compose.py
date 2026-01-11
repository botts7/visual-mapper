"""
Screenshot Stitcher Compose Module

Contains image stitching and composition methods:
- stitch_by_elements: Main stitch orchestrator using known scroll distances
- stitch_two_captures_simple: Simple stitch with pre-detected overlap
- stitch_two_captures_deterministic: Image-based stitch using template matching
- stitch_two_captures: Tracing paper method with hybrid offset detection
- stitch_images_smart: Smart stitching using UI elements
- stitch_images: Basic pixel-based stitching
"""

import logging
import re
from typing import Tuple, Optional, List
from PIL import Image

logger = logging.getLogger(__name__)


class ImageComposer:
    """Composes multiple screenshots into a single stitched image."""

    def __init__(
        self,
        overlap_detector,
        element_analyzer,
        remove_duplicates_fn,
        feature_stitcher=None,
    ):
        """
        Initialize image composer.

        Args:
            overlap_detector: OverlapDetector instance for overlap detection
            element_analyzer: ElementAnalyzer instance for element analysis
            remove_duplicates_fn: Function to remove consecutive duplicates
            feature_stitcher: Optional FeatureBasedStitcher for ORB matching
        """
        self.overlap_detector = overlap_detector
        self.element_analyzer = element_analyzer
        self.remove_duplicates_fn = remove_duplicates_fn
        self.feature_stitcher = feature_stitcher

    def stitch_by_elements(
        self,
        captures: list,  # List of (image, elements, _unused, known_scroll) tuples
        screen_height: int,
    ) -> Tuple[Image.Image, list, dict]:
        """
        DETERMINISTIC STITCH method - uses KNOWN scroll distances:
        For each capture after the first:
        1. We know exactly how much was scrolled (known_scroll)
        2. New content = bottom portion of new capture (height - overlap)
        3. Overlap = screen_height - known_scroll - fixed_header

        Returns:
            Tuple of (stitched_image, combined_elements, stitch_info)
            - combined_elements: All elements with adjusted Y positions for the stitched image
            - stitch_info: Dict with scroll_offset, header_height, footer_height, etc.
        """
        if not captures:
            raise ValueError("No captures to stitch")

        # Handle different tuple lengths (3 or 4 elements)
        def unpack_capture(cap):
            if len(cap) >= 4:
                return cap[0], cap[1], cap[2], cap[3]
            else:
                return cap[0], cap[1], cap[2] if len(cap) > 2 else 0, 0

        if len(captures) == 1:
            img, elements, _, _ = unpack_capture(captures[0])
            return (
                img,
                elements,
                {"scroll_offset": 0, "header_height": 0, "footer_height": 0},
            )

        # For 2+ captures, stitch iteratively
        # Start with first capture as base
        img, elements, _, _ = unpack_capture(captures[0])
        result_img = img
        result_elements = elements
        width, height = result_img.size
        total_stitch_info = {
            "scroll_offset": 0,
            "header_height": 0,
            "footer_height": 0,
            "stitch_count": len(captures) - 1,
        }

        # Track the LAST RAW capture for template matching
        prev_raw_img = img
        current_result_height = height

        # Stitch each subsequent capture to the result
        for i in range(1, len(captures)):
            img_next, elements_next, precalc_first_new_y, known_scroll = unpack_capture(
                captures[i]
            )
            is_last = i == len(captures) - 1

            # For element-based short page stitching, use TRACING PAPER method
            # This matches the stable stitcher's approach
            if precalc_first_new_y > 0 and len(captures) == 2:
                logger.info(f"  === TRACING PAPER STITCHING (element-based) ===")
                result_img, result_elements, stitch_info = self.stitch_tracing_paper(
                    result_img, result_elements, img_next, elements_next, screen_height
                )
                continue

            logger.info(
                f"  === IMAGE-BASED STITCHING: Capture {i}/{len(captures)-1} ==="
            )

            # Check if we have a pre-calculated first_new_y (from bookend element matching)
            if precalc_first_new_y > 0:
                # Use the element-based calculation (more reliable for bookend approach)
                detected_new_content_start = precalc_first_new_y
                # Still detect footer for proper cropping
                detected_footer = self.overlap_detector.detect_fixed_bottom_height(
                    prev_raw_img, img_next
                )
                if detected_footer > 250:
                    detected_footer = 250
                logger.info(
                    f"  Using pre-calculated new_content_start={detected_new_content_start} (element-based)"
                )
            else:
                # Do image-based template matching for sequential scroll approach
                detected_new_content_start, detected_footer = (
                    self.overlap_detector.detect_overlap_between_captures(
                        prev_raw_img, img_next, height, known_scroll
                    )
                )
            logger.info(
                f"  Detected new content starts at y={detected_new_content_start}, footer={detected_footer}px"
            )

            # CRITICAL: When we crop footer from first capture, adjust new_content_start accordingly
            # First capture ends at (screen_height - footer), not screen_height
            # Content at that position in cap1 is at y = (screen_height - footer - known_scroll)
            # BUT: Skip this for element-based overlap (precalc_first_new_y > 0) - the element
            # calculation already accounts for positions correctly
            if current_result_height == screen_height and precalc_first_new_y == 0:
                footer_adjusted_start = screen_height - detected_footer - known_scroll
                if footer_adjusted_start < 0:
                    footer_adjusted_start = 0
                logger.info(
                    f"  Footer adjustment: first cap ends at {screen_height - detected_footer}, in cap2 this is y={footer_adjusted_start}"
                )
                # Use the LOWER value to ensure no gap
                if detected_new_content_start > footer_adjusted_start:
                    logger.info(
                        f"  Adjusting new_content_start from {detected_new_content_start} to {footer_adjusted_start} (footer compensation)"
                    )
                    detected_new_content_start = footer_adjusted_start

            # For last capture, do DIRECT comparison between accumulated image and new capture
            # BUT ONLY if we don't have reliable element-based overlap (precalc_first_new_y > 0)
            # Element-based overlap is more reliable for short pages with gradient backgrounds
            if is_last:
                if precalc_first_new_y > 0:
                    # We have element-based overlap - trust it, don't override with template matching
                    # This is important for apps with gradient backgrounds (BYD, Netflix) where
                    # template matching can be confused by color changes
                    logger.info(f"  === LAST CAPTURE - USING ELEMENT-BASED OVERLAP ===")
                    logger.info(
                        f"  Element-based new_content_start={detected_new_content_start} (trusted)"
                    )
                else:
                    logger.info(f"  === LAST CAPTURE - DIRECT OVERLAP DETECTION ===")

                    # Take template from bottom of accumulated image, but ABOVE the footer
                    # Important: if there's a fixed footer, taking template from very bottom
                    # would match the footer (which doesn't move) and give wrong results
                    acc_height = result_img.size[1]
                    template_height = 100
                    # Account for footer - take template from CONTENT area, not footer
                    footer_margin = (
                        detected_footer + 100
                    )  # Detected footer + safety margin
                    template_y = acc_height - template_height - footer_margin
                    logger.info(
                        f"  Template from y={template_y}-{template_y+template_height} (footer={detected_footer}px, acc_height={acc_height})"
                    )

                    if template_y > 0:
                        template = result_img.crop(
                            (
                                0,
                                template_y,
                                result_img.size[0],
                                template_y + template_height,
                            )
                        )

                        # Search for this template in the new capture
                        match_y, confidence = self.overlap_detector.find_overlap_offset(
                            template, img_next, screen_height
                        )

                        if match_y is not None and confidence and confidence > 0.8:
                            # Found where accumulated content appears in new capture
                            # New content starts AFTER this match
                            direct_new_content_start = match_y + template_height
                            logger.info(
                                f"  DIRECT MATCH: template found at y={match_y} (conf={confidence:.3f})"
                            )

                            # === TRACEPAPER REFINEMENT ===
                            # Fine-tune position by sliding template in small range to find best match
                            import numpy as np

                            # Ensure both are RGB (not RGBA) to avoid shape mismatch
                            template_arr = np.array(template.convert("RGB"))
                            img_arr = np.array(img_next.convert("RGB"))

                            best_y = match_y
                            best_score = 0
                            search_range = 30  # Search +/- 30 pixels

                            for test_y in range(
                                max(0, match_y - search_range),
                                min(
                                    screen_height - template_height,
                                    match_y + search_range + 1,
                                ),
                            ):
                                test_region = img_arr[
                                    test_y : test_y + template_height, :, :
                                ]
                                if test_region.shape[0] == template_height:
                                    score = (
                                        np.sum(template_arr == test_region)
                                        / template_arr.size
                                    )
                                    if score > best_score:
                                        best_score = score
                                        best_y = test_y

                            if best_y != match_y:
                                logger.info(
                                    f"  TRACEPAPER: Refined y={match_y} -> y={best_y} (score {best_score*100:.1f}%)"
                                )
                                direct_new_content_start = best_y + template_height

                            logger.info(
                                f"  DIRECT: new_content_start={direct_new_content_start} (vs scroll-based={detected_new_content_start})"
                            )

                            # For LAST capture, be CONSERVATIVE to avoid duplicates
                            # If direct and scroll-based differ significantly, use the HIGHER value
                            # (higher y = less new content = safer, avoids duplicating)
                            diff = abs(
                                direct_new_content_start - detected_new_content_start
                            )
                            if diff > 150:
                                # Big discrepancy - template might have matched similar content (e.g., episode thumbnails)
                                # Use the MORE CONSERVATIVE value (higher y = less content included)
                                conservative_start = max(
                                    direct_new_content_start, detected_new_content_start
                                )
                                logger.info(
                                    f"  LAST CAPTURE: Big diff ({diff}px), using conservative {conservative_start} (was direct={direct_new_content_start})"
                                )
                                detected_new_content_start = conservative_start
                            else:
                                # Small diff - trust the direct detection
                                detected_new_content_start = direct_new_content_start
                        else:
                            logger.info(
                                f"  DIRECT MATCH failed (conf={confidence}), using scroll-based={detected_new_content_start}"
                            )

                expected_new_content = screen_height - detected_new_content_start
                logger.info(
                    f"  is_last=True, final new_content_start={detected_new_content_start}, new_content={expected_new_content}px"
                )

            result_img, result_elements, stitch_info = self.stitch_two_captures_simple(
                result_img,
                result_elements,
                img_next,
                elements_next,
                screen_height,
                detected_new_content_start,  # Use detected position
                current_result_height,
                detected_footer,  # Pass detected footer - no hardcoding!
                is_last_capture=is_last,
            )

            # Update for next iteration
            prev_raw_img = img_next
            current_result_height = result_img.size[1]

            # Accumulate stitch info
            total_stitch_info["scroll_offset"] += stitch_info.get("scroll_offset", 0)
            if is_last:
                total_stitch_info["header_height"] = stitch_info.get("header_height", 0)
                total_stitch_info["footer_height"] = stitch_info.get("footer_height", 0)

        # Final summary
        final_w, final_h = result_img.size
        logger.info(f"  === STITCH SUMMARY ===")
        logger.info(
            f"  Final image: {final_w}x{final_h}px from {len(captures)} captures"
        )
        logger.info(f"  Total elements: {len(result_elements)}")

        # === POST-PROCESS: Remove consecutive duplicate content ===
        # Scan entire image for sections that repeat immediately after themselves
        result_img, result_elements = self.remove_duplicates_fn(
            result_img, result_elements, screen_height
        )

        return result_img, result_elements, total_stitch_info

    def stitch_tracing_paper(
        self,
        img1: Image.Image,
        elements1: list,
        img2: Image.Image,
        elements2: list,
        screen_height: int,
    ) -> Tuple[Image.Image, list, dict]:
        """
        TRACING PAPER stitch method - matches the stable stitcher's approach.

        Logic:
        1. Find common elements between C1 and C2
        2. Calculate scroll offset: where element is in C1 vs C2
        3. C1 contributes: y=0 to y=(scroll_offset + fixed_header)
        4. C2 contributes: y=fixed_header to y=height, pasted at (scroll_offset + fixed_header)

        Returns:
            Tuple of (stitched_image, combined_elements, stitch_info)
        """
        width, height = img1.size

        logger.info(f"  Screen: {width}x{height}")

        # Step 1: Build element position maps (fingerprint -> y_center)
        elem1_positions = {}
        for elem in elements1:
            fp = self.element_analyzer.get_element_fingerprint(elem)
            if fp:
                y_center = self.element_analyzer.get_element_y_center(elem)
                y_bottom = self.element_analyzer.get_element_bottom(elem)
                elem1_positions[fp] = (y_center, y_bottom)

        elem2_positions = {}
        for elem in elements2:
            fp = self.element_analyzer.get_element_fingerprint(elem)
            if fp:
                y_center = self.element_analyzer.get_element_y_center(elem)
                y_bottom = self.element_analyzer.get_element_bottom(elem)
                elem2_positions[fp] = (y_center, y_bottom)

        logger.info(
            f"  C1: {len(elem1_positions)} elements, C2: {len(elem2_positions)} elements"
        )

        # Step 2: Find common elements (excluding fixed header/footer regions)
        header_limit = height * 0.15
        footer_limit = height * 0.80

        common_elements = []
        for fp in elem1_positions:
            if fp in elem2_positions:
                y1_center = elem1_positions[fp][0]
                y2_center = elem2_positions[fp][0]

                # Element must be in scrollable region in BOTH captures
                if y1_center > header_limit and y2_center < footer_limit:
                    offset = y1_center - y2_center
                    common_elements.append((fp, y1_center, y2_center, offset))
                    if len(common_elements) <= 10:  # Log first 10
                        logger.info(
                            f"    Common: '{fp[:35]}' C1_y={int(y1_center)}, C2_y={int(y2_center)}, offset={int(offset)}"
                        )

        if not common_elements:
            logger.warning("  No common elements found! Checking all elements...")
            for fp in elem1_positions:
                if fp in elem2_positions:
                    y1 = elem1_positions[fp][0]
                    y2 = elem2_positions[fp][0]
                    offset = y1 - y2
                    if offset > 50:
                        common_elements.append((fp, y1, y2, offset))

        if not common_elements:
            logger.error("  Still no common elements! Using default 50% overlap")
            scroll_offset = int(height * 0.5)
        else:
            # Filter out elements with offset=0 or near 0 (full-screen containers)
            meaningful_offsets = [c[3] for c in common_elements if c[3] > 100]

            if meaningful_offsets:
                meaningful_offsets.sort()
                scroll_offset = int(meaningful_offsets[len(meaningful_offsets) // 2])
                logger.info(
                    f"  Median scroll offset: {scroll_offset}px (from {len(meaningful_offsets)} moving elements)"
                )
            else:
                all_offsets = [c[3] for c in common_elements]
                scroll_offset = max(all_offsets) if all_offsets else int(height * 0.5)
                logger.info(f"  Using max offset: {scroll_offset}px")

        # Step 3: Detect fixed header height
        fixed_header_height = self.overlap_detector.detect_fixed_top_height(img1, img2)
        if fixed_header_height < 80:
            fixed_header_height = 80  # Minimum Android status bar

        logger.info(f"  Fixed header height: {fixed_header_height}px")

        # Step 4: Calculate crop and paste positions
        # C1 contributes: y=0 to y=(scroll_offset + fixed_header)
        # C2 contributes: y=fixed_header to y=height, pasted at (scroll_offset + fixed_header)
        c1_crop_bottom = scroll_offset + fixed_header_height
        c2_crop_top = fixed_header_height
        c2_crop_bottom = height
        c2_height_used = c2_crop_bottom - c2_crop_top
        c2_paste_y = scroll_offset + fixed_header_height

        total_height = c2_paste_y + c2_height_used

        logger.info(
            f"  C1: crop y=0-{c1_crop_bottom} ({c1_crop_bottom}px), paste at y=0"
        )
        logger.info(
            f"  C2: crop y={c2_crop_top}-{c2_crop_bottom} ({c2_height_used}px), paste at y={c2_paste_y}"
        )
        logger.info(f"  Final size: {width}x{total_height}")

        # Step 5: Create stitched image
        stitched = Image.new("RGB", (width, total_height))

        # Paste C1's top portion
        if c1_crop_bottom > 0:
            c1_cropped = img1.crop((0, 0, width, c1_crop_bottom))
            stitched.paste(c1_cropped, (0, 0))
            logger.info(f"  Pasted C1 ({c1_cropped.size[1]}px) at y=0")

        # Paste C2 without its header
        c2_cropped = img2.crop((0, c2_crop_top, width, c2_crop_bottom))
        stitched.paste(c2_cropped, (0, c2_paste_y))
        logger.info(f"  Pasted C2 ({c2_cropped.size[1]}px) at y={c2_paste_y}")

        # Step 6: Combine elements from both captures
        combined_elements = []

        # Add elements from C1 within its crop region
        for elem in elements1:
            bounds = elem.get("bounds", {})
            if isinstance(bounds, dict):
                elem_y = bounds.get("y", 0)
                if elem_y < c1_crop_bottom:
                    combined_elements.append(elem.copy())

        # Add elements from C2 within its crop region, with adjusted Y
        for elem in elements2:
            bounds = elem.get("bounds", {})
            if isinstance(bounds, dict):
                elem_y = bounds.get("y", 0)
                if c2_crop_top <= elem_y < c2_crop_bottom:
                    adjusted_elem = elem.copy()
                    adjusted_bounds = bounds.copy()
                    adjusted_bounds["y"] = (elem_y - c2_crop_top) + c2_paste_y
                    adjusted_elem["bounds"] = adjusted_bounds
                    combined_elements.append(adjusted_elem)

        logger.info(f"  Combined {len(combined_elements)} elements")

        return (
            stitched,
            combined_elements,
            {
                "scroll_offset": scroll_offset,
                "header_height": fixed_header_height,
                "footer_height": 0,
            },
        )

    def stitch_two_captures_simple(
        self,
        accumulated_img: Image.Image,
        accumulated_elements: list,
        new_img: Image.Image,
        new_elements: list,
        screen_height: int,
        new_content_start: int,  # Where new content starts in new_img
        current_result_height: int,
        detected_footer: int,  # Dynamically detected footer height
        is_last_capture: bool = True,
    ) -> Tuple[Image.Image, list, dict]:
        """
        Simple stitch - just paste new content at the detected position.
        new_content_start is already determined by template matching.
        detected_footer is dynamically detected from image comparison.
        """
        width = accumulated_img.size[0]
        acc_height = accumulated_img.size[1]

        # Use the dynamically detected footer - no hardcoding!
        fixed_footer = detected_footer
        logger.info(f"  Using dynamically detected footer: {fixed_footer}px")

        # Where to stop in new_img
        new_content_end = (
            screen_height if is_last_capture else (screen_height - fixed_footer)
        )
        new_content_height = new_content_end - new_content_start

        if new_content_height <= 0:
            logger.warning(f"  No new content! height={new_content_height}")
            return accumulated_img, accumulated_elements, {"scroll_offset": 0}

        # Skip captures with very little new content (likely duplicates at end of page)
        MIN_NEW_CONTENT = 50  # At least 50px of new content needed
        if new_content_height < MIN_NEW_CONTENT and not is_last_capture:
            logger.warning(
                f"  Too little new content ({new_content_height}px < {MIN_NEW_CONTENT}px), skipping this capture"
            )
            return accumulated_img, accumulated_elements, {"scroll_offset": 0}

        # For first stitch (acc is single screen), ALWAYS crop footer from accumulated image
        # The last capture will provide the footer, so we don't want it duplicated
        if acc_height == screen_height:
            paste_y = acc_height - fixed_footer
        else:
            paste_y = acc_height

        # Total height
        total_height = paste_y + new_content_height

        logger.info(
            f"  Stitching: new content y={new_content_start}-{new_content_end} ({new_content_height}px)"
        )
        logger.info(f"  Paste at y={paste_y}, total height={total_height}px")

        # Create stitched image
        stitched = Image.new("RGB", (width, total_height))

        # Paste accumulated image (crop footer if first stitch)
        if acc_height == screen_height:
            # First stitch - crop footer from accumulated image
            cropped_acc = accumulated_img.crop((0, 0, width, paste_y))
            stitched.paste(cropped_acc, (0, 0))
        else:
            stitched.paste(accumulated_img, (0, 0))

        # Paste new content (no gradient blending - it was causing black lines)
        new_content = new_img.crop((0, new_content_start, width, new_content_end))

        # DISABLED: Gradient blending was causing artifacts (black lines, cut text)
        # The overlap detection is accurate enough that we don't need blending
        blend_height = 0  # Disabled - was 10
        if False and paste_y > blend_height and new_content_height > blend_height:
            import numpy as np

            # Get the overlap region from both images (ensure RGB, not RGBA)
            if acc_height == screen_height:
                acc_bottom = np.array(
                    accumulated_img.crop(
                        (0, paste_y - blend_height, width, paste_y)
                    ).convert("RGB")
                )
            else:
                acc_bottom = np.array(
                    stitched.crop((0, paste_y - blend_height, width, paste_y)).convert(
                        "RGB"
                    )
                )
            new_top = np.array(
                new_content.convert("RGB").crop((0, 0, width, blend_height))
            )

            # Create gradient blend
            for i in range(blend_height):
                alpha = i / blend_height  # 0 at top (acc), 1 at bottom (new)
                blended_row = (1 - alpha) * acc_bottom[i] + alpha * new_top[i]
                acc_bottom[i] = blended_row.astype(np.uint8)

            # Paste blended region (replaces the area just before paste_y)
            blended_img = Image.fromarray(acc_bottom)
            stitched.paste(blended_img, (0, paste_y - blend_height))

            # Paste rest of new content starting at paste_y (NOT paste_y + blend_height!)
            if new_content_height > blend_height:
                rest_content = new_content.crop(
                    (0, blend_height, width, new_content_height)
                )
                stitched.paste(
                    rest_content, (0, paste_y)
                )  # Fixed: was paste_y + blend_height

            logger.info(f"  Applied {blend_height}px gradient blend at seam")
        else:
            stitched.paste(new_content, (0, paste_y))

        # === STITCH QUALITY CHECK ===
        # Compare the seam region to detect misalignment
        import numpy as np

        seam_height = 20  # Compare 20px around the seam
        if paste_y > seam_height and new_content_start > 0:
            # Get the bottom of accumulated image (above where we paste)
            if acc_height == screen_height:
                acc_seam = accumulated_img.crop(
                    (0, paste_y - seam_height, width, paste_y)
                )
            else:
                acc_seam = accumulated_img.crop(
                    (0, paste_y - seam_height, width, paste_y)
                )

            # Get the top of new content (what we're pasting)
            new_seam = new_img.crop(
                (0, new_content_start, width, new_content_start + seam_height)
            )

            # Compare - if very different, the stitch might be misaligned (ensure RGB)
            acc_arr = np.array(acc_seam.convert("RGB"))
            new_arr = np.array(new_seam.convert("RGB"))
            seam_similarity = np.sum(acc_arr == new_arr) / acc_arr.size

            if seam_similarity < 0.5:
                logger.warning(
                    f"  ⚠️ STITCH QUALITY: Seam similarity only {seam_similarity*100:.1f}% - possible misalignment!"
                )
            else:
                logger.info(
                    f"  Stitch quality OK: seam similarity {seam_similarity*100:.1f}%"
                )

        # === Combine elements ===
        combined_elements = []

        # Elements from accumulated image (filter out footer area if first stitch)
        for elem in accumulated_elements:
            y_center = self.element_analyzer.get_element_y_center(elem)
            if y_center <= paste_y:
                combined_elements.append(elem.copy())

        # Y adjustment for element positions
        # Use template-based adjustment (same as image stitching) for perfect alignment
        y_adjustment = paste_y - new_content_start
        logger.info(f"  Element Y adjustment: {y_adjustment}px (template-based)")

        # Elements from new image (only in new content region)
        # Use inclusive boundary check to avoid missing elements at edges
        for elem in new_elements:
            y_center = self.element_analyzer.get_element_y_center(elem)
            if new_content_start <= y_center <= new_content_end:
                adjusted_elem = elem.copy()
                bounds = adjusted_elem.get("bounds", {})
                if isinstance(bounds, dict):
                    adjusted_elem["bounds"] = {
                        "x": bounds.get("x", 0),
                        "y": bounds.get("y", 0) + y_adjustment,
                        "width": bounds.get("width", 0),
                        "height": bounds.get("height", 0),
                    }
                combined_elements.append(adjusted_elem)

        return stitched, combined_elements, {"scroll_offset": new_content_start}

    def stitch_two_captures_deterministic(
        self,
        img1: Image.Image,
        elements1: list,
        img2: Image.Image,
        elements2: list,
        screen_height: int,
        known_scroll: int,  # KNOWN scroll distance from swipe (used as fallback)
        current_result_height: int,
        is_last_capture: bool = True,
    ) -> Tuple[Image.Image, list, dict]:
        """
        IMAGE-BASED stitch using visual template matching.
        Works for ANY app by detecting actual overlap visually.

        Logic:
        1. Detect fixed footer by comparing bottom regions of img1 and img2
        2. Detect fixed header by comparing top regions
        3. Extract template strip from img1 (above footer)
        4. Find where this template appears in img2 using template matching
        5. New content starts AFTER the matched region
        """
        width = img1.size[0]
        img1_height = img1.size[1]

        logger.info(
            f"  IMAGE-BASED STITCH: screen={screen_height}, result={img1_height}, is_last={is_last_capture}"
        )

        # === STEP 1: Detect fixed header by comparing top regions ===
        fixed_header = (
            self.overlap_detector.detect_fixed_top_height(img1, img2)
            if img1_height == screen_height
            else 0
        )
        if fixed_header < 50:
            fixed_header = 50  # Minimum header (status bar)
        logger.info(f"  Detected fixed header: {fixed_header}px")

        # === STEP 2: Detect fixed footer by comparing bottom regions ===
        # Only detect for raw screenshots (not accumulated images)
        if img1_height == screen_height:
            fixed_footer = self.overlap_detector.detect_fixed_bottom_height(img1, img2)
            if fixed_footer < 50:
                fixed_footer = 100  # Minimum footer (nav bar)
        else:
            fixed_footer = 100  # Use reasonable default for accumulated images

        effective_footer = 0 if is_last_capture else fixed_footer
        logger.info(
            f"  Detected fixed footer: {fixed_footer}px, effective={effective_footer}px"
        )

        # === STEP 3: Find actual overlap using template matching ===
        # Extract a template strip from img1 (above the footer area)
        template_height = 80  # Use 80px strip for reliable matching

        # For accumulated images, get template from the bottom portion
        if img1_height > screen_height:
            # Use content from the last screen-worth, avoiding footer
            template_top = img1_height - fixed_footer - template_height - 30
        else:
            # For first image, use content above footer
            template_top = screen_height - fixed_footer - template_height - 30

        template_top = max(fixed_header + 50, template_top)  # Ensure we're below header
        template_bottom = template_top + template_height

        logger.info(
            f"  Template extraction: y={template_top}-{template_bottom} ({template_height}px)"
        )

        # Extract template from img1
        template = img1.crop((0, template_top, width, template_bottom))

        # Search for template in img2
        match_y, confidence = self.overlap_detector.find_overlap_offset(
            template, img2, screen_height - fixed_header  # Search in most of img2
        )

        # Calculate new_content_start based on match
        if match_y is not None and confidence and confidence > 0.7:
            # Good match found - new content starts after the matched region
            new_content_start = match_y + template_height
            logger.info(
                f"  Template matched at y={match_y} (confidence={confidence:.3f})"
            )
            logger.info(
                f"  New content starts at y={new_content_start} (from image matching)"
            )
        else:
            # Fallback to calculated overlap
            logger.warning(
                f"  Template match failed (conf={confidence}), using calculated fallback"
            )
            scrollable_height = screen_height - fixed_header - fixed_footer
            overlap = max(0, scrollable_height - known_scroll)
            new_content_start = fixed_header + overlap
            logger.info(
                f"  Fallback: new_content_start={new_content_start} (calculated)"
            )

        # Where to stop - include footer only on last capture
        new_content_end = (
            screen_height if is_last_capture else (screen_height - effective_footer)
        )
        new_content_height = new_content_end - new_content_start

        if new_content_height <= 0:
            logger.warning(f"  No new content! new_content_height={new_content_height}")
            return (
                img1,
                elements1,
                {
                    "scroll_offset": known_scroll,
                    "header_height": fixed_header,
                    "footer_height": effective_footer,
                },
            )

        # Calculate paste position: bottom of img1
        # On first stitch, crop footer from img1 too
        if img1_height == screen_height and not is_last_capture:
            paste_y = img1_height - fixed_footer  # First image - remove its footer
        else:
            paste_y = img1_height  # Accumulated image - footer already removed

        # Total height of stitched image
        total_height = paste_y + new_content_height

        logger.info(
            f"  New content: y={new_content_start}-{new_content_end} ({new_content_height}px)"
        )
        logger.info(f"  Paste at y={paste_y}, Total height={total_height}px")
        logger.info(
            f"  DEBUG: img1 crop y=0-{paste_y}, img2 crop y={new_content_start}-{new_content_end}"
        )
        logger.info(
            f"  DEBUG: Strip {1 if img1_height == screen_height else 'N'} contributes {paste_y}px from img1, {new_content_height}px from img2"
        )

        # Create canvas and stitch
        stitched = Image.new("RGB", (width, total_height))

        # Paste img1 (crop footer on first stitch, except if it's also the last)
        if img1_height == screen_height and fixed_footer > 0 and not is_last_capture:
            # First image - crop out its footer
            img1_cropped = img1.crop((0, 0, width, img1_height - fixed_footer))
            stitched.paste(img1_cropped, (0, 0))
            logger.info(f"  Pasted img1 cropped (removed {fixed_footer}px footer)")
        else:
            stitched.paste(img1, (0, 0))
            logger.info(f"  Pasted img1 full ({img1_height}px)")

        # Paste new content from img2
        new_content = img2.crop((0, new_content_start, width, new_content_end))
        stitched.paste(new_content, (0, paste_y))

        logger.info(
            f"  Pasted img1 at y=0, new content ({new_content_height}px) at y={paste_y}"
        )

        # === BUILD COMBINED ELEMENTS ===
        combined_elements = []
        fingerprint_y_positions = {}

        # Determine the crop boundary for img1 elements
        # If we cropped the footer from img1, exclude elements in that region
        img1_crop_bottom = paste_y  # Elements above this Y are included

        # Add elements from img1 (only those within the included region)
        img1_included = 0
        img1_excluded = 0
        for elem in elements1:
            y_center = self.element_analyzer.get_element_y_center(elem)

            # Skip elements that are in the cropped footer region
            if y_center > img1_crop_bottom:
                img1_excluded += 1
                continue

            fp = self.element_analyzer.get_element_fingerprint(elem)
            combined_elements.append(elem.copy())
            img1_included += 1
            if fp:
                if fp not in fingerprint_y_positions:
                    fingerprint_y_positions[fp] = []
                fingerprint_y_positions[fp].append(y_center)

        logger.info(
            f"  Elements from img1: {img1_included} included, {img1_excluded} excluded (in footer)"
        )

        # Add NEW elements from img2 (only those in the new content region)
        y_adjustment = paste_y - new_content_start
        added_count = 0

        for elem in elements2:
            fp = self.element_analyzer.get_element_fingerprint(elem)
            y_center = self.element_analyzer.get_element_y_center(elem)

            # Only include elements in the NEW content region
            if y_center < new_content_start or y_center > new_content_end:
                continue

            # Check for position-aware duplicates
            adjusted_y = y_center + y_adjustment
            if fp and fp in fingerprint_y_positions:
                is_dup = any(
                    abs(existing_y - adjusted_y) < 50
                    for existing_y in fingerprint_y_positions[fp]
                )
                if is_dup:
                    continue

            # Create adjusted element
            adjusted_elem = elem.copy()
            bounds = adjusted_elem.get("bounds", {})
            if isinstance(bounds, dict):
                adjusted_elem["bounds"] = {
                    "x": bounds.get("x", 0),
                    "y": bounds.get("y", 0) + y_adjustment,
                    "width": bounds.get("width", 0),
                    "height": bounds.get("height", 0),
                }
            elif isinstance(bounds, str):
                match = re.findall(r"\[(\d+),(\d+)\]", bounds)
                if len(match) >= 2:
                    x1, y1 = int(match[0][0]), int(match[0][1])
                    x2, y2 = int(match[1][0]), int(match[1][1])
                    adjusted_elem["bounds"] = (
                        f"[{x1},{y1 + y_adjustment}][{x2},{y2 + y_adjustment}]"
                    )

            combined_elements.append(adjusted_elem)
            added_count += 1
            if fp:
                if fp not in fingerprint_y_positions:
                    fingerprint_y_positions[fp] = []
                fingerprint_y_positions[fp].append(adjusted_y)

        logger.info(
            f"  Combined: {len(combined_elements)} elements (added {added_count} from img2)"
        )
        logger.info(
            f"  DEBUG: Element Y adjustment = {y_adjustment}px (paste_y={paste_y} - crop_top={new_content_start})"
        )

        # Log sample element bounds for debugging
        if added_count > 0 and combined_elements:
            sample = combined_elements[-1]  # Last added element
            sample_bounds = sample.get("bounds", {})
            sample_text = sample.get("text", "")[:30]
            logger.info(
                f"  DEBUG: Sample element '{sample_text}' bounds={sample_bounds}"
            )

        stitch_info = {
            "scroll_offset": known_scroll,
            "header_height": fixed_header,
            "footer_height": effective_footer,
            "new_content_start": new_content_start,
            "paste_y": paste_y,
            "is_last": is_last_capture,
        }

        return stitched, combined_elements, stitch_info

    def stitch_two_captures(
        self,
        img1: Image.Image,
        elements1: list,
        img2: Image.Image,
        elements2: list,
        screen_height: int,
        prev_raw_elements: list,  # Raw elements from previous capture for scroll offset calc
        current_result_height: int,  # Current height of accumulated result
        is_last_capture: bool = True,
    ) -> Tuple[Image.Image, list, dict]:
        """
        Stitch two captures together using the tracing paper method.
        img1 is the accumulated result (may be taller than screen_height)
        img2 is the new capture (screen_height tall)
        prev_raw_elements are the RAW elements from the previous capture (for scroll offset calc)
        """
        width = img1.size[0]
        height = screen_height  # Use screen height for calculations
        img1_height = img1.size[1]

        logger.info(f"  Screen: {width}x{height}, Accumulated: {img1_height}px")

        # Step 0: Detect fixed footer using two raw screen-height images
        # For iterative stitching, we need to crop img1 to bottom screen_height pixels
        if img1_height > height:
            # Get bottom portion of accumulated image for footer detection
            img1_bottom = img1.crop((0, img1_height - height, width, img1_height))
            fixed_footer_height = self.overlap_detector.detect_fixed_bottom_height(
                img1_bottom, img2
            )
        else:
            fixed_footer_height = self.overlap_detector.detect_fixed_bottom_height(
                img1, img2
            )
        logger.info(f"  Fixed footer height: {fixed_footer_height}px")

        # Step 1: Build element position maps using RAW elements for scroll offset calculation
        # Use prev_raw_elements (RAW positions) instead of elements1 (which may be adjusted)
        # fingerprint -> (y_center, y_top, y_bottom)
        prev_positions = {}
        for elem in prev_raw_elements:
            fp = self.element_analyzer.get_element_fingerprint(elem)
            if fp:
                y_center = self.element_analyzer.get_element_y_center(elem)
                y_bottom = self.element_analyzer.get_element_bottom(elem)
                y_top = y_center - (y_bottom - y_center)  # Estimate top
                prev_positions[fp] = (y_center, y_top, y_bottom)

        elem2_positions = {}
        for elem in elements2:
            fp = self.element_analyzer.get_element_fingerprint(elem)
            if fp:
                y_center = self.element_analyzer.get_element_y_center(elem)
                y_bottom = self.element_analyzer.get_element_bottom(elem)
                y_top = y_center - (y_bottom - y_center)
                elem2_positions[fp] = (y_center, y_top, y_bottom)

        logger.info(
            f"  Prev: {len(prev_positions)} elements, New: {len(elem2_positions)} elements"
        )

        # Step 2: Find common elements (excluding fixed header/footer regions)
        # Header region: top 15% of screen
        # Footer region: bottom 20% of screen
        header_limit = height * 0.15
        footer_limit = height * 0.80

        common_elements = []
        for fp in prev_positions:
            if fp in elem2_positions:
                y1_center = prev_positions[fp][0]
                y2_center = elem2_positions[fp][0]

                # Element must be in scrollable region in BOTH captures
                # In prev: should be in middle-to-bottom (scrollable content)
                # In new: should be in top-to-middle (scrolled up content)
                if y1_center > header_limit and y2_center < footer_limit:
                    offset = y1_center - y2_center
                    common_elements.append((fp, y1_center, y2_center, offset))
                    logger.info(
                        f"    Common: '{fp[:35]}' prev_y={int(y1_center)}, new_y={int(y2_center)}, offset={int(offset)}"
                    )

        if not common_elements:
            logger.warning("  No common elements found! Checking all elements...")
            # Try with looser constraints
            for fp in prev_positions:
                if fp in elem2_positions:
                    y1 = prev_positions[fp][0]
                    y2 = elem2_positions[fp][0]
                    offset = y1 - y2
                    # Only consider positive offsets (scrolled down)
                    if offset > 50:
                        common_elements.append((fp, y1, y2, offset))
                        logger.info(f"    Found: '{fp[:35]}' offset={int(offset)}")

        # === HYBRID APPROACH: 3 methods, cross-validate ===
        # 1. Element-based (fastest, semantic)
        # 2. ORB feature matching (robust to rendering variations)
        # 3. Template matching (fallback)

        element_offset = None
        feature_offset = None
        template_offset = None

        # Method 1: Element-based offset
        if common_elements:
            meaningful_offsets = [c[3] for c in common_elements if 100 < c[3] < height]
            if meaningful_offsets:
                meaningful_offsets.sort()
                element_offset = int(meaningful_offsets[len(meaningful_offsets) // 2])
                logger.info(
                    f"  [1] Element-based offset: {element_offset}px (from {len(meaningful_offsets)} elements)"
                )

        # Method 2: ORB Feature matching
        if self.feature_stitcher:
            try:
                offset, confidence, debug = (
                    self.feature_stitcher.find_overlap_offset_features(
                        img1, img2, height
                    )
                )
                if offset and confidence > 0.5:
                    feature_offset = offset
                    logger.info(
                        f"  [2] ORB feature offset: {feature_offset}px (confidence: {confidence:.2f})"
                    )
                else:
                    logger.info(
                        f"  [2] ORB feature matching: low confidence ({confidence:.2f})"
                    )
            except Exception as e:
                logger.warning(f"  [2] ORB feature matching failed: {e}")

        # Method 3: Template matching
        template_offset = self.overlap_detector.find_overlap_by_image(
            img1, img2, height
        )
        logger.info(f"  [3] Template offset: {template_offset}px")

        # Cross-validate and pick best result
        # Lower minimum to accept smaller scrolls (device may scroll less than expected)
        min_valid = int(height * 0.08)  # At least 8% scroll (~100px on 1200px screen)
        max_valid = int(height * 0.85)  # At most 85% scroll

        valid_offsets = []
        if element_offset and min_valid < element_offset < max_valid:
            valid_offsets.append(("element", element_offset))
        if feature_offset and min_valid < feature_offset < max_valid:
            valid_offsets.append(("feature", feature_offset))
        if template_offset and min_valid < template_offset < max_valid:
            valid_offsets.append(("template", template_offset))

        logger.info(f"  Valid offsets: {valid_offsets}")

        if len(valid_offsets) >= 2:
            # Multiple methods gave valid results - find consensus
            offsets_values = [v[1] for v in valid_offsets]

            # Check if at least 2 methods agree (within 150px for more tolerance)
            agreeing = []
            for i, (name1, val1) in enumerate(valid_offsets):
                for name2, val2 in valid_offsets[i + 1 :]:
                    if abs(val1 - val2) < 150:
                        agreeing.append((name1, val1))
                        agreeing.append((name2, val2))

            if agreeing:
                # Use average of agreeing methods
                avg_offset = sum(v[1] for v in agreeing) // len(agreeing)
                scroll_offset = avg_offset
                names = list(set(v[0] for v in agreeing))
                logger.info(
                    f"  HYBRID: {names} agree! Using average: {scroll_offset}px"
                )
            else:
                # No agreement - prefer element-based if available (most semantic)
                element_result = next(
                    (v for v in valid_offsets if v[0] == "element"), None
                )
                feature_result = next(
                    (v for v in valid_offsets if v[0] == "feature"), None
                )

                if element_result:
                    scroll_offset = element_result[1]
                    logger.info(
                        f"  HYBRID: No consensus, preferring element-based: {scroll_offset}px"
                    )
                elif feature_result:
                    scroll_offset = feature_result[1]
                    logger.info(
                        f"  HYBRID: No consensus, preferring feature-based: {scroll_offset}px"
                    )
                else:
                    # Use median as last resort
                    offsets_values.sort()
                    scroll_offset = offsets_values[len(offsets_values) // 2]
                    logger.warning(
                        f"  HYBRID: No consensus, using median: {scroll_offset}px"
                    )
        elif len(valid_offsets) == 1:
            scroll_offset = valid_offsets[0][1]
            logger.info(
                f"  HYBRID: Only {valid_offsets[0][0]} valid: {scroll_offset}px"
            )
        else:
            # No method gave valid result - check if element offset exists but was filtered
            if element_offset and element_offset > 50:
                scroll_offset = element_offset
                logger.warning(
                    f"  HYBRID: Using element offset outside normal range: {scroll_offset}px"
                )
            else:
                # Use safe default based on swipe distance
                scroll_offset = int(height * 0.35)  # ~420px, closer to actual scroll
                logger.warning(
                    f"  HYBRID: No valid offset! Using default 35%: {scroll_offset}px"
                )

        # Step 3: Detect fixed header height in C2 (status bar + app header)
        # Find elements that are at y=0 or very top - these are fixed headers
        fixed_header_height = 0
        for fp, (y_center, y_top, y_bottom) in elem2_positions.items():
            # Elements starting at y < 10 are likely fixed headers
            if y_top < 10 and y_bottom < height * 0.15:
                if y_bottom > fixed_header_height:
                    fixed_header_height = int(y_bottom)
                    logger.debug(f"    Header element: {fp[:30]} bottom={y_bottom}")

        # Also check by comparing top portions of both images (should be identical if fixed)
        if fixed_header_height < 50:
            # Use pixel comparison as fallback
            fixed_header_height = self.overlap_detector.detect_fixed_top_height(
                img1, img2
            )

        # Ensure minimum header (at least status bar ~50px)
        fixed_header_height = max(
            fixed_header_height, 80
        )  # Android status + app bar minimum
        logger.info(f"  Fixed header height: {fixed_header_height}px")

        # Step 4: Stitch using tracing paper method
        # For iterative stitching, img1 may be taller than screen_height (accumulated result)
        #
        # scroll_offset = how much content moved between prev and new captures
        # Content at prev_y=Y appears at new_y=(Y - scroll_offset)
        #
        # Logic:
        # - Keep ALL of img1 (the accumulated result)
        # - Calculate the overlap region in img2 (content that's already in img1)
        # - Append ONLY the NEW (non-overlapping) content from img2

        c2_crop_top = fixed_header_height  # CUT OFF the header from img2

        # For img2, the overlap ends at approximately (height - scroll_offset)
        # So new content starts at around that point
        # But we already cropped the header, so adjust accordingly
        #
        # The "overlap zone" in img2 is content that was in the BOTTOM of prev capture
        # After scrolling, that content moved UP by scroll_offset pixels
        # So in img2: overlap is from fixed_header_height to (height - scroll_offset)
        # New content is from (height - scroll_offset) to (height - fixed_footer if not last)

        # Calculate where to paste img2's content
        # The paste position = img1_height - (overlap height in img2)
        # overlap_height_in_img2 = (height - scroll_offset) - fixed_header_height
        # = height - scroll_offset - fixed_header_height
        overlap_in_img2 = height - scroll_offset - fixed_header_height
        if overlap_in_img2 < 0:
            overlap_in_img2 = 0  # No overlap (big scroll)

        c2_paste_y = (
            img1_height - fixed_footer_height
        )  # Paste at bottom of img1 (before footer)

        c2_crop_bottom = height if is_last_capture else height - fixed_footer_height
        c2_height_used = c2_crop_bottom - c2_crop_top

        # New content starts after the overlap
        new_content_start = c2_crop_top + overlap_in_img2
        if new_content_start < c2_crop_top:
            new_content_start = c2_crop_top

        # For simplicity: paste full img2 content (minus header) starting where overlap begins
        # This means some content overlaps, but that's OK - it's the same content
        # The key is to get the paste position right

        # SAFETY: If scroll_offset is 0 or very small, the captures don't actually overlap
        # This can happen if we're stitching non-adjacent captures. Use minimum scroll distance.
        min_scroll = int(
            height * 0.3
        )  # Expect at least 30% scroll between adjacent captures
        if scroll_offset < min_scroll:
            logger.warning(
                f"  Low scroll_offset ({scroll_offset}px < {min_scroll}px) - captures may not overlap!"
            )
            logger.warning(f"  Using minimum scroll_offset to prevent shrinkage")
            scroll_offset = min_scroll
            overlap_in_img2 = height - scroll_offset - fixed_header_height

        # Calculate paste position
        if img1_height == height:
            # First stitch
            c2_paste_y = scroll_offset + fixed_header_height
        else:
            # Iterative stitch - paste at bottom of img1 minus overlap
            c2_paste_y = img1_height - overlap_in_img2 - fixed_footer_height
            if c2_paste_y < img1_height - height:
                c2_paste_y = img1_height - height  # Safety: don't paste too high

        # Ensure paste position is never negative
        if c2_paste_y < 0:
            logger.warning(f"  Negative paste position {c2_paste_y}px! Adjusting to 0")
            c2_paste_y = 0

        # Calculate total height - must be at least as tall as img1
        total_height = max(img1_height, c2_paste_y + c2_height_used)

        logger.info(f"  Img1 height: {img1_height}px, scroll_offset: {scroll_offset}px")
        logger.info(f"  Overlap in img2: {overlap_in_img2}px")
        logger.info(
            f"  C2: crop y={c2_crop_top}-{c2_crop_bottom} ({c2_height_used}px), paste at y={c2_paste_y}"
        )
        logger.info(f"  Final size: {width}x{total_height}")

        # Create canvas and stitch
        stitched = Image.new("RGB", (width, total_height))

        # Paste ALL of img1 (the accumulated result)
        stitched.paste(img1, (0, 0))
        logger.info(f"  Pasted Img1 ({img1_height}px) at y=0")

        # Paste img2 content (minus header) at calculated position
        c2_cropped = img2.crop((0, c2_crop_top, width, c2_crop_bottom))
        stitched.paste(c2_cropped, (0, c2_paste_y))
        logger.info(f"  Pasted Img2 ({c2_cropped.size[1]}px) at y={c2_paste_y}")

        # === BUILD COMBINED ELEMENTS WITH ADJUSTED Y POSITIONS ===
        # Elements from img1: keep ALL (they're already at correct positions)
        # Elements from img2: adjust Y by (c2_paste_y - c2_crop_top), skip header/close duplicates
        combined_elements = []
        # Track fingerprint -> list of Y positions (for position-aware deduplication)
        fingerprint_y_positions = {}  # fp -> list of (y_center_adjusted)

        # Add ALL elements from img1 (accumulated result)
        # For iterative stitching, elements1 already has correct Y positions
        for elem in elements1:
            fp = self.element_analyzer.get_element_fingerprint(elem)
            combined_elements.append(elem.copy())
            if fp:
                y_center = self.element_analyzer.get_element_y_center(elem)
                if fp not in fingerprint_y_positions:
                    fingerprint_y_positions[fp] = []
                fingerprint_y_positions[fp].append(y_center)

        # Add elements from img2 (adjust Y positions, skip header/close duplicates)
        y_adjustment = c2_paste_y - c2_crop_top  # How much to shift img2 elements
        added_count = 0
        skipped_header = 0
        skipped_footer = 0
        skipped_duplicate = 0

        for elem in elements2:
            fp = self.element_analyzer.get_element_fingerprint(elem)
            y_center = self.element_analyzer.get_element_y_center(elem)

            # Skip elements in header region (they were cropped)
            if y_center < c2_crop_top:
                skipped_header += 1
                continue

            # Skip footer elements from img2 if we're not at the last capture
            if not is_last_capture and y_center > (height - fixed_footer_height):
                skipped_footer += 1
                continue

            # Calculate adjusted Y position
            adjusted_y_center = y_center + y_adjustment

            # Position-aware deduplication: skip only if there's an element
            # with same fingerprint at CLOSE Y position (within 50px)
            if fp and fp in fingerprint_y_positions:
                is_duplicate = False
                for existing_y in fingerprint_y_positions[fp]:
                    if abs(existing_y - adjusted_y_center) < 50:
                        is_duplicate = True
                        break
                if is_duplicate:
                    skipped_duplicate += 1
                    continue

            # Create adjusted element
            adjusted_elem = elem.copy()
            bounds = adjusted_elem.get("bounds", {})
            if isinstance(bounds, dict):
                adjusted_elem["bounds"] = {
                    "x": bounds.get("x", 0),
                    "y": bounds.get("y", 0) + y_adjustment,
                    "width": bounds.get("width", 0),
                    "height": bounds.get("height", 0),
                }
            elif isinstance(bounds, str):
                # Parse and adjust "[x1,y1][x2,y2]" format
                match = re.findall(r"\[(\d+),(\d+)\]", bounds)
                if len(match) >= 2:
                    x1, y1 = int(match[0][0]), int(match[0][1])
                    x2, y2 = int(match[1][0]), int(match[1][1])
                    adjusted_elem["bounds"] = (
                        f"[{x1},{y1 + y_adjustment}][{x2},{y2 + y_adjustment}]"
                    )

            combined_elements.append(adjusted_elem)
            added_count += 1
            if fp:
                if fp not in fingerprint_y_positions:
                    fingerprint_y_positions[fp] = []
                fingerprint_y_positions[fp].append(adjusted_y_center)

        logger.info(
            f"  Combined elements: {len(combined_elements)} (Img1: {len(elements1)}, Img2 added: {added_count})"
        )
        logger.info(
            f"  Img2 skipped: header={skipped_header}, footer={skipped_footer}, duplicate={skipped_duplicate}"
        )

        # Build stitch info
        stitch_info = {
            "scroll_offset": scroll_offset,
            "header_height": fixed_header_height,
            "footer_height": fixed_footer_height,
            "c2_crop_top": c2_crop_top,
            "c2_paste_y": c2_paste_y,
            "y_adjustment": y_adjustment,
        }

        return stitched, combined_elements, stitch_info

    def stitch_images_smart(
        self,
        captures: list,  # List of (image, elements) tuples
        overlap_ratio: float,
        screen_height: int,
    ) -> Image.Image:
        """
        Smart stitching using UI elements to determine exact crop boundaries.
        Falls back to pixel-based stitching if element tracking fails.
        """
        if not captures:
            raise ValueError("No captures to stitch")

        if len(captures) == 1:
            return captures[0][0]

        images = [c[0] for c in captures]
        width, height = images[0].size
        overlap_height = int(height * overlap_ratio)

        # Detect fixed bottom element
        fixed_bottom_height = 0
        if len(captures) >= 2:
            fixed_bottom_height = self.overlap_detector.detect_fixed_bottom_height(
                images[0], images[1]
            )

        # Track all seen element fingerprints and their Y positions in final image
        seen_elements = {}  # fingerprint -> max_y_in_final

        # Calculate crop regions using element tracking
        crop_regions = []  # (image, crop_top, crop_bottom)

        for i, (img, elements) in enumerate(captures):
            if i == 0:
                # First image: full content minus fixed footer
                crop_top = 0
                crop_bottom = (
                    height - fixed_bottom_height if fixed_bottom_height > 0 else height
                )

                # Track all elements from first image
                for elem in elements:
                    fp = self.element_analyzer.get_element_fingerprint(elem)
                    if fp:
                        y = self.element_analyzer.get_element_y_center(elem)
                        if y < crop_bottom:  # Only track if above fixed footer
                            seen_elements[fp] = y
            else:
                # Subsequent images: find where new content starts
                prev_img, prev_elements = captures[i - 1]

                # Use element-based calculation
                scroll_amount, confidence = (
                    self.element_analyzer.calculate_scroll_from_elements(
                        prev_elements, elements, height
                    )
                )

                if scroll_amount and confidence > 0.3:
                    # Calculate crop_top based on element positions
                    crop_top = self.element_analyzer.find_new_content_boundary(
                        prev_elements, elements, scroll_amount, height
                    )
                else:
                    # Fallback to pixel-based
                    offset_y, _ = self.overlap_detector.find_overlap_offset(
                        prev_img, img, overlap_height
                    )
                    crop_top = (
                        (offset_y + overlap_height) if offset_y else overlap_height
                    )

                # Ensure we don't crop too much
                crop_top = max(0, min(crop_top, height - 100))

                # For non-final images, crop fixed footer
                if i < len(captures) - 1 and fixed_bottom_height > 0:
                    crop_bottom = height - fixed_bottom_height
                else:
                    crop_bottom = height

                # Track new elements
                for elem in elements:
                    fp = self.element_analyzer.get_element_fingerprint(elem)
                    if fp and fp not in seen_elements:
                        y = self.element_analyzer.get_element_y_center(elem)
                        if crop_top < y < crop_bottom:
                            seen_elements[fp] = y

            crop_regions.append((img, crop_top, crop_bottom))
            logger.debug(
                f"  Image {i}: crop {crop_top}-{crop_bottom} ({crop_bottom - crop_top}px)"
            )

        # Calculate total height
        total_height = sum(cb - ct for _, ct, cb in crop_regions)
        logger.info(
            f"  Smart stitching {len(captures)} images -> {width}x{total_height}px (fixed bar: {fixed_bottom_height}px)"
        )

        # Create canvas and stitch
        stitched = Image.new("RGB", (width, total_height))
        current_y = 0

        for i, (img, crop_top, crop_bottom) in enumerate(crop_regions):
            cropped = img.crop((0, crop_top, width, crop_bottom))
            stitched.paste(cropped, (0, current_y))
            current_y += cropped.size[1]

        return stitched

    def stitch_images(self, images: list, overlap_ratio: float) -> Image.Image:
        """
        Stitch multiple images together vertically by CROPPING overlapping portions.
        Also detects and removes fixed bottom elements (like nav bars) from non-final images.

        Args:
            images: List of PIL Images to stitch
            overlap_ratio: Overlap as ratio of height (for offset calculation)

        Returns:
            Single stitched PIL Image
        """
        if not images:
            raise ValueError("No images to stitch")

        if len(images) == 1:
            return images[0]

        first_img = images[0]
        width, height = first_img.size
        overlap_height = int(height * overlap_ratio)

        # Detect fixed bottom element height (nav bar, etc.)
        fixed_bottom_height = 0
        if len(images) >= 2:
            fixed_bottom_height = self.overlap_detector.detect_fixed_bottom_height(
                images[0], images[1]
            )

        # Calculate how much NEW content each image contributes
        # and store crop information
        crops = []  # List of (image, crop_top, crop_bottom)

        # First image: crop bottom if there's a fixed element
        first_crop_bottom = (
            height - fixed_bottom_height if fixed_bottom_height > 0 else height
        )
        crops.append((images[0], 0, first_crop_bottom))
        logger.debug(
            f"  Image 0: full height {height}, cropping bottom to {first_crop_bottom}"
        )

        for i in range(1, len(images)):
            # Find where the overlap ends in this image
            offset_y, _ = self.overlap_detector.find_overlap_offset(
                images[i - 1], images[i], overlap_height
            )

            if offset_y is not None:
                # offset_y = where template (bottom of prev img) is found in this img
                # New content starts AFTER the template region
                crop_top = offset_y + overlap_height
                logger.debug(
                    f"  Image {i}: template at y={offset_y}, crop top={crop_top}"
                )
            else:
                # Fallback: assume overlap_height worth of overlap
                crop_top = overlap_height
                logger.debug(f"  Image {i}: no match, fallback crop top={crop_top}")

            # For non-final images, also crop the fixed bottom element
            if i < len(images) - 1 and fixed_bottom_height > 0:
                crop_bottom = height - fixed_bottom_height
            else:
                crop_bottom = height  # Last image: keep the nav bar

            crops.append((images[i], crop_top, crop_bottom))

        # Calculate total height
        total_height = 0
        for i, (img, crop_top, crop_bottom) in enumerate(crops):
            contribution = crop_bottom - crop_top
            total_height += contribution
            logger.debug(
                f"  Image {i}: contributes {contribution}px (crop {crop_top}-{crop_bottom})"
            )

        logger.info(
            f"  Stitching {len(images)} images -> {width}x{total_height}px (fixed bar: {fixed_bottom_height}px)"
        )

        # Create canvas and stitch
        stitched = Image.new("RGB", (width, total_height))
        current_y = 0

        for i, (img, crop_top, crop_bottom) in enumerate(crops):
            # Crop the image
            cropped = img.crop((0, crop_top, width, crop_bottom))

            # Paste at current position
            stitched.paste(cropped, (0, current_y))

            # Move position down
            current_y += cropped.size[1]

        return stitched
