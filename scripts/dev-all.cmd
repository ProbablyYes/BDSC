@echo off
setlocal

set ROOT=%~dp0..
set BACKEND=%ROOT%\apps\backend
set WEB=%ROOT%\apps\web

echo [0/2] Clean stale listeners on 8037 ^& 8030...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=@(8037,8030); foreach($p in $ports){$ids=(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); foreach($id in $ids){Stop-Process -Id $id -Force -ErrorAction SilentlyContinue}}"

echo [1/2] Start backend...
start "BDSC Backend" cmd /k "cd /d %BACKEND% && uv sync && uv run uvicorn app.main:app --host 127.0.0.1 --port 8037"

timeout /t 3 /nobreak >nul

echo [2/2] Start web...
start "BDSC Web" cmd /k "cd /d %WEB% && set NEXT_PUBLIC_API_BASE=http://127.0.0.1:8037 && npm run dev -- -p 8030"

echo Done. Backend: http://localhost:8037  Web: http://localhost:8030
