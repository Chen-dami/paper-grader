@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   AI Grading System - Setup
echo ============================================
echo.

echo [1/4] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    echo Python not found.
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   OK: Python %%v
echo.

echo [2/4] Creating venv...
if exist ".venv\Scripts\python.exe" (
    echo   SKIP: already exists
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo   FAIL
        pause
        exit /b 1
    )
    echo   OK
)
echo.

echo [3/4] Upgrading pip...
.venv\Scripts\python.exe -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple
echo   OK
echo.

echo [4/4] Installing packages...
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
)
echo   OK
echo.
echo ============================================
echo   Done! Run start.bat to launch.
echo ============================================
pause
