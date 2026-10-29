@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python не найден. Поставьте Python 3 с python.org и запустите снова.
  pause
  exit /b 1
)
%PY% COUNCIL.py %*
pause
