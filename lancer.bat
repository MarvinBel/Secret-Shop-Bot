@echo off
:: Relance en administrateur (necessaire si le jeu ignore les clics simules)
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m pip install -q -r requirements.txt
"%PY%" e7_shop_bot.py
if %errorlevel% neq 0 pause
