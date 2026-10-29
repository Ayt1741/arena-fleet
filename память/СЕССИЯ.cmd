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
echo.
echo   Забираю сессии всех профилей Chrome и запоминаю переписку.
echo   Chrome будет закрыт и открыт заново на несколько секунд.
echo.
pause
taskkill /IM chrome.exe /F >nul 2>nul
%PY% ЗАБРАТЬ-СЕССИИ.py
echo.
echo   Теперь собираю переписку в память бота...
%PY% СЛЕЖКА-ЧАТОВ.py --once
echo.
pause
