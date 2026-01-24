# Visual Mapper Project Instructions

## Building the Android Companion App

The Android app requires JAVA_HOME to be set correctly. Use this command to build:

```bash
cmd //c "C:\\Users\\botts\\build_android.bat"
```

Or use the batch file directly in Windows:
```cmd
C:\Users\botts\build_android.bat
```

The batch file sets JAVA_HOME and runs:
- `JAVA_HOME=C:\Program Files\Android\Android Studio\jbr`
- `gradlew clean assembleDebug`

### APK Location
After build: `android-companion\app\build\outputs\apk\debug\app-debug.apk`

### Installing on Device

1. Connect device via WiFi ADB:
   ```bash
   adb pair <ip>:<pair-port> <pairing-code>
   adb connect <ip>:<connection-port>
   ```

2. Install APK:
   ```bash
   adb install -r "C:\Users\botts\Downloads\Visual Mapper\android-companion\app\build\outputs\apk\debug\app-debug.apk"
   ```

3. Force restart app if needed:
   ```bash
   adb shell am force-stop com.visualmapper.companion
   adb shell am start -n com.visualmapper.companion/.ui.fragments.MainContainerActivity
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
