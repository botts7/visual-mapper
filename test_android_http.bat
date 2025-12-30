@echo off
echo Testing Android HTTP connection...
echo.
echo Please try connecting from the Android app NOW, then press any key here
pause >nul
echo.
echo Capturing logs...
adb -s R9YT50J4S9D logcat -d | findstr "ServerSync\|VisualMapper\|HttpClient\|Exception"
echo.
echo Done. Check logs above for errors.
pause
