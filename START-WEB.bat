@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Invoice Checker - Web

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo Python is not installed. Get it from https://python.org
  echo.
  pause
  exit /b 1
)

python web_app.py
echo.
pause
