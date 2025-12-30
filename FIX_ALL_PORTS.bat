@echo off
REM Fix All Visual Mapper Ports - ONE TIME SETUP
REM Right-click and "Run as Administrator"

echo ========================================
echo Visual Mapper - Complete Port Setup
echo ========================================
echo.

REM Check admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Must run as Administrator!
    echo.
    echo Right-click this file and select "Run as Administrator"
    echo.
    pause
    exit /b 1
)

echo Removing old firewall rules...
netsh advfirewall firewall delete rule name="Visual Mapper" >nul 2>&1
netsh advfirewall firewall delete rule name="Visual Mapper HTTP" >nul 2>&1
netsh advfirewall firewall delete rule name="Visual Mapper Server" >nul 2>&1
netsh advfirewall firewall delete rule name="Visual Mapper 8080" >nul 2>&1
netsh advfirewall firewall delete rule name="Visual Mapper Port 8080" >nul 2>&1
netsh advfirewall firewall delete rule name="Visual Mapper MQTT" >nul 2>&1
echo Done.
echo.

echo Adding firewall rules for:
echo   - Port 8080 (HTTP Server)
echo   - Port 1883 (MQTT Broker)
echo.

REM HTTP Server
netsh advfirewall firewall add rule name="Visual Mapper - HTTP Server" dir=in action=allow protocol=TCP localport=8080 enable=yes
if %errorlevel% equ 0 (
    echo [OK] Port 8080 allowed
) else (
    echo [FAIL] Port 8080 failed
)

REM MQTT Broker
netsh advfirewall firewall add rule name="Visual Mapper - MQTT Broker" dir=in action=allow protocol=TCP localport=1883 enable=yes
if %errorlevel% equ 0 (
    echo [OK] Port 1883 allowed
) else (
    echo [FAIL] Port 1883 failed
)

echo.
echo ========================================
echo SETUP COMPLETE!
echo ========================================
echo.
echo Your Android app can now connect:
echo.
echo   Server: http://192.168.86.129:8080
echo   MQTT Broker: 192.168.86.129:1883
echo.
echo Try connecting from the app now!
echo.
pause
