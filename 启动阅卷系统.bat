@echo off
title Grading System
cd /d "%~dp0"

echo.
echo   ========================================
echo         Grading System
echo   ========================================
echo.

REM Kill old process on port 8501
echo   [1/3] Cleaning old process...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo   Done
echo.

REM Find Python: 1) system PATH  2) bundled .venv  3) common locations
echo   [2/3] Finding Python...
set PYTHON=python

REM If .venv python exists AND works, use it
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >nul 2>&1
    if not errorlevel 1 (
        set PYTHON=.venv\Scripts\python.exe
        echo   Using bundled .venv
    )
)

REM Verify it works
%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo   Python not found in PATH or .venv
    echo   Please install Python 3.8+ and add it to PATH
    echo   Then run: pip install -r requirements.txt
    pause
    exit /b 1
)
echo   OK  [%PYTHON%]
echo.

REM Install deps if missing
%PYTHON% -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo   Installing dependencies...
    %PYTHON% -m pip install -r requirements.txt -q
    if errorlevel 1 (
        echo   Failed to install. Try manually:
        echo     %PYTHON% -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

REM Start
echo   [3/3] Starting http://localhost:8501
echo   ========================================
echo.

%PYTHON% -m streamlit run app.py --server.port 8501

echo.
echo   Server stopped.
pause
