# Phase 8 Implementation Plan - Advanced Flow System

**Version:** 1.0.0
**Created:** 2025-12-23
**Target Completion:** 5 weeks
**Status:** Planning Phase

---

## 🎯 Executive Summary

Phase 8 transforms Visual Mapper from a simple screenshot scraper to a sophisticated automation platform by implementing:

1. **Multi-Sensor Collection Flows** - Navigate once, capture many sensors (10x efficiency gain)
2. **Screenshot Stitching** - Capture full scrollable pages using OpenCV template matching
3. **Smart Scheduling Engine** - Priority queue with device locking to prevent overlaps
4. **Performance Monitoring** - Real-time alerts with actionable recommendations
5. **Hierarchical UX** - Flow-chart based UI inspired by Power Automate, n8n, and Node-RED

**Critical Problem Solved:** Current implementation can only capture sensors from the current screen. No app navigation = severely limited usefulness.

**Performance Impact:**
- **Before:** 10 Spotify sensors = 10 app launches = 10 screenshots = ~60s + high battery drain
- **After:** 10 sensors in 1 flow = 1 app launch = 1 screenshot = ~6s + minimal battery impact

---

## 📋 Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Screenshot Stitching Algorithm](#screenshot-stitching-algorithm)
3. [Flow Execution System](#flow-execution-system)
4. [Scheduling Engine](#scheduling-engine)
5. [Performance Monitoring](#performance-monitoring)
6. [UI/UX Design](#uiux-design)
7. [Implementation Phases](#implementation-phases)
8. [API Specification](#api-specification)
9. [Testing Strategy](#testing-strategy)
10. [Success Criteria](#success-criteria)

---

## Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend Layer                          │
├─────────────────────────────────────────────────────────────┤
│  flows.html         - Flow management page                   │
│  flow-builder.js    - Visual flow editor (Simple + Advanced) │
│  flow-card.js       - Flow summary cards                     │
│  perf-dashboard.js  - Performance monitoring UI              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                       API Layer                              │
├─────────────────────────────────────────────────────────────┤
│  POST   /api/flows                    - Create flow          │
│  GET    /api/flows/{device_id}        - List flows           │
│  PUT    /api/flows/{flow_id}          - Update flow          │
│  DELETE /api/flows/{flow_id}          - Delete flow          │
│  POST   /api/flows/{flow_id}/execute  - Manual execution     │
│  GET    /api/flows/metrics            - Performance data     │
│  POST   /api/adb/{device_id}/stitch   - Screenshot stitch    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    Core Engine Layer                         │
├─────────────────────────────────────────────────────────────┤
│  flow_executor.py     - Unified flow execution engine        │
│  flow_scheduler.py    - Priority queue + device locking      │
│  performance_monitor.py - Metrics tracking + alerts          │
│  screenshot_stitcher.py - OpenCV template matching           │
│  adb_helpers.py       - Smart navigation utilities           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                   Data/Storage Layer                         │
├─────────────────────────────────────────────────────────────┤
│  flow_manager.py      - CRUD operations (already created)    │
│  flow_models.py       - Pydantic models (already created)    │
│  config/flows/        - JSON storage per device              │
└─────────────────────────────────────────────────────────────┘
```

### Execution Flow

```
User Creates Flow (flows.html)
         ↓
FlowManager saves to config/flows/
         ↓
FlowScheduler adds to priority queue
         ↓
FlowExecutor locks device → executes steps → releases lock
         ↓
PerformanceMonitor tracks metrics → alerts if backlog
         ↓
MQTT publishes sensor states to Home Assistant
```

---

## Screenshot Stitching Algorithm

### Overview

Captures full scrollable pages by:
1. Taking initial screenshot
2. Scrolling down by calculated distance
3. Finding overlap region using OpenCV template matching
4. Stitching images together with pixel-perfect alignment
5. Detecting bottom of page (scroll position stops changing)

### Algorithm Specification

**Template Matching Approach:**
- **Method:** OpenCV `cv2.matchTemplate()` with `TM_CCOEFF_NORMED`
- **Why:** Most accurate for pixel-perfect alignment, handles anti-aliasing
- **Overlap Region:** 25% of screenshot height (~400 pixels on 1920x1080 screen)
- **Scroll Distance:** 75% of screenshot height (~1200 pixels)

**Pseudocode:**

```python
def capture_scrolling_screenshot(device_id: str, max_scrolls: int = 20) -> Image:
    """
    Capture full scrollable page using adaptive template matching

    Performance: ~1s per scroll, ~20s total for 20-screen page
    """
    images = []
    scroll_positions = []

    # 1. Capture initial screenshot
    img1 = capture_screenshot(device_id)
    images.append(img1)
    height = img1.height

    # 2. Calculate scroll and overlap regions
    scroll_distance = int(height * 0.75)  # 75% scroll
    overlap_height = int(height * 0.25)   # 25% overlap

    for i in range(max_scrolls):
        # 3. Get current scroll position (adb dumpsys)
        current_pos = get_scroll_position(device_id)
        scroll_positions.append(current_pos)

        # 4. Scroll down
        swipe(device_id,
              x1=height/2, y1=height*0.75,  # Start at 75%
              x2=height/2, y2=height*0.25,  # End at 25%
              duration=300)

        await asyncio.sleep(0.5)  # Wait for scroll animation

        # 5. Capture new screenshot
        img2 = capture_screenshot(device_id)

        # 6. Check if reached bottom (scroll position unchanged)
        new_pos = get_scroll_position(device_id)
        if new_pos == current_pos:
            break  # Bottom reached

        # 7. Find overlap offset using template matching
        template = img1.crop((0, height - overlap_height, width, height))
        search_region = img2.crop((0, 0, width, overlap_height * 2))

        offset_y = find_overlap_offset(template, search_region)

        # 8. Stitch images
        stitched = stitch_images(img1, img2, offset_y)

        # 9. Update for next iteration
        img1 = img2
        images.append(img2)

    return stitched


def find_overlap_offset(template: Image, search_region: Image) -> int:
    """
    Find Y-offset where template best matches search region
    Uses OpenCV template matching with normalized cross-correlation

    Returns: Y-offset in pixels
    """
    # Convert PIL to numpy arrays
    template_np = np.array(template)
    search_np = np.array(search_region)

    # Convert to grayscale for better matching
    template_gray = cv2.cvtColor(template_np, cv2.COLOR_RGB2GRAY)
    search_gray = cv2.cvtColor(search_np, cv2.COLOR_RGB2GRAY)

    # Template matching
    result = cv2.matchTemplate(search_gray, template_gray, cv2.TM_CCOEFF_NORMED)

    # Find best match
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    # max_loc = (x, y) of top-left corner of best match
    offset_y = max_loc[1]

    # Quality check
    if max_val < 0.8:  # Threshold for match quality
        logger.warning(f"Low match quality: {max_val}, may have alignment issues")

    return offset_y


def stitch_images(img1: Image, img2: Image, offset_y: int) -> Image:
    """
    Stitch two images with known Y-offset
    Uses alpha blending in overlap region for smooth transition
    """
    width = img1.width
    height1 = img1.height

    # Calculate final image height
    # img1 contributes: full height
    # img2 contributes: everything below offset_y
    final_height = height1 + (img2.height - offset_y)

    # Create new image
    stitched = Image.new('RGB', (width, final_height))

    # Paste img1 at top
    stitched.paste(img1, (0, 0))

    # Paste img2 below with offset
    stitched.paste(img2, (0, height1 - offset_y))

    # Optional: Alpha blend overlap region for smooth transition
    # (Advanced - for future improvement)

    return stitched


def get_scroll_position(device_id: str) -> int:
    """
    Get current scroll position from UI hierarchy

    Methods:
    1. adb shell dumpsys window | grep mCurrentFocus
    2. adb shell uiautomator dump → parse ScrollView position
    3. Fallback: Compare screenshots (perceptual hash)
    """
    # Method 1: UI hierarchy (most reliable)
    ui_xml = get_ui_elements(device_id)
    # Parse XML for ScrollView with scrollable="true"
    # Extract bounds and scrollY attribute

    # Method 2: Fallback - perceptual hash comparison
    # If scroll position can't be extracted from UI
```

### Edge Cases

1. **Dynamic Content (ads, infinite scroll):**
   - Solution: Compare scroll positions instead of image similarity
   - If position unchanged after scroll → bottom reached

2. **Memory Limits:**
   - Max 20 scrolls by default (configurable)
   - Each 1080p screenshot ~6MB → 20 scrolls = 120MB
   - Implement streaming stitching (don't keep all in memory)

3. **Bottom Detection:**
   - Primary: Scroll position unchanged
   - Fallback: Template matching fails (can't find overlap)
   - Fallback 2: Max scrolls reached

4. **Performance:**
   - Target: <1s per scroll iteration
   - Breakdown: 300ms scroll + 200ms screenshot + 300ms matching + 200ms stitching
   - Total for 20-screen page: ~20-25 seconds

### API Endpoint

```python
@app.post("/api/adb/{device_id}/screenshot/stitch")
async def stitch_scrolling_screenshot(
    device_id: str,
    max_scrolls: int = 20,
    scroll_ratio: float = 0.75,
    overlap_ratio: float = 0.25
):
    """
    Capture full scrollable page

    Returns:
    {
        "image": "base64_encoded_png",
        "metadata": {
            "scroll_count": 15,
            "final_height": 16200,
            "original_height": 1920,
            "duration_ms": 18500,
            "bottom_reached": true
        }
    }
    """
```

---

## Flow Execution System

### FlowExecutor Architecture

**Replaces:** `sensor_updater.py` and integrates `action_executor.py`

**Responsibilities:**
1. Execute flow steps sequentially
2. Handle retries and error recovery
3. Capture sensors at designated steps
4. Execute actions at designated steps
5. Track execution metrics
6. Publish results to MQTT

### Step Execution Map

```python
class FlowExecutor:
    """
    Unified execution engine for sensor collection and action execution
    """

    STEP_HANDLERS = {
        "launch_app": self._execute_launch_app,
        "wait": self._execute_wait,
        "tap": self._execute_tap,
        "swipe": self._execute_swipe,
        "text": self._execute_text,
        "keyevent": self._execute_keyevent,
        "execute_action": self._execute_action,
        "capture_sensors": self._execute_capture_sensors,
        "validate_screen": self._execute_validate_screen,
        "go_home": self._execute_go_home,
        "conditional": self._execute_conditional,
        "scroll_capture": self._execute_scroll_capture,  # NEW
    }

    async def execute_flow(self, flow: SensorCollectionFlow) -> FlowExecutionResult:
        """
        Execute complete flow

        Flow:
        1. Lock device (prevent concurrent flows)
        2. Execute each step sequentially
        3. Retry failed steps if retry_on_failure=True
        4. Stop on error if stop_on_error=True
        5. Capture screenshot for sensor steps
        6. Extract sensor values
        7. Publish to MQTT
        8. Update flow metrics
        9. Release device lock
        """
        start_time = time.time()
        result = FlowExecutionResult(
            flow_id=flow.flow_id,
            success=False,
            executed_steps=0,
            captured_sensors={}
        )

        # 1. Lock device
        if not await self.scheduler.lock_device(flow.device_id):
            result.error_message = "Device locked by another flow"
            return result

        try:
            # 2. Execute steps
            for i, step in enumerate(flow.steps):
                # Timeout check
                elapsed = time.time() - start_time
                if elapsed > flow.flow_timeout:
                    result.error_message = f"Flow timeout after {elapsed}s"
                    result.failed_step = i
                    break

                # Execute step with retry
                success = await self._execute_step_with_retry(
                    flow.device_id,
                    step,
                    result
                )

                if not success:
                    result.failed_step = i
                    if flow.stop_on_error:
                        break

                result.executed_steps += 1

            # 3. Mark success if all steps executed
            result.success = (result.executed_steps == len(flow.steps))

            # 4. Update flow metadata
            flow.last_executed = datetime.now()
            flow.execution_count += 1
            if result.success:
                flow.success_count += 1
                flow.last_success = True
                flow.last_error = None
            else:
                flow.failure_count += 1
                flow.last_success = False
                flow.last_error = result.error_message

            self.flow_manager.update_flow(flow)

        finally:
            # 5. Release device lock
            await self.scheduler.unlock_device(flow.device_id)

        result.execution_time_ms = int((time.time() - start_time) * 1000)
        return result


    async def _execute_step_with_retry(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """Execute step with retry logic"""
        max_attempts = step.max_retries if step.retry_on_failure else 1

        for attempt in range(max_attempts):
            try:
                handler = self.STEP_HANDLERS.get(step.step_type)
                if not handler:
                    raise ValueError(f"Unknown step type: {step.step_type}")

                success = await handler(device_id, step, result)

                if success:
                    return True

                if attempt < max_attempts - 1:
                    logger.info(f"Retrying step {step.step_type} (attempt {attempt+2}/{max_attempts})")
                    await asyncio.sleep(1)  # Brief delay before retry

            except Exception as e:
                logger.error(f"Step execution error: {e}")
                if attempt == max_attempts - 1:
                    result.error_message = str(e)
                    return False

        return False


    async def _execute_capture_sensors(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """
        Capture sensors at this step
        Uses current screenshot (already in memory from navigation)
        """
        if not step.sensor_ids:
            return True

        # 1. Capture screenshot
        screenshot = await self.adb_bridge.capture_screenshot(device_id)

        # 2. Extract each sensor
        for sensor_id in step.sensor_ids:
            sensor = self.sensor_manager.get_sensor(device_id, sensor_id)
            if not sensor:
                logger.warning(f"Sensor {sensor_id} not found")
                continue

            # 3. Extract value using text_extractor
            value = self.text_extractor.extract(
                screenshot,
                sensor.source.custom_bounds,
                sensor.extraction_rule
            )

            # 4. Store in result
            result.captured_sensors[sensor_id] = value

            # 5. Publish to MQTT immediately (don't wait for flow completion)
            await self.mqtt_manager.publish_sensor_state(sensor, value)

        return True


    async def _execute_validate_screen(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """
        Validate expected UI element is present

        Uses UI hierarchy matching:
        - step.validation_element = {"text": "Now Playing", "class": "android.widget.TextView"}
        """
        if not step.validation_element:
            return True

        # Get UI hierarchy
        ui_elements = await self.adb_bridge.get_ui_elements(device_id)

        # Search for matching element
        for element in ui_elements:
            match = True
            for key, value in step.validation_element.items():
                if element.get(key) != value:
                    match = False
                    break

            if match:
                logger.info(f"Validation successful: found {step.validation_element}")
                return True

        logger.warning(f"Validation failed: {step.validation_element} not found")
        return False


    async def _execute_scroll_capture(
        self,
        device_id: str,
        step: FlowStep,
        result: FlowExecutionResult
    ) -> bool:
        """
        NEW: Capture full scrollable page
        Uses screenshot stitching algorithm
        """
        stitched = await self.screenshot_stitcher.capture_scrolling_screenshot(
            device_id,
            max_scrolls=step.max_scrolls or 20
        )

        # Store stitched screenshot for sensor extraction
        self._current_screenshot = stitched

        return True
```

### Simple Mode Auto-Migration

**Problem:** Existing sensors have navigation config but no flows

**Solution:** Auto-generate simple flows from sensor definitions

```python
# Already implemented in flow_models.py:
def sensor_to_simple_flow(sensor: SensorDefinition) -> SensorCollectionFlow:
    """
    Convert sensor with navigation config to simple flow

    Example:
    - Sensor: Spotify Now Playing
    - target_app: com.spotify.music
    - prerequisite_actions: ["spotify_goto_now_playing"]

    Generated Flow:
    1. launch_app: com.spotify.music
    2. wait: 2000ms
    3. execute_action: spotify_goto_now_playing
    4. wait: 500ms
    5. validate_screen: {"text": "Now Playing"}
    6. capture_sensors: [spotify_now_playing]
    7. go_home
    """
```

**Migration Strategy:**
1. On first startup after Phase 8 upgrade:
   - Scan all sensors for `target_app` or `prerequisite_actions`
   - Auto-generate simple flows using `sensor_to_simple_flow()`
   - Save flows to `config/flows/`
   - Log migration: "Migrated 15 sensors to 15 simple flows"

2. Backward compatibility:
   - Keep `sensor_updater.py` as fallback for sensors without flows
   - Gradual migration: new sensors → flows, old sensors → legacy updater

---

## Scheduling Engine

### Priority Queue System

**Problem:** Multiple flows for same device must not overlap (ADB limitations)

**Solution:** Device-level locking with priority queue

### Architecture

```python
class FlowScheduler:
    """
    Manages flow execution scheduling

    Features:
    - Priority queue (on-demand > periodic)
    - Device-level locking
    - Queue depth tracking
    - Backlog detection
    """

    def __init__(self):
        # Device locks
        self._device_locks: Dict[str, asyncio.Lock] = {}

        # Priority queues per device
        self._queues: Dict[str, asyncio.PriorityQueue] = {}

        # Background tasks
        self._scheduler_tasks: Dict[str, asyncio.Task] = {}

        # Metrics
        self._queue_depths: Dict[str, int] = {}
        self._last_execution: Dict[str, datetime] = {}


    async def schedule_flow(
        self,
        flow: SensorCollectionFlow,
        priority: int = 10,
        reason: str = "periodic"
    ):
        """
        Add flow to execution queue

        Priorities:
        - 0-4: On-demand (user triggered, Home Assistant automation)
        - 5-9: High priority periodic (fast update intervals)
        - 10-14: Normal priority periodic (standard intervals)
        - 15-19: Low priority periodic (slow update intervals)
        """
        device_id = flow.device_id

        # Create queue if needed
        if device_id not in self._queues:
            self._queues[device_id] = asyncio.PriorityQueue()
            self._device_locks[device_id] = asyncio.Lock()

        # Add to queue
        queue_item = (priority, time.time(), flow, reason)
        await self._queues[device_id].put(queue_item)

        # Update metrics
        self._queue_depths[device_id] = self._queues[device_id].qsize()

        # Start scheduler if not running
        if device_id not in self._scheduler_tasks:
            task = asyncio.create_task(self._run_scheduler(device_id))
            self._scheduler_tasks[device_id] = task


    async def _run_scheduler(self, device_id: str):
        """
        Background task that processes queue for a device

        Flow:
        1. Wait for item in queue
        2. Lock device
        3. Execute flow
        4. Release lock
        5. Update metrics
        6. Repeat
        """
        queue = self._queues[device_id]

        while True:
            try:
                # 1. Wait for flow (blocks until available)
                priority, timestamp, flow, reason = await queue.get()

                # 2. Check if flow still enabled
                if not flow.enabled:
                    logger.info(f"Skipping disabled flow: {flow.flow_id}")
                    continue

                # 3. Execute with lock
                logger.info(f"Executing flow {flow.flow_id} (priority={priority}, reason={reason})")

                result = await self.flow_executor.execute_flow(flow)

                # 4. Update metrics
                self._last_execution[device_id] = datetime.now()
                self._queue_depths[device_id] = queue.qsize()

                # 5. Send to performance monitor
                await self.performance_monitor.record_execution(flow, result)

                # 6. Reschedule if periodic
                if reason == "periodic" and flow.enabled:
                    await asyncio.sleep(flow.update_interval_seconds)
                    await self.schedule_flow(flow, priority, reason)

            except Exception as e:
                logger.error(f"Scheduler error for {device_id}: {e}")
                await asyncio.sleep(5)  # Brief pause before retry


    async def lock_device(self, device_id: str) -> bool:
        """
        Lock device for exclusive access
        Non-blocking - returns False if already locked
        """
        if device_id not in self._device_locks:
            self._device_locks[device_id] = asyncio.Lock()

        lock = self._device_locks[device_id]

        # Try to acquire without blocking
        acquired = lock.locked() == False
        if acquired:
            await lock.acquire()

        return acquired


    async def unlock_device(self, device_id: str):
        """Release device lock"""
        if device_id in self._device_locks:
            self._device_locks[device_id].release()


    def get_queue_depth(self, device_id: str) -> int:
        """Get current queue depth for performance monitoring"""
        return self._queue_depths.get(device_id, 0)
```

### Periodic Scheduling

**Problem:** Each flow has different `update_interval_seconds`

**Solution:** Independent scheduling per flow

```python
async def start_periodic_flows(self, device_id: str):
    """
    Start all enabled periodic flows for a device
    Called on device connection or server startup
    """
    flows = self.flow_manager.get_enabled_flows(device_id)

    for flow in flows:
        # Calculate priority based on interval
        if flow.update_interval_seconds < 30:
            priority = 5  # High priority (fast updates)
        elif flow.update_interval_seconds < 120:
            priority = 10  # Normal priority
        else:
            priority = 15  # Low priority (slow updates)

        # Schedule immediately
        await self.schedule_flow(flow, priority, reason="periodic")

        logger.info(f"Started periodic flow: {flow.name} (interval={flow.update_interval_seconds}s)")
```

---

## Performance Monitoring

### Metrics Tracking

**Tracks:**
1. Queue depth per device
2. Execution time per flow
3. Success/failure rates
4. Backlog detection (queue growing faster than processing)
5. Slow step identification

### Alert System

```python
class PerformanceMonitor:
    """
    Monitors flow execution performance and generates alerts
    """

    def __init__(self):
        # Metrics storage
        self._execution_history: Dict[str, List[FlowExecutionResult]] = {}
        self._alerts: List[PerformanceAlert] = []

        # Thresholds
        self.QUEUE_DEPTH_WARNING = 5
        self.QUEUE_DEPTH_CRITICAL = 10
        self.BACKLOG_RATIO = 0.5  # If execution > 50% of interval


    async def record_execution(
        self,
        flow: SensorCollectionFlow,
        result: FlowExecutionResult
    ):
        """Record execution result and check for issues"""
        device_id = flow.device_id

        # 1. Store result
        if device_id not in self._execution_history:
            self._execution_history[device_id] = []

        self._execution_history[device_id].append(result)

        # Keep last 100 results
        if len(self._execution_history[device_id]) > 100:
            self._execution_history[device_id] = self._execution_history[device_id][-100:]

        # 2. Check queue depth
        queue_depth = self.scheduler.get_queue_depth(device_id)

        if queue_depth > self.QUEUE_DEPTH_CRITICAL:
            await self._create_alert(
                device_id,
                severity="critical",
                message=f"Queue backlog critical: {queue_depth} flows waiting",
                recommendations=[
                    "Increase update intervals for non-critical sensors",
                    "Disable unused flows",
                    "Combine sensors into optimized flows",
                    f"Current avg execution time: {self._get_avg_execution_time(device_id)}ms"
                ]
            )

        elif queue_depth > self.QUEUE_DEPTH_WARNING:
            await self._create_alert(
                device_id,
                severity="warning",
                message=f"Queue backlog detected: {queue_depth} flows waiting",
                recommendations=[
                    "Consider increasing update intervals",
                    "Review flow execution times"
                ]
            )

        # 3. Check execution time vs interval
        execution_ms = result.execution_time_ms
        interval_ms = flow.update_interval_seconds * 1000

        if execution_ms > (interval_ms * self.BACKLOG_RATIO):
            await self._create_alert(
                device_id,
                severity="warning",
                message=f"Flow '{flow.name}' taking too long: {execution_ms}ms (interval: {interval_ms}ms)",
                recommendations=[
                    f"Increase update interval to at least {int(execution_ms / 1000 * 2)}s",
                    "Optimize flow steps (remove unnecessary waits)",
                    "Check for failed validation steps causing retries"
                ]
            )

        # 4. Check failure rate
        recent_results = self._execution_history[device_id][-10:]
        failure_rate = sum(1 for r in recent_results if not r.success) / len(recent_results)

        if failure_rate > 0.5:
            await self._create_alert(
                device_id,
                severity="error",
                message=f"Flow '{flow.name}' failing frequently: {int(failure_rate*100)}% failure rate",
                recommendations=[
                    f"Check device connection (last error: {flow.last_error})",
                    "Review failed step validation",
                    "Increase navigation timeouts"
                ]
            )


    def _get_avg_execution_time(self, device_id: str) -> int:
        """Calculate average execution time for device"""
        history = self._execution_history.get(device_id, [])
        if not history:
            return 0

        return int(sum(r.execution_time_ms for r in history) / len(history))


    async def _create_alert(
        self,
        device_id: str,
        severity: str,
        message: str,
        recommendations: List[str]
    ):
        """
        Create performance alert

        Alerts shown in:
        1. Performance dashboard UI
        2. MQTT (optional notification to HA)
        3. Logs
        """
        alert = PerformanceAlert(
            device_id=device_id,
            severity=severity,
            message=message,
            recommendations=recommendations,
            timestamp=datetime.now()
        )

        self._alerts.append(alert)

        # Publish to MQTT for Home Assistant notification
        if severity in ["error", "critical"]:
            await self.mqtt_manager.publish_alert(alert)

        logger.warning(f"[PerformanceMonitor] {severity.upper()}: {message}")


    def get_metrics(self, device_id: str) -> Dict[str, Any]:
        """Get performance metrics for UI dashboard"""
        history = self._execution_history.get(device_id, [])

        if not history:
            return {"no_data": True}

        recent = history[-10:]

        return {
            "queue_depth": self.scheduler.get_queue_depth(device_id),
            "avg_execution_time_ms": self._get_avg_execution_time(device_id),
            "success_rate": sum(1 for r in recent if r.success) / len(recent),
            "total_executions": len(history),
            "recent_alerts": [a.dict() for a in self._alerts[-5:]],
            "slowest_flows": self._get_slowest_flows(device_id, limit=5)
        }
```

---

## UI/UX Design

### Design Principles (From Research)

Based on web research of Power Automate, n8n, Automate, Tasker, Node-RED, Home Assistant:

**Key Findings:**
1. **Visual Flow-Chart** (n8n, Automate) - Most intuitive for complex flows
2. **Two-Mode Approach** (MacroDroid vs Tasker) - Simple for beginners, Advanced for power users
3. **Card-Based Layout** (Home Assistant) - Expandable cards with metrics
4. **Hierarchical Organization** (Power Automate) - Projects/folders with descriptive naming
5. **Link-Out Pattern** (Node-RED) - Keep main view clean, link to details

### Page Structure

```
┌─────────────────────────────────────────────────────────────┐
│  Visual Mapper - Flows                           [+ New]     │
├─────────────────────────────────────────────────────────────┤
│  📊 Performance Dashboard                                    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Device: Pixel 6 (192.168.1.100:5555)               │    │
│  │  Queue: 2 flows waiting                              │    │
│  │  Avg Execution: 4.2s  Success Rate: 98%              │    │
│  │  ⚠️  1 warning: Spotify flow taking 55% of interval │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  🎯 Quick Flow Builder (Simple Mode)                        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Select sensors to combine into optimized flow:     │    │
│  │  ☑ Spotify - Now Playing                            │    │
│  │  ☑ Spotify - Artist                                 │    │
│  │  ☑ Spotify - Volume                                 │    │
│  │  [Generate Flow] ← Auto-creates navigation          │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  📋 Active Flows                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  🎵 Spotify Multi-Sensor Collection                  │    │
│  │  3 sensors • 60s interval • Enabled                  │    │
│  │  Last run: 2m ago • ✅ Success                       │    │
│  │  [Edit] [▶ Execute] [📊 Metrics] [❌ Delete]        │    │
│  │                                                      │    │
│  │  [Expand ▼]                                          │    │
│  │  Steps:                                              │    │
│  │    1. 🚀 Launch com.spotify.music                    │    │
│  │    2. ⏱️ Wait 2s                                     │    │
│  │    3. ✅ Validate "Now Playing" screen              │    │
│  │    4. 📸 Capture: now_playing, artist, volume       │    │
│  │    5. 🏠 Return home                                 │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  📱 Simple: Phone Battery                            │    │
│  │  1 sensor • 300s interval • Enabled                  │    │
│  │  Last run: 1m ago • ✅ Success                       │    │
│  │  [Edit] [▶ Execute] [Convert to Advanced]           │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Advanced Flow Builder

**Visual Flow-Chart Editor** (inspired by Automate app, n8n):

```
┌─────────────────────────────────────────────────────────────┐
│  Flow Builder - Spotify Multi-Sensor                         │
├─────────────────────────────────────────────────────────────┤
│  [◀ Back] [💾 Save] [▶ Test Run] [❌ Delete]                │
├─────────────────────────────────────────────────────────────┤
│  Canvas                              │  Step Palette         │
│  ┌───────────────────────────────┐  │  ┌──────────────────┐ │
│  │                               │  │  │  🚀 Launch App   │ │
│  │  [START]                      │  │  │  ⏱️ Wait         │ │
│  │     │                         │  │  │  👆 Tap          │ │
│  │     ↓                         │  │  │  👉 Swipe        │ │
│  │  ┌──────────────┐             │  │  │  📸 Capture      │ │
│  │  │ 🚀 Launch    │             │  │  │  ✅ Validate     │ │
│  │  │ Spotify      │             │  │  │  ⚙️  Action      │ │
│  │  └──────────────┘             │  │  │  🏠 Go Home      │ │
│  │     │                         │  │  │  📜 Scroll Cap   │ │
│  │     ↓                         │  │  │  🔀 Conditional  │ │
│  │  ┌──────────────┐             │  │  └──────────────────┘ │
│  │  │ ⏱️ Wait 2s   │             │  │                        │
│  │  └──────────────┘             │  │  Properties            │
│  │     │                         │  │  ┌──────────────────┐ │
│  │     ↓                         │  │  │  Step Type:      │ │
│  │  ┌──────────────┐             │  │  │  📸 Capture      │ │
│  │  │ ✅ Validate  │             │  │  │                  │ │
│  │  │ "Now Playing"│             │  │  │  Sensor IDs:     │ │
│  │  └──────────────┘             │  │  │  ☑ now_playing   │ │
│  │     │                         │  │  │  ☑ artist        │ │
│  │     ↓                         │  │  │  ☑ volume        │ │
│  │  ┌──────────────┐             │  │  │                  │ │
│  │  │ 📸 Capture   │ ← Selected  │  │  │  Retry: ☑ Yes    │ │
│  │  │ 3 sensors    │             │  │  │  Max: 3          │ │
│  │  └──────────────┘             │  │  └──────────────────┘ │
│  │     │                         │  │                        │
│  │     ↓                         │  │                        │
│  │  ┌──────────────┐             │  │                        │
│  │  │ 🏠 Go Home   │             │  │                        │
│  │  └──────────────┘             │  │                        │
│  │     │                         │  │                        │
│  │     ↓                         │  │                        │
│  │  [END]                        │  │                        │
│  │                               │  │                        │
│  └───────────────────────────────┘  │                        │
└─────────────────────────────────────┴────────────────────────┘
```

**Interaction:**
- Drag steps from palette to canvas
- Click step to edit in properties panel
- Arrow connections auto-generated (sequential flow)
- Click arrow to insert step between
- Delete step → auto-reconnects flow

### Component Breakdown

#### **1. FlowCard.js**
```javascript
/**
 * Expandable card showing flow summary + details
 *
 * Features:
 * - Collapse/expand step list
 * - Real-time status updates via WebSocket
 * - Quick actions (execute, edit, delete)
 * - Execution metrics
 */

class FlowCard {
    constructor(flow) {
        this.flow = flow;
    }

    render() {
        return `
            <div class="flow-card" data-flow-id="${this.flow.flow_id}">
                <div class="flow-header">
                    <div class="flow-icon">${this._getIcon()}</div>
                    <div class="flow-info">
                        <h3>${this.flow.name}</h3>
                        <div class="flow-meta">
                            ${this.flow.steps.length} steps •
                            ${this.flow.update_interval_seconds}s interval •
                            ${this.flow.enabled ? 'Enabled' : 'Disabled'}
                        </div>
                        <div class="flow-status">
                            Last run: ${this._formatTimestamp(this.flow.last_executed)} •
                            ${this._getStatusBadge()}
                        </div>
                    </div>
                    <div class="flow-actions">
                        <button onclick="editFlow('${this.flow.flow_id}')">Edit</button>
                        <button onclick="executeFlow('${this.flow.flow_id}')">▶ Execute</button>
                        <button onclick="showMetrics('${this.flow.flow_id}')">📊 Metrics</button>
                        <button onclick="deleteFlow('${this.flow.flow_id}')">Delete</button>
                    </div>
                </div>

                <div class="flow-steps collapsed">
                    <button onclick="toggleSteps('${this.flow.flow_id}')">
                        Show Steps ▼
                    </button>
                    <ol class="step-list">
                        ${this.flow.steps.map(step => this._renderStep(step)).join('')}
                    </ol>
                </div>

                <div class="flow-metrics">
                    <span>Executions: ${this.flow.execution_count}</span>
                    <span>Success Rate: ${this._getSuccessRate()}%</span>
                    ${this.flow.last_error ? `<span class="error">Last Error: ${this.flow.last_error}</span>` : ''}
                </div>
            </div>
        `;
    }

    _renderStep(step) {
        const icons = {
            'launch_app': '🚀',
            'wait': '⏱️',
            'tap': '👆',
            'swipe': '👉',
            'capture_sensors': '📸',
            'validate_screen': '✅',
            'go_home': '🏠',
            'scroll_capture': '📜'
        };

        return `
            <li>
                ${icons[step.step_type] || '⚙️'}
                ${step.description || step.step_type}
            </li>
        `;
    }
}
```

#### **2. QuickFlowBuilder.js**
```javascript
/**
 * Simple mode - auto-generate flows from sensor selection
 *
 * Algorithm:
 * 1. User selects multiple sensors
 * 2. Group by target_app
 * 3. Auto-generate optimized flow:
 *    - Single launch_app
 *    - Execute all prerequisite_actions (deduplicated)
 *    - Capture all sensors at once
 *    - Single go_home
 */

class QuickFlowBuilder {
    constructor(sensors) {
        this.sensors = sensors;
    }

    generateFlow(selectedSensorIds) {
        // 1. Get sensor objects
        const selectedSensors = this.sensors.filter(s =>
            selectedSensorIds.includes(s.sensor_id)
        );

        // 2. Group by target_app
        const groups = this._groupByApp(selectedSensors);

        // 3. Generate flow for each app
        const flows = groups.map(group => this._createFlowForGroup(group));

        return flows;
    }

    _groupByApp(sensors) {
        const groups = {};

        for (const sensor of sensors) {
            const app = sensor.target_app || 'none';
            if (!groups[app]) {
                groups[app] = [];
            }
            groups[app].push(sensor);
        }

        return Object.values(groups);
    }

    _createFlowForGroup(sensors) {
        const steps = [];
        const targetApp = sensors[0].target_app;
        const sensorIds = sensors.map(s => s.sensor_id);

        // 1. Launch app
        if (targetApp) {
            steps.push({
                step_type: 'launch_app',
                package: targetApp,
                description: `Launch ${targetApp}`
            });

            steps.push({
                step_type: 'wait',
                duration: 2000,
                description: 'Wait for app to load'
            });
        }

        // 2. Execute prerequisite actions (deduplicated)
        const uniqueActions = [...new Set(
            sensors.flatMap(s => s.prerequisite_actions)
        )];

        for (const actionId of uniqueActions) {
            steps.push({
                step_type: 'execute_action',
                action_id: actionId,
                description: `Execute ${actionId}`
            });

            steps.push({
                step_type: 'wait',
                duration: 500
            });
        }

        // 3. Validate screen (use first sensor's validation)
        if (sensors[0].validation_element) {
            steps.push({
                step_type: 'validate_screen',
                validation_element: sensors[0].validation_element,
                retry_on_failure: true,
                max_retries: 3,
                description: 'Validate correct screen'
            });
        }

        // 4. Capture all sensors
        steps.push({
            step_type: 'capture_sensors',
            sensor_ids: sensorIds,
            description: `Capture ${sensorIds.length} sensors`
        });

        // 5. Go home
        if (sensors[0].return_home_after) {
            steps.push({
                step_type: 'go_home',
                description: 'Return to home screen'
            });
        }

        // 6. Create flow object
        return {
            flow_id: `quick_${targetApp || 'combined'}_${Date.now()}`,
            device_id: sensors[0].device_id,
            name: `Quick Flow: ${targetApp || 'Combined'}`,
            description: `Auto-generated flow for ${sensorIds.length} sensors`,
            steps: steps,
            update_interval_seconds: Math.min(...sensors.map(s => s.update_interval_seconds)),
            enabled: true
        };
    }
}
```

#### **3. AdvancedFlowBuilder.js**
```javascript
/**
 * Advanced mode - visual flow-chart editor
 *
 * Features:
 * - Drag-and-drop step blocks
 * - Visual canvas with arrow connections
 * - Properties panel for step configuration
 * - Real-time validation
 */

class AdvancedFlowBuilder {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.canvas = null;
        this.palette = null;
        this.properties = null;

        this.flow = {
            steps: [],
            selected_step: null
        };
    }

    init() {
        this.render();
        this._initDragDrop();
    }

    render() {
        this.container.innerHTML = `
            <div class="flow-builder-layout">
                <div class="canvas" id="flowCanvas">
                    <!-- Flow-chart rendered here -->
                </div>
                <div class="sidebar">
                    <div class="palette" id="stepPalette">
                        <!-- Drag palette -->
                    </div>
                    <div class="properties" id="stepProperties">
                        <!-- Selected step config -->
                    </div>
                </div>
            </div>
        `;

        this._renderPalette();
        this._renderCanvas();
    }

    _renderPalette() {
        const stepTypes = [
            {type: 'launch_app', icon: '🚀', label: 'Launch App'},
            {type: 'wait', icon: '⏱️', label: 'Wait'},
            {type: 'tap', icon: '👆', label: 'Tap'},
            {type: 'swipe', icon: '👉', label: 'Swipe'},
            {type: 'capture_sensors', icon: '📸', label: 'Capture'},
            {type: 'validate_screen', icon: '✅', label: 'Validate'},
            {type: 'execute_action', icon: '⚙️', label: 'Action'},
            {type: 'go_home', icon: '🏠', label: 'Go Home'},
            {type: 'scroll_capture', icon: '📜', label: 'Scroll Capture'},
            {type: 'conditional', icon: '🔀', label: 'Conditional'}
        ];

        const palette = document.getElementById('stepPalette');
        palette.innerHTML = stepTypes.map(st => `
            <div class="step-block" draggable="true" data-step-type="${st.type}">
                <span class="icon">${st.icon}</span>
                <span class="label">${st.label}</span>
            </div>
        `).join('');
    }

    addStep(stepType, afterIndex = -1) {
        const newStep = {
            step_type: stepType,
            description: `New ${stepType} step`
        };

        if (afterIndex === -1) {
            this.flow.steps.push(newStep);
        } else {
            this.flow.steps.splice(afterIndex + 1, 0, newStep);
        }

        this._renderCanvas();
    }

    _renderCanvas() {
        const canvas = document.getElementById('flowCanvas');

        if (this.flow.steps.length === 0) {
            canvas.innerHTML = `
                <div class="empty-state">
                    <p>Drag steps from the palette to build your flow</p>
                </div>
            `;
            return;
        }

        let html = '<div class="flow-start">START</div>';

        for (let i = 0; i < this.flow.steps.length; i++) {
            const step = this.flow.steps[i];
            const isSelected = this.flow.selected_step === i;

            html += `
                <div class="arrow-connector">
                    <div class="arrow">↓</div>
                    <button class="insert-btn" onclick="insertStepBefore(${i})">+</button>
                </div>
                <div class="step-block ${isSelected ? 'selected' : ''}"
                     onclick="selectStep(${i})"
                     data-step-index="${i}">
                    <div class="step-icon">${this._getStepIcon(step.step_type)}</div>
                    <div class="step-content">
                        <div class="step-type">${step.step_type}</div>
                        <div class="step-desc">${step.description}</div>
                    </div>
                    <button class="delete-step" onclick="deleteStep(${i})">×</button>
                </div>
            `;
        }

        html += `
            <div class="arrow-connector">
                <div class="arrow">↓</div>
            </div>
            <div class="flow-end">END</div>
        `;

        canvas.innerHTML = html;
    }
}
```

#### **4. PerformanceDashboard.js**
```javascript
/**
 * Real-time performance monitoring UI
 *
 * Shows:
 * - Queue depth
 * - Avg execution time
 * - Success rate
 * - Active alerts with recommendations
 */

class PerformanceDashboard {
    constructor(deviceId) {
        this.deviceId = deviceId;
        this.metrics = null;
    }

    async refresh() {
        // Fetch metrics from API
        const response = await fetch(`/api/flows/metrics?device_id=${this.deviceId}`);
        this.metrics = await response.json();
        this.render();
    }

    render() {
        const container = document.getElementById('perfDashboard');

        if (!this.metrics || this.metrics.no_data) {
            container.innerHTML = '<p>No performance data yet</p>';
            return;
        }

        const queueStatus = this._getQueueStatus();
        const successRate = (this.metrics.success_rate * 100).toFixed(1);

        container.innerHTML = `
            <div class="perf-card ${queueStatus.severity}">
                <h3>Device: ${this.deviceId}</h3>

                <div class="metrics-grid">
                    <div class="metric">
                        <span class="label">Queue</span>
                        <span class="value">${this.metrics.queue_depth} flows</span>
                    </div>
                    <div class="metric">
                        <span class="label">Avg Execution</span>
                        <span class="value">${(this.metrics.avg_execution_time_ms / 1000).toFixed(1)}s</span>
                    </div>
                    <div class="metric">
                        <span class="label">Success Rate</span>
                        <span class="value">${successRate}%</span>
                    </div>
                </div>

                ${this._renderAlerts()}

                ${this._renderSlowFlows()}
            </div>
        `;
    }

    _getQueueStatus() {
        const depth = this.metrics.queue_depth;

        if (depth > 10) {
            return {severity: 'critical', label: 'Critical Backlog'};
        } else if (depth > 5) {
            return {severity: 'warning', label: 'Backlog Detected'};
        } else {
            return {severity: 'ok', label: 'Healthy'};
        }
    }

    _renderAlerts() {
        if (!this.metrics.recent_alerts || this.metrics.recent_alerts.length === 0) {
            return '';
        }

        return `
            <div class="alerts">
                <h4>⚠️ Recent Alerts</h4>
                ${this.metrics.recent_alerts.map(alert => `
                    <div class="alert ${alert.severity}">
                        <div class="alert-message">${alert.message}</div>
                        <div class="alert-recommendations">
                            <strong>Recommendations:</strong>
                            <ul>
                                ${alert.recommendations.map(rec => `<li>${rec}</li>`).join('')}
                            </ul>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    _renderSlowFlows() {
        if (!this.metrics.slowest_flows || this.metrics.slowest_flows.length === 0) {
            return '';
        }

        return `
            <div class="slow-flows">
                <h4>Slowest Flows</h4>
                <table>
                    <thead>
                        <tr>
                            <th>Flow</th>
                            <th>Avg Time</th>
                            <th>Interval</th>
                            <th>Ratio</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${this.metrics.slowest_flows.map(flow => `
                            <tr class="${this._getRowClass(flow)}">
                                <td>${flow.name}</td>
                                <td>${(flow.avg_time_ms / 1000).toFixed(1)}s</td>
                                <td>${flow.interval_s}s</td>
                                <td>${((flow.avg_time_ms / (flow.interval_s * 1000)) * 100).toFixed(0)}%</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    _getRowClass(flow) {
        const ratio = flow.avg_time_ms / (flow.interval_s * 1000);
        if (ratio > 0.5) return 'warning';
        if (ratio > 0.75) return 'critical';
        return '';
    }
}
```

---

## Implementation Phases

### Week 1: Core Engine

**Deliverables:**
- ✅ Screenshot stitching (`screenshot_stitcher.py`)
- ✅ Flow executor (`flow_executor.py`)
- ✅ Flow scheduler (`flow_scheduler.py`)
- ✅ ADB helpers (`adb_helpers.py` - UI hierarchy utilities)

**Tasks:**
1. Add OpenCV to `requirements.txt`
2. Implement template matching algorithm
3. Implement FlowExecutor with step handlers
4. Implement FlowScheduler with priority queue
5. Write unit tests (>60% coverage)
6. Integration test: Execute simple flow end-to-end

**Success Criteria:**
- Screenshot stitching works on 5+ test pages
- Flow executor completes all step types
- Scheduler prevents device lock conflicts
- Tests pass

---

### Week 2: Performance Monitoring

**Deliverables:**
- ✅ Performance monitor (`performance_monitor.py`)
- ✅ Alert system
- ✅ Metrics API endpoints

**Tasks:**
1. Implement PerformanceMonitor class
2. Add metrics tracking to FlowExecutor
3. Create alert generation logic
4. Add API endpoint: `GET /api/flows/metrics`
5. Test alert thresholds (queue depth, execution time)

**Success Criteria:**
- Metrics tracked for all executions
- Alerts generated when thresholds exceeded
- API returns accurate metrics

---

### Week 3: Backend Integration

**Deliverables:**
- ✅ API endpoints for flows
- ✅ Auto-migration from sensors to flows
- ✅ Server.py integration

**Tasks:**
1. Add flow management endpoints to `server.py`:
   - `POST /api/flows` - Create flow
   - `GET /api/flows/{device_id}` - List flows
   - `PUT /api/flows/{flow_id}` - Update flow
   - `DELETE /api/flows/{flow_id}` - Delete flow
   - `POST /api/flows/{flow_id}/execute` - Manual execution
2. Replace `sensor_updater` with `flow_executor` in startup
3. Implement auto-migration script
4. Test backward compatibility

**Success Criteria:**
- All API endpoints functional
- Existing sensors auto-migrate to flows
- No regressions in sensor updates

---

### Week 4: Frontend UI

**Deliverables:**
- ✅ `flows.html` page
- ✅ FlowCard component
- ✅ QuickFlowBuilder (Simple mode)
- ✅ PerformanceDashboard

**Tasks:**
1. Create `flows.html` page structure
2. Implement FlowCard.js component
3. Implement QuickFlowBuilder.js
4. Implement PerformanceDashboard.js
5. Add WebSocket updates for real-time status
6. Test UI on localhost:3000

**Success Criteria:**
- flows.html loads without errors
- Can create flow via Quick Builder
- Can view/edit/delete flows
- Performance dashboard shows metrics

---

### Week 5: Advanced Builder & Polish

**Deliverables:**
- ✅ AdvancedFlowBuilder (flow-chart editor)
- ✅ Complete testing
- ✅ Documentation updates

**Tasks:**
1. Implement AdvancedFlowBuilder.js (flow-chart canvas)
2. Add drag-and-drop functionality
3. Implement step properties panel
4. End-to-end testing (create flow → execute → verify MQTT)
5. Update USER_GUIDE.md with flow documentation
6. Update TROUBLESHOOTING_DETAILED.md with flow issues

**Success Criteria:**
- Can build complex flows visually
- Drag-and-drop works smoothly
- All tests pass
- Documentation complete

---

## API Specification

### Flow Management Endpoints

#### **POST /api/flows**
Create new flow

**Request:**
```json
{
  "flow_id": "spotify_multi_001",
  "device_id": "192.168.1.100:5555",
  "name": "Spotify Multi-Sensor",
  "description": "Collect all Spotify sensors in one flow",
  "steps": [
    {
      "step_type": "launch_app",
      "package": "com.spotify.music",
      "description": "Launch Spotify"
    },
    {
      "step_type": "wait",
      "duration": 2000
    },
    {
      "step_type": "capture_sensors",
      "sensor_ids": ["spotify_song", "spotify_artist"],
      "description": "Capture Now Playing"
    },
    {
      "step_type": "go_home"
    }
  ],
  "update_interval_seconds": 60,
  "enabled": true
}
```

**Response:**
```json
{
  "success": true,
  "flow_id": "spotify_multi_001",
  "message": "Flow created successfully"
}
```

---

#### **GET /api/flows/{device_id}**
List all flows for device

**Response:**
```json
{
  "device_id": "192.168.1.100:5555",
  "flows": [
    {
      "flow_id": "spotify_multi_001",
      "name": "Spotify Multi-Sensor",
      "enabled": true,
      "steps": [...],
      "last_executed": "2025-12-23T10:30:00",
      "execution_count": 145,
      "success_count": 142,
      "failure_count": 3,
      "last_success": true
    }
  ],
  "total": 1
}
```

---

#### **PUT /api/flows/{flow_id}**
Update existing flow

**Request:** (Same as POST)

**Response:**
```json
{
  "success": true,
  "message": "Flow updated successfully"
}
```

---

#### **DELETE /api/flows/{flow_id}**
Delete flow

**Response:**
```json
{
  "success": true,
  "message": "Flow deleted successfully"
}
```

---

#### **POST /api/flows/{flow_id}/execute**
Manually execute flow (high priority)

**Response:**
```json
{
  "success": true,
  "result": {
    "flow_id": "spotify_multi_001",
    "success": true,
    "executed_steps": 4,
    "captured_sensors": {
      "spotify_song": "Bohemian Rhapsody",
      "spotify_artist": "Queen"
    },
    "execution_time_ms": 4200,
    "timestamp": "2025-12-23T10:35:00"
  }
}
```

---

#### **GET /api/flows/metrics**
Get performance metrics

**Query Params:**
- `device_id` (required)

**Response:**
```json
{
  "device_id": "192.168.1.100:5555",
  "queue_depth": 2,
  "avg_execution_time_ms": 4200,
  "success_rate": 0.98,
  "total_executions": 450,
  "recent_alerts": [
    {
      "severity": "warning",
      "message": "Queue backlog detected: 6 flows waiting",
      "recommendations": [
        "Consider increasing update intervals",
        "Review flow execution times"
      ],
      "timestamp": "2025-12-23T10:30:00"
    }
  ],
  "slowest_flows": [
    {
      "flow_id": "spotify_multi_001",
      "name": "Spotify Multi-Sensor",
      "avg_time_ms": 4200,
      "interval_s": 60,
      "ratio": 0.07
    }
  ]
}
```

---

#### **POST /api/adb/{device_id}/screenshot/stitch**
Capture scrolling screenshot

**Request:**
```json
{
  "max_scrolls": 20,
  "scroll_ratio": 0.75,
  "overlap_ratio": 0.25
}
```

**Response:**
```json
{
  "success": true,
  "image": "data:image/png;base64,...",
  "metadata": {
    "scroll_count": 15,
    "final_height": 16200,
    "original_height": 1920,
    "duration_ms": 18500,
    "bottom_reached": true
  }
}
```

---

## Testing Strategy

### Unit Tests

**Coverage Target:** >60%

**Test Files:**
- `tests/test_screenshot_stitcher.py`
- `tests/test_flow_executor.py`
- `tests/test_flow_scheduler.py`
- `tests/test_performance_monitor.py`

**Critical Tests:**
1. Screenshot stitching with mock images
2. Template matching accuracy
3. Flow step execution (all types)
4. Scheduler queue priority
5. Device locking
6. Performance alert generation

---

### Integration Tests

**Test Scenarios:**
1. **Simple Flow End-to-End:**
   - Create flow via API
   - Scheduler picks up flow
   - FlowExecutor executes all steps
   - Sensors captured and published to MQTT
   - Metrics recorded

2. **Advanced Flow:**
   - Multi-step navigation (launch → tap → validate → capture)
   - Retry logic triggers on validation failure
   - Error handling stops flow on critical error

3. **Performance Monitoring:**
   - Queue depth exceeds threshold → alert generated
   - Slow flow detected → recommendations provided

4. **Screenshot Stitching:**
   - Capture scrolling page
   - Verify image height matches expected
   - Extract sensor from stitched image

---

### Manual Testing Checklist

- [ ] Create simple flow via Quick Builder
- [ ] Create advanced flow via visual editor
- [ ] Execute flow manually and verify MQTT updates
- [ ] Test retry logic (validation fails → retries → succeeds)
- [ ] Test error handling (invalid step → flow stops)
- [ ] Verify performance dashboard shows metrics
- [ ] Test alert generation (create backlog → alert appears)
- [ ] Screenshot stitching captures full page
- [ ] Auto-migration from sensors to flows

---

## Success Criteria

### Phase 8 Complete When:

1. **Core Functionality:**
   - ✅ Screenshot stitching works reliably
   - ✅ Flow executor handles all step types
   - ✅ Scheduler prevents device conflicts
   - ✅ Performance monitoring generates alerts

2. **User Experience:**
   - ✅ Simple mode: Auto-generate flows in <5 clicks
   - ✅ Advanced mode: Build complex flows visually
   - ✅ Performance dashboard provides actionable insights
   - ✅ Real-time updates via WebSocket

3. **Performance:**
   - ✅ 10 sensors → 1 flow = 10x faster than separate captures
   - ✅ Screenshot stitching <25s for 20-screen page
   - ✅ Flow execution <flow_timeout (60s default)
   - ✅ Queue backlog alerts within 30s of detection

4. **Testing:**
   - ✅ >60% unit test coverage
   - ✅ All integration tests pass
   - ✅ Manual testing checklist complete
   - ✅ No console errors in browser

5. **Documentation:**
   - ✅ USER_GUIDE.md updated with flow documentation
   - ✅ TROUBLESHOOTING_DETAILED.md covers flow issues
   - ✅ API documentation complete
   - ✅ Code comments for complex algorithms

6. **Backward Compatibility:**
   - ✅ Existing sensors auto-migrate to flows
   - ✅ Legacy sensor_updater fallback available
   - ✅ No breaking changes to MQTT topics

---

## Dependencies

### New Python Packages

```txt
# Add to requirements.txt
opencv-python>=4.8.0  # Template matching for screenshot stitching
numpy>=1.24.0         # Image array manipulation
```

### Existing Dependencies (Unchanged)
- FastAPI
- Pydantic
- Pillow (PIL)
- paho-mqtt
- aiofiles
- uvicorn

---

## Risk Assessment

### High Risk Items

1. **Screenshot Stitching Accuracy**
   - **Risk:** Template matching fails on dynamic content
   - **Mitigation:** Fallback to scroll position detection, configurable overlap ratio

2. **Performance Overhead**
   - **Risk:** Flow execution slower than expected
   - **Mitigation:** Optimize screenshot caching, parallel sensor extraction

3. **Device Lock Deadlocks**
   - **Risk:** Locks not released on exception
   - **Mitigation:** Use try/finally blocks, timeout-based lock release

### Medium Risk Items

1. **UI Complexity**
   - **Risk:** Flow-chart editor too complex for average user
   - **Mitigation:** Emphasize Simple mode, provide templates

2. **Migration Issues**
   - **Risk:** Sensor-to-flow migration breaks existing setups
   - **Mitigation:** Thorough testing, optional migration (user confirmation)

### Low Risk Items

1. **MQTT Topic Changes**
   - **Risk:** Breaking changes to MQTT structure
   - **Mitigation:** No changes planned, flows reuse existing sensor topics

---

## Open Questions

1. **Screenshot Stitching:**
   - Q: Should stitched screenshots be cached?
   - A: Yes, cache for 30s to avoid re-stitching on sensor extraction

2. **Flow Scheduling:**
   - Q: How to handle flows with same interval?
   - A: FIFO within priority level

3. **Performance Alerts:**
   - Q: Should alerts auto-clear when backlog resolves?
   - A: Yes, keep only last 5 alerts, mark as resolved when queue < threshold

4. **Advanced Builder:**
   - Q: Support conditional branches in UI?
   - A: Phase 8: Sequential only, Phase 9: Add conditionals

---

**Document Version:** 1.0.0
**Created:** 2025-12-23
**Last Updated:** 2025-12-23
**Author:** Claude (Sonnet 4.5)
**Status:** Ready for Review
