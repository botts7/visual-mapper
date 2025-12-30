@echo off
REM Quick Fix for Android Connection
REM Right-click and "Run as Administrator"

echo ========================================
echo Visual Mapper - Quick Fix
echo ========================================
echo.

REM Check admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Must run as Administrator!
    echo Right-click this file and select "Run as Administrator"
    pause
    exit /b 1
)

echo Adding firewall rule for port 8080...
netsh advfirewall firewall add rule name="Visual Mapper Port 8080" dir=in action=allow protocol=TCP localport=8080 enable=yes

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo SUCCESS!
    echo ========================================
    echo.
    echo Firewall now allows port 8080.
    echo.
    echo Android app should connect now using:
    echo   http://192.168.86.129:8080
    echo.
) else (
    echo.
    echo ERROR: Failed to add rule
    echo.
)

pause
