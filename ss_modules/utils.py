"""
Screenshot Stitcher Utilities Module

Contains standalone utility functions:
- remove_consecutive_duplicates: Post-process to remove duplicate content
- Height estimation helpers for content scrolling
"""

import logging
import re
from typing import Tuple, Optional
from PIL import Image

logger = logging.getLogger(__name__)


def get_element_y_center(elem: dict) -> int:
    """Get the Y center position of an element."""
    bounds = elem.get('bounds', {})
    if isinstance(bounds, dict):
        y = bounds.get('y', 0)
        height = bounds.get('height', 0)
        return y + height // 2
    return 0


def remove_consecutive_duplicates(
    img: Image.Image,
    elements: list,
    screen_height: int
) -> Tuple[Image.Image, list]:
    """
    Post-process to remove CONSECUTIVE duplicate content anywhere in the image.

    This detects when the same content appears twice in a row - which happens
    when overlap detection fails during stitching.

    Strategy:
    1. Scan the image for sections that match content 150-400px later
    2. When found, remove the duplicate section (the later occurrence)
    3. Repeat until no more duplicates found

    IMPORTANT: Uses center 60% of width to avoid false positives from
    consistent UI edges/margins.
    """
    import numpy as np

    width, height = img.size
    if height <= screen_height:
        return img, elements  # Single screen, no duplicates possible

    logger.info(f"  === SCANNING FOR CONSECUTIVE DUPLICATES ===")
    logger.info(f"  Image size: {width}x{height}")

    arr = np.array(img.convert('RGB'))
    strip_height = 150  # Height of strip to compare

    # Only compare CENTER 60% of width (skip edges with consistent UI)
    left_margin = width // 5
    right_margin = 4 * width // 5

    # Skip header area (top 200px) - often has fixed elements
    header_skip = 200

    # Track duplicate regions to remove
    # Each entry is (start_y, end_y) of the duplicate section to remove
    duplicates_to_remove = []

    # Scan for consecutive duplicates
    # Check every 25px for thorough coverage
    y = header_skip
    while y < height - strip_height - 150:  # Need room for offset check
        strip1 = arr[y:y + strip_height, left_margin:right_margin, :]

        # Skip dark/blank regions (variance < 1500 = not real content)
        # Netflix and similar apps have lots of dark background that matches
        # but isn't actually duplicate content
        strip1_variance = np.var(strip1)
        if strip1_variance < 1500:
            y += 50  # Skip faster through dark regions
            continue

        # Check for match 150-400px later (typical scroll distances)
        for offset in [150, 200, 250, 300, 350, 400]:
            later_y = y + offset
            if later_y + strip_height > height:
                continue

            strip2 = arr[later_y:later_y + strip_height, left_margin:right_margin, :]

            # Also check second strip has content
            strip2_variance = np.var(strip2)
            if strip2_variance < 1500:
                continue

            # Check if strips are very similar (>92% match for content regions)
            matching = np.sum(strip1 == strip2)
            total = strip1.size
            score = matching / total

            if score > 0.92:  # Lower threshold OK since we verified content exists
                # Found a consecutive duplicate!
                # The duplicate section runs from y+offset to some point beyond

                # Find how far the duplicate extends
                dup_start = later_y
                dup_end = dup_start

                # Extend the duplicate region as long as it keeps matching
                check_y = dup_start
                original_y = y
                while check_y + strip_height <= height and original_y + strip_height <= dup_start:
                    check_strip = arr[check_y:check_y + strip_height, left_margin:right_margin, :]
                    orig_strip = arr[original_y:original_y + strip_height, left_margin:right_margin, :]

                    match_score = np.sum(check_strip == orig_strip) / check_strip.size
                    if match_score > 0.90:
                        dup_end = check_y + strip_height
                        check_y += 50  # Step forward
                        original_y += 50
                    else:
                        break

                if dup_end > dup_start + 50:  # Minimum 50px duplicate
                    logger.info(f"  CONSECUTIVE DUP: y={y} repeats at y={dup_start}-{dup_end} ({score*100:.1f}%)")
                    duplicates_to_remove.append((dup_start, dup_end))
                    y = dup_end  # Skip past this duplicate
                    break

        y += 25  # Step by 25px for thorough coverage

    # Remove duplicates (from bottom to top to preserve y-coordinates)
    if duplicates_to_remove:
        logger.info(f"  Found {len(duplicates_to_remove)} duplicate region(s) to remove")

        # Sort by start position descending (process from bottom up)
        duplicates_to_remove.sort(key=lambda x: x[0], reverse=True)

        current_arr = arr
        total_removed = 0

        for dup_start, dup_end in duplicates_to_remove:
            dup_height = dup_end - dup_start
            logger.info(f"  Removing duplicate region y={dup_start}-{dup_end} ({dup_height}px)")

            # Create new array without the duplicate region
            new_arr = np.vstack([
                current_arr[:dup_start, :, :],
                current_arr[dup_end:, :, :]
            ])
            current_arr = new_arr
            total_removed += dup_height

            # Adjust elements
            new_elements = []
            for elem in elements:
                y_center = get_element_y_center(elem)

                if y_center < dup_start:
                    # Element is before duplicate - keep as is
                    new_elements.append(elem)
                elif y_center >= dup_end:
                    # Element is after duplicate - adjust Y position
                    adjusted_elem = elem.copy()
                    bounds = adjusted_elem.get('bounds', {})
                    if isinstance(bounds, dict):
                        bounds = bounds.copy()
                        bounds['y'] = bounds.get('y', 0) - dup_height
                        adjusted_elem['bounds'] = bounds
                    new_elements.append(adjusted_elem)
                # Elements inside the duplicate region are dropped

            elements = new_elements

        new_height = current_arr.shape[0]
        logger.info(f"  TOTAL REMOVED: {total_removed}px, new height: {height}px -> {new_height}px")
        logger.info(f"  Elements: after filtering: {len(elements)}")

        result_img = Image.fromarray(current_arr)
        return result_img, elements
    else:
        logger.info(f"  No consecutive duplicates found")

    return img, elements


