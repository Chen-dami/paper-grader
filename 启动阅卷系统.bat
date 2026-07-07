@echo off
setlocal enabledelayedexpansion
title AI 阅卷系统
cd /d "%~dp0"

echo.
echo   ============================
echo     AI 阅卷系统
echo   ============================
echo.

echo   [1/3] 释放端口...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501"') do (
    taskkill /F /PID %%a >nul 2>&1
    echo   [OK]  8501 端口已释放
)

echo   [2/3] 查找 Python...
set PY=python

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >nul 2>&1
    if !errorlevel! equ 0 (
        set PY=.venv\Scripts\python.exe
        echo   [OK]  使用项目 .venv
    )
) else (
    echo   [提示] 首次使用请先运行 "一键安装.bat"
)

!PY! --version >nul 2>&1
if !errorlevel! neq 0 (
    echo   [FAIL] Python 未找到
    echo   请先运行 "一键安装.bat"
    pause
    exit /b 1
)
echo   [OK]  !PY!

echo   [3/3] 启动服务...

!PY! -c "import streamlit" >nul 2>&1
if !errorlevel! neq 0 (
    echo   [提示] 依赖缺失, 正在安装...
    !PY! -m pip install -r requirements.txt -q -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo.
echo   ============================
echo   浏览器打开 http://localhost:8501
echo   Ctrl+C 或关闭窗口停止服务
echo   ============================
echo.

start "" http://localhost:8501
!PY! -m streamlit run app.py --server.port 8501 --server.headless true

echo.
echo   服务已停止
pause
