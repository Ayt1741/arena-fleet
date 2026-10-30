@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" (where python >nul 2>nul && set PY=python)
if "%PY%"=="" (where python3 >nul 2>nul && set PY=python3)
if "%PY%"=="" (
  echo Python не найден. Поставь Python 3 с python.org, галочка "Add to PATH".
  pause
  exit /b 1
)
rem Первым делом — постоянный доступ к хранилищу Telegram для любого агента на этой машине
%PY% ".ФЛОТ-флот\память\УСТАНОВИТЬ-АВТОДОСТУП.py" >nul 2>&1
%PY% ".ФЛОТ-флот\память\УСТАНОВИТЬ-АВТОДОСТУП.py" %*

pause
