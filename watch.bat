@echo off
cd /d "%~dp0"
title Price watch
python watch.py run
echo.
echo Stop.
pause
