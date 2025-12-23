# Live Streaming Implementation Plan

**Purpose:** Step-by-step plan for implementing live streaming with overlays.

**Starting Version:** 0.0.5 (Phase 4)
**Last Updated:** 2025-12-21

---

## 🎯 Goal

**Achieve <100ms latency live streaming with interactive UI element overlays.**

---

## 📋 Implementation Phases

### **Phase 4.1: ws-scrcpy Integration**

**Tasks:**
- [ ] Install ws-scrcpy as backend dependency
- [ ] Configure ws-scrcpy server (port 8100)
- [ ] Test standalone video streaming
- [ ] Integrate with FastAPI backend
- [ ] Update nginx config for WebRTC proxy

**Success Criteria:**
- Can view live stream in browser
- Latency <100ms
- 30 FPS achieved

### **Phase 4.2: UI Element WebSocket**

**Tasks:**
- [ ] Create separate WebSocket endpoint for UI data
- [ ] Stream UI elements at 10 FPS (lighter than video)
- [ ] Synchronize timestamps with video
- [ ] Handle connection drops gracefully

**Success Criteria:**
- UI elements update in real-time
- Synchronized with video stream
- Low CPU usage (<10%)

### **Phase 4.3: Canvas Compositor**

**Tasks:**
- [ ] Create canvas overlay renderer
- [ ] Composite video + UI elements
- [ ] Implement 60 FPS render loop
- [ ] Add visual styles (boxes, labels)
- [ ] Optimize rendering performance

**Success Criteria:**
- Smooth 60 FPS rendering
- No visual artifacts
- <40% client CPU usage

### **Phase 4.4: Interactive Overlays**

**Tasks:**
- [ ] Add click detection on canvas
- [ ] Map click coords to device coords
- [ ] Send tap commands to device
- [ ] Visual feedback on click
- [ ] Hover highlighting

**Success Criteria:**
- Can click UI elements
- Visual feedback immediate
- Commands execute correctly

---

## 🔧 Architecture

