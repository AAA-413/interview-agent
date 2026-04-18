@echo off
echo ========================================
echo   AI Interview Platform - Stopping
echo ========================================
echo.

echo [1/2] Stopping Backend (Port 8001)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8001 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >/dev/null 2>&1
    echo   Backend stopped (PID: %%a)
)

echo [2/2] Stopping Frontend (Port 5173)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >/dev/null 2>&1
    echo   Frontend stopped (PID: %%a)
)

echo.
echo ========================================
echo   All Services Stopped
echo ========================================
echo.
pause
