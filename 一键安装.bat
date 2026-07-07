@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   AI Grading System - Setup Wizard
echo ============================================
echo.

echo [1/5] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    echo Python not installed.
    echo Download: https://www.python.org/downloads/
    echo Mirror: https://registry.npmmirror.com/binary.html?path=python/
    echo Make sure to check "Add Python to PATH" during install.
    echo Then re-run this script.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   OK: Python %%v
echo.

echo [2/5] Checking Git (optional)...
where git >nul 2>&1
if errorlevel 1 (
    echo   Git not found - skip (needed for auto-update only)
) else (
    for /f "tokens=3" %%v in ('git --version 2^>^&1') do echo   OK: Git %%v
)
echo.

echo [3/5] Creating virtual environment...
if exist ".venv\Scripts\python.exe" (
    echo   SKIP: .venv already exists
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo   FAIL: Cannot create venv
        pause
        exit /b 1
    )
    echo   OK: Created
)
echo.

echo [4/5] Installing dependencies (first time ~3-5 min)...
.venv\Scripts\python.exe -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo   Retry with aliyun mirror...
    .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
)
if errorlevel 1 (
    echo   FAIL: Install failed. Check network.
    pause
    exit /b 1
)
echo   OK: Done
echo.

echo [5/5] API Key Setup
echo.
echo   Required: at least one API key
echo.
echo   Recommended:
echo     - DeepSeek (text scoring): https://platform.deepseek.com
echo     - Aliyun Qwen (vision):    https://bailian.console.aliyun.com
echo     - Zhipu GLM (free vision): https://open.bigmodel.cn
echo.
echo   Set in cmd (reopen terminal after):
echo     setx DEEPSEEK_KEY "your-key"
echo     setx BAILIAN_KEY "your-key"
echo     setx ZHIPU_KEY "your-key"
echo.
echo   After setting keys, go to Settings -> Model Router -> Detect
echo.
echo ============================================
echo   Setup Complete!
echo   Double-click: start.bat
echo   Browser: http://localhost:8501
echo ============================================
pause
