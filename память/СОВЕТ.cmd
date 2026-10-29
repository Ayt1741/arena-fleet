@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
where py >nul 2>nul || (where python >nul 2>nul || (echo Python не найден. Поставьте Python 3 с python.org & pause & exit /b))
py -3 COUNCIL.py %* 2>nul || python COUNCIL.py %*
pause
