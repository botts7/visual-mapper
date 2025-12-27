/**
 * ws-scrcpy Client Module
 * Connects to ws-scrcpy server for low-latency H.264 streaming
 * Version: 0.0.2
 *
 * Flow:
 * 1. Connect to device tracker to get device list
 * 2. Find matching device and get its stream URL
 * 3. Request server start if needed
 * 4. Connect to video stream
 */

class ScrcpyClient {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.ws = null;
        this.trackerWs = null;
        this.deviceId = null;
        this.isConnected = false;
        this.isActive = false;
        this.scrcpyBaseUrl = 'ws://localhost:8000';

        // Video decoder
        this.decoder = null;
        this.useWebCodecs = 'VideoDecoder' in window;

        // Device info from initial frame
        this.deviceName = '';
        this.screenWidth = 0;
        this.screenHeight = 0;
        this.scrcpyDevice = null; // ws-scrcpy device descriptor

        // Metrics
        this.frameCount = 0;
        this.lastFrameTime = 0;
        this.fps = 0;
        this.fpsCounter = 0;
        this.fpsInterval = null;

        // Callbacks
        this.onConnect = null;
        this.onDisconnect = null;
        this.onError = null;
        this.onFrame = null;
        this.onMetricsUpdate = null;

        // Frame buffer for rendering
        this.pendingFrame = null;

        // H.264 parsing state
        this.nalBuffer = [];
        this.receivedInitial = false;

