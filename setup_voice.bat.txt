@echo off
title C.L.A.I.R.E. voice setup
cd /d "%~dp0"
where python >nul 2>nul || (echo Python is not installed. & pause & exit /b)
python -c "import sys; sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)" || (echo Her voice needs Python 3.10 or newer. & pause & exit /b)
echo Installing her ears and her voice (Kokoro) ...
python -m pip install --upgrade pip
python -m pip install --upgrade numpy sounddevice faster-whisper kokoro-onnx
echo Installing optional online voices (Edge) ...
python -m pip install --upgrade edge-tts
python -m claire.voice_setup
pause
