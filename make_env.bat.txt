@echo off
rem Makes C.L.A.I.R.E.'s own Python (.venv) next to the app, from a Python version her voice packages support.
rem Safe to run again. Used by setup_claire.bat and setup_voice.bat.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" exit /b 0
for %%v in (3.13 3.12 3.11 3.10) do if not exist ".venv\Scripts\python.exe" py -%%v -m venv .venv >nul 2>nul
if not exist ".venv\Scripts\python.exe" python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>nul && python -m venv .venv >nul 2>nul
if exist ".venv\Scripts\python.exe" exit /b 0
echo.
echo I need Python 3.10 to 3.13 - 3.12 is best.
echo Your Python is probably too new for the voice packages, or it is not installed.
echo Install Python 3.12 from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^),
echo then run this again. Your other Python can stay installed.
exit /b 1
