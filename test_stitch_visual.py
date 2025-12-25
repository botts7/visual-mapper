"""
Visual Stitch Test - Saves debug images for inspection
Run this to capture and stitch, then examine the output images
"""

import asyncio
import os
from PIL import Image, ImageDraw, ImageFont
from adb_bridge import ADBBridge
from screenshot_stitcher import ScreenshotStitcher

# Output directory
OUTPUT_DIR = "test_stitch_output"

async def run_test():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("VISUAL STITCH TEST")
    print("=" * 60)

    # Initialize
    adb = ADBBridge()
    stitcher = ScreenshotStitcher(adb)

    # Get device
    devices = await adb.get_devices()
    if not devices:
        print("ERROR: No devices connected")
        return

    device_id = devices[0]["id"]
    print(f"Using device: {device_id}")
    print(f"Device info: {devices[0]}")

    # Test basic screenshot first
    print("\nTesting basic screenshot...")
    try:
        test_img = await adb.capture_screenshot(device_id)
        print(f"Basic screenshot OK: {len(test_img)} bytes")
    except Exception as e:
        print(f"Basic screenshot FAILED: {e}")
        # Try to reconnect
        print("Attempting reconnect...")
        discovered = await adb.discover_devices()
        print(f"Discovered: {discovered}")
        devices = await adb.get_devices()
        print(f"Devices after rediscover: {devices}")

    # Capture stitched screenshot
    print("\nCapturing stitched screenshot...")
    result = await stitcher.capture_scrolling_screenshot(device_id)

    stitched_img = result["image"]
    elements = result["elements"]
    metadata = result["metadata"]
    debug_screenshots = result.get("debug_screenshots", [])

    print(f"\n=== RESULTS ===")
    print(f"Final size: {stitched_img.size}")
    print(f"Total elements: {len(elements)}")
    print(f"Captures: {metadata['capture_count']}")
    print(f"Duration: {metadata['duration_ms']}ms")

    # Save stitched image
    stitched_path = os.path.join(OUTPUT_DIR, "stitched.png")
    stitched_img.save(stitched_path)
    print(f"\nSaved: {stitched_path}")

    # Save individual captures
    for i, debug in enumerate(debug_screenshots):
        import base64
        img_data = base64.b64decode(debug["image"])
        with open(os.path.join(OUTPUT_DIR, f"capture_{i}.png"), "wb") as f:
            f.write(img_data)
        print(f"Saved: capture_{i}.png (y_offset={debug.get('first_new_y', 0)}, scroll={debug.get('known_scroll', 0)})")

    # Create debug image with overlays and strip boundaries
    debug_img = stitched_img.copy()
    draw = ImageDraw.Draw(debug_img)

    # Draw strip boundaries (red lines) - dynamic based on actual captures
    screen_height = metadata["original_height"]
    stitch_info = metadata.get("stitch_info", {})

    # Draw a line at screen_height to show first capture boundary
    if metadata["capture_count"] > 1:
        # First capture ends approximately at screen_height minus footer
        footer_height = stitch_info.get("footer_height", 200)
        first_boundary = screen_height - footer_height
        draw.line([(0, first_boundary), (stitched_img.width, first_boundary)], fill="red", width=3)
        draw.text((10, first_boundary + 5), f"Capture 1 ends @ y={first_boundary}", fill="red")

    # Draw element overlays (green boxes)
    element_count = 0
    for elem in elements:
        bounds = elem.get("bounds", {})
        if isinstance(bounds, dict):
            x = bounds.get("x", 0)
            y = bounds.get("y", 0)
            w = bounds.get("width", 0)
            h = bounds.get("height", 0)

            if w > 10 and h > 10:  # Skip tiny elements
                draw.rectangle([x, y, x + w, y + h], outline="green", width=2)
                element_count += 1

    print(f"Drew {element_count} element overlays")

    # Save debug image
    debug_path = os.path.join(OUTPUT_DIR, "stitched_debug.png")
    debug_img.save(debug_path)
    print(f"Saved: {debug_path}")

    # Log some sample elements for verification
    print(f"\n=== SAMPLE ELEMENTS ===")
    text_elements = [e for e in elements if e.get("text")]
    for elem in text_elements[:10]:
        text = elem.get("text", "")[:40]
        bounds = elem.get("bounds", {})
        if isinstance(bounds, dict):
            y = bounds.get("y", 0)
            print(f"  '{text.encode('ascii', 'replace').decode()}' @ y={y}")

    # === DUPLICATE DETECTION ===
    print(f"\n=== DUPLICATE DETECTION ===")

    # Common fixed UI elements to exclude from duplicate detection
    # These often appear in headers/footers across many apps
    fixed_ui_texts = {"Home", "Back", "Settings", "Menu", "Search", "More", "OK", "Cancel", "Done"}

    text_counts = {}
    for elem in elements:
        text = elem.get("text", "")
        if text and len(text) > 3:  # Skip short texts
            if text not in text_counts:
                text_counts[text] = []
            bounds = elem.get("bounds", {})
            if isinstance(bounds, dict):
                text_counts[text].append(bounds.get("y", 0))

    content_duplicates_found = False
    fixed_ui_duplicates = []
    for text, y_positions in text_counts.items():
        if len(y_positions) > 1:
            # Check if positions are significantly different (not just small variation)
            y_sorted = sorted(y_positions)
            for i in range(1, len(y_sorted)):
                if y_sorted[i] - y_sorted[i-1] > 200:  # More than 200px apart = duplicate
                    if text in fixed_ui_texts:
                        fixed_ui_duplicates.append((text, y_positions))
                    else:
                        content_duplicates_found = True
                        print(f"  CONTENT DUPLICATE: '{text[:40]}' at y={y_positions}")

    if fixed_ui_duplicates:
        print(f"  Fixed UI duplicates (expected): {len(fixed_ui_duplicates)}")
        for text, y_pos in fixed_ui_duplicates:
            print(f"    '{text}' at y={y_pos}")

    if not content_duplicates_found:
        print(f"  No content duplicates found!")

    # === VALIDATION SUMMARY ===
    print(f"\n=== VALIDATION SUMMARY ===")

    # Check 1: No content duplicates (excludes fixed UI)
    no_content_dups = not content_duplicates_found
    print(f"  [{'PASS' if no_content_dups else 'FAIL'}] No duplicate content")

    # Check 2: Image height reasonable (not excessively tall from duplicates)
    # Allow up to 10 screen heights for very long scrollable pages
    screen_height = metadata["original_height"]
    max_reasonable_height = screen_height * 10
    height_reasonable = stitched_img.size[1] < max_reasonable_height
    print(f"  [{'PASS' if height_reasonable else 'FAIL'}] Height reasonable: {stitched_img.size[1]}px")

    # Check 3: Has content (elements were captured)
    has_content = len(elements) > 10
    print(f"  [{'PASS' if has_content else 'FAIL'}] Content captured: {len(elements)} elements")

    # Final result
    all_passed = no_content_dups and height_reasonable and has_content
    print(f"\n  {'=' * 30}")
    print(f"  OVERALL: {'PASS' if all_passed else 'FAIL'}")
    print(f"  {'=' * 30}")

    print(f"\n=== DONE ===")
    print(f"Check {OUTPUT_DIR}/ for output images")
    print(f"  - stitched.png: Final stitched image")
    print(f"  - stitched_debug.png: With overlays and strip boundaries")
    print(f"  - capture_N.png: Individual captures")

if __name__ == "__main__":
    asyncio.run(run_test())
