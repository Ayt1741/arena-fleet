@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" (where python >nul 2>nul && set PY=python)
if "%PY%"=="" (where python3 >nul 2>nul && set PY=python3)
if "%PY%"=="" (
  echo Python не найден. Установи Python 3 с python.org, галочка "Add to PATH".
  pause
  exit /b 1
)
%PY% "ВОЙТИ.py" %*
echo.
echo Готово. Сессии: папка ВХОДЫ. Лог: ЛОГ-ВХОДОВ.txt
pause
