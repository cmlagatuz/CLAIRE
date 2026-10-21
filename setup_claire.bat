@echo off
title C.L.A.I.R.E. setup
cd /d "%~dp0"
echo === C.L.A.I.R.E. setup ===
where ollama >nul 2>nul || (echo Ollama is not installed. Download it from https://ollama.com/download then run this again. & pause & exit /b 1)
call make_env.bat || (pause & exit /b 1)
set "PY=.venv\Scripts\python.exe"
set MODEL=
for /f "usebackq delims=" %%m in (`%PY% -c "import json;print(json.load(open('settings.json'))['model'])"`) do set MODEL=%%m
if "%MODEL%"=="" (echo Could not read the model name from settings.json & pause & exit /b 1)
echo Downloading model %MODEL% - one time, a few GB ...
ollama pull %MODEL%
echo Running self-test ...
"%PY%" -m unittest discover -s tests -t .
echo.
echo Done. Next: setup_voice.bat for her voice, then window.bat or start_claire.bat
pause
