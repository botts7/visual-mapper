@echo off
REM Refactoring Test Helper Script
REM Automated testing for server.py vs server_new.py

echo ================================================================================
echo Visual Mapper - Refactoring Validation Tests
echo ================================================================================
echo.

REM Check if servers are running
echo [1/3] Checking if server is running on port 3000...
curl -s http://localhost:3000/api/health >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ERROR: No server running on port 3000
    echo.
    echo Please start server first:
    echo   python server.py        (for original server)
    echo   python server_new.py    (for new modular server)
    echo.
    pause
    exit /b 1
)
echo   OK - Server is running
echo.

REM Run pytest tests
echo [2/3] Running automated comparison tests...
echo.
python -m pytest tests/test_server_refactoring.py -v --tb=short

if %errorlevel% neq 0 (
    echo.
    echo ================================================================================
    echo TESTS FAILED - Review output above
    echo ================================================================================
    pause
    exit /b 1
)

echo.
echo [3/3] Running manual comparison (detailed output)...
echo.
python tests/test_server_refactoring.py

echo.
echo ================================================================================
echo REFACTORING VALIDATION COMPLETE
echo ================================================================================
echo.
echo Next steps:
echo   1. Review test output above
echo   2. If all tests pass, extract next module
echo   3. Re-run this script after each extraction
echo.
pause
