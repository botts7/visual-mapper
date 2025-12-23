# Code Pattern: Coordinate Mapping

**Purpose:** Convert between display coordinates and device coordinates.

**Starting Version:** 0.0.3 (Phase 2)
**Last Updated:** 2025-12-21

---

## ⚠️ LEGACY REFERENCE - Test Before Using!

This pattern worked in v4.6.0-beta.X but had offset bugs. Validate carefully.

---

## 🎯 The Problem

**Canvas size ≠ Screenshot size:**

```
Canvas:      800x600
Screenshot:  1080x1920

User clicks at canvas (400, 300)
Device needs: (540, 960)  // Scaled coordinates
```

---

## ✅ The Solution

**⚠️ LEGACY REFERENCE:**

```javascript
class CoordinateMapper {
    constructor() {
        this.scale = 1.0;
        this.offsetX = 0;
        this.offsetY = 0;
        this.imageWidth = 0;
        this.imageHeight = 0;
    }

    setScale(canvasWidth, canvasHeight, imageWidth, imageHeight) {
        this.imageWidth = imageWidth;
        this.imageHeight = imageHeight;

        // Calculate scale to fit (maintain aspect ratio)
        const scaleX = canvasWidth / imageWidth;
        const scaleY = canvasHeight / imageHeight;
        this.scale = Math.min(scaleX, scaleY);

        // Calculate offset to center
        const scaledWidth = imageWidth * this.scale;
        const scaledHeight = imageHeight * this.scale;
        this.offsetX = (canvasWidth - scaledWidth) / 2;
        this.offsetY = (canvasHeight - scaledHeight) / 2;

        console.log('[CoordMapper] Scale:', this.scale);
        console.log('[CoordMapper] Offset:', this.offsetX, this.offsetY);
    }

    // Convert display click → device coordinates
    displayToDevice(x, y) {
        const deviceX = Math.round((x - this.offsetX) / this.scale);
        const deviceY = Math.round((y - this.offsetY) / this.scale);

        // Clamp to image bounds
        return {
            x: Math.max(0, Math.min(deviceX, this.imageWidth)),
            y: Math.max(0, Math.min(deviceY, this.imageHeight))
        };
    }

    // Convert device coordinates → display position
    deviceToDisplay(x, y) {
        return {
            x: Math.round((x * this.scale) + this.offsetX),
            y: Math.round((y * this.scale) + this.offsetY)
        };
    }
}

export default CoordinateMapper;
window.CoordinateMapper = CoordinateMapper;
```

---

## 🔧 Usage Example

```javascript
// Setup
const mapper = new CoordinateMapper();
const canvas = document.getElementById('screenshot-canvas');
const img = new Image();

img.onload = () => {
    // Set scale based on canvas and image sizes
    mapper.setScale(
        canvas.width,
        canvas.height,
        img.width,
        img.height
    );

    // Draw image
    ctx.drawImage(img, mapper.offsetX, mapper.offsetY,
        img.width * mapper.scale,
        img.height * mapper.scale);
};

// Handle clicks
canvas.addEventListener('click', async (e) => {
    const rect = canvas.getBoundingClientRect();
    const displayX = e.clientX - rect.left;
    const displayY = e.clientY - rect.top;

    // Convert to device coordinates
    const deviceCoords = mapper.displayToDevice(displayX, displayY);

    console.log('Display:', displayX, displayY);
    console.log('Device:', deviceCoords.x, deviceCoords.y);

    // Send tap command
    await apiClient.post('/adb/tap', {
        device_id: currentDevice,
        x: deviceCoords.x,
        y: deviceCoords.y
    });
});
```

---

## 🚨 Legacy Issue: Offset Bug

**Problem in beta.X:** Drawing tools had wrong offset calculation.

**Fix:** Always use the SAME mapper instance for both rendering and input.

---

## 📚 Related Documentation

- [22_CODE_PATTERN_SCREENSHOT.md](22_CODE_PATTERN_SCREENSHOT.md) - Screenshot capture
- [11_FRONTEND_MODULES.md](11_FRONTEND_MODULES.md) - Module system

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.3+
