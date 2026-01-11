#!/usr/bin/env python3
"""
Quick Endpoint Comparison Script

Compares specific endpoints between original and new server.
Useful for quick manual testing during refactoring.

Usage:
    python compare_endpoints.py /api/
    python compare_endpoints.py /api/device-classes
    python compare_endpoints.py /api/health
"""

import sys
import httpx
import json
from typing import Dict, Any

ORIGINAL_SERVER = "http://localhost:3000"
NEW_SERVER = "http://localhost:3000"  # Change to :3001 if running both simultaneously


def compare_endpoint(path: str) -> Dict[str, Any]:
    """Compare single endpoint"""
    print(f"\n{'='*80}")
    print(f"Comparing: {path}")
    print(f"{'='*80}")

    try:
        # Fetch from both servers
        print(f"Fetching from original server ({ORIGINAL_SERVER})...")
        original_response = httpx.get(f"{ORIGINAL_SERVER}{path}", timeout=10.0)
        print(f"  Status: {original_response.status_code}")

        print(f"Fetching from new server ({NEW_SERVER})...")
        new_response = httpx.get(f"{NEW_SERVER}{path}", timeout=10.0)
        print(f"  Status: {new_response.status_code}")

        # Compare status codes
        if original_response.status_code != new_response.status_code:
            print(f"\n[FAIL] STATUS CODE MISMATCH:")
            print(f"   Original: {original_response.status_code}")
            print(f"   New:      {new_response.status_code}")
            return {"status": "different", "reason": "status_code_mismatch"}

        # Parse JSON (or compare raw text if not JSON)
        try:
            original_data = original_response.json()
            new_data = new_response.json()
        except Exception as e:
            # Not JSON - compare raw text (e.g., HTML error pages)
            original_text = original_response.text
            new_text = new_response.text
            if original_text == new_text:
                print(f"\n[OK] IDENTICAL (Non-JSON response)")
                print(f"\nResponse preview (first 200 chars):")
                print(original_text[:200])
                return {"status": "identical", "data": original_text}
            else:
                print(f"\n[FAIL] DIFFERENT (Non-JSON response)")
                print(f"\nOriginal Response:")
                print(original_text[:500])
                print(f"\nNew Response:")
                print(new_text[:500])
                return {"status": "different", "reason": "text_mismatch"}

        # Compare responses
        if original_data == new_data:
            print(f"\n[OK] IDENTICAL")
            print(f"\nResponse preview:")
            print(json.dumps(original_data, indent=2)[:500])
            if len(json.dumps(original_data, indent=2)) > 500:
                print("... (truncated)")
            return {"status": "identical", "data": original_data}
        else:
            print(f"\n[FAIL] DIFFERENT")
            print(f"\nOriginal Response:")
            print(json.dumps(original_data, indent=2))
            print(f"\nNew Response:")
            print(json.dumps(new_data, indent=2))

            # Find differences
            differences = find_differences(original_data, new_data)
            print(f"\nDifferences:")
            print(json.dumps(differences, indent=2))

            return {"status": "different", "differences": differences}

    except httpx.ConnectError as e:
        print(f"\n[ERROR] CONNECTION ERROR:")
        print(f"   {e}")
        print(f"\nMake sure server is running:")
        print(f"   python server.py (for original)")
        print(f"   python server_new.py (for new)")
        return {"status": "error", "reason": "connection_error"}

    except Exception as e:
        print(f"\n[ERROR] {e}")
        return {"status": "error", "reason": str(e)}


