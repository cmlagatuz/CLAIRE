@echo off
cd /d "%~dp0"
echo === C.L.A.I.R.E. setup ===
where python >nul 2>nul || (echo Python is not installed. Get it from https://www.python.org/downloads/ ^(tick "Add to PATH"^) then run this again. & pause & exit /b)
where ollama >nul 2>nul || (echo Ollama is not installed. Download it from https://ollama.com/download then run this again. & pause & exit /b)
set MODEL=
for /f "usebackq delims=" %%m in (`python -c "import json;print(json.load(open('settings.json'))['model'])"`) do set MODEL=%%m
if "%MODEL%"=="" (echo Could not read the model name from settings.json & pause & exit /b)
echo Downloading model %MODEL% (one time, a few GB)...
ollama pull %MODEL%
echo Running self-test...
python -m unittest discover -s tests -t .
echo Done. Start her with start_claire.bat
pause