        console.log('[ScrcpyClient] Initialized, WebCodecs:', this.useWebCodecs);
    }

    /**
     * Start streaming from device via ws-scrcpy
     */
    start(deviceId, scrcpyUrl = 'ws://localhost:8000') {
        if (this.isActive) {
            console.warn('[ScrcpyClient] Already active');
            return;
        }

        this.deviceId = deviceId;
        this.scrcpyBaseUrl = scrcpyUrl;
        this.isActive = true;
        this.receivedInitial = false;

        console.log('[ScrcpyClient] Starting for device:', deviceId);

        // Step 1: Connect to device tracker to find device and start server
        this._connectToTracker();
    }

    /**
     * Connect to ws-scrcpy device tracker to get device list
     */
    _connectToTracker() {
        const trackerUrl = `${this.scrcpyBaseUrl}/?action=goog-device-list`;
        console.log('[ScrcpyClient] Connecting to device tracker:', trackerUrl);

        try {
            this.trackerWs = new WebSocket(trackerUrl);

            this.trackerWs.onopen = () => {
                console.log('[ScrcpyClient] Tracker connected, waiting for device list...');
            };

            this.trackerWs.onmessage = (e) => {
                try {
                    const msg = JSON.parse(e.data);
                    console.log('[ScrcpyClient] Tracker message:', msg.type);

                    if (msg.type === 'devicelist') {
                        this._handleDeviceList(msg.data);
                    } else if (msg.type === 'device') {
                        // Single device update
                        this._handleDeviceUpdate(msg.data);
                    }
                } catch (err) {
                    console.error('[ScrcpyClient] Tracker parse error:', err);
                }
            };

            this.trackerWs.onerror = (e) => {
                console.error('[ScrcpyClient] Tracker error:', e);
                if (this.onError) {
                    this.onError(new Error('Failed to connect to ws-scrcpy device tracker'));
                }
            };

            this.trackerWs.onclose = () => {
                console.log('[ScrcpyClient] Tracker closed');
            };

        } catch (error) {
            console.error('[ScrcpyClient] Tracker connection error:', error);
            this.isActive = false;
            if (this.onError) this.onError(error);
        }
    }

    /**
     * Handle device list from tracker
     */
    _handleDeviceList(data) {
        const devices = data.list || [];
        console.log('[ScrcpyClient] Received device list:', devices.length, 'devices');

        // Find matching device by udid
        const device = devices.find(d => d.udid === this.deviceId);

        if (device) {
            console.log('[ScrcpyClient] Found device:', device.udid, 'pid:', device.pid);
            this.scrcpyDevice = device;

            if (device.pid && device.pid !== -1) {
                // Server is running, connect to stream
                this._connectToStream(device);
            } else {
                // Need to start server first
                console.log('[ScrcpyClient] Server not running, requesting start...');
                this._requestServerStart(device.udid);
            }
        } else {
            console.error('[ScrcpyClient] Device not found in ws-scrcpy:', this.deviceId);
            console.log('[ScrcpyClient] Available devices:', devices.map(d => d.udid));

            if (this.onError) {
                this.onError(new Error(`Device ${this.deviceId} not found in ws-scrcpy. Make sure the device is connected.`));
            }
            this.stop();
        }
    }

    /**
     * Handle single device update
     */
    _handleDeviceUpdate(data) {
        const device = data.device;
        if (device && device.udid === this.deviceId) {
            console.log('[ScrcpyClient] Device updated:', device.udid, 'pid:', device.pid);
            this.scrcpyDevice = device;

            if (device.pid && device.pid !== -1 && !this.ws) {
                // Server just started, connect to stream
                this._connectToStream(device);
            }
        }
    }

    /**
     * Request server start via tracker WebSocket
     */
    _requestServerStart(udid) {
        if (!this.trackerWs || this.trackerWs.readyState !== WebSocket.OPEN) {
            console.error('[ScrcpyClient] Tracker not connected');
            return;
        }

        const msg = {
            id: Date.now(),
            type: 'start-server',
            data: { udid }
        };

        console.log('[ScrcpyClient] Sending start-server request');
        this.trackerWs.send(JSON.stringify(msg));

        // Wait for device update with pid
        setTimeout(() => {
            if (!this.ws && this.scrcpyDevice && this.scrcpyDevice.pid === -1) {
                console.log('[ScrcpyClient] Server start timeout, retrying...');
                this._requestServerStart(udid);
            }
        }, 3000);
    }

    /**
     * Connect to actual video stream
     */
    _connectToStream(device) {
        // Build stream URL - use proxy through ws-scrcpy
        // Format: ws://host:port/?action=stream&udid=xxx&player=webcodecs&ws=proxyUrl

        // The ws parameter should point to the proxy URL that ws-scrcpy provides
        const proxyUrl = `${this.scrcpyBaseUrl}/?action=proxy-adb&remote=tcp:8886&udid=${encodeURIComponent(device.udid)}`;

        const streamUrl = `${this.scrcpyBaseUrl}/?action=stream&udid=${encodeURIComponent(device.udid)}&player=webcodecs&ws=${encodeURIComponent(proxyUrl)}`;

        console.log('[ScrcpyClient] Connecting to stream:', streamUrl);

        try {
            this.ws = new WebSocket(streamUrl);
            this.ws.binaryType = 'arraybuffer';

            this.ws.onopen = () => this._onOpen();
            this.ws.onmessage = (e) => this._onMessage(e);
            this.ws.onerror = (e) => this._onError(e);
            this.ws.onclose = () => this._onClose();

        } catch (error) {
            console.error('[ScrcpyClient] Stream connection error:', error);
            if (this.onError) this.onError(error);
        }
    }

    /**
     * Stop streaming
     */
    stop() {
        this.isActive = false;

        if (this.trackerWs) {
            this.trackerWs.close();
            this.trackerWs = null;
        }

        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        if (this.decoder) {
            try {
                this.decoder.close();
            } catch (e) {}
            this.decoder = null;
        }

        if (this.fpsInterval) {
            clearInterval(this.fpsInterval);
            this.fpsInterval = null;
        }

        this.isConnected = false;
        this.scrcpyDevice = null;
        console.log('[ScrcpyClient] Stopped');
    }

    /**
     * Send touch event to device
     */
    sendTouch(action, x, y, pointerId = 0) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            console.warn('[ScrcpyClient] Cannot send touch - not connected');
            return false;
        }

        // Touch control message format (29 bytes)
        const buffer = new ArrayBuffer(29);
        const view = new DataView(buffer);

        // Type = 2 (TYPE_TOUCH)
        view.setUint8(0, 2);

        // Action: 0=DOWN, 1=UP, 2=MOVE
        view.setUint8(1, action);

        // Pointer ID (64-bit, split into two 32-bit)
        view.setUint32(2, 0, false); // Upper 32 bits
        view.setUint32(6, pointerId, false); // Lower 32 bits

        // X coordinate
        view.setUint32(10, Math.round(x), false);

        // Y coordinate
        view.setUint32(14, Math.round(y), false);

        // Screen width/height
        view.setUint16(18, this.screenWidth, false);
        view.setUint16(20, this.screenHeight, false);

        // Pressure (0xFFFF = full pressure for DOWN/MOVE, 0 for UP)
        view.setUint16(22, action === 1 ? 0 : 0xFFFF, false);

        // Buttons (0 for touch)
        view.setUint32(24, 0, false);

        // Note: This is 28 bytes, but the format says 29
        // The extra byte might be padding

        this.ws.send(buffer);
        console.log(`[ScrcpyClient] Touch ${['DOWN', 'UP', 'MOVE'][action]} at (${x}, ${y})`);
        return true;
    }

    /**
     * Send tap (touch down + up)
     */
    sendTap(x, y) {
        this.sendTouch(0, x, y); // DOWN
        setTimeout(() => {
            this.sendTouch(1, x, y); // UP
        }, 50);
    }

    /**
     * Send swipe
     */
    sendSwipe(x1, y1, x2, y2, duration = 300) {
        const steps = Math.max(10, Math.floor(duration / 16));
        const dx = (x2 - x1) / steps;
        const dy = (y2 - y1) / steps;

        this.sendTouch(0, x1, y1); // DOWN

        for (let i = 1; i <= steps; i++) {
            setTimeout(() => {
                const x = x1 + dx * i;
                const y = y1 + dy * i;
                this.sendTouch(2, x, y); // MOVE

                if (i === steps) {
                    setTimeout(() => {
                        this.sendTouch(1, x2, y2); // UP
                    }, 16);
                }
            }, i * 16);
        }
    }

    // ========================================
    // Private methods
    // ========================================

    _onOpen() {
        console.log('[ScrcpyClient] WebSocket connected');
        this.isConnected = true;

        // Start FPS counter
        this.fpsInterval = setInterval(() => {
            this.fps = this.fpsCounter;
            this.fpsCounter = 0;
            this._updateMetrics();
        }, 1000);

        if (this.onConnect) this.onConnect();
    }

    _onMessage(event) {
        if (!(event.data instanceof ArrayBuffer)) {
            console.log('[ScrcpyClient] Non-binary message:', event.data);
            return;
        }

        const data = new Uint8Array(event.data);

        // Check for initial frame (starts with "scrcpy_initial")
        if (!this.receivedInitial && data.length > 14) {
            const magic = String.fromCharCode(...data.slice(0, 14));
            if (magic === 'scrcpy_initial') {
                this._parseInitialFrame(data);
                return;
            }
        }

        // Check for device message (starts with "scrcpy_message")
        if (data.length > 14) {
            const magic = String.fromCharCode(...data.slice(0, 14));
            if (magic === 'scrcpy_message') {
                this._parseDeviceMessage(data);
                return;
            }
        }

        // Otherwise it's video data
        this._handleVideoFrame(data);
    }

    _parseInitialFrame(data) {
        console.log('[ScrcpyClient] Received initial frame, length:', data.length);

        try {
            // Skip magic (14 bytes)
            let offset = 14;

            // Device name (64 bytes, null-padded)
            const nameBytes = data.slice(offset, offset + 64);
            this.deviceName = String.fromCharCode(...nameBytes).replace(/\0+$/, '');
            offset += 64;

            console.log('[ScrcpyClient] Device name:', this.deviceName);

            // Parse display info (simplified - just get first display)
            // The format is complex, so we'll use defaults and update on first frame
            this.screenWidth = 1080;
            this.screenHeight = 1920;

            this.receivedInitial = true;

            // Initialize decoder
            this._initDecoder();

        } catch (error) {
            console.error('[ScrcpyClient] Error parsing initial frame:', error);
        }
    }

    _parseDeviceMessage(data) {
        // Skip magic (14 bytes)
        const type = data[14];
        console.log('[ScrcpyClient] Device message type:', type);

        // Type 0 = clipboard, etc.
        // We can ignore most of these for now
    }

    _handleVideoFrame(data) {
        if (!this.decoder) {
            console.warn('[ScrcpyClient] No decoder initialized');
            return;
        }

        this.frameCount++;
        this.fpsCounter++;
        this.lastFrameTime = Date.now();

        // Feed to decoder
        try {
            if (this.useWebCodecs) {
                this._decodeWebCodecs(data);
            } else {
                console.warn('[ScrcpyClient] No fallback decoder implemented');
            }
        } catch (error) {
            console.error('[ScrcpyClient] Decode error:', error);
        }
    }

    _initDecoder() {
        if (this.useWebCodecs) {
            this._initWebCodecsDecoder();
        } else {
            console.error('[ScrcpyClient] WebCodecs not available, fallback not implemented');
            if (this.onError) {
                this.onError(new Error('WebCodecs not supported in this browser'));
            }
        }
    }

    _initWebCodecsDecoder() {
        console.log('[ScrcpyClient] Initializing WebCodecs decoder');

        try {
            this.decoder = new VideoDecoder({
                output: (frame) => this._onDecodedFrame(frame),
                error: (error) => {
                    console.error('[ScrcpyClient] Decoder error:', error);
                }
            });

            // Configure for H.264
            this.decoder.configure({
                codec: 'avc1.42E01E', // H.264 Baseline Profile
                optimizeForLatency: true
            });

            console.log('[ScrcpyClient] WebCodecs decoder initialized');

        } catch (error) {
            console.error('[ScrcpyClient] Failed to init WebCodecs:', error);
            this.useWebCodecs = false;
        }
    }

    _decodeWebCodecs(data) {
        if (!this.decoder || this.decoder.state === 'closed') {
            return;
        }

        try {
            // Create EncodedVideoChunk
            const chunk = new EncodedVideoChunk({
                type: this._isKeyFrame(data) ? 'key' : 'delta',
                timestamp: performance.now() * 1000, // microseconds
                data: data
            });

            this.decoder.decode(chunk);

        } catch (error) {
            // Decoder might need reconfiguration
            if (error.name === 'InvalidStateError') {
                console.warn('[ScrcpyClient] Decoder needs reconfigure');
            }
        }
    }

    _isKeyFrame(data) {
        // Check for H.264 IDR NAL unit (keyframe)
        // NAL unit type is in lower 5 bits of first byte after start code
        for (let i = 0; i < data.length - 4; i++) {
            // Look for start code (0x00 0x00 0x00 0x01 or 0x00 0x00 0x01)
            if (data[i] === 0 && data[i + 1] === 0) {
                let nalStart = -1;
                if (data[i + 2] === 1) {
                    nalStart = i + 3;
                } else if (data[i + 2] === 0 && data[i + 3] === 1) {
                    nalStart = i + 4;
                }

                if (nalStart > 0 && nalStart < data.length) {
                    const nalType = data[nalStart] & 0x1F;
                    // Type 5 = IDR slice (keyframe)
                    // Type 7 = SPS, Type 8 = PPS (also indicate keyframe set)
                    if (nalType === 5 || nalType === 7) {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    _onDecodedFrame(frame) {
        // Update screen dimensions from actual frame
        if (frame.displayWidth !== this.screenWidth || frame.displayHeight !== this.screenHeight) {
            this.screenWidth = frame.displayWidth;
            this.screenHeight = frame.displayHeight;
            this.canvas.width = this.screenWidth;
            this.canvas.height = this.screenHeight;
            console.log(`[ScrcpyClient] Screen size: ${this.screenWidth}x${this.screenHeight}`);
        }

        // Draw frame to canvas
        this.ctx.drawImage(frame, 0, 0);

        // Close the frame to free resources
        frame.close();

        // Callback
        if (this.onFrame) {
            this.onFrame({
                width: this.screenWidth,
                height: this.screenHeight,
                frameCount: this.frameCount
            });
        }
    }

    _onError(error) {
        console.error('[ScrcpyClient] WebSocket error:', error);
        if (this.onError) this.onError(error);
    }

    _onClose() {
        console.log('[ScrcpyClient] WebSocket closed');
        this.isConnected = false;

        if (this.fpsInterval) {
            clearInterval(this.fpsInterval);
            this.fpsInterval = null;
        }

        if (this.isActive) {
            // Unexpected disconnect
            if (this.onDisconnect) this.onDisconnect();
        }

        this.isActive = false;
    }

    _updateMetrics() {
        if (this.onMetricsUpdate) {
            this.onMetricsUpdate({
                fps: this.fps,
                frameCount: this.frameCount,
                latency: 0, // Would need round-trip measurement
                bandwidth: 0 // Would need byte counting
            });
        }
    }
}

// Dual export
export default ScrcpyClient;
if (typeof window !== 'undefined') {
    window.ScrcpyClient = ScrcpyClient;
}
