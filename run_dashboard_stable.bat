@echo off
REM Stable dashboard mode for auto-start (no file watching)
echo Building dashboard...
cd /d %~dp0

set NPM_CMD=
where npm.cmd >nul 2>nul
if %errorlevel%==0 (
	set NPM_CMD=npm.cmd
) else (
	if exist "C:\Program Files\nodejs\npm.cmd" (
		set NPM_CMD="C:\Program Files\nodejs\npm.cmd"
	)
)

if "%NPM_CMD%"=="" (
	echo npm.cmd was not found. Please install Node.js or add npm to PATH.
	exit /b 1
)

%NPM_CMD% run build
if %errorlevel% neq 0 (
	echo Build failed. Dashboard not started.
	exit /b 1
)

echo Starting dashboard preview on port 5176...
start "" "http://localhost:5176"
%NPM_CMD% run preview -- --host --port 5176 --strictPort
