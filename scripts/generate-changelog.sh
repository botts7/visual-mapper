#!/bin/bash
# Generate changelog entries from git commits since last tag/version
# Usage: ./scripts/generate-changelog.sh [since_ref]
#   since_ref: git ref to start from (default: last tag or 10 commits)

SINCE_REF=${1:-$(git describe --tags --abbrev=0 2>/dev/null || echo "HEAD~10")}
VERSION=$(cat .build-version 2>/dev/null || echo "UNRELEASED")

echo "## $VERSION"
echo ""

# Group commits by type based on conventional commit prefixes
echo "### Bug Fixes"
git log "$SINCE_REF"..HEAD --pretty=format:"- %s" --grep="^fix" -i | head -20
echo ""

echo "### New Features"
git log "$SINCE_REF"..HEAD --pretty=format:"- %s" --grep="^feat" -i | head -20
echo ""

echo "### Improvements"
git log "$SINCE_REF"..HEAD --pretty=format:"- %s" --grep="^chore\|^refactor\|^perf\|^style" -i | head -20
echo ""

echo "### All Changes (for reference)"
git log "$SINCE_REF"..HEAD --pretty=format:"- %s" | head -30
