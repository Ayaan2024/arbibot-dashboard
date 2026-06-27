"""
Simple Flask API server for the ArbBot.
Runs on port 5000 and provides HTTP endpoints to control the bot and fetch status.
The React frontend can call these endpoints via the wallet UI.

Usage:
  py -3 bot_api.py
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timedelta
import threading
import time
import json
import os
from web3 import Web3

app = Flask(__name__)
CORS(app)  # Enable CORS for the React frontend

# ============================================
# BOT STATE (shared with main bot)
# ============================================
bot_state = {
    "running": False,
    "starting_capital": 50.0,
    "cycle_number": 1,
    "cycle_start": datetime.now().isoformat(),
    "cycle_end": (datetime.now() + timedelta(days=7)).isoformat(),
    "cycle_profit": 0.0,
    "cycle_loss": 0.0,
    "total_withdrawn": 0.0,
    "total_trades": 0,
    "flash_loan_trades": 0,
    "triangle_trades": 0,
    "failed_trades": 0,
    "uptime_seconds": 0,
    "last_scan": datetime.now().isoformat(),
    "recent_trades": [],
    "logs": [],
    "wallet_connected": None,
    "binance_address": None,
    "auto_withdraw_enabled": True,
    "auto_withdraw_percentage": 100.0,
    "auto_withdraw_min_profit": 5.0,
    "gas_gwei": 0.0,
    "dex_scores": {"PancakeSwap": 0, "Biswap": 0, "ApeSwap": 0},
}

bot_process_thread = None
bot_running_event = threading.Event()

# ============================================
# LIVE BSC PRICE SCAN (READ-ONLY)
# ============================================
QUICKNODE_URL = os.environ.get("QUICKNODE_URL", "https://bsc-dataseed.binance.org/")
_w3 = Web3(Web3.HTTPProvider(QUICKNODE_URL, request_kwargs={"timeout": 8}))

ROUTERS = {
    "PancakeSwap": "0x10ED43C718714eb63d5aA57B78B54704E256024E",
    "Biswap": "0x3a6d8cA21D1CF76F653A67577FA0D27453350dD8",
    "ApeSwap": "0xcF0feBd3f17CEf5b47b0cD257aCf6025c5BFf3b",
}

TOKENS = {
    "BNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    "USDT": "0x55d398326f99059fF775485246999027B3197955",
    "BUSD": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
    "CAKE": "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
    "ETH": "0x2170Ed0880ac9A755fd29B2688956BD959F933F8",
    "XRP": "0x1D2F0da169ceB9fC7B3144628dB156f3F6c60dBE",
}

PAIRS = ["BNB/USDT", "CAKE/USDT", "ETH/USDT", "XRP/USDT", "BUSD/USDT"]

ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
        ],
        "name": "getAmountsOut",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function",
    }
]


def _quote_token_to_usdt(router_name: str, token_symbol: str):
    """Return 1 token quoted to USDT using on-chain getAmountsOut."""
    try:
        router = _w3.eth.contract(address=Web3.to_checksum_address(ROUTERS[router_name]), abi=ROUTER_ABI)
        token_in = Web3.to_checksum_address(TOKENS[token_symbol])
        token_out = Web3.to_checksum_address(TOKENS["USDT"])
        amount_in = 10 ** 18
        amounts = router.functions.getAmountsOut(amount_in, [token_in, token_out]).call()
        return float(amounts[-1]) / (10 ** 18)
    except Exception:
        return None

# ============================================
# ROUTES — STATUS
# ============================================

@app.route("/api/status", methods=["GET"])
def get_status():
    """Return current bot status and cycle info."""
    return jsonify({
        "success": True,
        "status": bot_state,
        "timestamp": datetime.now().isoformat(),
    })

@app.route("/api/health", methods=["GET"])
def health_check():
    """Simple health check endpoint."""
    return jsonify({"alive": True, "timestamp": datetime.now().isoformat()})

# ============================================
# ROUTES — BOT CONTROL
# ============================================

@app.route("/api/bot/start", methods=["POST"])
def start_bot():
    """Start the bot with optional parameters."""
    global bot_state
    
    if bot_state["running"]:
        return jsonify({"success": False, "error": "Bot already running"}), 400
    
    try:
        data = request.json or {}
        starting_capital = data.get("starting_capital", 50)
        dry_run = data.get("dry_run", False)
        bot_state["starting_capital"] = float(starting_capital)
        bot_state["binance_address"] = data.get("binance_address")
        bot_state["auto_withdraw_enabled"] = bool(data.get("auto_withdraw_enabled", True))
        bot_state["auto_withdraw_percentage"] = float(data.get("auto_withdraw_percentage", 100))
        bot_state["auto_withdraw_min_profit"] = float(data.get("auto_withdraw_min_profit", 5))
        
        bot_state["running"] = True
        bot_state["cycle_start"] = datetime.now().isoformat()
        bot_state["cycle_end"] = (datetime.now() + timedelta(days=7)).isoformat()
        bot_state["uptime_seconds"] = 0
        
        # In a real scenario, you would spawn the Python bot process here
        # using subprocess.Popen(...) and monitor its output
        bot_running_event.set()
        
        add_log(f"Bot started: capital=${starting_capital} dry_run={dry_run}", "info")
        
        return jsonify({
            "success": True,
            "message": "Bot started successfully",
            "status": bot_state,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/bot/stop", methods=["POST"])
def stop_bot():
    """Stop the bot."""
    global bot_state
    
    if not bot_state["running"]:
        return jsonify({"success": False, "error": "Bot not running"}), 400
    
    try:
        bot_state["running"] = False
        bot_running_event.clear()
        add_log("Bot stopped manually", "info")
        
        return jsonify({
            "success": True,
            "message": "Bot stopped",
            "status": bot_state,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================
# ROUTES — TRADES AND LOGS
# ============================================

@app.route("/api/trades", methods=["GET"])
def get_trades():
    """Return recent trades."""
    limit = request.args.get("limit", 20, type=int)
    return jsonify({
        "success": True,
        "trades": bot_state["recent_trades"][:limit],
        "total": len(bot_state["recent_trades"]),
    })

@app.route("/api/logs", methods=["GET"])
def get_logs():
    """Return recent logs."""
    limit = request.args.get("limit", 50, type=int)
    return jsonify({
        "success": True,
        "logs": bot_state["logs"][:limit],
        "total": len(bot_state["logs"]),
    })

# ============================================
# ROUTES — WALLET
# ============================================

@app.route("/api/wallet/connect", methods=["POST"])
def connect_wallet():
    """Register a wallet address (from MetaMask/Trust Wallet)."""
    try:
        data = request.json or {}
        wallet_address = data.get("address")
        signature = data.get("signature")  # Optional: for verification
        
        if not wallet_address:
            return jsonify({"success": False, "error": "Missing wallet address"}), 400
        
        # Validate checksum address (basic check)
        if not wallet_address.startswith("0x") or len(wallet_address) != 42:
            return jsonify({"success": False, "error": "Invalid BSC wallet address"}), 400
        
        bot_state["wallet_connected"] = wallet_address
        add_log(f"Wallet connected: {wallet_address[:6]}...{wallet_address[-4:]}", "success")
        
        return jsonify({
            "success": True,
            "message": "Wallet connected",
            "wallet": wallet_address,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/wallet/disconnect", methods=["POST"])
def disconnect_wallet():
    """Disconnect the wallet."""
    bot_state["wallet_connected"] = None
    add_log("Wallet disconnected", "info")
    return jsonify({"success": True, "message": "Wallet disconnected"})

@app.route("/api/wallet/current", methods=["GET"])
def get_current_wallet():
    """Return currently connected wallet."""
    return jsonify({
        "success": True,
        "wallet": bot_state["wallet_connected"],
    })

@app.route("/api/withdraw", methods=["POST"])
def withdraw_profits():
    """Register a manual profit withdrawal request."""
    try:
        data = request.json or {}
        amount = float(data.get("amount", 0))
        destination_address = data.get("destination_address") or bot_state.get("binance_address")

        if amount <= 0:
            return jsonify({"success": False, "error": "Withdrawal amount must be greater than zero"}), 400

        if not destination_address or not destination_address.startswith("0x") or len(destination_address) != 42:
            return jsonify({"success": False, "error": "Invalid Binance BEP20 address"}), 400

        bot_state["cycle_profit"] = max(0.0, round(bot_state["cycle_profit"] - amount, 2))
        bot_state["total_withdrawn"] = round(bot_state.get("total_withdrawn", 0.0) + amount, 2)
        bot_state["binance_address"] = destination_address
        add_log(f"Manual withdrawal queued: ${amount:.2f} -> {destination_address[:6]}...{destination_address[-4:]}", "success")

        return jsonify({
            "success": True,
            "amount": amount,
            "destination_address": destination_address,
            "total_withdrawn": bot_state["total_withdrawn"],
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================
# ROUTES — MANUAL TRADE (via wallet UI)
# ============================================

@app.route("/api/trade/simulate", methods=["POST"])
def simulate_trade():
    """Simulate a trade without executing it (dry-run style)."""
    try:
        data = request.json or {}
        buy_dex = data.get("buy_dex", "PancakeSwap")
        sell_dex = data.get("sell_dex", "Biswap")
        token_in = data.get("token_in", "USDT")
        token_out = data.get("token_out", "BNB")
        amount = data.get("amount", 10)
        
        # Simulate profit calculation (in real setup, call the bot's simulate_profit function)
        simulated_profit = amount * 0.05  # 5% profit simulation
        gap_pct = 0.8 + (amount * 0.01)
        
        return jsonify({
            "success": True,
            "simulation": {
                "buy_dex": buy_dex,
                "sell_dex": sell_dex,
                "token_in": token_in,
                "token_out": token_out,
                "amount_in": amount,
                "estimated_profit": round(simulated_profit, 4),
                "gap_pct": round(gap_pct, 3),
                "profitable": simulated_profit > 0,
                "message": f"✅ PROFITABLE" if simulated_profit > 0 else "❌ NOT PROFITABLE",
            },
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/live/scan", methods=["GET"])
def live_scan():
    """Read-only live BSC scan: fetches on-chain prices and opportunities."""
    try:
        if not _w3.is_connected():
            return jsonify({"success": False, "error": "BSC RPC not connected"}), 503

        prices = {}
        opportunities = []

        for pair in PAIRS:
            token_symbol, quote_symbol = pair.split("/")
            if quote_symbol != "USDT":
                continue

            prices[pair] = {}
            entries = []
            for dex_name in ROUTERS:
                px = _quote_token_to_usdt(dex_name, token_symbol)
                if px is not None and px > 0:
                    prices[pair][dex_name] = px
                    entries.append((dex_name, px))

            if len(entries) >= 2:
                min_dex, min_px = min(entries, key=lambda x: x[1])
                max_dex, max_px = max(entries, key=lambda x: x[1])
                gap = ((max_px - min_px) / min_px) * 100 if min_px > 0 else 0.0
                opportunities.append({
                    "pair": pair,
                    "buyOn": min_dex,
                    "sellOn": max_dex,
                    "buyPrice": min_px,
                    "sellPrice": max_px,
                    "gap": gap,
                    "profitable": gap > 0.8,
                    "flashLoan": gap > 0.9,
                })

        opportunities.sort(key=lambda x: x["gap"], reverse=True)

        return jsonify({
            "success": True,
            "live": True,
            "source": "bsc-onchain",
            "prices": prices,
            "opportunities": opportunities,
            "rpc": QUICKNODE_URL,
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================
# HELPER FUNCTIONS
# ============================================

def add_log(message: str, log_type: str = "info"):
    """Add a log entry."""
    log_entry = {
        "id": int(time.time() * 1000),
        "time": datetime.now().isoformat(),
        "message": message,
        "type": log_type,
    }
    bot_state["logs"].insert(0, log_entry)
    # Keep only last 100 logs
    bot_state["logs"] = bot_state["logs"][:100]

def add_trade(trade_data: dict):
    """Add a trade to the recent trades list."""
    trade_entry = {
        "id": int(time.time() * 1000),
        "time": datetime.now().isoformat(),
        **trade_data,
    }
    bot_state["recent_trades"].insert(0, trade_entry)
    # Keep only last 50 trades
    bot_state["recent_trades"] = bot_state["recent_trades"][:50]

# ============================================
# BACKGROUND UPTIME COUNTER
# ============================================

def background_uptime_counter():
    """Background thread to increment uptime when bot is running."""
    while True:
        time.sleep(1)
        if bot_state["running"]:
            bot_state["uptime_seconds"] += 1

# ============================================
# STARTUP
# ============================================

if __name__ == "__main__":
    # Start background uptime counter
    uptime_thread = threading.Thread(target=background_uptime_counter, daemon=True)
    uptime_thread.start()
    
    print("""
╔════════════════════════════════════════╗
  🤖 ArbBot API Server
  Port: 5000
  CORS: Enabled for React frontend
╠════════════════════════════════════════╣
  POST  /api/bot/start      — Start bot
  POST  /api/bot/stop       — Stop bot
  GET   /api/status         — Get bot status
  GET   /api/trades         — Recent trades
  GET   /api/logs           — Recent logs
  POST  /api/wallet/connect — Connect wallet
  GET   /api/wallet/current — Current wallet
  POST  /api/trade/simulate — Simulate trade
╚════════════════════════════════════════╝
    """)
    
    add_log("API server started", "info")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
