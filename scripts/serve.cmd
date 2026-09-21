@echo off
rem Arranca TRAMA (API + worker + interfaz compilada) en loopback.
cd /d "%~dp0..\backend"
if not exist ".venv\Scripts\python.exe" (
  echo Falta el entorno virtual. Ejecuta scripts\setup.cmd primero.
  exit /b 1
)
".venv\Scripts\python.exe" -m trama serve %*
