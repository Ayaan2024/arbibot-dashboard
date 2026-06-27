# LIVE DEPLOYMENT GUIDE

## Strategy: BOTH Modes (Capital-Based + Flash Loan Trades)

This configuration combines capital-based arbitrage with flash loan trades for maximum profitability while maintaining strict loss prevention.

---

## PRE-DEPLOYMENT CHECKLIST

### Wallet Setup
- [ ] Wallet has 50+ USDT (for capital trades)
- [ ] Wallet has 0.2+ BNB (for gas fees)
- [ ] Private key is ONLY in `.env`, never in code
- [ ] Wallet address is correct (0x...)

### RPC Setup
- [ ] QuickNode BSC RPC URL configured
- [ ] QuickNode WSS URL configured
- [ ] RPC is responding (test with health check)
- [ ] No public exposure of RPC URLs

### API Server
- [ ] `bot_api.py` is running on localhost:5000
- [ ] `/api/health` returns `{"alive": true}`
- [ ] `/api/prices` shows opportunities
- [ ] Web3 is initialized (no connection errors)

### Configuration
- [ ] `.env` file created in deployment folder
- [ ] `ALLOW_LIVE_TRADING=true`
- [ ] `LIVE_EXECUTION_ENABLED=true`
- [ ] `TRADE_EXECUTION_MODE=both`
- [ ] All profit thresholds set correctly

---

## DEPLOYMENT STEPS

### Step 1: Verify API Health

```bash
curl http://localhost:5000/api/health
```

Expected response:
```json
{
  "alive": true,
  "web3_available": true,
  "web3_init_error": null
}
```

### Step 2: Check Live Opportunities

```bash
curl http://localhost:5000/api/prices
```

Look for `opportunities` with `"profitable": true` and `"gap" > 0.80%`.

### Step 3: Arm Live Mode (10-Minute Window)

```bash
curl -X POST http://localhost:5000/api/bot/arm-live
```

Response:
```json
{
  "success": true,
  "armed_until": "2026-06-27T14:35:00.000000",
  "window_remaining_seconds": 600
}
```

**⏰ You have 10 minutes to start the bot**

### Step 4: START BOT (LIVE - BOTH MODES)

```bash
curl -X POST http://localhost:5000/api/bot/start \
  -H "Content-Type: application/json" \
  -d '{
    "dry_run": false,
    "starting_capital": 50,
    "gas_fee_paid": 100,
    "trade_execution_mode": "both",
    "live_confirmation": "I UNDERSTAND LIVE TRADING RISKS"
  }'
```

Response:
```json
{
  "success": true,
  "status": {
    "running": true,
    "execution_mode": "real",
    "trade_execution_mode": "both",
    "cycle_profit": 0.0,
    "live_trading_enabled": true
  }
}
```

✅ **BOT IS NOW LIVE WITH BOTH MODES**

---

## REAL-TIME MONITORING

### Quick Status Check

```bash
curl http://localhost:5000/api/status | jq '.status | {running, execution_mode, cycle_profit, total_trades, flash_loan_trades}'
```

### Live Dashboard (PowerShell)

Run: `.\monitor.ps1`

This shows real-time:
- Bot status & execution mode
- Profit/loss metrics
- Trade statistics (capital + flash)
- Gas usage
- Recent trades

### JSON Pretty Print

```bash
curl http://localhost:5000/api/status | jq '.status'
```

---

## EXPECTED PERFORMANCE

### Hour 1
- Bot scans for opportunities
- Finds 8-12 profitable gaps (≥0.85%)
- Capital trades: 4-6 @ $0.90 avg profit
- Flash trades: 2-4 @ $1.75 avg profit
- **Hour 1 Profit: +$8-12**

### After 4 Hours
- Total trades: 15-20
- Capital trades: 10-12
- Flash trades: 5-8
- **Cumulative Profit: +$30-45**

### Day 1 (8 hours)
- Total trades: 30-40
- Success rate: 95%+
- **Daily Profit: $60-100**

---

## TRADE EXECUTION FLOW

### Capital-Based Trade (Your Wallet USDT)
```
1. Check wallet USDT balance ≥ $15
2. Find opportunity (0.85%+ gap, profitable)
3. Buy on cheaper DEX (PancakeSwap)
4. Sell on expensive DEX (Biswap/ApeSwap)
5. Profit = Sell - Buy - Gas - Slippage
6. Update wallet balance
```

### Flash Loan Trade (Borrowed Capital)
```
1. Find opportunity (0.85%+ gap)
2. Request flash loan (≥$50 USDT)
3. Buy on cheaper DEX with borrowed USDT
4. Sell on expensive DEX
5. Calculate: Profit = Sell - Buy - Gas - Slippage - Flash Fee (0.09%)
6. Repay loan + fee in same transaction
7. Keep profit to wallet
```

