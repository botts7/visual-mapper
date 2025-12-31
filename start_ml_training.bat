@echo off
REM ============================================================================
REM ML Training Server Startup Script for Smart Explorer
REM ============================================================================
REM
REM This script starts the ML training server on your Surface Laptop 7.
REM The server receives exploration data from Android devices via MQTT
REM and trains Q-learning models to improve app exploration.
REM
REM Requirements:
REM   - Python 3.8+
REM   - pip install paho-mqtt numpy
REM   - (Optional) pip install torch torch-directml (for NPU acceleration)
REM
REM Usage:
REM   start_ml_training.bat                    - Start with default settings
REM   start_ml_training.bat --dqn              - Use Deep Q-Network (requires PyTorch)
REM   start_ml_training.bat --info             - Show hardware info
REM
REM ============================================================================

echo ============================================================
echo   Smart Explorer - ML Training Server
echo ============================================================
echo.

REM Check if Python is installed
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found in PATH
    echo Please install Python 3.8+ and add it to PATH
    pause
    exit /b 1
)

REM Check Python version
python --version

REM Check for required packages
echo.
echo Checking dependencies...
python -c "import paho.mqtt.client" 2>nul
if %errorlevel% neq 0 (
    echo Installing paho-mqtt...
    pip install paho-mqtt
)

python -c "import numpy" 2>nul
if %errorlevel% neq 0 (
    echo Installing numpy...
    pip install numpy
)

REM Check for optional packages (PyTorch for NPU acceleration)
python -c "import torch" 2>nul
if %errorlevel% neq 0 (
    echo.
    echo NOTE: PyTorch not installed. For NPU acceleration, run:
    echo   pip install torch torch-directml
    echo.
) else (
    echo PyTorch is available
    python -c "import torch_directml" 2>nul
    if %errorlevel% neq 0 (
        echo.
        echo NOTE: torch-directml not installed. For NPU acceleration, run:
        echo   pip install torch-directml
        echo.
    ) else (
        echo DirectML (NPU) is available!
    )
)

REM Default broker settings (HA Docker MQTT)
set BROKER=192.168.86.66
set PORT=1883

echo.
echo ============================================================
echo   Configuration:
echo   - MQTT Broker: %BROKER%:%PORT%
echo   - Data folder: data/
echo   - Log file: ml_training.log
echo ============================================================
echo.

REM Check if custom broker was specified
if not "%1"=="" (
    if "%1"=="--broker" (
        set BROKER=%2
    )
    if "%1"=="--info" (
        python ml_training_server.py --info
        pause
        exit /b 0
    )
)

REM Create data directory
if not exist "data" mkdir data

echo Starting ML Training Server...
echo Press Ctrl+C to stop
echo.

REM Start the server
python ml_training_server.py --broker %BROKER% --port %PORT% %*

REM If we get here, the server stopped
echo.
echo Server stopped.
pause
