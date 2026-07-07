@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title AI 阅卷系统 - 环境安装
cd /d "%~dp0"

echo.
echo   ============================
echo     AI 阅卷系统 - 安装依赖
echo   ============================
echo.

echo   [1/5] 检测 Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [FAIL] Python 未安装
    echo   下载: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   [OK]  Python %%v
echo.

echo   [2/5] 创建虚拟环境...
if exist ".venv\Scripts\python.exe" (
    echo   [SKIP] .venv 已存在
) else (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo   [FAIL] 创建失败
        pause
        exit /b 1
    )
    echo   [OK]  已创建
)
echo.

echo   [3/5] 升级 pip (清华源)...
.venv\Scripts\python.exe -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple
echo   [OK]
echo.

echo   [4/5] 安装依赖 (清华源)...
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
    echo   [FAIL] 安装失败
    echo   手动执行:
    echo   .venv\Scripts\pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
    pause
    exit /b 1
)
echo   [OK]  完成
echo.

echo   [5/5] 检测 API Key...
set HAS=0
if not "%ZHIPU_KEY%"=="" set HAS=1
if not "%DEEPSEEK_KEY%"=="" set HAS=1
if not "%BAILIAN_KEY%"=="" set HAS=1
if not "%OPENAI_API_KEY%"=="" set HAS=1

if !HAS! equ 0 (
    echo.
    echo   [WARN] 未检测到任何 API Key
    echo   请至少配置一个:
    echo     setx DEEPSEEK_KEY "你的Key"   (DeepSeek文本 - 推荐)
    echo     setx BAILIAN_KEY "你的Key"    (阿里云视觉)
    echo     setx ZHIPU_KEY "你的Key"      (智谱视觉 - 免费)
    echo   配置后重新打开终端生效
)
echo.
echo   ============================
echo   安装完成!
echo   双击 "启动阅卷系统.bat" 启动
echo   ============================
pause
