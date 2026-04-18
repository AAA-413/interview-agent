@echo off
echo ========================================
echo   AI Interview Platform - Starting
echo ========================================
echo.

echo [1/2] Starting Backend (Port 8001)...
start "Backend" cmd /k "cd /d D:\work\xiaofuge\111\python && .venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload"
timeout /t 3 >/dev/null

echo [2/2] Starting Frontend (Port 5173)...
start "Frontend" cmd /k "cd /d D:\work\xiaofuge\111\python\frontend && npm run dev"
timeout /t 2 >/dev/null

echo.
echo ========================================
echo   Services Started!
echo ========================================
echo.
echo   Backend: http://localhost:8001
echo   Frontend: http://localhost:5173
echo   Login: http://localhost:5173/login
echo.
echo   Test Account:
echo   Username: admin
echo   Password: admin123
echo.
pause
