#!/usr/bin/env python3
"""
Automated exploration testing script.
Launches exploration, monitors logs, and reports issues.

Usage:
    python test_exploration.py --package com.byd.bydautolink --strategy SYSTEMATIC --deep
    python test_exploration.py --package com.byd.bydautolink --strategy ADAPTIVE
    python test_exploration.py --list-devices
"""

import subprocess
import argparse
import time
import re
import sys
from datetime import datetime
from typing import List, Optional, Tuple

# ADB device (can be overridden)
DEFAULT_DEVICE = "192.168.86.2:46747"

class ExplorationTester:
    def __init__(self, device: str = DEFAULT_DEVICE):
        self.device = device
        self.companion_package = "com.visualmapper.companion"

    def run_adb(self, *args) -> Tuple[int, str, str]:
        """Run an ADB command and return (returncode, stdout, stderr)."""
        cmd = ["adb", "-s", self.device] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr

    def list_devices(self) -> List[str]:
        """List connected ADB devices."""
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')[1:]  # Skip header
        devices = []
        for line in lines:
            if '\t' in line:
                device_id, status = line.split('\t')
                if status == 'device':
                    devices.append(device_id)
        return devices

    def clear_logcat(self):
        """Clear the logcat buffer."""
        self.run_adb("logcat", "-c")
        print("Cleared logcat buffer")

    def set_exploration_settings(self, strategy: str, deep: bool = False,
                                  max_passes: int = 1, target_coverage: int = 90):
        """Set exploration settings via shared preferences."""
        prefs_file = f"/data/data/{self.companion_package}/shared_prefs/{self.companion_package}_preferences.xml"

        # Use am broadcast to set preferences (requires the app to have a receiver)
        # For now, we'll document manual setup
        print(f"\n=== Exploration Settings ===")
        print(f"Strategy: {strategy}")
        print(f"Deep Exploration: {deep}")
        print(f"Max Passes: {max_passes}")
        print(f"Target Coverage: {target_coverage}%")
        print(f"\nNote: Make sure these settings are configured in the app!")
        print("=" * 40)

    def start_exploration(self, package: str, strategy: str = "SYSTEMATIC",
                          deep: bool = False):
        """Start exploration of a package."""
        print(f"\n=== Starting Exploration ===")
        print(f"Target App: {package}")
        print(f"Strategy: {strategy}")
        print(f"Deep Mode: {deep}")

        # Launch companion app
        print("\nLaunching Visual Mapper Companion...")
        self.run_adb("shell", "am", "start", "-n",
                     f"{self.companion_package}/.ui.fragments.MainContainerActivity")
        time.sleep(2)

        # Start exploration service with intent
        mode = "DEEP_ANALYSIS" if deep else "NORMAL"
        intent_action = "com.visualmapper.companion.START_EXPLORATION"

        print(f"Starting exploration service for {package}...")
        self.run_adb("shell", "am", "startservice",
                     "-n", f"{self.companion_package}/.explorer.AppExplorerService",
                     "-a", intent_action,
                     "--es", "package_name", package,
                     "--es", "mode", mode)

        return True

    def stop_exploration(self):
        """Stop the current exploration."""
        print("\nStopping exploration...")
        self.run_adb("shell", "am", "startservice",
                     "-n", f"{self.companion_package}/.explorer.AppExplorerService",
                     "-a", "com.visualmapper.companion.STOP_EXPLORATION")

    def monitor_logs(self, duration: int = 60, patterns: Optional[List[str]] = None):
        """
        Monitor logcat for exploration progress.

        Args:
            duration: How long to monitor in seconds
            patterns: List of regex patterns to watch for
        """
        if patterns is None:
            patterns = [
                r"Strategy selection.*using (\w+)",
                r"STEP 3\.5.*SKIPPING.*NAV",
                r"\[SYSTEMATIC\].*Reading element at \((\d+), (\d+)\)",
                r"\[SYSTEMATIC\].*priority=(\d+)",
                r"Queue has (\d+) elements.*Priority range: (\d+) to (\d+)",
                r"=== EXPLORATION COMPLETED ===",
                r"Coverage: (\d+)%",
                r"Screens: (\d+)",
                r"Elements: (\d+)",
                r"Issues: (\d+)",
                r"ERROR|FAILED|CRASH",
            ]

        print(f"\n=== Monitoring Logs for {duration}s ===")
        print("Press Ctrl+C to stop early\n")

        start_time = time.time()
        issues_found = []
        stats = {
            'strategy': None,
            'screens': 0,
            'elements': 0,
            'coverage': 0,
            'issues': 0,
            'first_tap_y': None,
            'tap_count': 0
        }

        try:
            # Start logcat process
            proc = subprocess.Popen(
                ["adb", "-s", self.device, "logcat", "-v", "time", "AppExplorer:D", "*:S"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            while time.time() - start_time < duration:
                line = proc.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue

                # Check patterns
                if "Strategy selection" in line:
                    match = re.search(r"using (\w+)", line)
                    if match:
                        stats['strategy'] = match.group(1)
                        print(f"[STRATEGY] {stats['strategy']}")

                if "[SYSTEMATIC]" in line and "Reading element at" in line:
                    match = re.search(r"\((\d+), (\d+)\).*priority=(\d+)", line)
                    if match:
                        x, y, prio = int(match.group(1)), int(match.group(2)), int(match.group(3))
                        stats['tap_count'] += 1
                        if stats['first_tap_y'] is None:
                            stats['first_tap_y'] = y
                            print(f"[FIRST TAP] y={y}, priority={prio}")
                        if stats['tap_count'] <= 5:
                            print(f"[TAP #{stats['tap_count']}] y={y}, priority={prio}")

                if "Queue has" in line and "Priority range" in line:
                    match = re.search(r"Queue has (\d+).*range: (\d+) to (\d+)", line)
                    if match:
                        count, min_p, max_p = match.groups()
                        print(f"[QUEUE] {count} elements, priority {min_p}-{max_p}")

                if "EXPLORATION COMPLETED" in line:
                    print("[COMPLETE] Exploration finished!")

                if "Coverage:" in line:
                    match = re.search(r"Coverage: (\d+)", line)
                    if match:
                        stats['coverage'] = int(match.group(1))
                        print(f"[COVERAGE] {stats['coverage']}%")

                if "ERROR" in line or "FAILED" in line:
                    issues_found.append(line.strip())
                    print(f"[ERROR] {line.strip()[-80:]}")

            proc.terminate()

        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")
            proc.terminate()

        # Print summary
        print("\n" + "=" * 50)
        print("=== Exploration Summary ===")
        print(f"Strategy Used: {stats['strategy']}")
        print(f"Total Taps: {stats['tap_count']}")
        print(f"First Tap Y: {stats['first_tap_y']}")
        print(f"Coverage: {stats['coverage']}%")
        print(f"Issues Found: {len(issues_found)}")

        if stats['first_tap_y'] and stats['first_tap_y'] > 1000:
            print("\n[BUG] First tap was at bottom of screen (y > 1000)!")
            print("SYSTEMATIC mode should start from top (y < 500)")

        if issues_found:
            print("\n=== Issues ===")
            for issue in issues_found[:10]:
                print(f"  - {issue[-100:]}")

        return stats

    def get_recent_logs(self, lines: int = 100) -> str:
        """Get recent AppExplorer logs."""
        _, stdout, _ = self.run_adb("logcat", "-d", "-t", str(lines), "-s", "AppExplorer:D")
        return stdout

    def analyze_systematic_bug(self):
        """Analyze the SYSTEMATIC priority bug from recent logs."""
        print("\n=== Analyzing SYSTEMATIC Bug ===")

        logs = self.get_recent_logs(500)

        # Find priority assignments
        assignments = re.findall(
            r"\[SYSTEMATIC\] Element (\S+) at y=(\d+) -> row=(\d+), readingOrder=(\d+), priority=(\d+)",
            logs
        )

        if assignments:
            print(f"\nFound {len(assignments)} priority assignments:")
            print(f"{'Element':<40} {'Y':>6} {'Row':>4} {'Order':>6} {'Priority':>8}")
            print("-" * 70)

            for elem, y, row, order, prio in assignments[:20]:
                print(f"{elem[:40]:<40} {y:>6} {row:>4} {order:>6} {prio:>8}")

            # Check if priorities are inverted
            priorities = [(int(y), int(prio)) for _, y, _, _, prio in assignments]
            top_elements = [p for y, p in priorities if y < 500]
            bottom_elements = [p for y, p in priorities if y > 1000]

            if top_elements and bottom_elements:
                avg_top = sum(top_elements) / len(top_elements)
                avg_bottom = sum(bottom_elements) / len(bottom_elements)
                print(f"\nAvg priority for top (y<500): {avg_top:.0f}")
                print(f"Avg priority for bottom (y>1000): {avg_bottom:.0f}")

                if avg_top > avg_bottom:
                    print("\n[OK] Priorities are correct (top > bottom)")
                else:
                    print("\n[BUG] Priorities are INVERTED (bottom > top)!")
        else:
            print("No priority assignments found in recent logs")

        # Find which element was selected first
        first_tap = re.search(r"\[SYSTEMATIC\] Reading element at \((\d+), (\d+)\)", logs)
        if first_tap:
            x, y = first_tap.groups()
            print(f"\nFirst element selected: ({x}, {y})")
            if int(y) > 1000:
                print("[BUG] First tap was at BOTTOM of screen!")


def main():
    parser = argparse.ArgumentParser(description="Automated exploration testing")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="ADB device ID")
    parser.add_argument("--package", default="com.byd.bydautolink", help="Package to explore")
    parser.add_argument("--strategy", default="SYSTEMATIC",
                        choices=["SYSTEMATIC", "ADAPTIVE", "SCREEN_FIRST", "DEPTH_FIRST"],
                        help="Exploration strategy")
    parser.add_argument("--deep", action="store_true", help="Enable deep exploration")
    parser.add_argument("--duration", type=int, default=120, help="Monitor duration in seconds")
    parser.add_argument("--list-devices", action="store_true", help="List connected devices")
    parser.add_argument("--analyze", action="store_true", help="Analyze recent logs for bugs")
    parser.add_argument("--start", action="store_true", help="Start exploration")
    parser.add_argument("--stop", action="store_true", help="Stop exploration")
    parser.add_argument("--logs", action="store_true", help="Show recent logs")

    args = parser.parse_args()

    tester = ExplorationTester(args.device)

    if args.list_devices:
        devices = tester.list_devices()
        print("Connected devices:")
        for d in devices:
            print(f"  - {d}")
        return

    if args.analyze:
        tester.analyze_systematic_bug()
        return

    if args.logs:
        print(tester.get_recent_logs(200))
        return

    if args.stop:
        tester.stop_exploration()
        return

    if args.start:
        tester.clear_logcat()
        tester.set_exploration_settings(args.strategy, args.deep)
        tester.start_exploration(args.package, args.strategy, args.deep)
        print("\nWaiting 3 seconds for exploration to start...")
        time.sleep(3)
        tester.monitor_logs(args.duration)
    else:
        # Default: just monitor
        tester.monitor_logs(args.duration)


if __name__ == "__main__":
    main()
