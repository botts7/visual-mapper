@echo off
REM ============================================================================
REM Automated ML Training - Explore Multiple Apps
REM ============================================================================
REM
REM This script automatically explores multiple Android apps to train the
REM Q-learning model. Just click to run!
REM
REM Requirements:
REM   - ML Training Server running (start_ml_training.bat)
REM   - Android device connected with app installed
REM   - MQTT broker running
REM
REM ============================================================================

echo ============================================================
echo   Smart Explorer - Automated Training
echo ============================================================
echo.

REM Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found
    pause
    exit /b 1
)

REM Check paho-mqtt
python -c "import paho.mqtt.client" 2>nul
if %errorlevel% neq 0 (
    echo Installing paho-mqtt...
    pip install paho-mqtt
)

echo Starting automated training session...
echo.

REM Run the Python automation script
python auto_explore_apps.py

echo.
echo ============================================================
echo   Training session complete!
echo ============================================================
pause
