# Branding Assets

## Current Assets

This directory contains placeholder branding assets for the Visual Mapper Home Assistant add-on:

- **icon.svg** - Add-on icon (256x256) - Android robot with phone screen
- **logo.svg** - Add-on logo (512x256) - Full branding with text

### Converting to PNG

For Home Assistant add-on requirements, you'll need PNG versions:

```bash
# Using ImageMagick or similar tool
convert icon.svg -resize 256x256 icon.png
convert logo.svg -resize 512x256 logo.png
```

Or use online converters like:
- https://cloudconvert.com/svg-to-png
- https://convertio.co/svg-png/

## Design Guidelines

### Colors

- **Primary Green:** #3DDC84 (Android green)
- **Primary Blue:** #2196F3 (Material blue)
- **Background Dark:** #1A1A1A
- **Text White:** #FFFFFF
- **Text Gray:** #9E9E9E

### Icon Requirements

- **Size:** 256x256 pixels
- **Format:** PNG with transparency
- **Content:** Should represent Android device control/monitoring
- **Current design:** Android robot with phone screen overlay

### Logo Requirements

- **Size:** 512x256 pixels (or wider)
- **Format:** PNG with transparency
- **Content:** Brand name + tagline + icon
- **Current text:** "Visual Mapper" with "Android Device Control for Home Assistant"

## Future Improvements

Consider professional design for:

1. **Icon variants:**
   - Light theme version
   - Dark theme version
   - Monochrome version

2. **Logo variations:**
   - Horizontal layout (current)
   - Vertical layout (stacked)
   - Icon-only version
   - Text-only version

3. **Additional assets:**
   - Favicon (16x16, 32x32)
   - App store screenshots
   - Social media banners
   - Documentation headers

## Usage

**Home Assistant Add-on:**
- Icon appears in add-on store
- Logo used in add-on documentation
- Referenced in [config.yaml](config.yaml:37) via `panel_icon: mdi:android` (using MDI icon for now)

**Future:**
- Can be embedded in add-on UI
- Used in GitHub repository
- Featured in documentation

---

**Note:** Current assets are functional placeholders. Consider hiring a designer or using tools like Canva/Figma for professional branding before v1.0.0 release.
