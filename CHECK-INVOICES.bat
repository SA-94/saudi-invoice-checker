@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Invoice Checker - %CD%

where python >/dev/null 2>&1
if errorlevel 1 (
  echo.
  echo Python is not installed. Get it from https://python.org
  echo.
  pause
  exit /b 1
)

python check.py %*
echo.
pause
