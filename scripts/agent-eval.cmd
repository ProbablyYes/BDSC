@echo off
setlocal

set ROOT=%~dp0..
set BACKEND=%ROOT%\apps\backend

cd /d %BACKEND%
uv run python -m eval.run_eval
uv run python -m eval.run_dialogue_eval
uv run python eval/run_dialogue_eval.py
