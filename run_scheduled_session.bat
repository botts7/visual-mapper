@echo off
REM ============================================================================
REM SCHEDULED TRAINING SESSION
REM ============================================================================
REM
REM This script is called by Windows Task Scheduler.
REM It runs a single training session and then exits.
REM
REM ============================================================================

cd /d "%~dp0"

REM Log start time
echo [%date% %time%] Starting scheduled training session >> training_schedule.log

REM Start ML Training Server
start "ML Training Server" /min cmd /c "python ml_training_server.py --broker 192.168.86.66 --port 1883"
timeout /t 5 /nobreak >nul

REM Run exploration
python auto_explore_apps.py --wait 180 >> training_schedule.log 2>&1

REM Log completion
echo [%date% %time%] Training session complete >> training_schedule.log

REM Stop ML Training Server (find and kill the process)
taskkill /fi "WINDOWTITLE eq ML Training Server*" /f >nul 2>&1

exit /b 0
