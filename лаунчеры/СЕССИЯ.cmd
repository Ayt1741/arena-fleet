@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (echo Python не найден. Поставьте Python 3 с python.org & pause & exit /b 1)
echo   Забираю входы всех профилей Chrome и собираю переписку в память бота.
echo   Chrome будет закрыт и открыт заново на несколько секунд.
pause
taskkill /IM chrome.exe /F >nul 2>nul
%PY% ".ФЛОТ-флот\память\ЗАБРАТЬ-СЕССИИ.py"
%PY% ".ФЛОТ-флот\память\СЛЕЖКА-ЧАТОВ.py" --once
pause
