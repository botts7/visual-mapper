# Visual Mapper Branding - Editing Guide

This guide shows you how to customize Visual Mapper's branding as your project evolves.

## Quick Updates

### 1. Update Version Number

**Easy way** - Use the version update script:

```bash
# From project root
python update_version.py 0.0.5

# With custom build date
python update_version.py 0.1.0 --build-date 2025-12-28

# Dry run (see what would change)
python update_version.py 1.0.0 --dry-run
```

This automatically updates:
- ✅ `branding/config.json`
- ✅ `manifest.webmanifest`
- ✅ All HTML files
- ✅ README files
- ✅ Social preview SVG

### 2. Update Colors

Edit `branding/config.json`:

```json
{
  "colors": {
    "primary": "#3b82f6",      // Main blue
    "primaryDark": "#2563eb",  // Darker blue
    "accent": "#ec4899"        // Pink highlight
  }
}
```

Then regenerate icons (see below).

### 3. Update Project Info

Edit `branding/config.json`:

```json
{
  "name": "Visual Mapper",
  "tagline": "YOUR NEW TAGLINE",
  "description": "Your new description here",
  "url": "https://your-actual-domain.com"
}
```

---

## Editing Individual Assets

### Favicon (favicon.svg)

**What it is:** The icon shown in browser tabs

**How to edit:**
1. Open `www/favicon.svg` in a text editor or vector graphics app
2. Key elements to customize:
   - Line 4-5: Change gradient colors (`stop-color` values)
   - Line 36: Change highlight color (`fill="#ec4899"`)

**Colors to change:**
```xml
<stop offset="0%" style="stop-color:#3b82f6" />  <!-- Primary -->
<stop offset="100%" style="stop-color:#2563eb" /> <!-- Dark -->
<rect ... fill="#ec4899" />  <!-- Accent highlight -->
```

**Testing:**
- View in browser: `http://localhost:3000/favicon.svg`
- Hard refresh browser (Ctrl+Shift+R) to see changes

---

### Horizontal Logo (branding/logo-horizontal.svg)

**What it is:** Full logo with text for headers and documentation

**How to edit:**

1. **Change text:**
```xml
<!-- Line ~45 -->
<text x="80" y="35" ...>Visual</text>  <!-- Change "Visual" -->
<text x="80" y="57" ...>Mapper</text>  <!-- Change "Mapper" -->
<text x="80" y="68" ...>ANDROID DEVICE MONITOR</text>  <!-- Change tagline -->
```

2. **Change colors:**
```xml
<text ... fill="#1e293b">Visual</text>     <!-- Top text color -->
<text ... fill="#3b82f6">Mapper</text>     <!-- Bottom text color -->
<text ... fill="#64748b">TAGLINE</text>    <!-- Tagline color -->
```

3. **Adjust spacing:**
   - Change `y` values to move text up/down
   - Change `x` values to move text left/right

---

### Social Preview (branding/social-preview.svg)

**What it is:** Image shown when sharing on Twitter, Facebook, etc.

**Key sections to edit:**

1. **Title (Line ~68):**
```xml
<text x="0" y="0" font-size="72" fill="#ffffff">
  Visual Mapper  <!-- Change this -->
</text>
```

2. **Subtitle (Line ~73):**
```xml
<text x="0" y="60" font-size="32" fill="#93c5fd">
  Android Device Monitor  <!-- Change this -->
</text>
```

3. **Features (Lines ~79-98):**
```xml
<text x="25" y="8" ...>Visual Element Detection</text>
<text x="25" y="58" ...>Screenshot Stitching</text>
<text x="25" y="108" ...>Home Assistant Integration</text>
```

4. **Version badge (Line ~104):**
```xml
<text x="60" y="288" ...>v0.0.4</text>  <!-- Auto-updated by script -->
```