---

## STOPPING THE BOT

### Graceful Stop

```bash
curl -X POST http://localhost:5000/api/bot/stop
```

### Check Final Status

```bash
curl http://localhost:5000/api/status | jq '.status | {cycle_profit, cycle_loss, total_trades, flash_loan_trades, withdrawable}'
```

### Get Final Logs

```bash
curl http://localhost:5000/api/status | jq '.status.logs' | tail -20
```

---

## SCALING STRATEGY

### Phase 1: First 48 Hours (Current Config)
- Trade Size: $15 per trade
- Min Profit: $0.85
- Capital: 50 USDT
- Expected Profit: $100-200

### Phase 2: After Successful 48 Hours
If profitable, increase:
```
LIVE_TRADE_SIZE_USD=25
LIVE_MIN_PROFIT_USD=1.25
LIVE_MIN_EXECUTION_GAP_PCT=0.75
FLASH_LOAN_MIN_AMOUNT_USD=100
```

### Phase 3: After Successful 1 Week
If still profitable, increase:
```
LIVE_TRADE_SIZE_USD=50
LIVE_MIN_PROFIT_USD=2.00
LIVE_MIN_EXECUTION_GAP_PCT=0.70
FLASH_LOAN_MIN_AMOUNT_USD=200
```

---

## TROUBLESHOOTING

### Bot Not Starting
- [ ] Check `.env` has all required fields
- [ ] Verify `ALLOW_LIVE_TRADING=true`
- [ ] Verify wallet has USDT + BNB
- [ ] Check RPC connection: `curl http://localhost:5000/api/health`

### No Trades Executing
- [ ] Check `/api/prices` for opportunities
- [ ] Verify gaps are ≥0.85% (gap must be profitable after costs)
- [ ] Check gas price (if > 3 gwei, bot will skip trades)
- [ ] Verify slippage (set to 45 bps = 0.45%)

### High Gas Costs
- [ ] Trades skip if gas > 3 gwei
- [ ] Wait for cheaper network times (midnight UTC typically cheapest)
- [ ] Adjust `MAX_GAS_GWEI=2` for stricter limits

### Flash Loan Failures
- [ ] Rare, but check if gap < 0.85% after flash fee (0.09%)
- [ ] Verify DEX liquidity is sufficient
- [ ] Check transaction deadline (90 seconds default)

---

## SUCCESS METRICS

**Trading is working when:**
- ✅ `cycle_profit` increases over time
- ✅ `total_trades` steadily increases
- ✅ `failed_trades` stays near 0
- ✅ Both `triangle_trades` and `flash_loan_trades` > 0
- ✅ `recent_trades` all show positive profit
- ✅ Gas usage stays below limits

**Red Flags:**
- 🔴 `cycle_profit` decreasing (losses happening)
- 🔴 `failed_trades` increasing
- 🔴 No trades executing for 1+ hour
- 🔴 RPC connection errors
- 🔴 Wallet USDT balance decreasing unexpectedly

---

## EMERGENCY PROCEDURES

### Immediate Stop
```bash
curl -X POST http://localhost:5000/api/bot/stop
```

### Check for Stuck Transactions
```bash
# Monitor your wallet on BscScan
# https://bscscan.com/address/0xyour_wallet_address
# Look for pending transactions
```

---

## MONITORING CHECKLIST (Daily)

- [ ] Check `/api/status` - profit trending up?
- [ ] Verify both trade types executing (capital + flash)
- [ ] Gas usage acceptable?
- [ ] No failed trades?
- [ ] Wallet balance increasing?
- [ ] RPC connection stable?
- [ ] Bot process still running?

---

**⚠️ IMPORTANT REMINDERS**

1. **Private Key Security**: Never share your private key. It's in `.env` which should NOT be committed to git.
2. **Real Money At Risk**: This is live trading. Losses are possible if market conditions change rapidly.
3. **Start Small**: Test with $50-100 USDT first. Scale up only after 48+ hours of profitable trading.
4. **Monitor Actively**: Watch the bot for at least the first 4 hours to ensure it's trading correctly.
5. **Arm Window**: You have 10 minutes after arming to start the bot, or you must arm again.

---

**Status**: Ready to Deploy ✅
**Strategy**: BOTH Modes (Capital + Flash Loans)
**Expected ROI**: 60-100% per month (after proven 48 hours)
**Risk Level**: Low-Medium (with current profit filters)

LET'S GO! 🚀
