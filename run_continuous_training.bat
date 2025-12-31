@echo off
REM ============================================================================
REM CONTINUOUS ML TRAINING - Runs Forever
REM ============================================================================
REM
REM Runs training sessions in an infinite loop:
REM   - Explores all configured apps
REM   - Waits 30 minutes
REM   - Repeats
REM
REM Great for overnight training sessions!
REM Press Ctrl+C to stop.
REM
REM ============================================================================

title Smart Explorer - Continuous Training

echo.
echo ============================================================
echo   CONTINUOUS ML TRAINING (Runs Forever)
echo ============================================================
echo.
echo This will run training sessions continuously.
echo Press Ctrl+C at any time to stop.
echo.
echo Press any key to start...
pause >nul

REM Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found
    pause
    exit /b 1
)

REM Install dependencies
python -c "import paho.mqtt.client" 2>nul || pip install paho-mqtt
python -c "import numpy" 2>nul || pip install numpy

if not exist "data" mkdir data

REM Start ML Training Server in background (if not already running)
echo Starting ML Training Server...
start "ML Training Server" /min cmd /c "python ml_training_server.py --broker 192.168.86.66 --port 1883"
timeout /t 5 /nobreak >nul

set SESSION=1

:LOOP
echo.
echo ============================================================
echo   TRAINING SESSION #%SESSION%
echo   Started: %date% %time%
echo ============================================================
echo.
echo NOTE: Apps must be whitelisted in Android Privacy Settings
echo.

REM Run exploration with auto-discovery
python auto_explore_apps.py --auto --wait 180

echo.
echo Session %SESSION% complete!
echo Waiting 30 minutes before next session...
echo (Press Ctrl+C to stop)
echo.

set /a SESSION=%SESSION%+1

REM Wait 30 minutes (1800 seconds)
timeout /t 1800

goto LOOP
