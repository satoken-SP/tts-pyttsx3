@echo off
setlocal

pushd "%~dp0"
if errorlevel 1 exit /b 1

python -m venv "venv"
if errorlevel 1 goto :failed

"venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

"venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto :failed

echo Setup completed. Run run_app.bat to start the application.
popd
pause
exit /b 0

:failed
echo [ERROR] Setup failed. Check the messages above.
popd
pause
exit /b 1
