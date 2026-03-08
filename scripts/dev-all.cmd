@echo off
setlocal

set ROOT=%~dp0..
set BACKEND=%ROOT%\apps\backend
set WEB=%ROOT%\apps\web

echo [1/2] Start backend...
start "BDSC Backend" cmd /k "cd /d %BACKEND% && uv sync && uv run uvicorn app.main:app --reload --port 8000"

echo [2/2] Start web...
start "BDSC Web" cmd /k "cd /d %WEB% && if exist .next rmdir /s /q .next && npm install && set NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 && npm.cmd run dev"

echo Done. Open http://localhost:3000
