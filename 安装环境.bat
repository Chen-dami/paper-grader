@echo off
chcp 65001 >nul
title AI阅卷系统 - 环境安装
cd /d "%~dp0"

echo.
echo   ========================================
echo     AI智能阅卷系统 - 首次环境安装
echo   ========================================
echo.

:: 检查 Python
echo   [1/3] 检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   [错误] 未检测到 Python，请先安装 Python 3.11+
    echo   下载地址：https://www.python.org/downloads/
    echo   安装时务必勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
python --version
echo   OK
echo.

:: 创建虚拟环境
echo   [2/3] 创建虚拟环境...
if exist ".venv\Scripts\python.exe" (
    echo   虚拟环境已存在，跳过
) else (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo   [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo   虚拟环境已创建
)
echo.

:: 安装依赖
echo   [3/3] 安装依赖包（首次约2-5分钟）...
call .venv\Scripts\activate.bat
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
if %errorlevel% neq 0 (
    echo.
    echo   [警告] 清华镜像安装失败，尝试默认源...
    pip install -r requirements.txt
)

echo.
echo   ========================================
echo     安装完成！
echo.
echo     以后直接双击 "启动阅卷系统.bat" 即可
echo   ========================================
echo.
pause