**Testing:**
- View: `http://localhost:3000/branding/social-preview.svg`
- Validate: Use [Twitter Card Validator](https://cards-dev.twitter.com/validator) or [Facebook Debugger](https://developers.facebook.com/tools/debug/)

---

## Customizing Colors Across All Icons

To change the color scheme for all branding:

### 1. Choose Your Colors

Pick colors for:
- **Primary**: Main brand color (used in gradients, backgrounds)
- **Accent**: Highlight color (for interactive elements)
- **Text**: Dark color for text

Example palettes:

**Green theme:**
```
Primary: #10b981 (emerald)
Accent: #f59e0b (amber)
```

**Purple theme:**
```
Primary: #8b5cf6 (purple)
Accent: #ec4899 (pink)
```

### 2. Find & Replace in SVG Files

Use your code editor's find/replace across files:

**In:** `www/favicon.svg`, `www/apple-touch-icon.svg`, `www/branding/*.svg`

**Replace:**
```
Find: #3b82f6  →  Replace: YOUR_PRIMARY_COLOR
Find: #2563eb  →  Replace: YOUR_PRIMARY_DARK
Find: #ec4899  →  Replace: YOUR_ACCENT_COLOR
```

### 3. Update Theme Color in HTML

Edit all HTML files' `<head>`:
```html
<meta name="theme-color" content="#3b82f6">
```

---

## Creating Custom Sizes/Formats

### Convert SVG to PNG

If you need PNG versions (for older systems):

```bash
# Using ImageMagick (install first: https://imagemagick.org/)

# Favicon - 32x32 PNG
magick -background none -density 300 www/favicon.svg -resize 32x32 www/favicon-32.png

# Apple Touch Icon - 180x180 PNG
magick -background none -density 300 www/apple-touch-icon.svg -resize 180x180 www/apple-touch-icon-180.png

# Social Preview - 1200x630 PNG
magick -background none -density 300 www/branding/social-preview.svg -resize 1200x630 www/branding/social-preview.png
```

### Convert SVG to ICO (for Windows)

```bash
# Create multi-size ICO file
magick -background none -density 300 www/favicon.svg -define icon:auto-resize=64,48,32,16 www/favicon.ico
```

Then add to HTML:
```html
<link rel="icon" href="favicon.ico" sizes="any">
```

---

## Advanced Customization

### Change Icon Design

The current icon shows a smartphone with a grid and crosshair. To create a different design:

1. **Use a vector graphics editor:**
   - Free: [Inkscape](https://inkscape.org/)
   - Free online: [Figma](https://figma.com)
   - Paid: Adobe Illustrator

2. **Design guidelines:**
   - Canvas: 64x64 pixels (favicon) or 128x128 (icon-only)
   - Export as SVG
   - Keep it simple - complex details don't show at small sizes
   - Use solid colors and gradients
   - Maintain good contrast

3. **Export settings:**
   - Format: Plain SVG (not Inkscape SVG)
   - Viewbox: `0 0 64 64` (for favicon)
   - No embedded images - vectors only

### Add Animated Icons

For loading states or special effects:

```svg
<!-- Add to any SVG file -->
<circle cx="32" cy="32" r="20" fill="none" stroke="#3b82f6" stroke-width="2">
  <animate attributeName="r" from="15" to="25" dur="1s" repeatCount="indefinite" />
  <animate attributeName="opacity" from="1" to="0" dur="1s" repeatCount="indefinite" />
</circle>
```

---

## Checklist: After Making Changes

- [ ] View all SVG files in browser to verify rendering
- [ ] Hard refresh (Ctrl+Shift+R) to clear cache
- [ ] Test favicon in different browsers
- [ ] Check social preview with validator tools
- [ ] Verify colors meet accessibility contrast requirements
- [ ] Update version number if significant changes
- [ ] Commit changes to git

---

## Troubleshooting

### Icons not updating in browser?

**Clear browser cache:**
- Chrome: Ctrl+Shift+Delete → Clear images and files
- Firefox: Ctrl+Shift+Delete → Cache
- Or hard refresh: Ctrl+Shift+R

### SVG rendering incorrectly?

**Validate SVG:**
- Use [SVG Validator](https://validator.w3.org/)
- Check for syntax errors
- Ensure no external dependencies

### Colors look wrong?

**Check color format:**
- Use hex: `#3b82f6` ✅
- Not RGB function: `rgb(59, 130, 246)` ❌ (in SVG attributes)

---

## Need Help?

- **SVG Documentation:** https://developer.mozilla.org/en-US/docs/Web/SVG
- **Web App Manifest:** https://developer.mozilla.org/en-US/docs/Web/Manifest
- **Open Graph Tags:** https://ogp.me/

---

**Last Updated:** 2025-12-27
