@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" (where python >nul 2>nul && set PY=python)
if "%PY%"=="" (where python3 >nul 2>nul && set PY=python3)
if "%PY%"=="" (echo Python не найден. Поставь Python 3 с python.org, галочка "Add to PATH". & pause & exit /b 1)
echo Заливаю всё новое из рабочей папки в хранилище Telegram...
%PY% ".ФЛОТ-флот\память\ХРАНИЛИЩЕ.py" sync "%CD%" "рабочая-папка"
echo.
echo Готово. Что лежит на складе:
%PY% ".ФЛОТ-флот\память\ХРАНИЛИЩЕ.py" stat
pause