def find_differences(original: Any, new: Any, path: str = "") -> list:
    """Find differences between two data structures"""
    differences = []

    if type(original) != type(new):
        return [
            {
                "path": path,
                "type": "type_mismatch",
                "original": type(original).__name__,
                "new": type(new).__name__,
            }
        ]

    if isinstance(original, dict):
        # Check keys
        original_keys = set(original.keys())
        new_keys = set(new.keys())

        if original_keys != new_keys:
            differences.append(
                {
                    "path": path,
                    "missing_in_new": list(original_keys - new_keys),
                    "extra_in_new": list(new_keys - original_keys),
                }
            )

        # Compare values
        for key in original_keys & new_keys:
            key_path = f"{path}.{key}" if path else key
            differences.extend(find_differences(original[key], new[key], key_path))

    elif isinstance(original, list):
        if len(original) != len(new):
            differences.append(
                {
                    "path": path,
                    "type": "length_mismatch",
                    "original_length": len(original),
                    "new_length": len(new),
                }
            )
        else:
            for i, (orig, new_item) in enumerate(zip(original, new)):
                differences.extend(find_differences(orig, new_item, f"{path}[{i}]"))

    else:
        if original != new:
            differences.append(
                {"path": path, "original_value": original, "new_value": new}
            )

    return differences


def test_meta_routes():
    """Test all extracted routes"""
    print("\n" + "=" * 80)
    print("TESTING EXTRACTED ROUTES")
    print("=" * 80)

    results = []

    # Test meta routes (routes/meta.py)
    print("\n[meta.py]")
    results.append(compare_endpoint("/api/"))
    results.append(compare_endpoint("/api/device-classes"))

    # Test health routes (routes/health.py)
    print("\n[health.py]")
    results.append(compare_endpoint("/api/health"))

    # Test ADB info routes (routes/adb_info.py)
    print("\n[adb_info.py]")
    results.append(compare_endpoint("/api/adb/devices"))
    results.append(compare_endpoint("/api/adb/connection-status"))
    results.append(compare_endpoint("/api/adb/scan"))
    # Note: /api/adb/screen-state/{device_id}, /api/adb/activity/{device_id}, and
    # /api/adb/stable-id/{device_id} require device_id parameters - tested separately

    # Test cache routes (routes/cache.py)
    print("\n[cache.py]")
    results.append(compare_endpoint("/api/cache/ui/stats"))
    results.append(compare_endpoint("/api/cache/screenshot/stats"))
    results.append(compare_endpoint("/api/cache/all/stats"))
    # Note: POST endpoints (ui/clear, ui/settings, screenshot/settings) tested separately

    # Test performance routes (routes/performance.py)
    print("\n[performance.py]")
    results.append(compare_endpoint("/api/performance/metrics"))
    results.append(compare_endpoint("/api/performance/cache"))
    results.append(compare_endpoint("/api/performance/adb"))
    results.append(compare_endpoint("/api/diagnostics/system"))
    # Note: Device-specific diagnostics tested separately
    # Note: POST endpoint /api/performance/cache/clear tested separately

    # Test shell routes (routes/shell.py)
    print("\n[shell.py]")
    results.append(compare_endpoint("/api/shell/stats"))
    # Note: POST/DELETE endpoints tested separately (require device_id and request body)

    # Test maintenance routes (routes/maintenance.py)
    print("\n[maintenance.py]")
    results.append(compare_endpoint("/api/maintenance/server/status"))
    results.append(compare_endpoint("/api/maintenance/metrics"))
    # Note: Device-specific and POST endpoints tested separately

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    identical = sum(1 for r in results if r.get("status") == "identical")
    different = sum(1 for r in results if r.get("status") == "different")
    errors = sum(1 for r in results if r.get("status") == "error")

    print(f"\nTotal endpoints tested: {len(results)}")
    print(f"  [OK]    Identical: {identical}")
    print(f"  [FAIL]  Different: {different}")
    print(f"  [ERROR] Errors:    {errors}")

    if different == 0 and errors == 0:
        print(f"\n{'='*80}")
        print("[SUCCESS] ALL TESTS PASSED - Refactoring successful!")
        print(f"{'='*80}")
        return True
    else:
        print(f"\n{'='*80}")
        print("[FAILED] TESTS FAILED - Review differences above")
        print(f"{'='*80}")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Test specific endpoint from command line
        path = sys.argv[1]
        compare_endpoint(path)
    else:
        # Test all meta routes
        success = test_meta_routes()
        sys.exit(0 if success else 1)
