@echo off
setlocal

set ROOT=%~dp0..
set BACKEND=%ROOT%\apps\backend
set WEB=%ROOT%\apps\web

echo [0/3] Clean stale listeners on 8037 ^& 8030...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=@(8037,8030); foreach($p in $ports){$ids=(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); foreach($id in $ids){Stop-Process -Id $id -Force -ErrorAction SilentlyContinue}}"

echo [1/3] Clean Python cache...
if exist "%BACKEND%\app\__pycache__" rd /s /q "%BACKEND%\app\__pycache__"
if exist "%BACKEND%\app\services\__pycache__" rd /s /q "%BACKEND%\app\services\__pycache__"

echo [2/3] Start backend...
start "BDSC Backend" cmd /k "cd /d %BACKEND% && uv sync && uv run uvicorn app.main:app --host 127.0.0.1 --port 8037 --reload"

timeout /t 3 /nobreak >nul

echo [3/3] Start web...
start "BDSC Web" cmd /k "cd /d %WEB% && set NEXT_PUBLIC_API_BASE=http://127.0.0.1:8037 && npm run dev -- -p 8030"

echo Done. Backend: http://localhost:8037  Web: http://localhost:8030
