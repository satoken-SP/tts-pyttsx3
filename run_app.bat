@echo off
setlocal

pushd "%~dp0"
if errorlevel 1 exit /b 1

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run install.bat first.
    popd
    pause
    exit /b 1
)

"venv\Scripts\python.exe" -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] The virtual environment's Python is unavailable.
    echo Rename the venv folder, then run install.bat to recreate it.
    popd
    pause
    exit /b 1
)

"venv\Scripts\python.exe" "app.py"
set "app_exit_code=%errorlevel%"

popd
pause
exit /b %app_exit_code%
