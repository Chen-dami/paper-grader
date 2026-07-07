"""
生成所有 .bat 脚本 —— 强制 GBK 编码确保中文 Windows 不乱码
"""
import os, sys

ROOT = os.path.join(os.path.dirname(__file__), "..")

def write_bat(filename, content):
    path = os.path.join(ROOT, filename)
    with open(path, "w", encoding="gbk") as f:
        f.write(content)
    print(f"  OK  {filename}")

# ============================================================
#  一键安装.bat
# ============================================================
write_bat("一键安装.bat", """@echo off
setlocal enabledelayedexpansion
title AI 阅卷系统 - 一键安装
cd /d "%~dp0"

echo.
echo   AI 阅卷系统 - 一键安装向导
echo   ============================
echo.

echo   [1/5] 检查 Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo   [MISS] Python 未安装
    echo   正在打开下载页面...
    start https://www.python.org/downloads/
    echo   国内镜像: https://registry.npmmirror.com/binary.html?path=python/
    echo   安装时务必勾选 "Add Python to PATH"
    echo   安装完成后重新运行本脚本
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   [OK]  Python %%v
echo.

echo   [2/5] 检查 pip...
python -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    python -m ensurepip --upgrade 2>&1
)
echo   [OK]  pip 就绪
echo.

echo   [3/5] 检查 Git（可选）...
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo   [INFO] Git 未安装，用于"更新"功能
    start https://git-scm.com/download/win
    echo   国内镜像: https://registry.npmmirror.com/binary.html?path=git-for-windows/
) else (
    for /f "tokens=3" %%v in ('git --version 2^>^&1') do echo   [OK]  Git %%v
)
echo.

echo   [4/5] 安装项目依赖...
echo   使用清华大学镜像，首次约3-5分钟
if not exist ".venv\\Scripts\\python.exe" (
    python -m venv .venv
)
.venv\\Scripts\\python.exe -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple

.venv\\Scripts\\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

if %errorlevel% neq 0 (
    echo   [RETRY] 清华镜像失败，尝试阿里云...
    .venv\\Scripts\\python.exe -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
)
if %errorlevel% neq 0 (
    echo   [FAIL] 安装失败，请检查网络
    pause
    exit /b 1
)
echo   [OK]  依赖安装完成
echo.

echo   [5/5] API Key 配置...
set HAS=0
if not "%ZHIPU_KEY%"=="" set HAS=1
if not "%DEEPSEEK_KEY%"=="" set HAS=1

if !HAS! equ 1 (
    echo   [OK]  已检测到 API Key
) else (
    echo   [INFO] 未检测到 API Key
    echo   推荐: 智谱 glm-4v-flash (免费) + DeepSeek (充值10元用很久)
    echo   获取: https://open.bigmodel.cn  /  https://platform.deepseek.com
    echo   配置: setx ZHIPU_KEY "你的Key"  &&  setx DEEPSEEK_KEY "你的Key"
)
echo.

echo   ============================
echo   安装完成！
echo   双击 "启动阅卷系统.bat" 即可
echo   浏览器打开 http://localhost:8501
echo   ============================
pause
""")

