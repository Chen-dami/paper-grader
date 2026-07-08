@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   AI Grading System - Update
echo ============================================
echo.

:: ============================================
:: 方式1: Git 更新（如果有 Git）
:: ============================================
where git >nul 2>&1
if not errorlevel 1 (
    echo [Git] Pulling latest code...
    git pull origin master
    if not errorlevel 1 (
        echo   OK - Git update done
        goto :update_deps
    )
    echo   Git pull failed, trying download method...
)

:: ============================================
:: 方式2: 下载 ZIP 更新（无需 Git）
:: ============================================
echo [Download] Fetching latest version from GitHub...
set "ZIP_URL=https://github.com/Chen-dami/paper-grader/archive/refs/heads/master.zip"
set "TEMP_ZIP=%TEMP%\paper-grader-update.zip"
set "TEMP_DIR=%TEMP%\paper-grader-update"

:: 清理旧的临时文件
if exist "%TEMP_ZIP%" del /q "%TEMP_ZIP%"
if exist "%TEMP_DIR%" rmdir /s /q "%TEMP_DIR%"

:: 下载（主URL + 备用URL，PowerShell + curl双保险，重试2次）
set "URLS=https://codeload.github.com/Chen-dami/paper-grader/zip/refs/heads/master https://github.com/Chen-dami/paper-grader/archive/refs/heads/master.zip"
set "DOWNLOADED=0"
for /l %%r in (1,1,2) do (
    if "!DOWNLOADED!"=="0" (
        if %%r gtr 1 (
            echo   Retrying (attempt %%r/2^)...
            timeout /t 2 >nul
        )
        for %%u in (%URLS%) do (
            if "!DOWNLOADED!"=="0" (
                powershell -Command "try { Invoke-WebRequest -Uri '%%u' -OutFile '%TEMP_ZIP%' -TimeoutSec 30 } catch { exit 1 }" 2>nul
                if exist "%TEMP_ZIP%" set "DOWNLOADED=1"
            )
        )
        if "!DOWNLOADED!"=="0" (
            for %%u in (%URLS%) do (
                if "!DOWNLOADED!"=="0" (
                    curl -sL -o "%TEMP_ZIP%" "%%u" 2>nul
                    if exist "%TEMP_ZIP%" set "DOWNLOADED=1"
                )
            )
        )
    )
)
if not exist "%TEMP_ZIP%" (
    echo   FAIL: Download failed (network or rate limit).
    echo   Manual update: https://github.com/Chen-dami/paper-grader
    echo   Click 'Code' -^> 'Download ZIP', extract and overwrite.
    pause
    exit /b 1
)
echo   Downloaded OK

:: 解压
echo [Extract] Unzipping...
powershell -Command "Expand-Archive -Path '%TEMP_ZIP%' -DestinationPath '%TEMP_DIR%' -Force" 2>nul
if not exist "%TEMP_DIR%" (
    :: 备用：使用 tar（Windows 10 1803+ 内置）
    tar -xf "%TEMP_ZIP%" -C "%TEMP_DIR%" 2>nul
)
if not exist "%TEMP_DIR%\paper-grader-master" (
    echo   FAIL: Cannot extract. Try manual update.
    pause
    exit /b 1
)
echo   Extracted OK

:: 复制新文件（保留用户数据: data/, output/, .env, .venv/）
echo [Copy] Updating files (preserving your data)...
set "SRC=%TEMP_DIR%\paper-grader-master"

:: 逐个目录/文件复制，跳过用户数据
for /d %%d in ("%SRC%\*") do (
    set "dirname=%%~nd"
    if /i not "!dirname!"=="data" if /i not "!dirname!"=="output" if /i not "!dirname!"==".venv" (
        if exist ".\!dirname!" rmdir /s /q ".\!dirname!" 2>nul
        xcopy "%%d" ".\!dirname!\" /E /Y /Q >nul 2>&1
    )
)
for %%f in ("%SRC%\*.*") do (
    set "fname=%%~nxf"
    if /i not "!fname!"==".env" (
        copy /y "%%f" ".\" >nul 2>&1
    )
)
:: 确保 data/ output/ 目录存在
if not exist "data" mkdir "data"
if not exist "output" mkdir "output"

:: 清理临时文件
del /q "%TEMP_ZIP%" 2>nul
rmdir /s /q "%TEMP_DIR%" 2>nul
echo   Files updated OK

:: ============================================
:: 更新依赖
:: ============================================
:update_deps
echo.
echo [Deps] Checking Python dependencies...
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m pip install -r requirements.txt -q --upgrade -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo   OK
) else (
    echo   WARN: .venv not found, run setup.bat first
)

echo.
echo ============================================
echo   Update complete!
echo   Your data/ output/ .env are safe.
echo   Restart the app to use new version.
echo ============================================
pause
