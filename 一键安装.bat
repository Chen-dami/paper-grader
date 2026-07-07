@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title AI 阅卷系统 - 一键安装向导
cd /d "%~dp0"

echo.
echo   ============================
echo     AI 阅卷系统 - 一键安装向导
echo   ============================
echo.

echo   [1/5] 检测 Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [MISS] Python 未安装
    echo   正在打开下载页...
    start https://www.python.org/downloads/
    echo   国内镜像: https://registry.npmmirror.com/binary.html?path=python/
    echo   安装时务必勾选 "Add Python to PATH"
    echo   安装完成后请重新运行本脚本
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   [OK]  Python %%v
echo.

echo   [2/5] 检测 pip...
python -m pip --version >nul 2>&1
if %errorlevel% neq 0 ( python -m ensurepip --upgrade 2>&1 )
echo   [OK]  pip 就绪
echo.

echo   [3/5] 检测 Git (可选, 用于后续更新)...
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo   [INFO] Git 未安装
    start https://git-scm.com/download/win
    echo   国内镜像: https://registry.npmmirror.com/binary.html?path=git-for-windows/
) else (
    for /f "tokens=3" %%v in ('git --version 2^>^&1') do echo   [OK]  Git %%v
)
echo.

echo   [4/5] 安装项目依赖 (清华源, 首次约3-5分钟)...
if not exist ".venv\Scripts\python.exe" ( python -m venv .venv )
.venv\Scripts\python.exe -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
    echo   [RETRY] 清华源失败, 尝试阿里源...
    .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
)
if %errorlevel% neq 0 (
    echo   [FAIL] 安装失败, 请检查网络连接
    pause
    exit /b 1
)
echo   [OK]  依赖安装完毕
echo.

echo   [5/5] API Key 配置...
set HAS=0
if not "%ZHIPU_KEY%"=="" set HAS=1
if not "%DEEPSEEK_KEY%"=="" set HAS=1
if not "%BAILIAN_KEY%"=="" set HAS=1

if !HAS! equ 1 (
    echo   [OK]  已检测到 API Key
) else (
    echo   [INFO] 未检测到 API Key 环境变量
    echo.
    echo   推荐配置方案: DeepSeek (文本评分) + 智谱免费 (视觉描述)
    echo               阿里云 Qwen-VL-Plus (视觉描述, 效果更好)
    echo.
    echo   获取地址:
    echo     DeepSeek: https://platform.deepseek.com
    echo     智谱:     https://open.bigmodel.cn
    echo     阿里云:   https://bailian.console.aliyun.com
    echo.
    echo   配置方法 (打开 cmd 执行):
    echo     setx DEEPSEEK_KEY "你的DeepSeek Key"
    echo     setx BAILIAN_KEY "你的阿里云Key"
    echo     setx ZHIPU_KEY "你的智谱Key"
    echo   配置后重新打开终端生效
)
echo.

echo   ============================
echo   安装完成!
echo   双击 "启动阅卷系统.bat" 启动
echo   浏览器打开 http://localhost:8501
echo   ============================
pause
