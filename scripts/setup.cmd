@echo off
rem Prepara TRAMA: entorno Python, dependencias, FFmpeg estatico, frontend compilado y migraciones.
cd /d "%~dp0.."
if not exist backend\.venv (
  python -m venv backend\.venv || exit /b 1
)
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt || exit /b 1
pushd frontend
call npm install || exit /b 1
call npm run build || exit /b 1
popd
if not exist .env copy .env.example .env
backend\.venv\Scripts\python.exe -m trama check
backend\.venv\Scripts\python.exe -m trama migrate
