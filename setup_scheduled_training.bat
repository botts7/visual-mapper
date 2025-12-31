@echo off
REM ============================================================================
REM SETUP SCHEDULED TRAINING
REM ============================================================================
REM
REM This script creates a Windows Scheduled Task to run ML training
REM automatically at a specific time (e.g., every night at 2 AM).
REM
REM Run this ONCE to set up the schedule, then training runs automatically!
REM
REM ============================================================================

title Smart Explorer - Setup Scheduled Training

echo.
echo ============================================================
echo   SETUP SCHEDULED ML TRAINING
echo ============================================================
echo.
echo This will create a Windows Scheduled Task to run training
echo automatically every day.
echo.
echo Default schedule: Every day at 2:00 AM
echo.

set /p SCHEDULE_TIME="Enter time (HH:MM, or press Enter for 02:00): "
if "%SCHEDULE_TIME%"=="" set SCHEDULE_TIME=02:00

set SCRIPT_PATH=%~dp0run_scheduled_session.bat

echo.
echo Creating scheduled task...
echo   Name: SmartExplorerTraining
echo   Time: %SCHEDULE_TIME% daily
echo   Script: %SCRIPT_PATH%
echo.

REM Create the scheduled task
schtasks /create /tn "SmartExplorerTraining" /tr "%SCRIPT_PATH%" /sc daily /st %SCHEDULE_TIME% /f

if %errorlevel% equ 0 (
    echo.
    echo ============================================================
    echo   SUCCESS! Scheduled task created.
    echo ============================================================
    echo.
    echo Training will run automatically every day at %SCHEDULE_TIME%
    echo.
    echo To manage the schedule:
    echo   - Open Task Scheduler (taskschd.msc)
    echo   - Look for "SmartExplorerTraining"
    echo.
    echo To remove the schedule:
    echo   schtasks /delete /tn "SmartExplorerTraining" /f
    echo.
) else (
    echo.
    echo ERROR: Could not create scheduled task.
    echo Try running this script as Administrator.
    echo.
)

pause
