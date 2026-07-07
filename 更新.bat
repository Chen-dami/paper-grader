@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   AI Grading System - Update
echo ============================================
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo Git not found. Cannot auto-update.
    echo Install Git: https://git-scm.com/download/win
    echo Or re-download from: https://github.com/Chen-dami/paper-grader
    pause
    exit /b 1
)

echo [1/2] Pulling latest code...
git pull origin master
if errorlevel 1 (
    echo FAIL: git pull failed. Check network.
    pause
    exit /b 1
)
echo   OK
echo.

echo [2/2] Updating dependencies...
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m pip install -r requirements.txt -q --upgrade -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo   OK
) else (
    echo   WARN: no .venv found, run setup.bat first
)
echo.
echo ============================================
echo   Update complete! Restart the app.
echo ============================================
pause