def estimate_from_patterns(elements: list) -> Optional[dict]:
    """
    Look for patterns like "Episode 5 of 8", "3/10", "Item 2 of 5"
    """
    patterns = [
        r'(\d+)\s*of\s*(\d+)',           # "5 of 8", "Episode 5 of 8"
        r'(\d+)\s*/\s*(\d+)',             # "5/8", "3/10"
        r'(\d+)\s*out of\s*(\d+)',        # "5 out of 8"
        r'Episode\s*(\d+).*?(\d+)\s*episodes',  # "Episode 5...8 episodes"
    ]

    for elem in elements:
        text = str(elem.get('text', '')) + ' ' + str(elem.get('content_desc', ''))

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                current = int(match.group(1))
                total = int(match.group(2))
                if 1 <= current <= total <= 1000:  # Sanity check
                    logger.info(f"[Pattern] Found '{match.group()}' -> {current} of {total}")
                    return {
                        'current_item': current,
                        'total_items': total,
                        'source_text': text[:50]
                    }

    return None


def estimate_from_numbered_items(elements: list) -> Optional[dict]:
    """
    Find numbered items like "1. Title", "2. Another", "Episode 3"
    Track the sequence to find max number.
    Also track the Y position of the FIRST numbered item to estimate header height.

    IMPORTANT: Prefer content_desc over text as it usually refers to the FULL container
    with accurate height, while text is often just a small label.
    """
    numbered_items = []
    seen_numbers = set()  # Track which numbers we've seen to avoid duplicates

    # Patterns for numbered items
    patterns = [
        r'Episode\s*(\d+)',          # "Episode 5" - prioritize full episode containers
        r'Chapter\s*(\d+)',          # "Chapter 3"
        r'Item\s*(\d+)',             # "Item 7"
        r'^(\d+)\.\s+\w',           # "1. Title"
        r'^(\d+)\)\s+\w',           # "1) Title"
        r'^#(\d+)',                  # "#5"
    ]

    # FIRST PASS: Check content_desc (usually full containers with correct height)
    for elem in elements:
        content_desc = str(elem.get('content_desc', ''))
        bounds = elem.get('bounds', {})

        for pattern in patterns:
            match = re.search(pattern, content_desc, re.IGNORECASE)
            if match:
                num = int(match.group(1))
                if 1 <= num <= 1000 and num not in seen_numbers:
                    y_pos = bounds.get('y', 0) if isinstance(bounds, dict) else 0
                    height = bounds.get('height', 0) if isinstance(bounds, dict) else 0
                    # Only add if height is reasonable (full card, not just text)
                    if height > 100:
                        seen_numbers.add(num)
                        numbered_items.append({
                            'number': num,
                            'text': content_desc[:40],
                            'height': height,
                            'y': y_pos,
                            'source': 'content_desc'
                        })
                break

    # SECOND PASS: Check text (fallback for apps without content_desc)
    for elem in elements:
        text = str(elem.get('text', ''))
        bounds = elem.get('bounds', {})

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                num = int(match.group(1))
                if 1 <= num <= 1000 and num not in seen_numbers:
                    y_pos = bounds.get('y', 0) if isinstance(bounds, dict) else 0
                    height = bounds.get('height', 0) if isinstance(bounds, dict) else 0
                    seen_numbers.add(num)
                    numbered_items.append({
                        'number': num,
                        'text': text[:30],
                        'height': height,
                        'y': y_pos,
                        'source': 'text'
                    })
                break

    if not numbered_items:
        return None

    # Find the highest number (likely total count)
    max_num = max(item['number'] for item in numbered_items)
    numbers_found = sorted(set(item['number'] for item in numbered_items))

    # Calculate average height of numbered items
    heights = [item['height'] for item in numbered_items if item['height'] > 50]
    avg_height = sum(heights) / len(heights) if heights else 200

    # Find the Y position of the FIRST visible numbered item
    # This helps estimate header height more accurately
    first_item = min(numbered_items, key=lambda x: x['number'])
    first_item_y = first_item.get('y', 0)
    first_item_num = first_item.get('number', 1)

    # Calculate where item #1 would start (extrapolate backward)
    # If we see item 6 at y=200, and items are ~230px each, then item 1 starts at y=200 - (5*230)
    estimated_item1_y = first_item_y - ((first_item_num - 1) * max(avg_height, 200))
    # Header is everything above where item 1 would be
    estimated_header = max(0, estimated_item1_y)

    logger.info(f"[Numbered] Found items: {numbers_found}, max={max_num}, avg_height={avg_height:.0f}px")
    logger.info(f"[Numbered] First visible: #{first_item_num} at y={first_item_y}, estimated header={estimated_header:.0f}px")

    return {
        'max_number': max_num,
        'numbers_found': numbers_found,
        'items_visible': len(numbered_items),
        'avg_height': int(avg_height),
        'first_item_y': first_item_y,
        'first_item_num': first_item_num,
        'estimated_header': int(estimated_header)
    }


