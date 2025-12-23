# Live Streaming Research - WebRTC vs WebSocket

**Purpose:** Research findings for implementing low-latency live streaming.

**Starting Version:** 0.0.5 (Phase 4)
**Last Updated:** 2025-12-21

---

## 🎯 Research Question

**How to achieve <100ms latency live streaming from Android with interactive overlays?**

---

## 📊 Comparison: WebRTC vs WebSocket

| Feature | WebSocket | WebRTC | Hybrid |
|---------|-----------|--------|--------|
| **Latency** | 200-500ms | <100ms | <100ms |
| **Protocol** | TCP | UDP | Both |
| **Bandwidth** | High | Optimized | Optimized |
| **Complexity** | Low | High | Medium |
| **Browser Support** | 100% | 95%+ | 95%+ |
| **NAT Traversal** | N/A | Built-in | Built-in |
| **Video Codec** | Base64 PNG | H.264 | H.264 |
| **Overlay Support** | Native | Canvas | Canvas |

---

## ✅ Recommended: Hybrid Architecture

**WebRTC for Video + WebSocket for UI Elements**

### **Why Hybrid?**

1. **WebRTC** - Low latency video (H.264)
   - UDP-based, handles packet loss
   - Built-in congestion control
   - Hardware acceleration

2. **WebSocket** - UI element overlays
   - Reliable delivery (TCP)
   - JSON-friendly
   - Easier to implement

3. **Canvas** - Composite rendering
   - drawImage() for video
   - Overlay UI elements
   - Interactive click-through

---

## 🔧 Architecture Design

```
┌─────────────────────────────────────────┐
│           Android Device                 │
│                                          │
│  ┌────────────┐      ┌────────────┐    │
│  │  screencap │      │ uiautomator│    │
│  │  (video)   │      │  (UI data) │    │
│  └─────┬──────┘      └──────┬─────┘    │
│        │                    │           │
└────────┼────────────────────┼───────────┘
         │                    │
         │ H.264              │ JSON
         │                    │
┌────────┼────────────────────┼───────────┐
│  Backend (FastAPI + ws-scrcpy)          │
│        │                    │           │
│  ┌─────▼──────┐      ┌──────▼─────┐    │
│  │  WebRTC    │      │ WebSocket  │    │
│  │  Server    │      │   Server   │    │
│  └─────┬──────┘      └──────┬─────┘    │
└────────┼────────────────────┼───────────┘
         │                    │
         │ WebRTC             │ WebSocket
         │ (video)            │ (UI data)
         │                    │
┌────────┼────────────────────┼───────────┐
│  Frontend (Browser)                     │
│        │                    │           │
│  ┌─────▼──────┐      ┌──────▼─────┐    │
│  │  <video>   │      │  UI Data   │    │
│  │  element   │      │  Handler   │    │
│  └─────┬──────┘      └──────┬─────┘    │
│        │                    │           │
│        └────────┬───────────┘           │
│                 │                       │
│          ┌──────▼────────┐              │
│          │   <canvas>    │              │
│          │  Compositor   │              │
│          └───────────────┘              │
└─────────────────────────────────────────┘
```

---

## 🔬 Research Findings

### **1. scrcpy Analysis**

**What is scrcpy?**
- Open-source Android screen mirror
- <100ms latency achieved
- Uses H.264 video encoding
- ADB-based

**Key Techniques:**
- Direct H.264 encoding on device
- UDP streaming (low latency)
- OpenGL for overlays (desktop only)
- Keyboard/mouse input forwarding

**Lesson:** Use H.264, not PNG streaming

### **2. ws-scrcpy**

**What is ws-scrcpy?**
- Web-based scrcpy implementation
- WebSocket + Broadway.js decoder
- Works in browsers

**Architecture:**
```
Android → H.264 → ws-scrcpy → WebSocket → Broadway.js → Canvas
```

**Lesson:** Can integrate with our FastAPI backend

### **3. Canvas Overlay Rendering**

**Technique from research:**

```javascript
// Render loop (60 FPS)
function render() {
    // Draw video frame
    ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height);

    // Draw UI element overlays
    uiElements.forEach(el => {
        if (!el.visible) return;

        // Draw box
        ctx.strokeStyle = el.clickable ? '#00ff00' : '#ffff00';
        ctx.strokeRect(el.x, el.y, el.width, el.height);

        // Draw label
        if (el.text) {
            ctx.fillStyle = '#ffffff';
            ctx.fillText(el.text, el.x, el.y - 5);
        }
    });

    requestAnimationFrame(render);
}
```

**Lesson:** requestAnimationFrame() for smooth rendering

---

## 📈 Performance Targets

| Metric | Target | How to Achieve |
|--------|--------|----------------|
| Latency | <100ms | WebRTC UDP streaming |
| FPS | 30 FPS | H.264 encoding, 30fps capture |
| Bandwidth | <5 Mbps | H.264 compression |
| CPU (device) | <20% | Hardware H.264 encoder |
| CPU (server) | <30% | Passthrough (no re-encode) |
| CPU (client) | <40% | Hardware video decode |

---

## 🛠️ Implementation Options

### **Option 1: ws-scrcpy Integration** ⭐ Recommended

**Pros:**
- Already implements WebRTC
- Proven low latency
- Active development
- Open source

**Cons:**
- External dependency
- Need to add overlay support

**Effort:** Medium

### **Option 2: Custom WebRTC Implementation**

**Pros:**
- Full control
- Tailored to our needs

**Cons:**
- High complexity
- WebRTC signaling required
- STUN/TURN servers needed

**Effort:** High

### **Option 3: Pure WebSocket (Current)**

**Pros:**
- Simple
- Already implemented

**Cons:**
- High latency (>200ms)
- High bandwidth
- Poor performance

**Effort:** Low (but limited results)

---

## ✅ Recommendation

**Use Hybrid: ws-scrcpy (WebRTC) + Custom WebSocket (UI)**

**Implementation Plan:**
1. Integrate ws-scrcpy for video streaming
2. Keep existing WebSocket for UI elements
3. Canvas compositor in frontend
4. Interactive overlay with click-through

**See:** [31_LIVE_STREAMING_IMPLEMENTATION.md](31_LIVE_STREAMING_IMPLEMENTATION.md) for detailed plan

---

## 📚 References

**Research Sources:**
- scrcpy: https://github.com/Genymobile/scrcpy
- ws-scrcpy: https://github.com/NetrisTV/ws-scrcpy
- WebRTC Best Practices: MDN Web Docs
- Canvas Performance: HTML5 Rocks
- Android screencap: Android Developer Docs

---

## 📝 Next Steps

1. Read [31_LIVE_STREAMING_IMPLEMENTATION.md](31_LIVE_STREAMING_IMPLEMENTATION.md)
2. Plan Phase 4 integration
3. Test ws-scrcpy standalone
4. Implement overlay compositor
5. Add click-through support

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.5+

**Read Next:** [31_LIVE_STREAMING_IMPLEMENTATION.md](31_LIVE_STREAMING_IMPLEMENTATION.md)
