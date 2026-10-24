@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
set "PYTHONUTF8=1"
pushd "%~dp0" || exit /b 1

where node.exe >nul 2>nul
if errorlevel 1 (
  echo [!] Не найден Node.js. Установите Node.js 20 или новее с https://nodejs.org и перезапустите батник.
  goto :fail
)
node.exe -e "if (Number(process.versions.node.split('.')[0]) < 20) process.exit(1)" >nul 2>nul
if errorlevel 1 (
  echo [!] Нужен Node.js 20 или новее. Обновите Node.js: https://nodejs.org
  goto :fail
)
where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo [!] Не найден npm.cmd. Переустановите Node.js вместе с npm и добавлением в PATH.
  goto :fail
)

set "PYTHON_CMD="
set "VENV_READY="
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys, pip; assert sys.prefix != sys.base_prefix; assert (3, 10) <= sys.version_info[:2] < (3, 14); assert sys.maxsize > 2**32" >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=".venv\Scripts\python.exe""
    set "VENV_READY=1"
  )
)
for %%V in (3.13 3.12 3.11 3.10) do if not defined PYTHON_CMD call :select_python py -%%V
if not defined PYTHON_CMD call :select_python python
if not defined PYTHON_CMD call :select_python python3
if not defined PYTHON_CMD (
  echo [!] Не найден рабочий Python 3.10-3.13 x64.
  echo Установите Python 3.13 x64 с https://www.python.org/downloads/
  echo В установщике включите Python Launcher или Add Python to PATH, затем перезапустите батник.
  goto :fail
)

if not exist ".env" (
  if not exist ".env.example" (
    echo [!] Нет .env и .env.example. Восстановите .env.example из репозитория.
    goto :fail
  )
  copy /y ".env.example" ".env" >nul
  if errorlevel 1 (
    echo [!] Не удалось создать .env. Проверьте права на папку проекта.
    goto :fail
  )
  echo [!] Создан .env из шаблона. Укажите в нём DATABASE_URL вашей базы и DGIS_API_KEY для карты.
  echo После сохранения .env запустите батник ещё раз.
  goto :fail
)
%PYTHON_CMD% -c "import os, sys; from pathlib import Path; lines = Path('.env').read_text(encoding='utf-8').splitlines(); config = dict((k.strip(), v.strip()) for line in lines if '=' in line and not line.lstrip().startswith('#') for k, v in [line.split('=', 1)]); url = os.environ.get('DATABASE_URL', config.get('DATABASE_URL', '')).strip(); sys.exit(0 if url and 'ПАРОЛЬ' not in url.upper() and '<' not in url and '>' not in url else 1)" >nul 2>nul
if errorlevel 1 (
  echo [!] В .env или переменной окружения DATABASE_URL нужна строка подключения с реальными реквизитами базы.
  echo Пример: DATABASE_URL=postgresql+psycopg://user:password@host:5432/database
  goto :fail
)

if not defined VENV_READY (
  echo [1/3] Создаю или пересоздаю нерабочее окружение .venv для этого компьютера...
  %PYTHON_CMD% -m venv --clear .venv
  if errorlevel 1 goto :fail
)
echo [2/3] Устанавливаю зависимости Python...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "backend\requirements.txt"
if errorlevel 1 goto :fail

echo [3/3] Проверяю зависимости сайта...
pushd "frontend"
if errorlevel 1 goto :fail
if not exist "node_modules\.bin\vite.cmd" goto :install_frontend
call "node_modules\.bin\vite.cmd" --version >nul 2>nul
if not errorlevel 1 goto :frontend_ready
:install_frontend
if exist "package-lock.json" (
  call npm.cmd ci --no-audit --no-fund
) else (
  call npm.cmd install --no-audit --no-fund
)
if errorlevel 1 (
  popd
  goto :fail
)
call "node_modules\.bin\vite.cmd" --version
if errorlevel 1 (
  popd
  goto :fail
)
:frontend_ready
popd

echo Проверяю подключение к базе...
if not defined PGCONNECT_TIMEOUT set "PGCONNECT_TIMEOUT=10"
".venv\Scripts\python.exe" -c "from backend.app.db import one; r = one('select count(*) as n from companies'); print('  База доступна, компаний:', r['n'])"
if errorlevel 1 (
  echo [!] Проверьте DATABASE_URL, доступность базы по сети и наличие загруженной таблицы companies.
  goto :fail
)

".venv\Scripts\python.exe" -c "import socket; ports = (8000, 5173); sockets = [socket.socket() for _ in ports]; [s.bind(('127.0.0.1', p)) for s, p in zip(sockets, ports)]" >nul 2>nul
if errorlevel 1 (
  echo [!] Порт 8000 или 5173 занят. Закройте предыдущие окна API и сайта либо освободите эти порты.
  goto :fail
)
set "API_URL=http://127.0.0.1:8000"
start "RT radar API" /d "%CD%" "%ComSpec%" /d /v:off /k ".venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"
start "RT radar site" /d "%CD%\frontend" "%ComSpec%" /d /v:off /k "npm.cmd run dev -- --port 5173 --strictPort"
echo Жду готовности API и сайта...
".venv\Scripts\python.exe" -c "import time, urllib.request; exec('for attempt in range(30):\n try:\n  with urllib.request.urlopen(\"http://127.0.0.1:8000/api/health\", timeout=1) as response: response.read()\n  with urllib.request.urlopen(\"http://localhost:5173\", timeout=1) as response: response.read(1)\n  break\n except Exception:\n  time.sleep(1)\nelse:\n raise SystemExit(1)')"
if errorlevel 1 (
  echo [!] API или сайт не запустились вовремя. Подробности ошибки смотрите в открытых окнах API и site.
  goto :fail
)
start "" "http://localhost:5173"
echo.
echo Радар открыт: http://localhost:5173
echo Чтобы остановить приложение, закройте два окна API и site.
popd
exit /b 0

:select_python
%* -c "import sys, venv; assert (3, 10) <= sys.version_info[:2] < (3, 14); assert sys.maxsize > 2**32" >nul 2>nul
if errorlevel 1 exit /b 0
set "PYTHON_CMD=%*"
exit /b 0

:fail
echo.
echo Запуск остановлен. Исправьте ошибку выше и повторите запуск start.bat.
pause
popd
exit /b 1
