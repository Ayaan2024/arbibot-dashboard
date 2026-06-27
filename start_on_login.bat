@echo off
REM Auto-start ArbBot API and Dashboard after Windows login.
REM Put a shortcut to this file in shell:startup for persistent auto-start.

set BASE_DIR=c:\Users\munira\Downloads\arbibot-deploy
cd /d %BASE_DIR%

start "ArbBot API" cmd /c "cd /d %BASE_DIR% && call run_api.bat"
timeout /t 3 /nobreak >nul
start "ArbBot Dashboard" cmd /c "cd /d %BASE_DIR% && call run_dashboard_stable.bat"