def estimate_from_bounds(elements: list, screen_height: int) -> Optional[dict]:
    """
    Analyze element bounds to estimate content structure.
    """
    # Find scrollable area
    scrollable_top = 0
    scrollable_bottom = screen_height

    for elem in elements:
        if elem.get('scrollable') == 'true' or elem.get('scrollable') == True:
            bounds = elem.get('bounds', {})
            if isinstance(bounds, dict):
                scrollable_top = bounds.get('y', 0)
                scrollable_bottom = scrollable_top + bounds.get('height', screen_height)
                break

    scrollable_height = scrollable_bottom - scrollable_top

    # Find items within scrollable area
    items_in_scroll = []
    for elem in elements:
        bounds = elem.get('bounds', {})
        if isinstance(bounds, dict):
            y = bounds.get('y', 0)
            h = bounds.get('height', 0)
            # Items with reasonable height within scroll area
            if scrollable_top <= y < scrollable_bottom and 50 < h < 400:
                items_in_scroll.append({'y': y, 'height': h})

    if not items_in_scroll:
        return None

    # Calculate stats
    heights = [item['height'] for item in items_in_scroll]
    avg_height = sum(heights) / len(heights)

    # Estimate header content (above scrollable area)
    header_estimate = scrollable_top + 400  # scrollable_top + some buffer for title/desc

    # Estimate total: visible items usually represent 30-50% of total
    # Use conservative 2.5x multiplier
    estimated_items = len(items_in_scroll) * 2.5
    estimated_total = header_estimate + (estimated_items * avg_height)

    return {
        'scrollable_area': scrollable_height,
        'scrollable_top': scrollable_top,
        'visible_items': len(items_in_scroll),
        'avg_item_height': int(avg_height),
        'header_estimate': header_estimate,
        'estimated_total': int(estimated_total)
    }


def get_scrollable_container_info(elements: list) -> Optional[dict]:
    """
    Get info about the scrollable container.
    """
    for elem in elements:
        if elem.get('scrollable') == 'true' or elem.get('scrollable') == True:
            bounds = elem.get('bounds', {})
            if isinstance(bounds, dict):
                return {
                    'class': elem.get('class', 'unknown'),
                    'bounds': bounds,
                    'resource_id': elem.get('resource_id', '')
                }
    return None
