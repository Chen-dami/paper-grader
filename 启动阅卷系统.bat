@echo off
setlocal
cd /d "%~dp0"

set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

%PY% --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please run setup.bat first.
    pause
    exit /b 1
)

%PY% -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    %PY% -m pip install -r requirements.txt -q -i https://pypi.tuna.tsinghua.edu.cn/simple
)

start "" http://localhost:8501
%PY% -m streamlit run app.py --server.port 8501 --server.headless true
pause
