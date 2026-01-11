@echo off
REM Capture Visual Mapper Companion app logs
REM Usage: capture_app_logs.bat [device_id]

set DEVICE=%1
if "%DEVICE%"=="" set DEVICE=192.168.1.2:46747

echo Capturing logs from device %DEVICE%...
echo Press Ctrl+C to stop

REM Clear and capture with app-specific tags
adb -s %DEVICE% logcat -c
adb -s %DEVICE% logcat VisualMapperApp:V MqttManager:V NavigationLearner:V AppDatabase:V VMAccessibility:V AppExplorer:V FlowExecutor:V *:S
