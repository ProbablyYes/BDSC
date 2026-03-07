@echo off
setlocal

set ROOT=%~dp0..
set BACKEND=%ROOT%\apps\backend

cd /d %BACKEND%
uv run python eval/run_eval.py
