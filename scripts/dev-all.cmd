@echo off
setlocal

set ROOT=%~dp0..
set BACKEND=%ROOT%\apps\backend
set WEB=%ROOT%\apps\web

echo [0/2] Clean stale backend listeners on 8787...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ids=(Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique); foreach($id in $ids){Stop-Process -Id $id -Force -ErrorAction SilentlyContinue}"

echo [1/2] Start backend...
start "BDSC Backend" cmd /k "cd /d %BACKEND% && uv sync && uv run uvicorn app.main:app --port 8787"

echo [2/2] Start web...
start "BDSC Web" cmd /k "cd /d %WEB% && if exist .next (rmdir /s /q .next) && npm.cmd install && set NEXT_PUBLIC_API_BASE=http://127.0.0.1:8787 && npm.cmd run dev"

echo Done. Open http://localhost:3000
