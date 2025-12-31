@echo off
REM iHIM Auto-Start Script for Windows
REM This keeps iHIM running in the background with auto-restart

cd /d "%~dp0"
start "iHIM Supervisor" /MIN python supervisor.py
echo iHIM Supervisor started in background (minimized window)
echo.
echo To stop: Close the "iHIM Supervisor" window from taskbar
echo To make it auto-start on boot: Put this .bat file in your Startup folder
echo   Startup folder: shell:startup (Win+R, type "shell:startup")
pause
