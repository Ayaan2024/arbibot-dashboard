@echo off
REM Live Deployment Script - Deploy to Live Trading
REM This script automates the steps to start live trading with both modes

color 0A
title Arbitrage Bot - Live Deployment

echo.
echo ╔════════════════════════════════════════════════════════╗
echo ║   ARBITRAGE BOT - LIVE DEPLOYMENT SCRIPT               ║
echo ║   Strategy: BOTH Modes (Capital + Flash Loans)         ║
echo ╚════════════════════════════════════════════════════════╝
echo.

REM Check if .env exists
if not exist ".env" (
    echo ❌ ERROR: .env file not found!
    echo.
    echo Please create .env file with:
    echo   - BSC_RPC_URL
    echo   - QUICKNODE_WSS
    echo   - PRIVATE_KEY
    echo   - WALLET_ADDRESS
    echo   - ALLOW_LIVE_TRADING=true
    echo.
    pause
    exit /b 1
)

echo ✅ .env file found
echo.

REM Step 1: Verify API Health
echo [1/5] Verifying API health...
curl -s http://localhost:5000/api/health | jq .alive
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Bot API is not running! Start bot_api.py first.
    pause
    exit /b 1
)
echo ✅ API is healthy
echo.

REM Step 2: Check Opportunities
echo [2/5] Checking for profitable opportunities...
for /f "tokens=*" %%A in ('curl -s http://localhost:5000/api/prices ^| jq ".opportunities | length"') do set OPP_COUNT=%%A
echo Found %OPP_COUNT% opportunities
echo.

REM Step 3: Arm Live Mode
echo [3/5] Arming live mode (10-minute window)...
for /f "tokens=*" %%A in ('curl -s -X POST http://localhost:5000/api/bot/arm-live ^| jq ".window_remaining_seconds"') do set ARM_WINDOW=%%A
echo ⏰ Live mode armed for %ARM_WINDOW% seconds
echo.

REM Step 4: Start Bot
echo [4/5] Starting bot in LIVE mode with BOTH trade types...
echo.
echo ⚠️  IMPORTANT: This will execute REAL TRADES with your wallet funds!
echo.
echo Wallet will use:
echo   - Capital-based trades: Your actual USDT
echo   - Flash loans: Borrowed capital (repaid in same transaction)
echo.
set /p CONFIRM="Type 'YES' to confirm: "
if /i not "%CONFIRM%"=="YES" (
    echo ❌ Deployment cancelled
    pause
    exit /b 1
)

curl -s -X POST http://localhost:5000/api/bot/start ^
  -H "Content-Type: application/json" ^
  -d "{\"dry_run\": false, \"starting_capital\": 50, \"gas_fee_paid\": 100, \"trade_execution_mode\": \"both\", \"live_confirmation\": \"I UNDERSTAND LIVE TRADING RISKS\"}" ^
  | jq '.status | {running, execution_mode, trade_execution_mode, cycle_profit}'

echo.
echo ✅ Bot is now LIVE!
echo.

REM Step 5: Start Monitoring
echo [5/5] Starting live monitor...
echo.
echo Press Ctrl+C to stop monitoring (bot will keep running)
echo.
timeout /t 3 /nobreak
powershell -NoProfile -ExecutionPolicy Bypass -File ".\monitor.ps1"

pause