# ============================================================
#  启动阅卷系统.bat
# ============================================================
write_bat("启动阅卷系统.bat", """@echo off
setlocal enabledelayedexpansion
title AI 阅卷系统
cd /d "%~dp0"

echo.
echo   ============================
echo     AI 阅卷系统
echo   ============================
echo.

echo   [1/3] 检查端口...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501"') do (
    taskkill /F /PID %%a >nul 2>&1
    echo   [OK]  已释放 8501 端口
)

echo   [2/3] 查找 Python...
set PY=python

if exist ".venv\\Scripts\\python.exe" (
    ".venv\\Scripts\\python.exe" --version >nul 2>&1
    if !errorlevel! equ 0 (
        set PY=.venv\\Scripts\\python.exe
        echo   [OK]  使用 .venv
    )
) else (
    echo   [提示] 首次使用请先运行 一键安装.bat
)

!PY! --version >nul 2>&1
if !errorlevel! neq 0 (
    echo   [FAIL] Python 未找到
    echo   请先运行 一键安装.bat
    pause
    exit /b 1
)
echo   [OK]  !PY!

echo   [3/3] 启动服务...

!PY! -c "import streamlit" >nul 2>&1
if !errorlevel! neq 0 (
    echo   [提示] 依赖缺失，正在安装...
    !PY! -m pip install -r requirements.txt -q -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo.
echo   ============================
echo   浏览器打开 http://localhost:8501
echo   Ctrl+C 或关闭窗口停止
echo   ============================
echo.

start "" http://localhost:8501
!PY! -m streamlit run app.py --server.port 8501 --server.headless true

echo.
echo   服务已停止
pause
""")

# ============================================================
#  setup.bat
# ============================================================
write_bat("setup.bat", """@echo off
setlocal enabledelayedexpansion
title AI 阅卷系统 - 环境安装
cd /d "%~dp0"

echo.
echo   ============================
echo     AI 阅卷系统 - 安装环境
echo   ============================
echo.

echo   [1/5] 检查 Python...
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
if exist ".venv\\Scripts\\python.exe" (
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

echo   [3/5] 升级 pip...
.venv\\Scripts\\python.exe -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple
echo   [OK]
echo.

echo   [4/5] 安装依赖（清华镜像）...
.venv\\Scripts\\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
    echo   [FAIL] 安装失败
    echo   手动: .venv\\Scripts\\pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
    pause
    exit /b 1
)
echo   [OK]  完成
echo.

echo   [5/5] 检查 API Key...
set HAS=0
if not "%ZHIPU_KEY%"=="" set HAS=1
if not "%DEEPSEEK_KEY%"=="" set HAS=1
if not "%OPENAI_API_KEY%"=="" set HAS=1
if not "%BAILIAN_KEY%"=="" set HAS=1
if not "%ANTHROPIC_API_KEY%"=="" set HAS=1

if !HAS! equ 0 (
    echo.
    echo   [WARN] 未检测到任何 API Key
    echo   请至少配置一个:
    echo     setx ZHIPU_KEY "你的Key"    (智谱视觉-免费)
    echo     setx DEEPSEEK_KEY "你的Key"  (DeepSeek文本-推荐)
    echo   配置后重新打开终端生效
)
echo.
echo   ============================
echo   安装完成！
echo   双击 "启动阅卷系统.bat" 即可
echo   ============================
pause
""")

# ============================================================
#  更新.bat
# ============================================================
write_bat("更新.bat", """@echo off
setlocal enabledelayedexpansion
title AI 阅卷系统 - 更新
cd /d "%~dp0"

echo.
echo   ============================
echo     AI 阅卷系统 - 检查更新
echo   ============================
echo.

where git >nul 2>&1
if %errorlevel% neq 0 (
    echo   [FAIL] 未找到 Git，无法自动更新
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
    echo   [OK]  已经是最新版本，无需更新
    pause
    exit /b 0
)

echo   发现新版本，正在拉取...
git pull origin master
if %errorlevel% neq 0 (
    echo   [FAIL] 拉取失败，请检查网络
    pause
    exit /b 1
)
echo   [OK]  代码已更新
echo.

echo   [2/3] 更新依赖...
if exist ".venv\\Scripts\\python.exe" (
    .venv\\Scripts\\python.exe -m pip install -r requirements.txt -q --upgrade -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo   [OK]  依赖已更新
) else (
    echo   [WARN] 虚拟环境不存在，请先运行 setup.bat
)
echo.

echo   [3/3] 更新完成
echo.
echo   ============================
echo   可以启动阅卷系统了！
echo   ============================
pause
""")

print("\n  全部 .bat 脚本已用 GBK 编码重新生成！")
print(f"  路径: {ROOT}")
""")
