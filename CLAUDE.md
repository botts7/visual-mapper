# Visual Mapper Project Instructions

## Building the Android Companion App

The Android app requires JAVA_HOME to be set. Use this command to build:

```bash
cd "C:/Users/botts/Downloads/Visual Mapper/android-companion" && JAVA_HOME="/c/Program Files/Android/Android Studio/jbr" ./gradlew.bat assembleDebug
```

### APK Location
After build: `android-companion/app/build/outputs/apk/debug/app-debug.apk`

### Installing on Device

```bash
adb install -r "C:/Users/botts/Downloads/Visual Mapper/android-companion/app/build/outputs/apk/debug/app-debug.apk"
```

### Force Restart App (if needed)

```bash
adb shell am force-stop com.visualmapper.companion && adb shell am start -n com.visualmapper.companion/.ui.fragments.MainContainerActivity
```

### WiFi ADB Connection (if needed)

```bash
adb pair <ip>:<pair-port> <pairing-code>
adb connect <ip>:<connection-port>
```

## Running the Backend

```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 3000 --log-level info
```

## Key Files

### Streaming Optimization
- `android-companion/app/src/main/java/com/visualmapper/companion/streaming/HardwareEncoder.kt` - H.264 hardware encoding
- `android-companion/app/src/main/java/com/visualmapper/companion/streaming/ScreenCaptureService.kt` - Screen capture service
- `android-companion/app/src/main/java/com/visualmapper/companion/streaming/StreamingConfig.kt` - Streaming configuration
- `backend/core/streaming/companion_receiver.py` - Backend frame receiver
- `backend/routes/streaming.py` - Streaming API endpoints
