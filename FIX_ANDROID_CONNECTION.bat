@echo off
REM Visual Mapper - Fix Android Connection
REM Right-click this file and select "Run as Administrator"

echo ========================================
echo Visual Mapper - Android Connection Fix
echo ========================================
echo.

REM Check if running as admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: This script must be run as Administrator!
    echo.
    echo Right-click this file and select "Run as Administrator"
    echo.
    pause
    exit /b 1
)

echo Adding firewall rule for port 8080...
echo.

REM Delete any existing rules
netsh advfirewall firewall delete rule name="Visual Mapper HTTP" >nul 2>&1
netsh advfirewall firewall delete rule name="Visual Mapper" >nul 2>&1
netsh advfirewall firewall delete rule name="Visual Mapper 8080" >nul 2>&1

REM Add new rule that works on Public networks
netsh advfirewall firewall add rule name="Visual Mapper HTTP" dir=in action=allow protocol=TCP localport=8080 profile=public,private,domain

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo SUCCESS! Firewall configured.
    echo ========================================
    echo.
    echo Your Android app can now connect using:
    echo   http://192.168.86.129:8080
    echo.
    echo The server will use port 8080 instead of 3000.
    echo.
) else (
    echo.
    echo ========================================
    echo ERROR: Failed to add firewall rule
    echo ========================================
    echo.
)

pause
