@echo off
REM Configure Windows Firewall for Visual Mapper
REM Run as Administrator

echo ========================================
echo Visual Mapper Firewall Configuration
echo ========================================
echo.

echo [Option 1] Change WiFi network from Public to Private (RECOMMENDED)
echo This allows local network devices to connect while keeping firewall protection.
echo.
echo [Option 2] Add specific firewall rule for Public profile
echo Allows port 8080 even on Public networks.
echo.
echo Which option? (1/2)
set /p OPTION=

if "%OPTION%"=="1" goto OPTION1
if "%OPTION%"=="2" goto OPTION2
echo Invalid option
pause
exit /b 1

:OPTION1
echo.
echo Changing network profile to Private...
echo.
echo NOTE: This requires opening Windows Settings manually.
echo.
echo Steps:
echo 1. Press Windows key
echo 2. Type "WiFi settings" and press Enter
echo 3. Click on your connected network ("Swampy 5")
echo 4. Under "Network profile type", select "Private"
echo 5. Close settings
echo.
echo After changing to Private, try connecting from Android app again.
echo.
pause
exit /b 0

:OPTION2
echo.
echo Adding firewall rule for port 8080 on Public profile...
echo.

REM Delete old rules
netsh advfirewall firewall delete rule name="Visual Mapper" >nul 2>&1
netsh advfirewall firewall delete rule name="Visual Mapper 8080" >nul 2>&1

REM Add new rule for port 8080 with Public profile explicitly
netsh advfirewall firewall add rule name="Visual Mapper HTTP" dir=in action=allow protocol=TCP localport=8080 profile=public,private,domain program=any enable=yes

if %errorlevel% equ 0 (
    echo.
    echo ✓ Firewall rule added successfully!
    echo.
    echo Server URL for Android app: http://192.168.86.129:8080
    echo.
) else (
    echo.
    echo ✗ Failed to add firewall rule.
    echo Make sure you're running as Administrator.
    echo.
)

echo.
echo Re-enabling Public firewall profile...
netsh advfirewall set publicprofile state on

echo.
echo Done! Try connecting from Android app now.
echo.
pause
