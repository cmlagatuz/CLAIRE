@echo off
title C.L.A.I.R.E. voice setup
cd /d "%~dp0"
call make_env.bat || (pause & exit /b 1)
set "PY=.venv\Scripts\python.exe"
echo Installing her ears and her voice - Kokoro ...
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install --upgrade numpy sounddevice faster-whisper kokoro-onnx
if errorlevel 1 (echo. & echo The voice packages did not install - read the red error text above. & echo Send me that text and I will fix it. & pause & exit /b 1)
echo Installing optional online voices - Edge ...
"%PY%" -m pip install --upgrade edge-tts
"%PY%" -m claire.doctor
"%PY%" -m claire.voice_setup
pause
