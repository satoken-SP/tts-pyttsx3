@echo off

python -m venv venv

call venv\Scripts\activate.bat

venv\Scripts\python.exe -m pip install --upgrade pip
pip install -r requirements.txt

pause