```javascript
// Frontend: live-stream.html

class LiveStreamManager {
    constructor() {
        this.video = document.getElementById('stream-video');
        this.canvas = document.getElementById('stream-canvas');
        this.ctx = this.canvas.getContext('2d');

        this.wsUI = null;  // WebSocket for UI elements
        this.uiElements = [];
        this.coordMapper = new CoordinateMapper();
    }

    async start(deviceId) {
        // 1. Start WebRTC video stream (ws-scrcpy)
        await this.startVideoStream(deviceId);

        // 2. Start WebSocket for UI elements
        this.startUIStream(deviceId);

        // 3. Start render loop
        this.startRenderLoop();

        // 4. Setup click handlers
        this.setupClickHandlers();
    }

    async startVideoStream(deviceId) {
        // ws-scrcpy WebRTC connection
        const apiBase = getApiBase();
        this.video.src = `${apiBase}/stream/${deviceId}`;

        await new Promise(resolve => {
            this.video.onloadedmetadata = resolve;
        });

        console.log('[LiveStream] Video started');
    }

    startUIStream(deviceId) {
        const apiBase = getApiBase();
        const wsUrl = apiBase.replace('http', 'ws') + `/ws/ui-elements/${deviceId}`;

        this.wsUI = new WebSocket(wsUrl);

        this.wsUI.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'ui-update') {
                this.uiElements = data.elements;
            }
        };
    }

    startRenderLoop() {
        const render = () => {
            // Clear canvas
            this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

            // Draw video frame
            if (this.video.readyState === this.video.HAVE_ENOUGH_DATA) {
                this.ctx.drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height);
            }

            // Update coordinate mapper
            this.coordMapper.setScale(
                this.canvas.width,
                this.canvas.height,
                this.video.videoWidth,
                this.video.videoHeight
            );

            // Draw UI element overlays
            this.drawUIElements();

            // Continue loop
            requestAnimationFrame(render);
        };

        requestAnimationFrame(render);
    }

    drawUIElements() {
        this.uiElements.forEach(el => {
            if (!el.visible || !el.bounds) return;

            // Convert device coords to display coords
            const display = this.coordMapper.deviceToDisplay(
                el.bounds.x,
                el.bounds.y
            );
            const displayEnd = this.coordMapper.deviceToDisplay(
                el.bounds.x + el.bounds.width,
                el.bounds.y + el.bounds.height
            );

            const x = display.x;
            const y = display.y;
            const w = displayEnd.x - display.x;
            const h = displayEnd.y - display.y;

            // Draw box
            this.ctx.strokeStyle = el.clickable ? '#00ff00' : 'rgba(255,255,0,0.5)';
            this.ctx.lineWidth = 2;
            this.ctx.strokeRect(x, y, w, h);

            // Draw text label
            if (el.text) {
                this.ctx.fillStyle = 'rgba(0,0,0,0.7)';
                this.ctx.fillRect(x, y - 20, Math.min(w, 200), 20);

                this.ctx.fillStyle = '#ffffff';
                this.ctx.font = '12px monospace';
                this.ctx.fillText(el.text.substring(0, 20), x + 2, y - 5);
            }
        });
    }

    setupClickHandlers() {
        this.canvas.addEventListener('click', async (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const displayX = e.clientX - rect.left;
            const displayY = e.clientY - rect.top;

            // Convert to device coordinates
            const deviceCoords = this.coordMapper.displayToDevice(displayX, displayY);

            console.log('Click:', deviceCoords);

            // Send tap command
            await apiClient.post('/adb/tap', {
                device_id: currentDevice,
                x: deviceCoords.x,
                y: deviceCoords.y
            });

            // Visual feedback
            this.showClickFeedback(displayX, displayY);
        });
    }

    showClickFeedback(x, y) {
        // Draw temporary circle
        this.ctx.strokeStyle = '#ff0000';
        this.ctx.lineWidth = 3;
        this.ctx.beginPath();
        this.ctx.arc(x, y, 20, 0, 2 * Math.PI);
        this.ctx.stroke();
    }
}
```

---

## 🐍 Backend Integration

```python
# server.py additions

# WebSocket for UI elements only (lighter than video)
@app.websocket("/ws/ui-elements/{device_id}")
async def ui_elements_stream(websocket: WebSocket, device_id: str):
    await websocket.accept()

    try:
        while True:
            # Extract UI elements (10 FPS, not 30)
            elements = await adb_bridge.get_ui_elements(device_id)

            await websocket.send_json({
                "type": "ui-update",
                "elements": elements,
                "timestamp": datetime.now().isoformat()
            })

            # 10 FPS (UI doesn't need 30)
            await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        print(f"[WS-UI] Disconnected: {device_id}")
```

---

## 📊 Performance Optimization

### **Video Stream**
- Use H.264 hardware encoding
- 30 FPS, 1080p max
- WebRTC adaptive bitrate

### **UI Stream**
- Only 10 FPS (sufficient for overlays)
- JSON compression
- Only send visible elements

### **Canvas Rendering**
- 60 FPS render loop
- Only redraw when changed
- Use offscreen canvas for complex rendering

---

## 🧪 Testing Plan

### **Unit Tests**
- CoordinateMapper accuracy
- UI element parsing
- Click detection logic

### **Integration Tests**
- WebRTC connection
- WebSocket connection
- Synchronization

### **E2E Tests**
- Full streaming flow
- Click-through interaction
- Performance metrics

---

## 📚 Related Documentation

- [30_LIVE_STREAMING_RESEARCH.md](30_LIVE_STREAMING_RESEARCH.md) - Research findings
- [23_CODE_PATTERN_COORDINATE_MAPPING.md](23_CODE_PATTERN_COORDINATE_MAPPING.md) - Coordinate conversion
- [NEW_PROJECT_PLAN.md](NEW_PROJECT_PLAN.md) - Phase 4 details

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.5+

**Read Previous:** [30_LIVE_STREAMING_RESEARCH.md](30_LIVE_STREAMING_RESEARCH.md)
