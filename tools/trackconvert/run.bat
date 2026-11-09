@echo off
cd /d "%~dp0"
set "PY=py"
%PY% -V >nul 2>&1
if errorlevel 1 set "PY=python"
%PY% main.py
if errorlevel 1 pause
