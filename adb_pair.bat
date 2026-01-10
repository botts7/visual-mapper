@echo off
echo ============================================================
echo ADB WIRELESS PAIRING SCRIPT
echo ============================================================
echo.
echo On your Samsung tablet:
echo 1. Settings - Developer Options - Wireless debugging - Enable
echo 2. Tap "Pair device with pairing code"
echo 3. Note the IP:Port and 6-digit code shown
echo.
echo ============================================================
echo.

set /p PAIR_IP="Enter pairing IP:PORT (e.g., 192.168.86.2:37123): "
set /p PAIR_CODE="Enter 6-digit pairing code: "

echo.
echo Pairing with %PAIR_IP% using code %PAIR_CODE%...
adb pair %PAIR_IP% %PAIR_CODE%

echo.
echo ============================================================
echo Now enter the CONNECTION port (shown on main wireless debugging screen)
echo ============================================================
set /p CONNECT_IP="Enter connection IP:PORT (e.g., 192.168.86.2:46747): "

echo.
echo Connecting to %CONNECT_IP%...
adb connect %CONNECT_IP%

echo.
echo ============================================================
echo Checking connection...
echo ============================================================
adb devices

echo.
echo ============================================================
echo Testing device...
echo ============================================================
adb -s %CONNECT_IP% shell echo "Connection successful!"
adb -s %CONNECT_IP% shell getprop ro.product.manufacturer
adb -s %CONNECT_IP% shell getprop ro.product.model

echo.
echo Done! You can now run: python test_unlock.py %CONNECT_IP% 1109
pause
