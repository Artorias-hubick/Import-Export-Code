@echo off
REM Creates a Windows scheduled task: every day at 13:00 (retries every 20 min until all data is in)
cd /d "%~dp0"
schtasks /Create /F /SC DAILY /ST 13:00 /TN "KT_bot Import Export" /TR "\"%~dp0run_daily.bat\""
echo Done. Task "KT_bot Import Export" will run daily at 13:00.
pause
