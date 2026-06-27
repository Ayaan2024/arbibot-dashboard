@echo off
REM Install Flask and dependencies if needed
echo Installing/updating Flask, CORS, and Web3...
set PYTHON_EXE=%~dp0.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
	set PYTHON_EXE=python
)

"%PYTHON_EXE%" -m pip install -q flask flask-cors web3

REM Force a single known API port so dashboard and health checks always match.
set BOT_PORT=5003

REM Start the API server
echo.
echo Starting ArbBot API Server on port 5003...
echo.
"%PYTHON_EXE%" bot_api.py
