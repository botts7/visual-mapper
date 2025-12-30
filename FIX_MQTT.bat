@echo off
REM Fix MQTT Connection
REM Right-click and "Run as Administrator"

echo ========================================
echo Visual Mapper - MQTT Fix
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

echo Adding firewall rule for MQTT port 1883...
netsh advfirewall firewall add rule name="Visual Mapper MQTT" dir=in action=allow protocol=TCP localport=1883 enable=yes

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo SUCCESS!
    echo ========================================
    echo.
    echo Firewall now allows MQTT port 1883.
    echo.
    echo MQTT should connect now.
    echo Broker: 192.168.86.129
    echo Port: 1883
    echo.
) else (
    echo.
    echo ERROR: Failed to add rule
    echo.
)

pause
