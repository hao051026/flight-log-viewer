@echo off
chcp 65001 >nul
setlocal
title Flight Log Viewer
cd /d "%~dp0"

echo.
echo ========================================
echo   Flight Log Viewer - starting
echo ========================================
echo.

set "PY=py"
%PY% --version >nul 2>&1
if not errorlevel 1 goto :pyok
set "PY=python"
%PY% --version >nul 2>&1
if errorlevel 1 goto :nopy
:pyok

for /f "delims=" %%p in ('%PY% -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%p"
if not defined PYEXE goto :nopy
echo [INFO] Python: %PYEXE%

echo [INFO] Checking dependencies...
"%PYEXE%" -c "import numpy, pandas, matplotlib, flask" >nul 2>&1
if not errorlevel 1 goto :depok
echo [INFO] Installing dependencies...
"%PYEXE%" -m pip install -r requirements.txt
if errorlevel 1 goto :depfail
echo [INFO] Dependencies installed.
:depok

echo.
echo ========================================
echo   [OK] Server started!
echo   Open browser: http://127.0.0.1:5000
echo   Upload a flight log to view analysis.
echo   Press Ctrl+C to stop.
echo ========================================
echo.

start "" /b cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5000"

"%PYEXE%" 主程序.py web --host 127.0.0.1 --port 5000

echo.
echo [INFO] Server stopped.
pause
exit /b 0

:nopy
echo [ERROR] Python not found. Install Python 3.8+ and add to PATH.
pause
exit /b 1

:depfail
echo [ERROR] Dependency install failed. Check network then retry.
pause
exit /b 1
