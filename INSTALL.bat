@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Install Libraries
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Done.
pause
