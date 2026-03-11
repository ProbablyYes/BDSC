@echo off
setlocal

set ROOT=%~dp0..
set BACKEND=%ROOT%\apps\backend
set EXAMPLE=%BACKEND%\.env.example
set TARGET=%BACKEND%\.env

if not exist "%EXAMPLE%" (
  echo Missing template: "%EXAMPLE%"
  exit /b 1
)

if exist "%TARGET%" (
  echo Local .env already exists:
  echo   "%TARGET%"
  echo No changes made.
  exit /b 0
)

copy "%EXAMPLE%" "%TARGET%" >nul
if errorlevel 1 (
  echo Failed to create local .env
  exit /b 1
)

echo Created local backend env:
echo   "%TARGET%"
echo Fill in local secrets such as LLM_API_KEY before using a real provider.
