@echo off
title AI阅卷系统
cd /d "%~dp0"

echo.
echo   ========================================
echo         AI智能阅卷系统  v1.1
echo   ========================================
echo.

:: 检查 .venv
if not exist ".venv\Scripts\python.exe" (
    echo   [错误] 虚拟环境不存在
    echo   请先双击运行 "安装环境.bat"
    echo.
    pause
    exit /b 1
)

set PYTHON=.venv\Scripts\python.exe

:: 检查依赖
%PYTHON% -c "import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [错误] 依赖未安装
    echo   请先双击运行 "安装环境.bat"
    echo.
    pause
    exit /b 1
)

:: 检查 API Key
%PYTHON% -c "import os; ok=os.environ.get('DEEPSEEK_KEY','') or os.environ.get('OPENAI_API_KEY','') or os.environ.get('DASHSCOPE_API_KEY',''); exit(0 if ok else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [提示] 未检测到 API Key 环境变量
    echo.
    echo   支持的变量：DEEPSEEK_KEY / OPENAI_API_KEY / DASHSCOPE_API_KEY
    echo   至少配置一个模型的 Key 才能评分
    echo.
    echo   设置方法：
    echo     Win+R 输入 sysdm.cpl → 高级 → 环境变量 → 新建
    echo.
    set /p "KEY_INPUT=或现在输入 DeepSeek Key（本次有效）: "
    if not "%KEY_INPUT%"=="" set DEEPSEEK_KEY=%KEY_INPUT%
    echo.
)

:: 启动
echo   正在启动 http://localhost:8501 ...
echo   浏览器将自动打开，按 Ctrl+C 停止
echo   ========================================
echo.

start "" http://localhost:8501
%PYTHON% -m streamlit run app.py --server.port 8501 --server.headless true

echo.
echo   服务已停止
pause
