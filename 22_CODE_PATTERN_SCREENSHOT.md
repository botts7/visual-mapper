# Code Pattern: Screenshot Capture

**Purpose:** Capture Android screenshot with UI elements.

**Starting Version:** 0.0.2 (Phase 1)
**Last Updated:** 2025-12-21

---

## ⚠️ LEGACY REFERENCE - Test Before Using!

This pattern worked in v4.6.0-beta.X but validate thoroughly.

---

## 🎯 Complete Flow

```
User clicks "Capture"
    ↓
Frontend: POST /api/adb/screenshot
    ↓
Backend: screencap -p (PNG bytes)
    ↓
Backend: uiautomator dump (XML)
    ↓
Backend: Parse XML → elements array
    ↓
Frontend: Render PNG on canvas
    ↓
Frontend: Draw element overlays
```

---

## 🔧 Frontend Code

**⚠️ LEGACY REFERENCE:**

```javascript
class ScreenshotCapture {
    constructor(apiClient, canvas) {
        this.apiClient = apiClient;
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.currentImage = null;
        this.elements = [];
    }

    async capture(deviceId) {
        try {
            // Call API
            const response = await this.apiClient.post('/adb/screenshot', {
                device_id: deviceId
            });

            // Decode base64 image
            const img = new Image();
            img.onload = () => {
                this.renderScreenshot(img, response.elements);
            };
            img.src = 'data:image/png;base64,' + response.screenshot;

            this.currentImage = img;
            this.elements = response.elements;

        } catch (error) {
            console.error('[Screenshot] Capture failed:', error);
            alert('Screenshot failed: ' + error.message);
        }
    }

    renderScreenshot(img, elements) {
        // Clear canvas
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Calculate scale to fit
        const scale = Math.min(
            this.canvas.width / img.width,
            this.canvas.height / img.height
        );

        const scaledWidth = img.width * scale;
        const scaledHeight = img.height * scale;
        const offsetX = (this.canvas.width - scaledWidth) / 2;
        const offsetY = (this.canvas.height - scaledHeight) / 2;

        // Draw image
        this.ctx.drawImage(img, offsetX, offsetY, scaledWidth, scaledHeight);

        // Draw element overlays
        this.drawElements(elements, scale, offsetX, offsetY);
    }

    drawElements(elements, scale, offsetX, offsetY) {
        elements.forEach(el => {
            if (!el.visible || !el.bounds) return;

            const x = (el.bounds.x * scale) + offsetX;
            const y = (el.bounds.y * scale) + offsetY;
            const w = el.bounds.width * scale;
            const h = el.bounds.height * scale;

            // Draw box
            this.ctx.strokeStyle = el.clickable ? '#00ff00' : '#ffff00';
            this.ctx.lineWidth = 2;
            this.ctx.strokeRect(x, y, w, h);

            // Draw text label
            if (el.text) {
                this.ctx.fillStyle = '#ffffff';
                this.ctx.fillRect(x, y - 20, w, 20);
                this.ctx.fillStyle = '#000000';
                this.ctx.font = '12px monospace';
                this.ctx.fillText(el.text, x + 2, y - 5);
            }
        });
    }
}

export default ScreenshotCapture;
window.ScreenshotCapture = ScreenshotCapture;
```

---

## 🐍 Backend Code

**⚠️ LEGACY REFERENCE:**

```python
@app.post("/api/adb/screenshot")
async def capture_screenshot(device_id: str):
    try:
        # Capture PNG
        screenshot_bytes = await adb_bridge.capture_screenshot(device_id)

        # Extract UI elements
        elements = await adb_bridge.get_ui_elements(device_id)

        return {
            "screenshot": base64.b64encode(screenshot_bytes).decode(),
            "elements": elements,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 📚 Related Documentation

- [11_FRONTEND_MODULES.md](11_FRONTEND_MODULES.md) - Module system
- [12_BACKEND_API.md](12_BACKEND_API.md) - Backend API
- [23_CODE_PATTERN_COORDINATE_MAPPING.md](23_CODE_PATTERN_COORDINATE_MAPPING.md) - Coordinate conversion

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.2+
