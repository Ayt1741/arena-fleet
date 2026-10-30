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
%PY% ".ФЛОТ-флот\память\УСТАНОВИТЬ-АВТОДОСТУП.py" >nul 2>&1
rem Сервер модели: OpenAI-совместимый API для всех агентов
if not exist "ИИ\модель.json" (
  echo Модель ещё не скачана. Сначала запусти УСТАНОВИТЬ-ИИ.cmd
  pause
  exit /b 1
)
for /f "delims=" %%i in ('%PY% -c "import json;print(json.load(open(r'ИИ\модель.json',encoding='utf-8'))['файл'])"') do set MODEL=%%i
set SRV=
for /r "ИИ\llama.cpp" %%f in (llama-server.exe) do if not defined SRV set SRV=%%f
if "%SRV%"=="" (
  echo Не нашёл llama-server.exe в папке ИИ\llama.cpp — перезапусти УСТАНОВИТЬ-ИИ.cmd
  pause
  exit /b 1
)
echo Сервер ИИ: http://0.0.0.0:8080 — любой агент зовёт POST /v1/chat/completions
"%SRV%" -m "%MODEL%" --ctx-size 65536 --host 0.0.0.0 --port 8080 --jinja

pause
