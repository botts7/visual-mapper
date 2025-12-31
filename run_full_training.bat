@echo off
REM ============================================================================
REM FULLY AUTOMATED ML TRAINING
REM ============================================================================
REM
REM ONE CLICK to run everything:
REM   1. Starts the ML Training Server
REM   2. Waits for it to be ready
REM   3. Runs automated exploration on all configured apps
REM   4. Saves the trained model
REM
REM Just double-click this file and walk away!
REM
REM ============================================================================

title Smart Explorer - Full Automated Training

echo.
echo ============================================================
echo   FULLY AUTOMATED ML TRAINING
echo ============================================================
echo.
echo This will:
echo   1. Start the ML Training Server
echo   2. Explore multiple apps automatically
echo   3. Train the Q-learning model
echo   4. Save the results
echo.
echo Press any key to start, or Ctrl+C to cancel...
pause >nul

REM Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found in PATH
    pause
    exit /b 1
)

REM Install dependencies if needed
echo.
echo Checking dependencies...
python -c "import paho.mqtt.client" 2>nul || pip install paho-mqtt
python -c "import numpy" 2>nul || pip install numpy

REM Create data directory
if not exist "data" mkdir data

REM Start ML Training Server in background
echo.
echo Starting ML Training Server...
start "ML Training Server" /min cmd /c "python ml_training_server.py --broker 192.168.86.66 --port 1883"

REM Wait for server to start
echo Waiting for server to initialize...
timeout /t 5 /nobreak >nul

REM Run automated exploration
echo.
echo ============================================================
echo   Starting Automated App Exploration
echo ============================================================
echo.
echo NOTE: Apps must be whitelisted in the Android app's Privacy Settings
echo       to be explored. The whitelist protects your personal data.
echo.

REM Use --auto to auto-discover safe apps, or remove it to use defaults
python auto_explore_apps.py --auto --wait 180

REM Training complete - server will keep running to process any remaining data
echo.
echo ============================================================
echo   TRAINING COMPLETE!
echo ============================================================
echo.
echo The ML Training Server is still running in the background.
echo Q-table saved to: data\exploration_q_table.json
echo.
echo You can:
echo   - Close the "ML Training Server" window to stop
echo   - Run this script again to train on more apps
echo   - Edit auto_explore_apps.py to add more apps
echo.
pause
