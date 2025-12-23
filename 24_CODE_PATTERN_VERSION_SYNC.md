# Code Pattern: Version Synchronization

**Purpose:** Keep version consistent across all files using git pre-commit hook.

**Starting Version:** 0.0.1
**Last Updated:** 2025-12-21

---

## ⚠️ LEGACY REFERENCE - Test Before Using!

This pattern worked after fixing the regex bug in v4.6.0-beta.X.

---

## 🎯 The Problem

**Version scattered across multiple files:**
- .build-version
- config.yaml
- Dockerfile
- www/*.html
- www/js/init.js

**Manual updates → errors, inconsistency, version accumulation bugs**

---

## ✅ The Solution

**Single source of truth:** `.build-version`

**Git pre-commit hook:** Auto-sync to all files

---

## 📝 .build-version Format

```
0.0.1
2025-12-21T12:00:00Z
REBUILD_ID: 0.0.1-BUILD-1703174400
```

---

## 🔧 Git Pre-Commit Hook

**⚠️ LEGACY REFERENCE - This had a regex bug that was fixed:**

```bash
#!/bin/bash
# .git/hooks/pre-commit

# Read version from .build-version
VERSION=$(head -n 1 .build-version)

echo "Syncing version $VERSION to all files..."

# CRITICAL: Regex must match version suffixes like -beta, -alpha, -rc
# Old regex: [0-9.]* (WRONG - caused version accumulation)
# New regex: [0-9.]*[^\"]* (CORRECT - matches suffixes)

# Sync to config.yaml
sed -i "s/version: [0-9.]*[^\"]*/version: $VERSION/" config.yaml

# Sync to Dockerfile
sed -i "s/LABEL version=[0-9.]*[^\"]*/LABEL version=$VERSION/" Dockerfile

# Sync to all HTML files
find www -name "*.html" -exec sed -i "s/content=\"[0-9.]*[^\"]*\"/content=\"$VERSION\"/" {} \;

# Sync to init.js
sed -i "s/const APP_VERSION = '[0-9.]*[^']*'/const APP_VERSION = '$VERSION'/" www/js/init.js

# Stage the updated files
git add config.yaml Dockerfile www/*.html www/js/init.js

echo "Version sync complete!"
```

---

## 🚨 Critical: Regex Pattern

### ❌ **OLD (Broken):**
```bash
sed -i "s/version: [0-9.]*/version: $VERSION/" config.yaml
```

**Problem:** `[0-9.]*` doesn't match `-beta.10`, so it APPENDS instead of REPLACES!

**Result:** `version: 4.6.0-beta.6-beta.5-beta.4...` (disaster!)

### ✅ **NEW (Fixed):**
```bash
sed -i "s/version: [0-9.]*[^\"]*/version: $VERSION/" config.yaml
```

**Matches:** `4.6.0-beta.10` ✅

---

## 🔧 Bumping Version

```bash
# Edit .build-version line 1
echo "0.0.2" > .build-version.tmp
tail -n +2 .build-version >> .build-version.tmp
mv .build-version.tmp .build-version

# Commit (hook auto-syncs)
git add .
git commit -m "bump: version 0.0.2"
```

---

## 📚 Related Documentation

- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) - Version strategy
- [NEW_PROJECT_PLAN.md](NEW_PROJECT_PLAN.md) - Build phases

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.1+
