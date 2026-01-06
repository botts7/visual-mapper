# Visual Mapper Branding Assets

This directory contains all branding and visual identity assets for Visual Mapper.

## Files Overview

### Icons

**favicon.svg** (64x64)
- Main favicon used across the website
- Optimized for browser tabs and bookmarks
- Features: Smartphone with grid overlay and targeting crosshair

**apple-touch-icon.svg** (180x180)
- Apple touch icon for iOS/iPadOS home screen
- Also used by some Android launchers
- No border radius (iOS applies it automatically)

**icon-only.svg** (128x128)
- High-resolution icon without text
- For use in app stores, PWA manifests, etc.
- Clean, scalable design

### Logos

**logo-horizontal.svg** (320x80)
- Full horizontal logo with text "Visual Mapper"
- Includes tagline "ANDROID DEVICE MONITOR"
- Best for: Headers, email signatures, documentation

### Social Media

**social-preview.svg** (1200x630)
- Open Graph / Twitter Card image
- Optimized for social media sharing
- Includes icon, title, features, and version badge
- Features highlighted:
  - Visual Element Detection
  - Screenshot Stitching
  - Home Assistant Integration

## Brand Colors

### Primary Colors
- **Primary Blue**: `#3b82f6` (rgb(59, 130, 246))
- **Dark Blue**: `#2563eb` (rgb(37, 99, 235))
- **Navy Blue**: `#1e40af` (rgb(30, 64, 175))

### Accent Colors
- **Pink/Magenta**: `#ec4899` (rgb(236, 72, 153)) - Used for highlights
- **Light Blue**: `#60a5fa` (rgb(96, 165, 250)) - Used for grid overlays
- **Green**: `#10b981` (rgb(16, 185, 129)) - Used for success states

### Neutral Colors
- **Dark Gray**: `#1e293b` (rgb(30, 41, 59))
- **Medium Gray**: `#64748b` (rgb(100, 116, 139))
- **Light Gray**: `#94a3b8` (rgb(148, 163, 184))
- **Very Light**: `#e5e7eb` (rgb(229, 231, 235))

## Typography

**Primary Font**: Arial, sans-serif
- **Headings**: 700 weight (Bold)
- **Body**: 400 weight (Regular)
- **Captions**: 400 weight, smaller size

## Icon Design Elements

### Core Concept
The Visual Mapper icon represents:
1. **Smartphone Device**: The target platform (Android)
2. **Grid Overlay**: Visual mapping and element detection
3. **Crosshair Target**: Precision targeting of UI elements
4. **Highlighted Element**: Pink square showing active selection

### Visual Hierarchy
- Blue gradient background (brand identity)
- White/gray device (contrast)
- Dark screen (depth)
- Light blue grid (subtle overlay)
- Pink highlight (attention grabber)
- White crosshair (focus point)

## Usage Guidelines

### Favicon
```html
<link rel="icon" type="image/svg+xml" href="favicon.svg">
```

### Apple Touch Icon
```html
<link rel="apple-touch-icon" href="apple-touch-icon.svg">
```

### Social Media Tags
```html
<!-- Open Graph -->
<meta property="og:image" content="branding/social-preview.svg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="branding/social-preview.svg">
```

### Logo in Documentation
```markdown
![Visual Mapper](branding/logo-horizontal.svg)
```

## File Formats

All assets are provided in **SVG format** for:
- ✅ Infinite scalability
- ✅ Small file size
- ✅ Sharp rendering at any resolution
- ✅ Easy editing and customization

### Converting to PNG/ICO
If you need raster formats:

```bash
# Using ImageMagick or similar tool
convert -background none -density 300 favicon.svg -resize 32x32 favicon-32.png
convert -background none -density 300 apple-touch-icon.svg -resize 180x180 apple-touch-icon-180.png
```

## Version History

**v0.0.5** - 2025-12-27
- Initial branding package created
- Modern gradient-based design
- Smartphone + grid concept
- Full suite of web/social assets

## Design Philosophy

Visual Mapper's branding emphasizes:
- **Precision**: Crosshair and grid show accuracy
- **Technology**: Modern gradients and clean lines
- **Clarity**: High contrast, clear iconography
- **Trust**: Professional blue color palette
- **Action**: Pink accent for interactive elements

---

**Last Updated**: 2025-12-27
**Version**: 0.0.4
