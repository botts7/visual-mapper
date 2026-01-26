/**
 * Visual Mapper - Live Stream Module
 * Version: 0.0.41 (Fix reconnection loop race condition - guard checks in _connect and _scheduleReconnect)
 *
 * WebSocket-based live screenshot streaming with UI element overlays.
 * Supports multiple codecs:
 * - JPEG: Universal compatibility, software decoding
 * - H.264: Hardware-accelerated via WebCodecs (3-5x faster when available)
 *
 * Legacy modes:
 * - websocket: Base64 JSON frames (original)
 * - mjpeg: Binary JPEG frames (~30% less bandwidth)
 *
 * Quality settings:
 * - high: Native resolution (~5 FPS)
 * - medium: 720p (~12 FPS)
 * - low: 480p (~18 FPS)
 * - fast: 360p (~25 FPS)
 * - ultrafast: 240p (~30 FPS) - Optimized for WiFi
 *
 * Fluency settings (adaptive element refresh):
 * - responsive (Fluent): Quick refresh (300ms), reacts fast to screen changes
 * - balanced (Balanced): Medium refresh (500ms), good for most use cases
 * - smooth (Clear): Slow refresh (1000ms), less CPU usage, clearer overlays
 *
 * Features:
 * - Auto-reconnect with exponential backoff
 * - Connection state tracking
 * - Container element filtering
 * - Backend benchmark support via stream_manager
 * - Enhanced quality indicators
 * - FPS performance hints (Phase 3)
 * - Adaptive smart refresh based on FPS
 */

class LiveStream {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.websocket = null;
        this.deviceId = null;
        this.isStreaming = false;

        // Streaming mode: 'websocket' (base64 JSON) or 'mjpeg' (binary)
        this.streamMode = 'websocket';
        this.streamQuality = 'fast'; // 'high', 'medium', 'low', 'fast' - default 'fast' for WiFi compatibility

        // Current state
        this.currentImage = null;
        this.elements = [];

        // Device dimensions (native resolution for element scaling)
        this.deviceWidth = 1080;   // Default, updated when elements are set
        this.deviceHeight = 1920;

        // Performance metrics
        this.metrics = {
            frameCount: 0,
            fps: 0,
            latency: 0,
            captureTime: 0,
            lastFrameTime: 0,
            fpsHistory: [],
            bandwidth: 0,          // KB/s
            bytesReceived: 0,
            bandwidthHistory: []
        };

        // Bandwidth tracking
        this._bandwidthStart = 0;
        this._bandwidthBytes = 0;

        // Auto-reconnect settings
        this.autoReconnect = true;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 20; // Increased for WiFi reliability
        this.reconnectDelay = 1000; // Start with 1 second
        this.maxReconnectDelay = 15000; // Max 15 seconds (reduced for faster retry)
        this._reconnectTimer = null;
        this._manualStop = false;

        // Connection state: 'disconnected', 'connecting', 'connected', 'reconnecting'
        this.connectionState = 'disconnected';

        // Callbacks
        this.onFrame = null;
        this.onConnect = null;
        this.onDisconnect = null;
        this.onError = null;
        this.onMetricsUpdate = null;
        this.onConnectionStateChange = null; // New callback for connection state
        this.onScreenChange = null;          // Smart refresh: fires when screen stabilizes after change
        this.onElementsCleared = null;       // Fires immediately when screen change detected (before stabilization)
        this.onDimensionsChange = null;      // Fires when canvas dimensions change (orientation change)

        // Overlay settings
        this.showOverlays = true;
        this.showTextLabels = true;
        this.hideContainers = true;
        this.hideEmptyElements = true;
        this.hideSmall = true;           // Hide tiny elements (< 20px)
        this.hideDividers = true;        // Hide horizontal line dividers
        this.showClickable = true;       // Show clickable elements
        this.showNonClickable = false;   // Show non-clickable elements
        this.displayMode = 'all';        // 'all', 'hoverOnly', 'topLayer'
        this.hoveredElement = null;      // Currently hovered element (for hoverOnly mode)

        // Element staleness tracking - hide elements when screen content has changed significantly
        this.elementsTimestamp = 0;      // When elements were last fetched
        this.autoHideStaleElements = false; // DISABLED by default - but smartRefreshEnabled handles this
        this.smartRefreshEnabled = true;  // Smart refresh: detect screen changes and fire onScreenChange callback
        this._lastFrameHash = 0;         // Simple hash of last frame for change detection
        this._screenChanged = false;     // True if screen content changed since last element refresh
        this._differentFrameCount = 0;   // Count of consecutive different frames (filters compression noise)
        this._stableFrameCount = 0;      // Count of consecutive same frames (confirms stabilization)
        this._lastScreenChangeCallback = 0;  // Rate limiting for screen change callback
        this._elementsStale = false;     // True when elements should be hidden (screen changed)

        // Adaptive smart refresh settings (configurable via setFluency)
        // These control how responsive element refresh is to screen changes
        this.smartRefreshRateMs = 500;           // Min ms between refresh callbacks (default: balanced)
        this.stableFrameThreshold = 2;           // Frames needed to confirm stabilization (adaptive)
        this.changeFrameThreshold = 2;           // Frames needed to detect change (filters noise)
        this.fluencyMode = 'balanced';           // 'responsive', 'balanced', or 'smooth'

        // OPTIMIZATION: Cache filtered elements to avoid re-filtering every frame
        this._filteredElements = [];
        this._lastElementsRef = null;    // Track when elements array changes
        this._filterSettingsHash = '';   // Track when filter settings change

        // Memory management: track current blob URL to prevent leaks
        this._currentBlobUrl = null;

        // H.264 WebCodecs decoder
        this._h264Decoder = null;
        this._h264DecoderConfigured = false;
        this._h264SpsData = null;
        this._h264PpsData = null;
        this._webCodecsSupported = typeof VideoDecoder !== 'undefined';
        // FIX: Use Map to track pending decodes by timestamp to avoid race condition
        // Previous bug: _h264ResolveFrame got overwritten before decoder output fired
        this._h264PendingDecodes = new Map();
        // P-frame queue: store frames until first keyframe arrives
        this._h264FrameQueue = [];
        this._h264HasKeyframe = false;
        console.log(`[LiveStream] WebCodecs H.264 support: ${this._webCodecsSupported}`);

        // Frame dropping: skip stale frames when rendering can't keep up
        this._isProcessingFrame = false;
        this._pendingFrame = null;  // Latest frame waiting to be processed
        this._droppedFrameCount = 0;

        // Pause state tracking for scheduler and sensors
        this._schedulerPaused = false;
        this._sensorsPaused = false;
        this._pausedDeviceId = null;

        // User-configurable pause options (set from dialog before start)
        this._pauseSchedulerOnStart = true;  // Default: pause scheduler
        this._pauseSensorsOnStart = true;    // Default: pause sensors

        // Container classes to filter out (reduce visual clutter)
        // Use Set for O(1) lookup instead of Array.includes() O(n)
        this.containerClasses = new Set([
            // Core Android containers
            'android.view.View',
            'android.view.ViewGroup',
            'android.widget.FrameLayout',
            'android.widget.LinearLayout',
            'android.widget.RelativeLayout',
            'android.widget.TableLayout',
            'android.widget.TableRow',
            'android.widget.GridLayout',
            'android.widget.ScrollView',
            'android.widget.HorizontalScrollView',
            'android.widget.ListView',
            'android.widget.GridView',
            'android.widget.AbsoluteLayout',
            // AndroidX containers
            'androidx.constraintlayout.widget.ConstraintLayout',
            'androidx.recyclerview.widget.RecyclerView',
            'androidx.viewpager.widget.ViewPager',
            'androidx.viewpager2.widget.ViewPager2',
            'androidx.coordinatorlayout.widget.CoordinatorLayout',
            'androidx.drawerlayout.widget.DrawerLayout',
            'androidx.appcompat.widget.LinearLayoutCompat',
            'androidx.cardview.widget.CardView',
            'androidx.core.widget.NestedScrollView',
            'androidx.swiperefreshlayout.widget.SwipeRefreshLayout',
            // Other non-interactive elements
            'android.widget.Space',
            'android.view.ViewStub'
        ]);

