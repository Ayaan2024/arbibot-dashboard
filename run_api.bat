@echo off
REM Install Flask and dependencies if needed
echo Installing/updating Flask and CORS...
python -m pip install -q flask flask-cors

REM Start the API server
echo.
echo Starting ArbBot API Server on port 5000...
echo.
python bot_api.py
