@echo off
echo ========================================
echo Testing Android Connection
echo ========================================
echo.
echo Logcat cleared.
echo.
echo NOW:
echo 1. Open Visual Mapper Companion app on Android
echo 2. Tap "Connect" button
echo 3. Wait 10 seconds
echo 4. Press any key here
echo.
pause

echo.
echo Checking Android logs...
echo.
adb -s 192.168.86.2:46747 logcat -d | findstr "ServerSync\|VisualMapper\|Exception\|Error"

echo.
echo.
echo Checking server logs...
tail -50 server_log.txt | findstr "192.168.86.2\|ERROR\|Exception"

echo.
echo Done!
pause
