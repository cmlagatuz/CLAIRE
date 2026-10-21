@echo off
title C.L.A.I.R.E. Voice Studio
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" where python >nul 2>nul || (echo Python is not installed. Run setup_claire.bat first. & pause & exit /b 1)
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" -m claire.voice_studio
pause
