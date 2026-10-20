@echo off
cd /d "%~dp0"
echo === C.L.A.I.R.E. setup ===
where ollama >nul 2>nul || (echo Ollama is not installed. Download it from https://ollama.com/download then run this again. & pause & exit /b)
for /f "tokens=2 delims=:," %%m in ('findstr /c:"\"model\"" settings.json') do set MODEL=%%~m
set MODEL=%MODEL: =%
set MODEL=%MODEL:"=%
echo Downloading model %MODEL% (one time, a few GB)...
ollama pull %MODEL%
echo Running self-test...
python -m unittest discover -s tests -t .
echo Done. Start her with start_claire.bat
pause
