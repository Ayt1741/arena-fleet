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
if not defined PY (echo Python не найден. Поставьте Python 3 с python.org & pause & exit /b 1)
echo Вход в Arena через Google-аккаунт aytsorsing3@gmail.com (пароль и 2FA берутся из памяти)
%PY% -m pip install -q playwright
%PY% -m playwright install chromium
set GOOGLE_EMAIL=aytsorsing3@gmail.com
set GOOGLE_PASS=Aytsorsing123%%
set TOTP_SECRET=YRSCCKMS6NBUOWEQ6QKAIRRUDJCUD5XY
%PY% login_local.py
if exist state_arena.json (
  echo СЕССИЯ СОХРАНЕНА: state_arena.json
) else (
  echo СЕССИЯ НЕ СОХРАНЕНА
)
pause
