@echo off
REM Android Connection Test Script
REM Tests all endpoints needed by Android Companion App

echo ========================================
echo Visual Mapper - Android Connection Test
echo ========================================
echo.

REM Get local IP address
echo [1/6] Finding server IP address...
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr "IPv4"') do (
    set IP=%%a
    goto :found_ip
)
:found_ip
set IP=%IP:~1%
echo     Server IP: %IP%
echo.

REM Test server running
echo [2/6] Testing if server is running on port 3000...
netstat -an | findstr ":3000.*LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo     ✓ Server is listening on port 3000
) else (
    echo     ✗ Server is NOT running on port 3000
    echo     Please start the server first: python server.py
    pause
    exit /b 1
)
echo.

REM Test health endpoint (localhost)
echo [3/6] Testing health endpoint (localhost)...
curl -s http://localhost:3000/api/health >nul 2>&1
if %errorlevel% equ 0 (
    echo     ✓ Health endpoint responding on localhost
    curl -s http://localhost:3000/api/health
) else (
    echo     ✗ Health endpoint not responding
    pause
    exit /b 1
)
echo.

REM Test health endpoint (network IP)
echo [4/6] Testing health endpoint (network IP)...
curl -s http://%IP%:3000/api/health >nul 2>&1
if %errorlevel% equ 0 (
    echo     ✓ Health endpoint responding on network IP
) else (
    echo     ✗ Health endpoint not responding on network IP
    echo     Check firewall settings
)
echo.

REM Test device registration endpoint
echo [5/6] Testing device registration endpoint...
curl -s http://localhost:3000/api/devices >nul 2>&1
if %errorlevel% equ 0 (
    echo     ✓ Device registration endpoint exists
    curl -s http://localhost:3000/api/devices
) else (
    echo     ✗ Device registration endpoint not found
    echo     Server needs to be restarted to load new endpoint
)
echo.

REM Test device registration
echo [6/6] Testing device registration (POST)...
curl -s -X POST http://localhost:3000/api/devices/register ^
  -H "Content-Type: application/json" ^
  -d "{\"deviceId\":\"test-device\",\"deviceName\":\"Test Device\",\"platform\":\"android\",\"appVersion\":\"1.0.0\",\"capabilities\":[\"test\"]}" >nul 2>&1

if %errorlevel% equ 0 (
    echo     ✓ Device registration successful
) else (
    echo     ✗ Device registration failed
    echo     Server may need to be restarted
)
echo.

echo ========================================
echo Test Complete!
echo ========================================
echo.
echo Next Steps:
echo 1. Make note of your server IP: %IP%
echo 2. Open Android Companion App
echo 3. Enter server URL: http://%IP%:3000
echo 4. Tap "Connect"
echo.
echo If connection fails, see ANDROID_CONNECTION_TROUBLESHOOTING.md
echo.
pause
