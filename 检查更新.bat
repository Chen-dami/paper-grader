@echo off
chcp 65001 >nul
title AI阅卷系统 - 检查更新
cd /d "%~dp0"

echo.
echo   ========================================
echo     AI智能阅卷系统 - 检查更新
echo   ========================================
echo.

:: 检查 git
git --version >nul 2>&1
if %errorlevel% equ 0 (
    echo   检测到 Git，正在拉取更新...
    echo.
    git pull origin master
    if %errorlevel% equ 0 (
        echo.
        echo   ========================================
        echo     更新完成！请重新启动系统
        echo   ========================================
    ) else (
        echo.
        echo   [提示] 更新失败，请确认网络正常
        echo   或手动下载：https://github.com/Chen-dami/paper-grader
    )
) else (
    echo   [提示] 未安装 Git
    echo.
    echo   手动更新方法：
    echo     1. 打开 https://github.com/Chen-dami/paper-grader
    echo     2. 点击 Code -^> Download ZIP
    echo     3. 解压覆盖当前文件夹
    echo     4. 注意备份 config.yaml 和 data/ 目录
)

echo.
pause