        console.log('[LiveStream] Initialized (WebSocket + MJPEG + Auto-reconnect + Container filtering)');
    }

    /**
     * Set connection state and notify listeners
     */
    _setConnectionState(state) {
        const oldState = this.connectionState;
        this.connectionState = state;
        console.log(`[LiveStream] Connection state: ${oldState} -> ${state}`);

        if (this.onConnectionStateChange) {
            this.onConnectionStateChange(state, this.reconnectAttempts);
        }
    }

    /**
     * Get WebSocket URL for device
     * @param {string} deviceId - Device identifier
     * @param {string} mode - 'websocket' or 'mjpeg'
     * @param {string} quality - 'high', 'medium', 'low', 'fast'
     * @returns {string} WebSocket URL
     */
    _getWebSocketUrl(deviceId, mode = 'websocket', quality = 'fast') {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const encodedDeviceId = encodeURIComponent(deviceId);

        // Endpoint based on mode
        let endpoint = 'ws/stream';
        if (mode === 'mjpeg') {
            endpoint = 'ws/stream-mjpeg';
        } else if (mode === 'mjpeg-v2') {
            endpoint = 'ws/stream-mjpeg-v2';
        }

        // Handle Home Assistant ingress
        const url = window.location.href;
        const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);

        // Add quality as query parameter
        const queryParams = `?quality=${quality}`;

        if (ingressMatch) {
            return `${protocol}//${host}${ingressMatch[0]}/${endpoint}/${encodedDeviceId}${queryParams}`;
        }

        return `${protocol}//${host}/api/${endpoint}/${encodedDeviceId}${queryParams}`;
    }

    /**
     * Start streaming from device
     * @param {string} deviceId - Device identifier (host:port)
     * @param {string} mode - 'websocket' (base64) or 'mjpeg' (binary)
     * @param {string} quality - 'high', 'medium', 'low', 'fast'
     */
    async start(deviceId, mode = 'websocket', quality = 'fast') {
        if (this.isStreaming) {
            console.warn('[LiveStream] Already streaming, stopping first');
            await this.stop();
        }

        this._manualStop = false;
        this.deviceId = deviceId;
        this.streamMode = mode;
        this.streamQuality = quality;

        // Pause scheduler and sensor updates to reduce ADB contention
        await this.pauseForStreaming(deviceId);

        this._connect();
    }

    /**
     * Internal connect method (used for initial connect and reconnect)
     */
    _connect() {
        // Guard against zombie reconnections - check if stop() was called during backoff delay
        if (this._manualStop) {
            console.log('[LiveStream] _connect() aborted - stream was manually stopped');
            this._setConnectionState('disconnected');
            return;
        }

        // Validate deviceId is still set (could be cleared by stop())
        if (!this.deviceId) {
            console.log('[LiveStream] _connect() aborted - no device ID');
            this._setConnectionState('disconnected');
            return;
        }

        const wsUrl = this._getWebSocketUrl(this.deviceId, this.streamMode, this.streamQuality);

        this._setConnectionState(this.reconnectAttempts > 0 ? 'reconnecting' : 'connecting');
        console.log(`[LiveStream] Connecting to ${wsUrl} (mode: ${this.streamMode}, quality: ${this.streamQuality}, attempt: ${this.reconnectAttempts + 1})`);

        // Reset bandwidth tracking
        this._bandwidthStart = performance.now();
        this._bandwidthBytes = 0;

        try {
            this.websocket = new WebSocket(wsUrl);

            // Enable binary type for MJPEG modes (v1 and v2)
            if (this.streamMode === 'mjpeg' || this.streamMode === 'mjpeg-v2') {
                this.websocket.binaryType = 'arraybuffer';
            }

            this.websocket.onopen = () => {
                console.log(`[LiveStream] Connected (${this.streamMode} mode)`);
                this.isStreaming = true;
                this.reconnectAttempts = 0; // Reset on successful connection
                this.reconnectDelay = 1000; // Reset delay
                this.metrics.frameCount = 0;
                this.metrics.lastFrameTime = performance.now();

                this._setConnectionState('connected');

                if (this.onConnect) {
                    this.onConnect();
                }
            };

            this.websocket.onmessage = (event) => {
                // Track bandwidth
                const dataSize = event.data instanceof ArrayBuffer
                    ? event.data.byteLength
                    : event.data.length;
                this._bandwidthBytes += dataSize;
                this._updateBandwidth();

                // Route to appropriate handler based on data type
                if (event.data instanceof ArrayBuffer) {
                    // Binary MJPEG frame
                    this._handleMjpegFrame(event.data);
                } else {
                    // JSON frame (websocket mode or MJPEG config message)
                    const data = JSON.parse(event.data);
                    if (data.type === 'config') {
                        console.log('[LiveStream] MJPEG config received:', data);
                        // Store native device dimensions for overlay scaling
                        if (data.width && data.height) {
                            this.deviceWidth = data.width;
                            this.deviceHeight = data.height;
                            console.log(`[LiveStream] Device dimensions: ${data.width}x${data.height}`);
                        }
                    } else if (data.type === 'source_change') {
                        // Handle streaming source change (companion <-> ADB)
                        console.log(`[LiveStream] Source changed to: ${data.source}`, data.message);
                        this._streamSource = data.source;
                        // Notify listeners
                        if (this.onSourceChange) {
                            this.onSourceChange(data.source, data.message, data.reason);
                        }
                    } else if (data.type === 'keepalive') {
                        // Ignore keepalive messages (just prevent timeout)
                    } else {
                        this._handleFrame(data);
                    }
                }
            };

            this.websocket.onclose = () => {
                console.log('[LiveStream] Disconnected');
                this.isStreaming = false;
                this.websocket = null;

                if (this.onDisconnect) {
                    this.onDisconnect();
                }

                // Auto-reconnect if not manually stopped
                if (!this._manualStop && this.autoReconnect && this.deviceId) {
                    this._scheduleReconnect();
                } else {
                    this._setConnectionState('disconnected');
                }
            };

            this.websocket.onerror = (error) => {
                console.error('[LiveStream] WebSocket error:', error);

                if (this.onError) {
                    this.onError(error);
                }
            };

        } catch (error) {
            console.error('[LiveStream] Failed to connect:', error);
            this._setConnectionState('disconnected');
            if (this.onError) {
                this.onError(error);
            }
        }
    }

    /**
     * Schedule a reconnection attempt with exponential backoff
     */
    _scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.log('[LiveStream] Max reconnect attempts reached, giving up');
            this._setConnectionState('disconnected');
            return;
        }

        // Calculate delay with exponential backoff
        const delay = Math.min(
            this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts),
            this.maxReconnectDelay
        );

        console.log(`[LiveStream] Reconnecting in ${Math.round(delay / 1000)}s (attempt ${this.reconnectAttempts + 1}/${this.maxReconnectAttempts})`);
        this._setConnectionState('reconnecting');

        this._reconnectTimer = setTimeout(() => {
            // Double-check state before reconnecting (stop() may have been called during delay)
            if (this._manualStop || !this.deviceId) {
                console.log('[LiveStream] Reconnect timer cancelled - stream was stopped during backoff');
                this._setConnectionState('disconnected');
                return;
            }
            this.reconnectAttempts++;
            this._connect();
        }, delay);
    }

    /**
     * Cancel any pending reconnection
     */
    _cancelReconnect() {
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
    }

    /**
     * Update bandwidth metrics (called on each message)
     */
    _updateBandwidth() {
        const now = performance.now();
        const elapsed = (now - this._bandwidthStart) / 1000; // seconds

        if (elapsed >= 1.0) {
            // Calculate KB/s
            const kbps = Math.round(this._bandwidthBytes / 1024 / elapsed);

            // Rolling average
            this.metrics.bandwidthHistory.push(kbps);
            if (this.metrics.bandwidthHistory.length > 5) {
                this.metrics.bandwidthHistory.shift();
            }
            this.metrics.bandwidth = Math.round(
                this.metrics.bandwidthHistory.reduce((a, b) => a + b, 0) /
                this.metrics.bandwidthHistory.length
            );
            this.metrics.bytesReceived += this._bandwidthBytes;

            // Reset for next second
            this._bandwidthStart = now;
            this._bandwidthBytes = 0;
        }
    }

    /**
     * Handle binary MJPEG frame
     * Implements frame dropping for slow connections - skips stale frames when rendering can't keep up
     * @param {ArrayBuffer} buffer - Binary frame data
     */
    async _handleMjpegFrame(buffer) {
        // Guard: Ignore frames if streaming was stopped (prevents race condition on quality switch)
        if (!this.isStreaming) {
            return;
        }

        // Frame dropping: if still processing previous frame, queue this one and skip
        if (this._isProcessingFrame) {
            this._pendingFrame = buffer;  // Keep only the latest frame
            this._droppedFrameCount++;
            return;
        }

        // Process this frame
        await this._processFrame(buffer);

        // Check if a newer frame arrived while processing
        while (this._pendingFrame && this.isStreaming) {
            const nextFrame = this._pendingFrame;
            this._pendingFrame = null;
            await this._processFrame(nextFrame);
        }
    }

    /**
     * Process a single frame (JPEG or H.264)
     * Detects codec from 16-byte header format
     * @param {ArrayBuffer} buffer - Binary frame data
     */
    async _processFrame(buffer) {
        this._isProcessingFrame = true;

        const now = performance.now();
        const view = new DataView(buffer);

        // Parse header - detect format by checking if it's a 16-byte H.264 format
        let frameNumber = 0, captureTime = 0, width = 0, height = 0;
        let isKeyframe = false, codec = 0, headerSize = 8;  // Default to 8-byte JPEG
        let frameData;

        // Try 16-byte H.264 format first
        if (buffer.byteLength >= 16) {
            frameNumber = view.getUint32(0, false);  // big-endian
            captureTime = view.getUint32(4, false);
            width = view.getUint16(8, false);
            height = view.getUint16(10, false);
            const flags = view.getUint8(12);
            const codecByte = view.getUint8(13);

            // Validate: codec should be 0 or 1, dimensions should be reasonable
            if ((codecByte === 0 || codecByte === 1) && width >= 100 && width <= 4096 && height >= 100 && height <= 4096) {
                codec = codecByte;  // 0 = JPEG, 1 = H.264
                isKeyframe = (flags & 0x01) !== 0;
                const hasSpsPs = (flags & 0x02) !== 0;
                headerSize = 16;

                // Extract SPS/PPS if present (H.264 keyframes)
                if (hasSpsPs && codec === 1) {
                    let offset = 16;
                    if (buffer.byteLength > offset + 2) {
                        const spsLen = view.getUint16(offset, false);
                        offset += 2;
                        if (buffer.byteLength > offset + spsLen) {
                            this._h264SpsData = new Uint8Array(buffer.slice(offset, offset + spsLen));
                            offset += spsLen;
                            if (buffer.byteLength > offset + 2) {
                                const ppsLen = view.getUint16(offset, false);
                                offset += 2;
                                if (buffer.byteLength > offset + ppsLen) {
                                    this._h264PpsData = new Uint8Array(buffer.slice(offset, offset + ppsLen));
                                    offset += ppsLen;
                                    headerSize = offset;
                                    console.log(`[LiveStream] H.264 SPS/PPS received: SPS=${spsLen}bytes, PPS=${ppsLen}bytes`);
                                }
                            }
                        }
                    }
                }
            } else {
                // Not 16-byte format, try legacy formats
                codec = 0;  // JPEG
                isKeyframe = false;
                // Try 12-byte format (with dimensions)
                if (buffer.byteLength >= 12) {
                    const w = view.getUint16(8, false);
                    const h = view.getUint16(10, false);
                    if (w >= 100 && w <= 4096 && h >= 100 && h <= 4096) {
                        width = w;
                        height = h;
                        headerSize = 12;
                    } else {
                        headerSize = 8;
                    }
                } else {
                    headerSize = 8;
                }
            }
        } else {
            // Legacy 8-byte JPEG format
            frameNumber = view.getUint32(0, false);
            captureTime = view.getUint32(4, false);
            codec = 0;
            isKeyframe = false;
            headerSize = 8;
        }

        frameData = buffer.slice(headerSize);

        // Validate JPEG magic bytes and auto-correct header size if needed
        let frameBytes = new Uint8Array(frameData.slice(0, 4));
        let isValidJpeg = frameBytes[0] === 0xFF && frameBytes[1] === 0xD8;

        // Auto-correct: If JPEG magic not found, try other common header sizes
        if (!isValidJpeg && codec === 0 && buffer.byteLength > 12) {
            // Try 12-byte header (companion JPEG format)
            const at12 = new Uint8Array(buffer.slice(12, 14));
            if (at12[0] === 0xFF && at12[1] === 0xD8) {
                console.log(`[LiveStream] Auto-correcting headerSize: ${headerSize} -> 12 (found JPEG at offset 12)`);
                headerSize = 12;
                frameData = buffer.slice(12);
                frameBytes = new Uint8Array(frameData.slice(0, 4));
                isValidJpeg = true;
            } else if (buffer.byteLength > 8) {
                // Try 8-byte header (ADB format)
                const at8 = new Uint8Array(buffer.slice(8, 10));
                if (at8[0] === 0xFF && at8[1] === 0xD8) {
                    console.log(`[LiveStream] Auto-correcting headerSize: ${headerSize} -> 8 (found JPEG at offset 8)`);
                    headerSize = 8;
                    frameData = buffer.slice(8);
                    frameBytes = new Uint8Array(frameData.slice(0, 4));
                    isValidJpeg = true;
                }
            }
        }

        const isH264StartCode = frameBytes[0] === 0x00 && (frameBytes[1] === 0x00 || frameBytes[2] === 0x00);

        // Log when JPEG validation fails or data looks like H.264
        if (this.metrics.frameCount < 5 || (!isValidJpeg && codec === 0)) {
            const rawBytes = new Uint8Array(buffer.slice(0, 20));
            const detectedWidth = buffer.byteLength >= 10 ? view.getUint16(8, false) : 0;
            const detectedHeight = buffer.byteLength >= 12 ? view.getUint16(10, false) : 0;
            const detectedFlags = buffer.byteLength >= 13 ? view.getUint8(12) : 0;
            const detectedCodec = buffer.byteLength >= 14 ? view.getUint8(13) : 0;

            console.log(`[LiveStream] Frame parse: headerSize=${headerSize}, codec=${codec}, ` +
                `w=${width}, h=${height}, ` +
                `detection(w=${detectedWidth}, h=${detectedHeight}, flags=0x${detectedFlags.toString(16)}, codec=${detectedCodec}), ` +
                `payload[0:4]=0x${frameBytes[0]?.toString(16)} 0x${frameBytes[1]?.toString(16)} 0x${frameBytes[2]?.toString(16)} 0x${frameBytes[3]?.toString(16)}` +
                (isH264StartCode ? ' [LOOKS LIKE H.264]' : '') +
                `, raw[0:20]=${Array.from(rawBytes).map(b => '0x' + b.toString(16).padStart(2, '0')).join(' ')}`);
        }

        // Update FPS metrics
        const frameDelta = now - this.metrics.lastFrameTime;
        this.metrics.lastFrameTime = now;

        this.metrics.fpsHistory.push(1000 / frameDelta);
        if (this.metrics.fpsHistory.length > 10) {
            this.metrics.fpsHistory.shift();
        }
        this.metrics.fps = Math.round(
            this.metrics.fpsHistory.reduce((a, b) => a + b, 0) / this.metrics.fpsHistory.length
        );

        this.metrics.captureTime = captureTime;
        this.metrics.frameCount = frameNumber;

        try {
            let img;

            if (codec === 1) {
                // H.264 frame
                if (this._webCodecsSupported) {
                    img = await this._decodeH264Frame(frameData, isKeyframe, width, height, frameNumber);
                } else {
                    // H.264 without WebCodecs - can't decode, skip frame
                    this._h264SkippedCount = (this._h264SkippedCount || 0) + 1;
                    if (this._h264SkippedCount <= 3 || this._h264SkippedCount % 60 === 0) {
                        console.warn(`[LiveStream] H.264 frame skipped - WebCodecs not supported (count: ${this._h264SkippedCount})`);
                    }
                    return; // Skip this frame entirely
                }
            } else {
                // JPEG frame - decode with Image element
                img = await this._decodeJpegFrame(frameData);
            }

            if (img) {
                this.currentImage = img;
                this._renderFrame(img, this.elements);

                if (this.onFrame) {
                    this.onFrame({ frame_number: frameNumber, capture_ms: captureTime });
                }

                if (this.onMetricsUpdate) {
                    this.onMetricsUpdate(this.metrics);
                }
            }

        } catch (error) {
            console.error('[LiveStream] Failed to render frame:', error);
        } finally {
            this._isProcessingFrame = false;
        }
    }

    /**
     * Decode JPEG frame using Image element
     * @param {ArrayBuffer} jpegData - JPEG image data
     * @returns {Promise<HTMLImageElement>} Decoded image or null on error
     */
    async _decodeJpegFrame(jpegData) {
        // Validate JPEG magic bytes (0xFF 0xD8)
        if (jpegData.byteLength < 2) {
            console.warn('[LiveStream] JPEG data too small:', jpegData.byteLength);
            return null;
        }

        const header = new Uint8Array(jpegData.slice(0, 2));
        if (header[0] !== 0xFF || header[1] !== 0xD8) {
            // Throttle warnings to avoid console spam
            this._invalidJpegCount = (this._invalidJpegCount || 0) + 1;
            if (this._invalidJpegCount <= 3 || this._invalidJpegCount % 30 === 0) {
                console.warn(`[LiveStream] Invalid JPEG magic bytes: 0x${header[0].toString(16)} 0x${header[1].toString(16)} (expected 0xFF 0xD8) - count: ${this._invalidJpegCount}`);
            }
            return null;
        }
        // Reset counter on valid frame
        this._invalidJpegCount = 0;

        // Store previous blob URL to revoke AFTER new image loads
        // This prevents race condition where rapid frames cause "Failed to load JPEG image"
        const previousBlobUrl = this._currentBlobUrl;

        const blob = new Blob([jpegData], { type: 'image/jpeg' });
        const blobUrl = URL.createObjectURL(blob);
        this._currentBlobUrl = blobUrl;

        const img = new Image();
        try {
            await new Promise((resolve, reject) => {
                img.onload = resolve;
                img.onerror = () => reject(new Error('Failed to load JPEG image'));
                img.src = blobUrl;
            });

            // Now safe to revoke previous blob URL (new image is loaded)
            if (previousBlobUrl) {
                URL.revokeObjectURL(previousBlobUrl);
            }

            return img;
        } catch (error) {
            // Clean up blob URL on error
            URL.revokeObjectURL(blobUrl);
            this._currentBlobUrl = previousBlobUrl; // Restore previous
            throw error;
        }
    }

    /**
     * Decode H.264 frame using WebCodecs VideoDecoder
     * Uses Map to track pending decodes by timestamp to avoid race condition
     * Queues P-frames until first keyframe arrives
     *
     * @param {ArrayBuffer} nalData - H.264 NAL unit data
     * @param {boolean} isKeyframe - Whether this is a keyframe
     * @param {number} width - Frame width
     * @param {number} height - Frame height
     * @param {number} frameNumber - Frame number for timestamp
     * @returns {Promise<HTMLImageElement|null>} Decoded image or null
     */
    async _decodeH264Frame(nalData, isKeyframe, width, height, frameNumber) {
        // Queue P-frames until first keyframe arrives with SPS/PPS
        if (!this._h264HasKeyframe && !isKeyframe) {
            // Queue P-frame for later
            this._h264FrameQueue.push({ nalData, isKeyframe, width, height, frameNumber });
            if (this._h264FrameQueue.length <= 3) {
                console.log(`[LiveStream] H.264: Queued P-frame ${frameNumber} (waiting for keyframe)`);
            }
            // Limit queue size to prevent memory buildup
            if (this._h264FrameQueue.length > 30) {
                this._h264FrameQueue.shift();
            }
            return null;
        }

        // Process keyframe - configure decoder and decode queued frames
        if (isKeyframe) {
            this._h264HasKeyframe = true;

            // Initialize decoder if needed
            if (!this._h264Decoder || this._h264Decoder.state === 'closed') {
                await this._initH264Decoder(width, height);
            }

            // Configure with SPS/PPS
            if (this._h264SpsData && this._h264PpsData) {
                await this._configureH264Decoder(width, height);
            }

            // Process queued P-frames that came before this keyframe
            // Note: These will likely be invalid since they reference this keyframe
            // but we clear the queue anyway to avoid stale data
            if (this._h264FrameQueue.length > 0) {
                console.log(`[LiveStream] H.264: Clearing ${this._h264FrameQueue.length} queued frames after keyframe`);
                this._h264FrameQueue = [];
            }
        }

        // Decoder still not ready
        if (!this._h264Decoder || this._h264Decoder.state !== 'configured') {
            return null;
        }

        // Actually decode the frame
        return this._actuallyDecodeH264Frame(nalData, isKeyframe, width, height, frameNumber);
    }

    /**
     * Internal: Actually decode an H.264 frame (after keyframe/queue handling)
     * @private
     */
    async _actuallyDecodeH264Frame(nalData, isKeyframe, width, height, frameNumber) {
        const timestamp = frameNumber * 33333;  // ~30fps timing

        return new Promise((resolve) => {
            // FIX: Use Map keyed by timestamp to track pending decodes
            // This prevents race condition where frame N+1 arrives before frame N completes
            this._h264PendingDecodes.set(timestamp, resolve);

            // Create EncodedVideoChunk
            const chunk = new EncodedVideoChunk({
                type: isKeyframe ? 'key' : 'delta',
                timestamp: timestamp,
                data: nalData
            });

            try {
                this._h264Decoder.decode(chunk);
            } catch (e) {
                console.error('[LiveStream] H.264 decode error:', e);
                this._h264PendingDecodes.delete(timestamp);
                resolve(null);
            }
        });
    }

    /**
     * Initialize H.264 VideoDecoder
     * @param {number} width - Frame width
     * @param {number} height - Frame height
     */
    async _initH264Decoder(width, height) {
        if (!this._webCodecsSupported) {
            console.warn('[LiveStream] WebCodecs not supported in this browser');
            return;
        }

        console.log(`[LiveStream] Initializing H.264 decoder for ${width}x${height}`);

        this._h264Decoder = new VideoDecoder({
            output: (frame) => {
                // FIX: Use Map to find the correct resolve callback by timestamp
                // This fixes race condition where frame N+1's resolve overwrote frame N's
                const timestamp = frame.timestamp;
                const resolve = this._h264PendingDecodes.get(timestamp);

                // Convert VideoFrame to Image via canvas
                this._videoFrameToImage(frame).then(img => {
                    frame.close();
                    if (resolve) {
                        this._h264PendingDecodes.delete(timestamp);
                        resolve(img);
                    } else {
                        // No pending decode for this timestamp - frame may have been dropped
                        console.warn(`[LiveStream] H.264: No pending decode for timestamp ${timestamp}`);
                    }
                });
            },
            error: (e) => {
                console.error('[LiveStream] H.264 decoder error:', e);
                // Resolve all pending decodes with null on error
                for (const [timestamp, resolve] of this._h264PendingDecodes) {
                    resolve(null);
                }
                this._h264PendingDecodes.clear();
            }
        });

        this._h264DecoderConfigured = false;
    }

    /**
     * Configure H.264 decoder with SPS/PPS
     * @param {number} width - Frame width
     * @param {number} height - Frame height
     */
    async _configureH264Decoder(width, height) {
        if (!this._h264Decoder || !this._h264SpsData || !this._h264PpsData) {
            return;
        }

        // Build avcC box from SPS/PPS for decoder configuration
        const avcC = this._buildAvcC(this._h264SpsData, this._h264PpsData);

        const config = {
            codec: 'avc1.42E01E',  // Baseline profile, level 3.0
            codedWidth: width,
            codedHeight: height,
            description: avcC
        };

        try {
            const support = await VideoDecoder.isConfigSupported(config);
            if (support.supported) {
                this._h264Decoder.configure(config);
                this._h264DecoderConfigured = true;
                console.log(`[LiveStream] H.264 decoder configured: ${width}x${height}`);
            } else {
                console.warn('[LiveStream] H.264 config not supported');
            }
        } catch (e) {
            console.error('[LiveStream] H.264 config error:', e);
        }
    }

    /**
     * Build avcC configuration box from SPS and PPS NAL units
     * @param {Uint8Array} sps - SPS NAL unit (without start code)
     * @param {Uint8Array} pps - PPS NAL unit (without start code)
     * @returns {Uint8Array} avcC box
     */
    _buildAvcC(sps, pps) {
        // avcC structure:
        // 1 byte: configurationVersion (1)
        // 1 byte: AVCProfileIndication (from SPS)
        // 1 byte: profile_compatibility (from SPS)
        // 1 byte: AVCLevelIndication (from SPS)
        // 1 byte: 0xFC | (lengthSizeMinusOne) = 0xFF for 4-byte lengths
        // 1 byte: 0xE0 | numOfSequenceParameterSets = 0xE1 (1 SPS)
        // 2 bytes: sequenceParameterSetLength
        // N bytes: sequenceParameterSetNALUnit (SPS)
        // 1 byte: numOfPictureParameterSets = 1
        // 2 bytes: pictureParameterSetLength
        // N bytes: pictureParameterSetNALUnit (PPS)

        const avcC = new Uint8Array(11 + sps.length + pps.length);
        let offset = 0;

        avcC[offset++] = 1;  // configurationVersion
        avcC[offset++] = sps[1];  // AVCProfileIndication
        avcC[offset++] = sps[2];  // profile_compatibility
        avcC[offset++] = sps[3];  // AVCLevelIndication
        avcC[offset++] = 0xFF;  // lengthSizeMinusOne = 3 (4-byte NAL length prefix)
        avcC[offset++] = 0xE1;  // numOfSequenceParameterSets = 1

        // SPS length (big-endian)
        avcC[offset++] = (sps.length >> 8) & 0xFF;
        avcC[offset++] = sps.length & 0xFF;

        // SPS data
        avcC.set(sps, offset);
        offset += sps.length;

        avcC[offset++] = 1;  // numOfPictureParameterSets

        // PPS length (big-endian)
        avcC[offset++] = (pps.length >> 8) & 0xFF;
        avcC[offset++] = pps.length & 0xFF;

        // PPS data
        avcC.set(pps, offset);

        return avcC;
    }

    /**
     * Convert VideoFrame to HTMLImageElement via canvas
     * @param {VideoFrame} frame - Decoded video frame
     * @returns {Promise<HTMLImageElement>} Image element
     */
    async _videoFrameToImage(frame) {
        // Create offscreen canvas to draw the frame
        const canvas = document.createElement('canvas');
        canvas.width = frame.displayWidth;
        canvas.height = frame.displayHeight;
        const ctx = canvas.getContext('2d');

        // Draw VideoFrame to canvas
        ctx.drawImage(frame, 0, 0);

        // Convert to Image
        const img = new Image();
        await new Promise((resolve, reject) => {
            img.onload = resolve;
            img.onerror = reject;
            img.src = canvas.toDataURL('image/jpeg', 0.95);
        });

        return img;
    }

    /**
     * Clean up H.264 decoder
     */
    _cleanupH264Decoder() {
        if (this._h264Decoder) {
            try {
                if (this._h264Decoder.state !== 'closed') {
                    this._h264Decoder.close();
                }
            } catch (e) {
                // Ignore close errors
            }
            this._h264Decoder = null;
        }
        this._h264DecoderConfigured = false;
        this._h264SpsData = null;
        this._h264PpsData = null;
        // Clean up pending decodes and frame queue
        if (this._h264PendingDecodes) {
            // Resolve pending promises with null to prevent memory leaks
            for (const [timestamp, resolve] of this._h264PendingDecodes) {
                resolve(null);
            }
            this._h264PendingDecodes.clear();
        }
        this._h264FrameQueue = [];
        this._h264HasKeyframe = false;
    }

    /**
     * Stop streaming
     * Removes event handlers before closing to prevent stale frame processing during quality switch
     */
    async stop() {
        console.log('[LiveStream] Stopping stream');
        this._manualStop = true;
        this.isStreaming = false;  // Set immediately to reject any pending frames
        this._cancelReconnect();
        this.reconnectAttempts = 0;

        if (this.websocket) {
            // Remove event handlers BEFORE closing to prevent stale frame processing
            this.websocket.onmessage = null;
            this.websocket.onerror = null;
            this.websocket.onclose = null;
            this.websocket.close();
            this.websocket = null;
        }

        // Clean up blob URL to prevent memory leak
        if (this._currentBlobUrl) {
            URL.revokeObjectURL(this._currentBlobUrl);
            this._currentBlobUrl = null;
        }

        // Clean up H.264 decoder
        this._cleanupH264Decoder();

        // Clean up frame dropping state
        this._isProcessingFrame = false;
        this._pendingFrame = null;
        if (this._droppedFrameCount > 0) {
            console.log(`[LiveStream] Dropped ${this._droppedFrameCount} frames during session (slow connection)`);
        }
        this._droppedFrameCount = 0;

        // Release image reference
        if (this.currentImage) {
            this.currentImage.src = '';  // Release image data
            this.currentImage = null;
        }

        this.deviceId = null;
        this._setConnectionState('disconnected');

        // Resume scheduler and sensor updates
        await this.resumeAfterStreaming();
    }

    /**
     * Pause scheduler and sensor updates to reduce ADB contention during streaming
     * @param {string} deviceId - Device identifier
     */
    async pauseForStreaming(deviceId) {
        const apiBase = window.API_BASE || '/api';

        // Pause flow scheduler (if enabled)
        if (this._pauseSchedulerOnStart) {
            try {
                const response = await fetch(`${apiBase}/scheduler/pause`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                if (response.ok) {
                    const data = await response.json();
                    if (data.success) {
                        console.log('[LiveStream] Paused flow scheduler for streaming');
                        this._schedulerPaused = true;
                    } else {
                        console.warn('[LiveStream] Scheduler pause returned:', data);
                    }
                } else {
                    console.warn('[LiveStream] Scheduler pause failed:', response.status, response.statusText);
                }
            } catch (e) {
                console.warn('[LiveStream] Could not pause scheduler:', e);
            }
        } else {
            console.log('[LiveStream] Scheduler pause disabled by user');
        }

        // Pause sensor updates for this device (if enabled)
        if (this._pauseSensorsOnStart && deviceId) {
            try {
                const response = await fetch(`${apiBase}/sensors/pause/${encodeURIComponent(deviceId)}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                if (response.ok) {
                    const data = await response.json();
                    if (data.success && data.paused) {
                        console.log(`[LiveStream] Paused sensor updates for ${deviceId}`);
                        this._sensorsPaused = true;
                        this._pausedDeviceId = deviceId;
                    } else if (data.message && data.message.includes('No sensor update loop')) {
                        // This is fine - no active sensor polling to pause
                        console.log(`[LiveStream] No active sensor polling for ${deviceId} (OK)`);
                    } else {
                        console.warn('[LiveStream] Sensor pause returned:', data);
                    }
                } else {
                    console.warn('[LiveStream] Sensor pause failed:', response.status, response.statusText);
                }
            } catch (e) {
                console.warn('[LiveStream] Could not pause sensor updates:', e);
            }
        } else if (!this._pauseSensorsOnStart) {
            console.log('[LiveStream] Sensor pause disabled by user');
        }
    }

    /**
     * Resume scheduler and sensor updates after streaming stops
     */
    async resumeAfterStreaming() {
        const apiBase = window.API_BASE || '/api';

        // Resume sensor updates first
        if (this._sensorsPaused && this._pausedDeviceId) {
            try {
                await fetch(`${apiBase}/sensors/resume/${encodeURIComponent(this._pausedDeviceId)}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                console.log(`[LiveStream] Resumed sensor updates for ${this._pausedDeviceId}`);
                this._sensorsPaused = false;
                this._pausedDeviceId = null;
            } catch (e) {
                console.warn('[LiveStream] Could not resume sensor updates:', e);
            }
        }

        // Resume flow scheduler
        if (this._schedulerPaused) {
            try {
                await fetch(`${apiBase}/scheduler/resume`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                console.log('[LiveStream] Resumed flow scheduler after streaming');
                this._schedulerPaused = false;
            } catch (e) {
                console.warn('[LiveStream] Could not resume scheduler:', e);
            }
        }
    }

    /**
     * Get current connection state
     * @returns {string} 'disconnected', 'connecting', 'connected', or 'reconnecting'
     */
    getConnectionState() {
        return this.connectionState;
    }

    /**
     * Enable/disable auto-reconnect
     * @param {boolean} enable
     */
    setAutoReconnect(enable) {
        this.autoReconnect = enable;
        if (!enable) {
            this._cancelReconnect();
        }
    }

    /**
     * Handle incoming frame from WebSocket
     * @param {Object} data - Frame data
     */
    async _handleFrame(data) {
        // Guard: Ignore frames if streaming was stopped (prevents race condition on quality switch)
        if (!this.isStreaming) {
            return;
        }

        if (data.type === 'error') {
            console.warn('[LiveStream] Server error:', data.message);
            return;
        }

        if (data.type !== 'frame') {
            return;
        }

        const now = performance.now();

        // Calculate FPS
        const frameDelta = now - this.metrics.lastFrameTime;
        this.metrics.lastFrameTime = now;

        // Update FPS using rolling average
        this.metrics.fpsHistory.push(1000 / frameDelta);
        if (this.metrics.fpsHistory.length > 10) {
            this.metrics.fpsHistory.shift();
        }
        this.metrics.fps = Math.round(
            this.metrics.fpsHistory.reduce((a, b) => a + b, 0) / this.metrics.fpsHistory.length
        );

        // Calculate latency (server timestamp to now)
        this.metrics.latency = Math.round((Date.now() / 1000 - data.timestamp) * 1000);
        this.metrics.captureTime = data.capture_ms;
        this.metrics.frameCount = data.frame_number;

        // Load and render image
        try {
            const img = new Image();

            await new Promise((resolve, reject) => {
                img.onload = resolve;
                img.onerror = reject;
                img.src = 'data:image/png;base64,' + data.image;
            });

            this.currentImage = img;

            // Update elements if provided
            if (data.elements && data.elements.length > 0) {
                this.elements = data.elements;

                // Infer device dimensions from element bounds (fixes coordinate issues when switching apps)
                // Elements are always in device pixel coordinates, so we can extract the native dimensions
                let maxX = 0, maxY = 0;
                data.elements.forEach(el => {
                    if (el.bounds) {
                        maxX = Math.max(maxX, el.bounds.x + el.bounds.width);
                        maxY = Math.max(maxY, el.bounds.y + el.bounds.height);
                    }
                });

                // Only update if we found valid bounds and they differ significantly
                if (maxX > 100 && maxY > 100) {
                    // Round to common device widths/heights
                    const inferredWidth = Math.round(maxX / 10) * 10;
                    const inferredHeight = Math.round(maxY / 10) * 10;

                    if (inferredWidth !== this.deviceWidth || inferredHeight !== this.deviceHeight) {
                        this.deviceWidth = inferredWidth;
                        this.deviceHeight = inferredHeight;
                        console.log(`[LiveStream] Updated device dimensions from elements: ${inferredWidth}x${inferredHeight}`);
                    }
                }
            }

            // CRITICAL FIX: Detect app changes by screenshot dimension changes
            // When user manually switches apps during streaming, screenshot dimensions change
            // but elements array is empty (streaming sends [] to save bandwidth)
            // Clear old cached elements to prevent misaligned overlays on new app
            if (this.currentImage && this.elements && this.elements.length > 0) {
                const dimensionsChanged =
                    img.naturalWidth !== this.currentImage.naturalWidth ||
                    img.naturalHeight !== this.currentImage.naturalHeight;

                if (dimensionsChanged) {
                    console.log(`[LiveStream] Screenshot dimensions changed: ${this.currentImage.naturalWidth}x${this.currentImage.naturalHeight} → ${img.naturalWidth}x${img.naturalHeight}`);
                    console.log(`[LiveStream] App switch detected - clearing ${this.elements.length} cached elements`);
                    this.elements = [];
                    // NOTE: Do NOT update deviceWidth/deviceHeight here!
                    // Stream resolution (img dimensions) != device native resolution
                    // Device dimensions should only come from elements API
                }
            }

            // Render frame
            this._renderFrame(img, this.elements);

            // Callback
            if (this.onFrame) {
                this.onFrame(data);
            }

            // Update metrics callback
            if (this.onMetricsUpdate) {
                this.onMetricsUpdate(this.metrics);
            }

        } catch (error) {
            console.error('[LiveStream] Failed to render frame:', error);
        }
    }

    /**
     * Render frame on canvas
     * @param {Image} img - Screenshot image
     * @param {Array} elements - UI elements
     */
    _renderFrame(img, elements) {
        // Resize canvas if needed
        if (this.canvas.width !== img.width || this.canvas.height !== img.height) {
            const oldWidth = this.canvas.width;
            const oldHeight = this.canvas.height;
            this.canvas.width = img.width;
            this.canvas.height = img.height;

            // CRITICAL FIX: Refresh context after canvas resize
            // Canvas resize can invalidate context state in some browsers
            this.ctx = this.canvas.getContext('2d');

            // NOTE: Do NOT update deviceWidth/deviceHeight from frame dimensions!
            // Frame dimensions = stream resolution (e.g., 360p = 640x1422)
            // Device dimensions = native screen resolution (e.g., 1080x2400)
            // Element bounds are in device coordinates, so we need device dimensions
            // for correct overlay scaling. Device dimensions come from elements API.
            //
            // For landscape detection, check if aspect ratio changed significantly
            const imgAspect = img.width / img.height;
            const deviceAspect = this.deviceWidth / this.deviceHeight;
            const aspectMismatch = Math.abs(imgAspect - deviceAspect) > 0.1;

            if (aspectMismatch) {
                // Aspect ratio changed (likely rotation) - clear stale elements
                // and wait for elements API to provide new device dimensions
                console.log(`[LiveStream] Aspect ratio changed (frame: ${imgAspect.toFixed(2)}, device: ${deviceAspect.toFixed(2)}) - clearing elements`);
                this.elements = [];
            }

            // Fire callback when dimensions change (for orientation handling)
            if (oldWidth !== 0 && oldHeight !== 0 && this.onDimensionsChange) {
                console.log(`[LiveStream] Dimensions changed: ${oldWidth}x${oldHeight} -> ${img.width}x${img.height}`);
                this.onDimensionsChange(img.width, img.height, oldWidth, oldHeight);
            }
        }

        // Detect if screen content has changed (for stale element detection or smart refresh)
        // Enabled when: autoHideStaleElements OR smartRefreshEnabled with callback
        // Note: Adds ~5-10ms per frame due to canvas sampling + hash
        if (this.autoHideStaleElements || (this.smartRefreshEnabled && this.onScreenChange)) {
            this._detectScreenChange(img);
        }

        // Clear canvas to remove old overlays
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw screenshot
        this.ctx.drawImage(img, 0, 0);

        // Draw overlays based on display mode
        // DEBUG: Log display mode periodically (every 100 frames)
        this._frameCount = (this._frameCount || 0) + 1;
        if (this._frameCount % 100 === 0) {
            console.log(`[LiveStream] Frame ${this._frameCount}: displayMode=${this.displayMode}, elements=${elements.length}, showOverlays=${this.showOverlays}, stale=${this.areElementsStale()}`);
        }

        // Skip drawing elements if they're stale (screen has changed but new elements haven't arrived)
        // This prevents showing old element positions on a new screen
        if (this.showOverlays && elements.length > 0 && !this.areElementsStale()) {
            switch (this.displayMode) {
                case 'hoverOnly':
                    // Only draw the currently hovered element - draw directly without filtering
                    if (this.hoveredElement && this.hoveredElement.bounds) {
                        this._drawSingleElement(this.hoveredElement);
                    }
                    // If not hovering anything, draw nothing (clean view)
                    break;

                case 'topLayer':
                    // Only draw elements that are not occluded by other elements
                    const topLayerElements = this._filterTopLayerElements(elements);
                    this._drawElements(topLayerElements);
                    break;

                case 'all':
                default:
                    // Draw all elements (original behavior)
                    this._drawElements(elements);
                    break;
            }
        }
    }

    /**
     * Calculate letterbox offset and scale for when device content is centered in frame
     * Returns {offsetX, offsetY, scale} for transforming device coords to canvas coords
     */
    _getLetterboxTransform() {
        if (this.deviceWidth <= 0 || this.deviceHeight <= 0) {
            return { offsetX: 0, offsetY: 0, scale: 1 };
        }

        const frameAspect = this.canvas.width / this.canvas.height;
        const deviceAspect = this.deviceWidth / this.deviceHeight;

        let scale, offsetX = 0, offsetY = 0;

        if (Math.abs(frameAspect - deviceAspect) < 0.01) {
            // Aspects match - simple scaling, no letterbox
            scale = this.canvas.width / this.deviceWidth;
        } else if (frameAspect > deviceAspect) {
            // Frame is wider than device (pillarbox - black bars on sides)
            // Device content is scaled to fit height, centered horizontally
            scale = this.canvas.height / this.deviceHeight;
            const contentWidth = this.deviceWidth * scale;
            offsetX = (this.canvas.width - contentWidth) / 2;
        } else {
            // Frame is taller than device (letterbox - black bars on top/bottom)
            // Device content is scaled to fit width, centered vertically
            scale = this.canvas.width / this.deviceWidth;
            const contentHeight = this.deviceHeight * scale;
            offsetY = (this.canvas.height - contentHeight) / 2;
        }

        // Debug log periodically
        this._letterboxLogCount = (this._letterboxLogCount || 0) + 1;
        if (this._letterboxLogCount % 100 === 1) {
            console.log(`[LiveStream] Letterbox: canvas=${this.canvas.width}x${this.canvas.height}, device=${this.deviceWidth}x${this.deviceHeight}, offset=(${offsetX.toFixed(1)},${offsetY.toFixed(1)}), scale=${scale.toFixed(4)}`);
        }

        return { offsetX, offsetY, scale };
    }

    /**
     * Draw a single element overlay (bypasses filtering for hover-only mode)
     * @param {Object} el - Element to draw
     */
    _drawSingleElement(el) {
        if (!el.bounds) return;

        // Get letterbox-aware transform
        const { offsetX, offsetY, scale } = this._getLetterboxTransform();

        // Scale and offset coordinates from device to canvas resolution
        const x = Math.floor(el.bounds.x * scale + offsetX);
        const y = Math.floor(el.bounds.y * scale + offsetY);
        const width = Math.floor(el.bounds.width * scale);
        const height = Math.floor(el.bounds.height * scale);

        // Draw bounding box
        this.ctx.strokeStyle = el.clickable ? '#00ff00' : '#ffff00';
        this.ctx.lineWidth = 2;
        this.ctx.strokeRect(x, y, width, height);

        // Draw text label
        if (this.showTextLabels && el.text && el.text.trim()) {
            this._drawTextLabel(el.text, x, y, width);
        }
    }

    /**
     * Filter elements to only include those in the top layer (not occluded)
     * An element is considered occluded if a LATER element (higher z-order) significantly overlaps it
     * @param {Array} elements - All elements
     * @returns {Array} Elements that appear to be in the top layer
     */
    _filterTopLayerElements(elements) {
        // OPTIMIZATION: Return cached result if elements and filter settings unchanged
        const currentHash = this._getFilterSettingsHash();
        if (elements === this._lastTopLayerElementsRef &&
            currentHash === this._lastTopLayerSettingsHash) {
            return this._cachedTopLayerElements;
        }

        const filtered = this._getFilteredElements(elements);
        if (filtered.length === 0) {
            this._cacheTopLayerResult(elements, currentHash, filtered);
            return filtered;
        }

        // Find all potential overlay elements (elements that might be covering others)
        // Look for elements in the later part of the array that are reasonably sized
        const overlayElements = [];
        for (let i = Math.floor(filtered.length * 0.3); i < filtered.length; i++) {
            const el = filtered[i];
            const area = el.bounds.width * el.bounds.height;
            // Elements larger than 5000 pixels could be overlays (cards, dialogs, etc.)
            if (area > 5000) {
                overlayElements.push({ element: el, index: i });
            }
        }

        // For each element, check if it's significantly covered by a later element
        const visibleElements = [];
        for (let i = 0; i < filtered.length; i++) {
            const el = filtered[i];
            let isOccluded = false;

            // Check against each potential overlay that comes AFTER this element
            for (const overlay of overlayElements) {
                if (overlay.index <= i) continue; // Only check elements that come later (on top)

                const overlayEl = overlay.element;

                // Calculate overlap between this element and the overlay
                const overlapX = Math.max(0, Math.min(el.bounds.x + el.bounds.width, overlayEl.bounds.x + overlayEl.bounds.width) - Math.max(el.bounds.x, overlayEl.bounds.x));
                const overlapY = Math.max(0, Math.min(el.bounds.y + el.bounds.height, overlayEl.bounds.y + overlayEl.bounds.height) - Math.max(el.bounds.y, overlayEl.bounds.y));
                const overlapArea = overlapX * overlapY;

                const elArea = el.bounds.width * el.bounds.height;

                // If more than 50% of this element is covered by the overlay, consider it occluded
                if (elArea > 0 && overlapArea / elArea > 0.5) {
                    isOccluded = true;
                    break;
                }
            }

            if (!isOccluded) {
                visibleElements.push(el);
            }
        }

        this._cacheTopLayerResult(elements, currentHash, visibleElements);
        return visibleElements;
    }

    /**
     * Cache the top layer filtering result
     * @private
     */
    _cacheTopLayerResult(elements, hash, result) {
        this._lastTopLayerElementsRef = elements;
        this._lastTopLayerSettingsHash = hash;
        this._cachedTopLayerElements = result;
    }

    /**
     * Get current filter settings as a hash for cache invalidation
     */
    _getFilterSettingsHash() {
        return `${this.showClickable}-${this.showNonClickable}-${this.hideContainers}-${this.hideSmall}-${this.hideDividers}-${this.hideEmptyElements}-${this.deviceWidth}`;
    }

    /**
     * Get filtered elements (cached for performance)
     * Only re-filters when elements array or filter settings change
     */
    _getFilteredElements(elements) {
        const currentHash = this._getFilterSettingsHash();

        // Return cached if elements and settings haven't changed
        if (elements === this._lastElementsRef && currentHash === this._filterSettingsHash) {
            return this._filteredElements;
        }

        // Re-filter elements
        this._filteredElements = elements.filter(el => {
            if (!el.bounds) return false;

            // Filter based on clickable state
            if (el.clickable && !this.showClickable) return false;
            if (!el.clickable && !this.showNonClickable) return false;

            // Filter out container elements
            if (this.hideContainers && el.class && this.containerClasses.has(el.class)) {
                return false;
            }

            // Filter out small elements (< 20px)
            if (this.hideSmall && (el.bounds.width < 20 || el.bounds.height < 20)) {
                return false;
            }

            // Filter out dividers (full-width horizontal lines)
            if (this.hideDividers && el.bounds.height <= 5 && el.bounds.width >= this.deviceWidth * 0.9) {
                return false;
            }

            // Filter out empty elements
            if (this.hideEmptyElements) {
                const hasText = el.text && el.text.trim();
                const hasContentDesc = el.content_desc && el.content_desc.trim();
                if (!el.clickable && !hasText && !hasContentDesc) {
                    return false;
                }
            }

            return true;
        });

        // Update cache references
        this._lastElementsRef = elements;
        this._filterSettingsHash = currentHash;

        return this._filteredElements;
    }

    /**
     * Draw UI element overlays
     * Scales element coordinates from device resolution to canvas resolution
     * Handles letterboxing when device and frame aspect ratios differ
     * @param {Array} elements - UI elements
     */
    _drawElements(elements) {
        // OPTIMIZATION: Use cached filtered elements
        const filteredElements = this._getFilteredElements(elements);

        // Get letterbox-aware transform (handles pillarbox/letterbox centering)
        const { offsetX, offsetY, scale } = this._getLetterboxTransform();

        // Draw all filtered elements (no per-element filtering needed)
        for (const el of filteredElements) {
            // Scale and offset coordinates from device to canvas resolution
            const x = Math.floor(el.bounds.x * scale + offsetX);
            const y = Math.floor(el.bounds.y * scale + offsetY);
            const width = Math.floor(el.bounds.width * scale);
            const height = Math.floor(el.bounds.height * scale);

            // Draw bounding box
            this.ctx.strokeStyle = el.clickable ? '#00ff00' : '#ffff00';
            this.ctx.lineWidth = 2;
            this.ctx.strokeRect(x, y, width, height);

            // Draw text label
            if (this.showTextLabels && el.text && el.text.trim()) {
                this._drawTextLabel(el.text, x, y, width);
            }
        }
    }

    /**
     * Set container filtering
     * @param {boolean} hide - Whether to hide containers
     */
    setHideContainers(hide) {
        this.hideContainers = hide;
        // Next frame will automatically use updated filter
    }

    /**
     * Set empty element filtering
     * @param {boolean} hide - Whether to hide empty elements
     */
    setHideEmptyElements(hide) {
        this.hideEmptyElements = hide;
        // Next frame will automatically use updated filter
    }

    /**
     * Set small element filtering
     * @param {boolean} hide - Whether to hide small elements (< 20px)
     */
    setHideSmall(hide) {
        this.hideSmall = hide;
    }

    /**
     * Set divider filtering
     * @param {boolean} hide - Whether to hide horizontal line dividers
     */
    setHideDividers(hide) {
        this.hideDividers = hide;
    }

    /**
     * Set clickable element visibility
     * @param {boolean} show - Whether to show clickable elements
     */
    setShowClickable(show) {
        this.showClickable = show;
    }

    /**
     * Set non-clickable element visibility
     * @param {boolean} show - Whether to show non-clickable elements
     */
    setShowNonClickable(show) {
        this.showNonClickable = show;
    }

    /**
     * Set overlay display mode
     * @param {string} mode - 'all', 'hoverOnly', or 'topLayer'
     */
    setDisplayMode(mode) {
        const validModes = ['all', 'hoverOnly', 'topLayer'];
        if (!validModes.includes(mode)) {
            console.warn(`[LiveStream] Invalid display mode: ${mode}, defaulting to 'all'`);
            mode = 'all';
        }
        this.displayMode = mode;
        console.log(`[LiveStream] Display mode set to: ${mode}`);
    }

    /**
     * Set currently hovered element (for hoverOnly display mode)
     * @param {Object|null} element - The element being hovered, or null
     */
    setHoveredElement(element) {
        this.hoveredElement = element;
    }

    /**
     * Set device dimensions for proper coordinate scaling
     * Call this when device dimensions are known (e.g., from elements API)
     * @param {number} width - Device width in pixels
     * @param {number} height - Device height in pixels
     */
    setDeviceDimensions(width, height) {
        if (width > 0 && height > 0) {
            this.deviceWidth = width;
            this.deviceHeight = height;
            this.elementsTimestamp = Date.now(); // Track when elements were refreshed
            this.resetScreenChangeTracking(); // Reset change detection
            console.log(`[LiveStream] Device dimensions updated: ${width}x${height}`);
        }
    }

    /**
     * Check if elements are stale (screen has changed since elements were fetched)
     * @returns {boolean} True if elements are stale
     */
    areElementsStale() {
        // No elements fetched yet
        if (this.elementsTimestamp === 0) return true;
        // Check if elements were marked stale by screen change detection
        // _elementsStale is set when screen change is detected and cleared when new elements arrive
        if (this._elementsStale) return true;
        // Also check if screen is currently changing (transitional state)
        return this._screenChanged;
    }

    /**
     * Mark elements as fresh (call after new elements are fetched)
     * This clears the stale flag so overlays will be drawn again
     */
    markElementsFresh() {
        this._elementsStale = false;
        this._elementsStaleTime = 0;
        this.elementsTimestamp = Date.now();
    }

    /**
     * Enable/disable auto-hiding of stale elements when screen changes
     * @param {boolean} enable - Whether to auto-hide stale elements
     */
    setAutoHideStaleElements(enable) {
        this.autoHideStaleElements = enable;
        console.log(`[LiveStream] Auto-hide stale elements: ${enable}`);
    }

    /**
     * Compute a simple hash of image data for change detection
     * Samples pixels in a grid pattern for better coverage of screen changes
     * @param {ImageData} imageData - Canvas image data
     * @returns {number} Simple hash value
     */
    _computeFrameHash(imageData) {
        const data = imageData.data;
        let hash = 0;
        // Sample more densely for better change detection
        // With 100x100 canvas (40000 bytes), sample every ~40 bytes = 1000 samples
        const step = Math.max(4, Math.floor(data.length / 4000));
        for (let i = 0; i < data.length; i += step) {
            // Combine R, G, B channels (skip alpha) for better sensitivity
            hash = ((hash << 5) - hash + data[i] + data[i+1] + data[i+2]) | 0;
        }
        return hash;
    }

    /**
     * Detect if screen content has changed significantly
     * When screen changes and then stabilizes, fires onScreenChange callback
     * Uses adaptive thresholds based on fluency mode and current FPS
     * @param {Image} img - New frame image
     */
    _detectScreenChange(img) {
        try {
            // Create temporary canvas to sample pixels
            const tempCanvas = document.createElement('canvas');
            tempCanvas.width = Math.min(img.width, 100); // Sample at low res for speed
            tempCanvas.height = Math.min(img.height, 100);
            const tempCtx = tempCanvas.getContext('2d');
            tempCtx.drawImage(img, 0, 0, tempCanvas.width, tempCanvas.height);

            const imageData = tempCtx.getImageData(0, 0, tempCanvas.width, tempCanvas.height);
            const newHash = this._computeFrameHash(imageData);

            // Adaptive threshold based on FPS - higher FPS = fewer frames needed
            // At 20+ FPS, use minimum thresholds for responsiveness
            const currentFps = this.metrics.fps || 10;
            const adaptiveStableThreshold = currentFps >= 15 ?
                Math.max(1, this.stableFrameThreshold) :
                Math.max(2, this.stableFrameThreshold);

            // Compare with previous frame
            if (this._lastFrameHash !== 0 && newHash !== this._lastFrameHash) {
                // Frame is different - could be real change or compression noise
                this._differentFrameCount = (this._differentFrameCount || 0) + 1;
                this._stableFrameCount = 0;

                // Only mark as "screen changing" after threshold consecutive different frames
                // This filters out compression noise (single-frame differences)
                if (this._differentFrameCount >= this.changeFrameThreshold && !this._screenChanged) {
                    console.log(`[LiveStream] Smart: change detected (${this._differentFrameCount} frames, FPS: ${currentFps})`);
                    this._screenChanged = true;
                    this._elementsStale = true;
                    this._elementsStaleTime = Date.now();
                }
            } else {
                // Frame is same as previous
                this._differentFrameCount = 0;
                this._stableFrameCount++;

                // Screen stabilized after a change - fire callback
                // Use adaptive threshold based on FPS
                if (this._screenChanged && this._stableFrameCount >= adaptiveStableThreshold) {
                    this._screenChanged = false;

                    // Rate limit using configurable smartRefreshRateMs
                    const now = Date.now();
                    if (!this._lastScreenChangeCallback || now - this._lastScreenChangeCallback > this.smartRefreshRateMs) {
                        this._lastScreenChangeCallback = now;
                        console.log(`[LiveStream] Smart: stabilized (${adaptiveStableThreshold} frames), refresh [${this.fluencyMode}]`);
                        if (this.onScreenChange) {
                            this.onScreenChange();
                        }
                    } else {
                        // Rate limited - but log less verbosely
                        if (window.VM_DEBUG) {
                            console.log(`[LiveStream] Smart: rate limited (${this.smartRefreshRateMs}ms)`);
                        }
                    }
                }
            }

            this._lastFrameHash = newHash;
            this._framesSinceElements++;
        } catch (e) {
            // Ignore errors in change detection
        }
    }

    /**
     * Reset screen change tracking (call when elements are refreshed)
     */
    resetScreenChangeTracking() {
        this._screenChanged = false;
        this._elementsStale = false;  // Clear stale flag when new elements arrive
        this._framesSinceElements = 0;
        this._stableFrameCount = 0;
        // Don't log - this is called frequently and creates noise
    }

    /**
     * Set fluency mode for adaptive element refresh
     * Controls how responsive element refresh is to screen changes
     *
     * @param {string} mode - 'responsive', 'balanced', or 'smooth'
     *   - responsive: Quick refresh (300ms), best for active interaction
     *   - balanced: Medium refresh (500ms), good for most use cases
     *   - smooth: Slow refresh (1000ms), less CPU, smoother overlays
     */
    setFluency(mode) {
        const settings = {
            responsive: {
                smartRefreshRateMs: 300,
                stableFrameThreshold: 1,
                changeFrameThreshold: 1
            },
            balanced: {
                smartRefreshRateMs: 500,
                stableFrameThreshold: 2,
                changeFrameThreshold: 2
            },
            smooth: {
                smartRefreshRateMs: 1000,
                stableFrameThreshold: 3,
                changeFrameThreshold: 2
            }
        };

        const config = settings[mode] || settings.balanced;
        this.fluencyMode = mode || 'balanced';
        this.smartRefreshRateMs = config.smartRefreshRateMs;
        this.stableFrameThreshold = config.stableFrameThreshold;
        this.changeFrameThreshold = config.changeFrameThreshold;

        console.log(`[LiveStream] Fluency set to '${this.fluencyMode}': refresh=${this.smartRefreshRateMs}ms, stable=${this.stableFrameThreshold}, change=${this.changeFrameThreshold}`);
    }

    /**
     * Get current fluency mode
     * @returns {string} Current fluency mode
     */
    getFluency() {
        return this.fluencyMode;
    }

    /**
     * Draw text label
     * Scales font size based on canvas width to look appropriate at all resolutions
     * Uses cached font settings when canvas size hasn't changed
     * @param {string} text - Label text
     * @param {number} x - X position
     * @param {number} y - Y position
     * @param {number} w - Width
     */
    _drawTextLabel(text, x, y, w) {
        // Cache font settings based on canvas width (avoid recalculating per label)
        if (this._cachedFontCanvasWidth !== this.canvas.width) {
            const scaleFactor = Math.max(0.6, Math.min(1.5, this.canvas.width / 720));
            this._cachedFontSize = Math.round(11 * scaleFactor);
            this._cachedLabelHeight = Math.round(18 * scaleFactor);
            this._cachedCharWidth = Math.round(7 * scaleFactor);
            this._cachedLabelOffset = Math.round(3 * scaleFactor);
            this._cachedFontString = `${this._cachedFontSize}px monospace`;
            this._cachedFontCanvasWidth = this.canvas.width;
        }

        const maxChars = Math.floor(w / this._cachedCharWidth);
        const displayText = text.length > maxChars
            ? text.substring(0, maxChars - 2) + '..'
            : text;

        // Background
        this.ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
        this.ctx.fillRect(x, y - this._cachedLabelHeight, Math.min(w, displayText.length * this._cachedCharWidth + 4), this._cachedLabelHeight);

        // Text
        this.ctx.fillStyle = '#ffffff';
        this.ctx.font = this._cachedFontString;
        this.ctx.textBaseline = 'top';
        this.ctx.fillText(displayText, x + 2, y - this._cachedLabelHeight + this._cachedLabelOffset);
    }

    /**
     * Update cached scale factors for coordinate conversion
     * Called when canvas or device dimensions change
     */
    _updateScaleFactors() {
        if (this.canvas.width > 0 && this.canvas.height > 0 &&
            this.deviceWidth > 0 && this.deviceHeight > 0) {
            this._cachedScaleX = this.deviceWidth / this.canvas.width;
            this._cachedScaleY = this.deviceHeight / this.canvas.height;
            this._cachedScaleCanvasWidth = this.canvas.width;
            this._cachedScaleCanvasHeight = this.canvas.height;
            this._cachedScaleDeviceWidth = this.deviceWidth;
            this._cachedScaleDeviceHeight = this.deviceHeight;
        }
    }

    /**
     * Convert canvas coordinates to device coordinates
     * Accounts for letterboxing when device and frame aspect ratios differ
     * @param {number} canvasX - Canvas X
     * @param {number} canvasY - Canvas Y
     * @returns {Object} Device coordinates {x, y} or null if no image loaded
     */
    canvasToDevice(canvasX, canvasY) {
        if (!this.currentImage) {
            // Return null instead of throwing - caller should check
            return null;
        }

        // Get letterbox-aware transform
        const { offsetX, offsetY, scale } = this._getLetterboxTransform();

        // Reverse the transform: device = (canvas - offset) / scale
        return {
            x: Math.round((canvasX - offsetX) / scale),
            y: Math.round((canvasY - offsetY) / scale)
        };
    }

    /**
     * Convert device coordinates to canvas coordinates
     * Accounts for letterboxing when device and frame aspect ratios differ
     * @param {number} deviceX - Device X
     * @param {number} deviceY - Device Y
     * @returns {Object} Canvas coordinates {x, y}
     */
    deviceToCanvas(deviceX, deviceY) {
        if (!this.currentImage) {
            return { x: deviceX, y: deviceY };
        }

        // Get letterbox-aware transform
        const { offsetX, offsetY, scale } = this._getLetterboxTransform();

        // Apply transform: canvas = device * scale + offset
        return {
            x: Math.round(deviceX * scale + offsetX),
            y: Math.round(deviceY * scale + offsetY)
        };
    }

    /**
     * Find element at canvas position
     * Scales canvas coordinates to device coordinates before comparing
     * @param {number} x - Canvas X
     * @param {number} y - Canvas Y
     * @returns {Object|null} Element or null
     */
    findElementAtPoint(x, y) {
        // Convert canvas position to device coordinates
        const scaleX = this.deviceWidth / this.canvas.width;
        const scaleY = this.deviceHeight / this.canvas.height;
        const deviceX = x * scaleX;
        const deviceY = y * scaleY;

        // Elements are in device coordinates - search from top (last) to bottom (first)
        // Prefer elements with text, skip containers
        let bestMatch = null;

        for (let i = this.elements.length - 1; i >= 0; i--) {
            const el = this.elements[i];
            if (!el.bounds) continue;

            const b = el.bounds;
            // Check if point is within element bounds
            if (!(deviceX >= b.x && deviceX <= b.x + b.width &&
                  deviceY >= b.y && deviceY <= b.y + b.height)) {
                continue;
            }

            // Check element properties
            const hasText = el.text && el.text.trim();
            const hasContentDesc = el.content_desc && el.content_desc.trim();
            const isContainer = el.class && this.containerClasses.has(el.class);

            // Always skip containers if filter is on
            if (this.hideContainers && isContainer) {
                continue;
            }

            // Skip empty elements if filter is on (except clickable buttons)
            if (this.hideEmptyElements) {
                const hasResourceId = el.resource_id && el.resource_id.trim();
                if (!hasText && !hasContentDesc && !(el.clickable && hasResourceId)) {
                    continue;
                }
            }

            // Prefer elements with text over those without
            if (hasText || hasContentDesc) {
                return el; // Return immediately if has text
            }

            // Keep as backup if it's clickable
            if (el.clickable && !bestMatch) {
                bestMatch = el;
            }
        }

        return bestMatch;
    }

    /**
     * Get current metrics
     * @returns {Object} Metrics
     */
    getMetrics() {
        return { ...this.metrics };
    }

    /**
     * Check if streaming
     * @returns {boolean}
     */
    isActive() {
        return this.isStreaming;
    }

    /**
     * Toggle overlay visibility
     * @param {boolean} show
     */
    setOverlaysVisible(show) {
        this.showOverlays = show;
    }

    /**
     * Toggle text labels
     * @param {boolean} show
     */
    setTextLabelsVisible(show) {
        this.showTextLabels = show;
    }

    /**
     * Get API base URL for REST calls
     * @returns {string} API base URL
     */
    _getApiBase() {
        const url = window.location.href;
        const ingressMatch = url.match(/\/api\/hassio_ingress\/[^\/]+/);
        if (ingressMatch) {
            return ingressMatch[0] + '/api';
        }
        return '/api';
    }

    /**
     * Run backend benchmark to compare capture methods
     * Uses stream_manager.benchmark_capture() on server
     * @param {string} deviceId - Device to benchmark
     * @param {number} iterations - Number of captures per backend (default: 5)
     * @returns {Promise<Object>} Benchmark results
     */
    async runBenchmark(deviceId, iterations = 5) {
        const apiBase = this._getApiBase();
        const url = `${apiBase}/diagnostics/benchmark/${encodeURIComponent(deviceId)}?iterations=${iterations}`;

        console.log(`[LiveStream] Running capture benchmark for ${deviceId}...`);

        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`Benchmark failed: ${response.status}`);
            }
            const results = await response.json();
            console.log('[LiveStream] Benchmark results:', results);
            return results;
        } catch (error) {
            console.error('[LiveStream] Benchmark error:', error);
            throw error;
        }
    }

    /**
     * Get server-side stream metrics for device
     * @param {string} deviceId - Device ID
     * @returns {Promise<Object>} Server metrics
     */
    async getServerMetrics(deviceId) {
        const apiBase = this._getApiBase();
        const url = `${apiBase}/diagnostics/stream-metrics/${encodeURIComponent(deviceId)}`;

        try {
            const response = await fetch(url);
            if (!response.ok) {
                return null;
            }
            return await response.json();
        } catch (error) {
            console.warn('[LiveStream] Could not fetch server metrics:', error);
            return null;
        }
    }

    /**
     * Get connection quality rating based on current metrics
     * @returns {Object} Quality rating { level: 'good'|'ok'|'slow', description: string }
     */
    getConnectionQuality() {
        const fps = this.metrics.fps || 0;
        const latency = this.metrics.latency || 0;
        const captureTime = this.metrics.captureTime || 0;

        // Determine quality level
        if (fps >= 8 && latency < 500 && captureTime < 1000) {
            return { level: 'good', description: `${fps} FPS, ${captureTime}ms capture` };
        } else if (fps >= 4 && captureTime < 2000) {
            return { level: 'ok', description: `${fps} FPS, ${captureTime}ms capture` };
        } else {
            return { level: 'slow', description: `${fps} FPS, ${captureTime}ms capture - WiFi ADB is slow` };
        }
    }
}

// ES6 export
export default LiveStream;

// Global export for non-module usage
window.LiveStream = LiveStream;
