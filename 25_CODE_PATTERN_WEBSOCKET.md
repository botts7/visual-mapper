# Code Pattern: WebSocket Streaming

**Purpose:** Real-time streaming from Android device.

**Starting Version:** 0.0.5 (Phase 4)
**Last Updated:** 2025-12-21

---

## ⚠️ LEGACY REFERENCE - Test Before Using!

WebSocket existed in beta.X but live streaming never worked properly. Needs WebRTC integration (see 30-31 docs).

---

## 🎯 Basic WebSocket Pattern

**⚠️ LEGACY REFERENCE:**

### **Backend (FastAPI)**

```python
@app.websocket("/ws/stream/{device_id}")
async def stream_endpoint(websocket: WebSocket, device_id: str):
    await websocket.accept()

    try:
        while True:
            # Capture frame
            screenshot = await adb_bridge.capture_screenshot(device_id)
            elements = await adb_bridge.get_ui_elements(device_id)

            # Send JSON message
            await websocket.send_json({
                "type": "frame",
                "screenshot": base64.b64encode(screenshot).decode(),
                "elements": elements,
                "timestamp": datetime.now().isoformat()
            })

            # 30 FPS
            await asyncio.sleep(1/30)

    except WebSocketDisconnect:
        print(f"[WS] Client disconnected: {device_id}")
```

### **Frontend (JavaScript)**

```javascript
class WebSocketClient {
    constructor(deviceId) {
        this.deviceId = deviceId;
        this.ws = null;
        this.onFrame = null;
    }

    connect() {
        const apiBase = getApiBase();
        const wsUrl = apiBase.replace('http', 'ws') + `/ws/stream/${this.deviceId}`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('[WS] Connected');
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'frame' && this.onFrame) {
                this.onFrame(data);
            }
        };

        this.ws.onerror = (error) => {
            console.error('[WS] Error:', error);
        };

        this.ws.onclose = () => {
            console.log('[WS] Closed');
        };
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
        }
    }
}

export default WebSocketClient;
window.WebSocketClient = WebSocketClient;
```

---

## 🚨 Legacy Issues

**Problems in beta.X:**
1. High latency (>500ms)
2. Frame drops
3. No overlay rendering
4. Bandwidth issues

**Solution:** See [30_LIVE_STREAMING_RESEARCH.md](30_LIVE_STREAMING_RESEARCH.md) for WebRTC approach.

---

## 📚 Related Documentation

- [30_LIVE_STREAMING_RESEARCH.md](30_LIVE_STREAMING_RESEARCH.md) - WebRTC research
- [31_LIVE_STREAMING_IMPLEMENTATION.md](31_LIVE_STREAMING_IMPLEMENTATION.md) - Implementation plan

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.5+
