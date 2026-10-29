@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
where py >nul 2>nul && (py -3 MEMORY.py %* & goto :eof)
where python >nul 2>nul && (python MEMORY.py %* & goto :eof)
echo Python не найден. Установите Python 3 с python.org и запустите снова.
pause
