#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Visual Mapper - Version Update Script

Updates version numbers across all project files.

Usage:
    python update_version.py 0.0.5
    python update_version.py 0.1.0 --build-date 2025-12-28
"""

import json
import re
import sys
import os
from pathlib import Path
from datetime import datetime
import argparse
from typing import Optional

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def update_config(new_version: str, build_date: Optional[str] = None):
    """Update branding/config.json"""
    config_path = Path("www/branding/config.json")

    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path}")
        return False

    with open(config_path, 'r') as f:
        config = json.load(f)

    config['version'] = new_version
    if build_date:
        config['buildDate'] = build_date
    else:
        config['buildDate'] = datetime.now().strftime('%Y-%m-%d')

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"[OK] Updated {config_path}")
    return True


def update_manifest(new_version: str):
    """Update manifest.webmanifest"""
    manifest_path = Path("www/manifest.webmanifest")

    if not manifest_path.exists():
        print(f"[WARN]  Manifest file not found: {manifest_path}")
        return False

    with open(manifest_path, 'r') as f:
        manifest = json.load(f)

    # Update name to include version
    manifest['name'] = f"Visual Mapper - Android Device Monitor v{new_version}"

    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    print(f"[OK] Updated {manifest_path}")
    return True


def update_html_files(new_version: str, build_date: Optional[str] = None):
    """Update version in all HTML files"""
    www_dir = Path("www")
    html_files = list(www_dir.glob("*.html"))

    if not build_date:
        build_date = datetime.now().strftime('%Y-%m-%d')

    updated_count = 0

    for html_file in html_files:
        with open(html_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Update version meta tag
        content = re.sub(
            r'<meta name="version" content="[^"]*" data-build="[^"]*">',
            f'<meta name="version" content="{new_version}" data-build="{build_date}">',
            content
        )

        # Update version in nav (if exists)
        content = re.sub(
            r'<li class="version">v[0-9.]+</li>',
            f'<li class="version">v{new_version}</li>',
            content
        )

        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(content)

        updated_count += 1

    print(f"[OK] Updated {updated_count} HTML files")
    return True


def update_readme_files(new_version: str):
    """Update version in README files"""
    readme_files = [
        Path("README.md"),
        Path("www/branding/README.md")
    ]

    for readme_file in readme_files:
        if not readme_file.exists():
            continue

        with open(readme_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Update version in markdown
        content = re.sub(
            r'\*\*v[0-9.]+\*\*',
            f'**v{new_version}**',
            content
        )
        content = re.sub(
            r'Version:\*\* [0-9.]+',
            f'Version:** {new_version}',
            content
        )

        with open(readme_file, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"[OK] Updated {readme_file}")

    return True


def update_svg_files(new_version: str):
    """Update version badge in social-preview.svg"""
    svg_file = Path("www/branding/social-preview.svg")

    if not svg_file.exists():
        print(f"[WARN]  Social preview SVG not found: {svg_file}")
        return False

    with open(svg_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Update version badge text (handles whitespace between tags)
    content = re.sub(
        r'<text[^>]*>\s*v[0-9.]+\s*</text>',
        f'<text x="60" y="288" font-family="Arial, sans-serif" font-size="20" font-weight="600" fill="#ffffff" text-anchor="middle">\n      v{new_version}\n    </text>',
        content
    )

    with open(svg_file, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"[OK] Updated {svg_file}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Update Visual Mapper version across all files'
    )
    parser.add_argument(
        'version',
        help='New version number (e.g., 0.0.5, 0.1.0, 1.0.0)'
    )
    parser.add_argument(
        '--build-date',
        help='Build date (YYYY-MM-DD). Defaults to today.',
        default=None
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without making changes'
    )

    args = parser.parse_args()

    # Validate version format
    if not re.match(r'^\d+\.\d+\.\d+$', args.version):
        print(f"[ERROR] Invalid version format: {args.version}")
        print("   Expected format: MAJOR.MINOR.PATCH (e.g., 0.0.5)")
        sys.exit(1)

    print(f"\n[UPDATE] Updating Visual Mapper to version {args.version}")
    if args.dry_run:
        print("   (DRY RUN - No files will be modified)")
    print()

    if args.dry_run:
        print("Would update:")
        print("  - www/branding/config.json")
        print("  - www/manifest.webmanifest")
        print("  - All HTML files in www/")
        print("  - README.md files")
        print("  - www/branding/social-preview.svg")
        return

    # Perform updates
    success = True
    success &= update_config(args.version, args.build_date)
    success &= update_manifest(args.version)
    success &= update_html_files(args.version, args.build_date)
    success &= update_readme_files(args.version)
    success &= update_svg_files(args.version)

    if success:
        print(f"\n[OK] Successfully updated to version {args.version}")
        print("\nNext steps:")
        print(f"  1. Review changes: git diff")
        print(f"  2. Test the application")
        print(f"  3. Commit: git commit -m 'Bump version to {args.version}'")
        print(f"  4. Tag: git tag v{args.version}")
        print(f"  5. Push: git push && git push --tags")
    else:
        print("\n[WARN]  Some files could not be updated. Please review the output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
