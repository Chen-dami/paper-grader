@echo off
chcp 65001 >nul
title AI阅卷系统
cd /d "%~dp0"

echo.
echo   ========================================
echo         AI智能阅卷系统  v1.1
echo   ========================================
echo.

:: 检查虚拟环境
if not exist ".venv\Scripts\python.exe" (
    echo   [提示] 首次运行，请先双击 "安装环境.bat"
    echo.
    pause
    exit /b 1
)

set PYTHON=.venv\Scripts\python.exe

:: 检查依赖
%PYTHON% -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo   [提示] 依赖未安装，请先双击 "安装环境.bat"
    echo.
    pause
    exit /b 1
)

:: 检查 API Key
set HAS_KEY=0
%PYTHON% -c "import os; exit(0 if os.environ.get('DEEPSEEK_KEY','') else 1)" >nul 2>&1
if %errorlevel% neq 0 set HAS_KEY=1

if %HAS_KEY% equ 1 (
    echo   API Key 未配置
    echo.
    echo   支持的环境变量：DEEPSEEK_KEY / OPENAI_API_KEY / DASHSCOPE_API_KEY
    echo   至少配置一个模型 API Key 才能评分
    echo.
    echo   设置方法：
    echo     1. 按 Win+R，输入 sysdm.cpl，回车
    echo     2. 高级 → 环境变量 → 新建用户变量
    echo     3. 变量名：DEEPSEEK_KEY  变量值：sk-xxxxx
    echo.
    set /p "KEY_INPUT=或者现在输入 DeepSeek API Key（仅本次生效）: "
    if not "%KEY_INPUT%"=="" (
        set DEEPSEEK_KEY=%KEY_INPUT%
        echo   Key 已临时设置
    )
    echo.
)

:: 清理旧进程
echo   [1/2] 检查端口...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo   OK

:: 启动
echo   [2/2] 启动服务...
echo.
echo   ========================================
echo     浏览器即将打开 http://localhost:8501
echo     按 Ctrl+C 或关闭此窗口停止服务
echo   ========================================
echo.

start "" http://localhost:8501
%PYTHON% -m streamlit run app.py --server.port 8501 --server.headless true

echo.
echo   服务已停止。
pause
