@echo off
REM Get recent Visual Mapper logs (last N lines)
REM Usage: get_app_logs.bat [lines] [device_id]

set LINES=%1
if "%LINES%"=="" set LINES=200

set DEVICE=%2
if "%DEVICE%"=="" set DEVICE=192.168.1.2:46747

set OUTFILE=%~dp0..\app_logs.txt

echo Getting last %LINES% app log lines from %DEVICE%...
adb -s %DEVICE% logcat -d -t %LINES% > "%OUTFILE%" 2>&1

REM Filter for our app tags
findstr /i "VisualMapper MqttManager NavigationLearner AppDatabase VMAccessibility AppExplorer FlowExecutor Room visual_mapper" "%OUTFILE%"

echo.
echo Full logs saved to: %OUTFILE%
