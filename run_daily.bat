@echo off
REM Daily update: JAO crossings + day-ahead prices (13:00 start, retries every 20 min until 18:00 Kyiv)
cd /d "%~dp0"
set "PY=C:\Program Files\Python310\python.exe"
if not exist "%PY%" set "PY=py"
"%PY%" run_all.py >> log.txt 2>&1
