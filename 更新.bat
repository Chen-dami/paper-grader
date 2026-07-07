@echo off
setlocal enabledelayedexpansion
title AI 阅卷系统 - 检查更新
cd /d "%~dp0"

echo.
echo   ============================
echo     AI 阅卷系统 - 检查更新
echo   ============================
echo.

where git >nul 2>&1
if %errorlevel% neq 0 (
    echo   [FAIL] 未找到 Git, 无法自动更新
    echo   请安装 Git: https://git-scm.com/download/win
    echo   或手动下载最新版覆盖本目录
    pause
    exit /b 1
)

echo   [1/3] 拉取最新代码...
git fetch origin
for /f "tokens=*" %%a in ('git rev-parse HEAD') do set OLD=%%a
for /f "tokens=*" %%a in ('git rev-parse origin/master') do set NEW=%%a

if "%OLD%"=="%NEW%" (
    echo   [OK]  已经是最新版本, 无需更新
    pause
    exit /b 0
)

echo   发现新版本, 正在拉取...
git pull origin master
if %errorlevel% neq 0 (
    echo   [FAIL] 拉取失败, 请检查网络
    pause
    exit /b 1
)
echo   [OK]  代码已更新
echo.

echo   [2/3] 更新依赖...
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m pip install -r requirements.txt -q --upgrade -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo   [OK]  依赖已更新
) else (
    echo   [WARN] 虚拟环境不存在, 请先运行 setup.bat
)
echo.

echo   [3/3] 更新完成!
echo.
echo   ============================
echo   可以启动阅卷系统了
echo   ============================
pause
