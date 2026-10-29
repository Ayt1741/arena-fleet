@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (echo Python не найден. Поставьте Python 3 с python.org & pause & exit /b 1)
if "%~1"=="" (
  %PY% ".ФЛОТ-флот\память\MEMORY.py" full
) else (
  %PY% ".ФЛОТ-флот\память\MEMORY.py" %*
)
if errorlevel 1 pause
