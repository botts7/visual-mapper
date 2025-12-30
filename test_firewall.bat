@echo off
echo ========================================
echo TEMPORARY FIREWALL TEST
echo ========================================
echo.
echo This will temporarily disable Windows Firewall to test connectivity.
echo IMPORTANT: Firewall will be re-enabled after test.
echo.
echo Press Ctrl+C to cancel, or
pause

echo.
echo [1/4] Disabling Windows Firewall...
netsh advfirewall set allprofiles state off
echo Done.
echo.

echo [2/4] Server is running on: http://192.168.86.129:8080
echo.
echo Now try these tests on your Android device:
echo.
echo Test 1: Open Chrome browser and go to:
echo   http://192.168.86.129:8080/api/health
echo.
echo Test 2: Open Companion App and enter:
echo   http://192.168.86.129:8080
echo   Then tap Connect
echo.
echo When you're done testing, press any key here to re-enable firewall...
pause >nul

echo.
echo [3/4] Re-enabling Windows Firewall...
netsh advfirewall set allprofiles state on
echo Done.
echo.

echo [4/4] Firewall restored.
echo.
echo Did the connection work with firewall disabled? (Y/N)
set /p WORKED=
if /i "%WORKED%"=="Y" (
    echo.
    echo Firewall was the problem. Now we need to configure it properly.
    echo Run: configure_firewall.bat
) else (
    echo.
    echo Firewall was NOT the problem. Different issue.
)
echo.
pause
