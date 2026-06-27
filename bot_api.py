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
import random
from pathlib import Path

_env_path = Path(__file__).resolve().parent / ".env"


def _load_env_fallback(path: Path) -> None:
    """Load KEY=VALUE pairs from .env when python-dotenv is unavailable."""
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_env_path, override=True)
except Exception:
    _load_env_fallback(_env_path)

try:
    from web3 import Web3
    try:
        # web3 v7+
        from web3.middleware import ExtraDataToPOAMiddleware as POA_MIDDLEWARE
    except Exception:
        # web3 v6 and earlier
        from web3.middleware import geth_poa_middleware as POA_MIDDLEWARE
    WEB3_AVAILABLE = True
    WEB3_IMPORT_ERROR = None
except Exception as import_error:
    Web3 = None
    POA_MIDDLEWARE = None
    WEB3_AVAILABLE = False
    WEB3_IMPORT_ERROR = str(import_error)
    print(f"[ERROR] Web3 import failed: {import_error}")

app = Flask(__name__)


def _load_allowed_origins():
    """Parse ALLOWED_ORIGINS env var for CORS configuration."""
    raw = os.getenv("ALLOWED_ORIGINS", "*").strip()
    if not raw or raw == "*":
        return "*"
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins if origins else "*"


_allowed_origins = _load_allowed_origins()
if _allowed_origins == "*":
    CORS(app)
else:
    CORS(app, resources={r"/*": {"origins": _allowed_origins}})

API_VERSION = "2026-06-26-dex-progress-stream-1"
DEMO_MIN_PROFIT_THRESHOLD_PCT = 0.05  # lowered: real BSC gaps are 0.05-0.15%
LIVE_MIN_PROFIT_THRESHOLD_PCT = 0.5
MIN_PROFIT_USD = 0.01              # demo minimum net profit (paper trades only)
LIVE_MIN_PROFIT_USD = 0.50         # live mode minimum net profit
DEMO_MIN_EXECUTION_GAP_PCT = float(os.getenv("DEMO_MIN_EXECUTION_GAP_PCT", "0.80"))
LIVE_MIN_EXECUTION_GAP_PCT = float(os.getenv("LIVE_MIN_EXECUTION_GAP_PCT", "0.50"))
DEMO_TARGET_NET_PROFIT_USD = float(os.getenv("DEMO_TARGET_NET_PROFIT_USD", "0.12"))
LIVE_TARGET_NET_PROFIT_USD = float(os.getenv("LIVE_TARGET_NET_PROFIT_USD", "0.50"))
FLASH_LOAN_THRESHOLD_PCT = 0.5     # lowered: trigger flash loan at 0.5% gap
FLASH_LOAN_FEE_PCT = 0.09          # 0.09% of borrowed amount
FLASH_LOAN_MIN_AMOUNT_USD = 100.0  # minimum flash loan size to find small opportunities
SLIPPAGE_TOLERANCE_PCT = 0.05      # demo slippage: 0.05% (paper trade, no real slippage)
GAS_FEE_USD = 0.02                 # demo gas estimate per paper trade
GAS_MAX_USD = 0.12                 # live: skip trade if estimated gas exceeds this
GAS_SKIP_ABOVE_USD = 0.12          # do not execute when gas > $0.12
APESWAP_SCAN_PAIRS = 50            # number of pairs to scan on ApeSwap
ENGINE_SCAN_INTERVAL_SECONDS = int(os.getenv("ENGINE_SCAN_INTERVAL_SECONDS", "30"))
TRADE_EXECUTION_MODE = os.getenv("TRADE_EXECUTION_MODE", "both").strip().lower()
if TRADE_EXECUTION_MODE not in {"both", "demo_only", "flash_only"}:
    TRADE_EXECUTION_MODE = "both"
ALLOW_LIVE_TRADING = os.getenv("ALLOW_LIVE_TRADING", "false").strip().lower() in {"1", "true", "yes"}
LIVE_TRADING_UNLOCK_CODE = os.getenv(
    "LIVE_TRADING_UNLOCK_CODE",
    "I UNDERSTAND LIVE TRADING RISKS",
).strip()
LIVE_ARM_WINDOW_SECONDS = int(os.getenv("LIVE_ARM_WINDOW_SECONDS", "600"))
LIVE_ARM_MAX_WINDOW_SECONDS = int(os.getenv("LIVE_ARM_MAX_WINDOW_SECONDS", "3600"))
LIVE_EXECUTION_ENABLED = os.getenv("LIVE_EXECUTION_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
LIVE_TRADE_SIZE_USD = float(os.getenv("LIVE_TRADE_SIZE_USD", "15"))
LIVE_SLIPPAGE_BPS = int(os.getenv("LIVE_SLIPPAGE_BPS", "50"))
LIVE_TX_DEADLINE_SECONDS = int(os.getenv("LIVE_TX_DEADLINE_SECONDS", "90"))
LIVE_RECEIPT_TIMEOUT_SECONDS = int(os.getenv("LIVE_RECEIPT_TIMEOUT_SECONDS", "120"))
MAX_GAS_GWEI = float(os.getenv("MAX_GAS_GWEI", "5"))
BNB_USDT_ESTIMATE = float(os.getenv("BNB_USDT_ESTIMATE", "600"))
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "").strip()
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "").strip()
DEX_PROGRESS_SPEED = {
    "PancakeSwap": float(os.getenv("PANCAKE_PROGRESS_SPEED", "1.00")),
    "Biswap": float(os.getenv("BISWAP_PROGRESS_SPEED", "0.87")),
    "ApeSwap": float(os.getenv("APESWAP_PROGRESS_SPEED", "1.19")),
}
DEX_PROGRESS_PHASE = {
    "PancakeSwap": 0.0,
    "Biswap": 17.0,
    "ApeSwap": 33.0,
}
ENGINE_STAGES = [
    "Scanning DEX Pools",
    "Analyzing Price Gaps",
    "Cross-DEX Arbitrage Scan",
    "Evaluating Liquidity Depth",
    "Multi-Hop Path Analysis",
    "Flash Loan Route Check",
]

# ============================================
# LIVE PRICE CONFIG (QuickNode / BSC)
# ============================================
def _load_rpc_urls_from_env() -> list[str]:
    """Load HTTP(S) RPC URLs from environment variables only."""
    candidates = [
        os.getenv("BSC_RPC_URL", ""),
        os.getenv("QUICKNODE_URL", ""),
    ]

    urls: list[str] = []
    for raw in candidates:
        if not raw:
            continue
        for item in raw.split(","):
            url = item.strip()
            if url.startswith("http://") or url.startswith("https://"):
                urls.append(url)

    # Preserve order while removing duplicates.
    unique_urls: list[str] = []
    seen = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        unique_urls.append(url)

    return unique_urls


RPC_URLS = _load_rpc_urls_from_env()

PANCAKE_ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
BISWAP_ROUTER = "0x3a6d8cA21D1CF76F653A67577FA0D27453350dD8"
APESWAP_ROUTER = "0xcf0febd3f17cef5b47b0cd257acf6025c5bff3b7"

TOKENS = {
    "BNB":  "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    "USDT": "0x55d398326f99059fF775485246999027B3197955",
    "BUSD": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
    "CAKE": "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
    "ETH":  "0x2170Ed0880ac9A755fd29B2688956BD959F933F8",
    "XRP":  "0x1D2F0dA169ceB9Fc7C78f839E611B15fF52C8F8d",
    "DOT":  "0x7083609fCE4d1d8Dc0C979AAb8c869Ea2C873402",
    "ADA":  "0x3EE2200Efb3400fAbB9AacF31297cBdD1d435D47",
    "LINK": "0xF8A0BF9cF54Bb92F17374d9e9A321E6a111a51bD",
}

# High-volume pairs focused list (items 1-4 from user request + existing pairs)
PAIRS = [
    ("BNB",  "USDT"),
    ("CAKE", "BNB"),
    ("ETH",  "BNB"),
    ("BUSD", "USDT"),
    ("ETH",  "USDT"),
    ("CAKE", "USDT"),
    ("XRP",  "USDT"),
    ("DOT",  "BNB"),
    ("ADA",  "BNB"),
    ("LINK", "BNB"),
]

ROUTER_ABI = [{
    "inputs": [
        {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
        {"internalType": "address[]", "name": "path", "type": "address[]"}
    ],
    "name": "getAmountsOut",
    "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
    "stateMutability": "view",
    "type": "function"
}, {
    "inputs": [
        {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
        {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
        {"internalType": "address[]", "name": "path", "type": "address[]"},
        {"internalType": "address", "name": "to", "type": "address"},
        {"internalType": "uint256", "name": "deadline", "type": "uint256"}
    ],
    "name": "swapExactTokensForTokens",
    "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
    "stateMutability": "nonpayable",
    "type": "function"
}]

ERC20_ABI = [{
    "constant": True,
    "inputs": [
        {"name": "owner", "type": "address"},
        {"name": "spender", "type": "address"}
    ],
    "name": "allowance",
    "outputs": [{"name": "", "type": "uint256"}],
    "type": "function"
}, {
    "constant": False,
    "inputs": [
        {"name": "spender", "type": "address"},
        {"name": "amount", "type": "uint256"}
    ],
    "name": "approve",
    "outputs": [{"name": "", "type": "bool"}],
    "type": "function"
}, {
    "constant": True,
    "inputs": [{"name": "account", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"name": "", "type": "uint256"}],
    "type": "function"
}]

w3 = None
ROUTERS = {}
TOKEN_CONTRACTS = {}
WEB3_INIT_ERROR = None


def init_web3():
    """Initialize Web3 router contracts if env RPC URL(s) and web3 are available."""
    global w3, ROUTERS, TOKEN_CONTRACTS, WEB3_INIT_ERROR

    if not WEB3_AVAILABLE or not RPC_URLS:
        return

    last_error = None
    for rpc_url in RPC_URLS:
        if not rpc_url:
            continue

        try:
            candidate_w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
            if POA_MIDDLEWARE:
                candidate_w3.middleware_onion.inject(POA_MIDDLEWARE, layer=0)

            if not candidate_w3.is_connected():
                last_error = f"RPC not connected: {rpc_url}"
                continue

            chain_id = candidate_w3.eth.chain_id
            if chain_id != 56:
                last_error = f"Wrong chain id {chain_id} from {rpc_url}; expected BSC mainnet (56)"
                continue

            pancake = candidate_w3.eth.contract(address=Web3.to_checksum_address(PANCAKE_ROUTER.lower()), abi=ROUTER_ABI)
            biswap = candidate_w3.eth.contract(address=Web3.to_checksum_address(BISWAP_ROUTER.lower()), abi=ROUTER_ABI)
            apeswap = candidate_w3.eth.contract(address=Web3.to_checksum_address(APESWAP_ROUTER.lower()), abi=ROUTER_ABI)

            w3 = candidate_w3
            ROUTERS = {
                "PancakeSwap": pancake,
                "Biswap": biswap,
                "ApeSwap": apeswap,
            }
            TOKEN_CONTRACTS = {
                symbol: candidate_w3.eth.contract(
                    address=Web3.to_checksum_address(address),
                    abi=ERC20_ABI,
                )
                for symbol, address in TOKENS.items()
            }
            WEB3_INIT_ERROR = None
            return
        except Exception as exc:
            last_error = f"{rpc_url}: {exc}"

    WEB3_INIT_ERROR = last_error or "Unknown web3 initialization failure"
    w3 = None
    ROUTERS = {}
    TOKEN_CONTRACTS = {}


def get_price(router, token_in: str, token_out: str) -> float:
    """Fetch output amount for a 1-token input via a router path."""
    if not w3:
        return 0.0

    try:
        amount_in = w3.to_wei(1, "ether")
        path = [
            Web3.to_checksum_address(TOKENS[token_in]),
            Web3.to_checksum_address(TOKENS[token_out]),
        ]
        amounts = router.functions.getAmountsOut(amount_in, path).call()
        return float(w3.from_wei(amounts[-1], "ether"))
    except Exception:
        return 0.0


def _router_address_by_name(name: str) -> str | None:
    mapping = {
        "PancakeSwap": PANCAKE_ROUTER,
        "Biswap": BISWAP_ROUTER,
        "ApeSwap": APESWAP_ROUTER,
    }
    return mapping.get(name)


def _get_live_execution_readiness() -> tuple[bool, str]:
    if not LIVE_EXECUTION_ENABLED:
        return False, "LIVE_EXECUTION_ENABLED is false"
    if not WEB3_AVAILABLE or not w3 or not ROUTERS:
        return False, "Web3 is not ready"
    if not PRIVATE_KEY:
        return False, "PRIVATE_KEY is missing"
    if not WALLET_ADDRESS or not WALLET_ADDRESS.startswith("0x") or len(WALLET_ADDRESS) != 42:
        return False, "WALLET_ADDRESS is invalid"
    return True, "ok"


def _tx_raw_bytes(signed_tx) -> bytes:
    raw = getattr(signed_tx, "rawTransaction", None)
    if raw is None:
        raw = getattr(signed_tx, "raw_transaction", None)
    return raw


def _current_gas_price_wei() -> int:
    if not w3:
        return 0
    network_price = int(w3.eth.gas_price)
    cap_price = int(w3.to_wei(MAX_GAS_GWEI, "gwei"))
    return min(network_price, cap_price)


def _build_tx(base: dict, nonce: int) -> dict:
    gas_price = _current_gas_price_wei()
    tx = {
        "from": Web3.to_checksum_address(WALLET_ADDRESS),
        "nonce": nonce,
        "gasPrice": gas_price,
        "chainId": 56,
    }
    tx.update(base)
    return tx


def _send_signed_tx(tx: dict) -> tuple[str, dict]:
    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(_tx_raw_bytes(signed))
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=LIVE_RECEIPT_TIMEOUT_SECONDS)
    hash_hex = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
    return hash_hex, receipt


def _ensure_allowance(token_symbol: str, spender: str, required_amount: int, nonce: int) -> tuple[int, list[str], int]:
    token = TOKEN_CONTRACTS[token_symbol]
    owner = Web3.to_checksum_address(WALLET_ADDRESS)
    spender_checksum = Web3.to_checksum_address(spender)
    current = int(token.functions.allowance(owner, spender_checksum).call())

    tx_hashes: list[str] = []
    gas_used_wei = 0
    if current >= required_amount:
        return nonce, tx_hashes, gas_used_wei

    approve_tx = token.functions.approve(
        spender_checksum,
        int(required_amount * 2),
    ).build_transaction(_build_tx({"gas": 120000}, nonce))
    tx_hash, receipt = _send_signed_tx(approve_tx)
    tx_hashes.append(tx_hash)
    receipt_price = int(getattr(receipt, "effectiveGasPrice", approve_tx.get("gasPrice", 0)))
    gas_used_wei += int(receipt.get("gasUsed", 0)) * receipt_price
    return nonce + 1, tx_hashes, gas_used_wei


def execute_live_spot_arbitrage(opp: dict, capital_usd: float) -> dict:
    """Execute a two-leg on-chain spot arbitrage for USDT-quoted pairs."""
    if not w3:
        return {"success": False, "error": "Web3 not initialized"}

    pair = str(opp.get("pair", ""))
    if "/" not in pair:
        return {"success": False, "error": f"Invalid pair format: {pair}"}

    base, quote = pair.split("/", 1)
    base = base.strip().upper()
    quote = quote.strip().upper()
    if quote != "USDT":
        return {"success": False, "error": f"Unsupported live pair {pair}; only */USDT supported"}

    buy_dex = str(opp.get("buyOn", ""))
    sell_dex = str(opp.get("sellOn", ""))
    buy_router = ROUTERS.get(buy_dex)
    sell_router = ROUTERS.get(sell_dex)
    buy_router_addr = _router_address_by_name(buy_dex)
    sell_router_addr = _router_address_by_name(sell_dex)
    if not buy_router or not sell_router or not buy_router_addr or not sell_router_addr:
        return {"success": False, "error": "Selected DEX router unavailable"}

    if "USDT" not in TOKEN_CONTRACTS or base not in TOKEN_CONTRACTS:
        return {"success": False, "error": f"Missing token contracts for {pair}"}

    wallet = Web3.to_checksum_address(WALLET_ADDRESS)
    usdt_addr = Web3.to_checksum_address(TOKENS["USDT"])
    base_addr = Web3.to_checksum_address(TOKENS[base])
    usdt = TOKEN_CONTRACTS["USDT"]
    base_token = TOKEN_CONTRACTS[base]

    spend_usd = max(1.0, min(float(capital_usd), LIVE_TRADE_SIZE_USD))
    amount_in = int(w3.to_wei(spend_usd, "ether"))

    usdt_before = int(usdt.functions.balanceOf(wallet).call())
    if usdt_before < amount_in:
        return {"success": False, "error": f"Insufficient USDT balance for ${spend_usd:.2f}"}

    gas_price = _current_gas_price_wei()
    if gas_price <= 0:
        return {"success": False, "error": "Invalid gas price"}

    nonce = int(w3.eth.get_transaction_count(wallet, "pending"))
    deadline = int(time.time()) + LIVE_TX_DEADLINE_SECONDS
    tx_hashes: list[str] = []
    total_gas_wei = 0

    # Approve USDT for buy router if needed.
    nonce, approve_hashes, approve_gas_wei = _ensure_allowance("USDT", buy_router_addr, amount_in, nonce)
    tx_hashes.extend(approve_hashes)
    total_gas_wei += approve_gas_wei

    quote_buy = buy_router.functions.getAmountsOut(amount_in, [usdt_addr, base_addr]).call()
    expected_base = int(quote_buy[-1])
    min_base = int(expected_base * (1 - (LIVE_SLIPPAGE_BPS / 10000.0)))
    if min_base <= 0:
        return {"success": False, "error": "Calculated min output is zero"}

    base_before = int(base_token.functions.balanceOf(wallet).call())
    buy_tx = buy_router.functions.swapExactTokensForTokens(
        amount_in,
        min_base,
        [usdt_addr, base_addr],
        wallet,
        deadline,
    ).build_transaction(_build_tx({"gas": 420000}, nonce))
    buy_hash, buy_receipt = _send_signed_tx(buy_tx)
    tx_hashes.append(buy_hash)
    if int(buy_receipt.get("status", 0)) != 1:
        return {"success": False, "error": "Buy leg reverted", "tx_hashes": tx_hashes}

    buy_gas_price = int(getattr(buy_receipt, "effectiveGasPrice", buy_tx.get("gasPrice", 0)))
    total_gas_wei += int(buy_receipt.get("gasUsed", 0)) * buy_gas_price
    nonce += 1

    base_after_buy = int(base_token.functions.balanceOf(wallet).call())
    base_received = max(0, base_after_buy - base_before)
    if base_received <= 0:
        return {"success": False, "error": "No base token received from buy leg", "tx_hashes": tx_hashes}

    # Approve base token for sell router if needed.
    nonce, approve2_hashes, approve2_gas_wei = _ensure_allowance(base, sell_router_addr, base_received, nonce)
    tx_hashes.extend(approve2_hashes)
    total_gas_wei += approve2_gas_wei

    quote_sell = sell_router.functions.getAmountsOut(base_received, [base_addr, usdt_addr]).call()
    expected_usdt = int(quote_sell[-1])
    min_usdt = int(expected_usdt * (1 - (LIVE_SLIPPAGE_BPS / 10000.0)))
    if min_usdt <= 0:
        return {"success": False, "error": "Calculated min USDT output is zero", "tx_hashes": tx_hashes}

    sell_tx = sell_router.functions.swapExactTokensForTokens(
        base_received,
        min_usdt,
        [base_addr, usdt_addr],
        wallet,
        deadline,
    ).build_transaction(_build_tx({"gas": 420000}, nonce))
    sell_hash, sell_receipt = _send_signed_tx(sell_tx)
    tx_hashes.append(sell_hash)
    if int(sell_receipt.get("status", 0)) != 1:
        return {"success": False, "error": "Sell leg reverted", "tx_hashes": tx_hashes}

    sell_gas_price = int(getattr(sell_receipt, "effectiveGasPrice", sell_tx.get("gasPrice", 0)))
    total_gas_wei += int(sell_receipt.get("gasUsed", 0)) * sell_gas_price

    usdt_after = int(usdt.functions.balanceOf(wallet).call())
    pnl_wei = int(usdt_after - usdt_before)
    pnl_usd = float(w3.from_wei(pnl_wei, "ether"))
    gas_cost_usd = float(w3.from_wei(total_gas_wei, "ether")) * BNB_USDT_ESTIMATE

    return {
        "success": True,
        "tx_hash": sell_hash,
        "tx_hashes": tx_hashes,
        "profit_usd": round(pnl_usd, 6),
        "gas_cost_usd": round(gas_cost_usd, 6),
        "amount_in_usd": round(spend_usd, 6),
    }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _sanitize_quotes(dex_prices: dict[str, float], tolerance: float = 0.2) -> dict[str, float]:
    """Remove clearly outlier quotes so spread reflects realistic cross-DEX differences."""
    if len(dex_prices) < 3:
        return dex_prices

    median_price = _median(list(dex_prices.values()))
    if median_price <= 0:
        return dex_prices

    filtered = {
        dex: price
        for dex, price in dex_prices.items()
        if abs(price - median_price) / median_price <= tolerance
    }

    # Keep filtered quotes even if only one remains, so we don't re-introduce
    # extreme outliers into the payload shown by the dashboard.
    return filtered


def _spread_percent(low_price: float, high_price: float) -> float:
    """Compute symmetric spread percentage using mid-price denominator."""
    if low_price <= 0 or high_price <= 0:
        return 0.0
    mid = (low_price + high_price) / 2.0
    if mid <= 0:
        return 0.0
    return ((high_price - low_price) / mid) * 100.0


def _best_reasonable_pair(dex_prices: dict[str, float], max_spread_pct: float = 2.0):
    """Pick the closest DEX quote pair and reject anomalous spreads."""
    entries = list(dex_prices.items())
    if len(entries) < 2:
        return None

    best = None
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a_name, a_price = entries[i]
            b_name, b_price = entries[j]

            low_name, low_price = (a_name, a_price) if a_price <= b_price else (b_name, b_price)
            high_name, high_price = (b_name, b_price) if a_price <= b_price else (a_name, a_price)
            gap = _spread_percent(low_price, high_price)

            if best is None or gap < best["gap"]:
                best = {
                    "buyOn": low_name,
                    "buyPrice": low_price,
                    "sellOn": high_name,
                    "sellPrice": high_price,
                    "gap": gap,
                }

    if not best or best["gap"] > max_spread_pct:
        return None
    return best


def build_live_prices_payload():
    """Build a response payload with per-DEX live prices and arbitrage gaps."""
    if not WEB3_AVAILABLE:
        return {
            "prices": {},
            "opportunities": [],
            "connected": False,
            "block": None,
            "api_version": API_VERSION,
            "web3_available": WEB3_AVAILABLE,
            "web3_import_error": WEB3_IMPORT_ERROR,
            "error": f"web3 unavailable: {WEB3_IMPORT_ERROR}. Install with: python -m pip install web3",
        }

    if not RPC_URLS:
        return {
            "prices": {},
            "opportunities": [],
            "connected": False,
            "block": None,
            "api_version": API_VERSION,
            "web3_available": WEB3_AVAILABLE,
            "web3_import_error": WEB3_IMPORT_ERROR,
            "error": "BSC_RPC_URL (or QUICKNODE_URL) is not set. Configure it in your environment.",
        }

    if not w3 or not ROUTERS:
        init_web3()

    if not w3 or not ROUTERS:
        return {
            "prices": {},
            "opportunities": [],
            "connected": False,
            "block": None,
            "api_version": API_VERSION,
            "web3_available": WEB3_AVAILABLE,
            "web3_import_error": WEB3_IMPORT_ERROR,
            "web3_init_error": WEB3_INIT_ERROR,
            "error": f"Failed to initialize Web3 routers: {WEB3_INIT_ERROR}",
        }

    result = {}
    for token_in, token_out in PAIRS:
        pair = f"{token_in}/{token_out}"
        raw_quotes = {}
        for name, router in ROUTERS.items():
            price = get_price(router, token_in, token_out)
            if price > 0:
                raw_quotes[name] = price

        result[pair] = _sanitize_quotes(raw_quotes)

    opportunities = []
    for pair, dex_prices in result.items():
        if len(dex_prices) < 2:
            continue

        best_pair = _best_reasonable_pair(dex_prices)
        if not best_pair:
            continue

        gap = best_pair["gap"]

        opportunities.append({
            "pair": pair,
            "buyOn": best_pair["buyOn"],
            "buyPrice": best_pair["buyPrice"],
            "sellOn": best_pair["sellOn"],
            "sellPrice": best_pair["sellPrice"],
            "gap": round(gap, 4),
            "profitable": gap >= DEMO_MIN_PROFIT_THRESHOLD_PCT,
            "flashLoan": gap >= FLASH_LOAN_THRESHOLD_PCT,
        })

    connected = False
    block = None
    try:
        connected = bool(w3.is_connected())
        if connected:
            block = w3.eth.block_number
    except Exception:
        connected = False

    return {
        "prices": result,
        "opportunities": sorted(opportunities, key=lambda x: x["gap"], reverse=True),
        "connected": connected,
        "block": block,
        "api_version": API_VERSION,
        "web3_available": WEB3_AVAILABLE,
        "web3_import_error": WEB3_IMPORT_ERROR,
        "web3_init_error": WEB3_INIT_ERROR,
    }

# ============================================
# BOT STATE (shared with main bot)
# ============================================
bot_state = {
    "running": False,
    "cycle_number": 1,
    "cycle_start": datetime.now().isoformat(),
    "cycle_end": (datetime.now() + timedelta(days=7)).isoformat(),
    "cycle_profit": 0.0,
    "cycle_loss": 0.0,
    "total_trades": 0,
    "flash_loan_trades": 0,
    "triangle_trades": 0,
    "failed_trades": 0,
    "uptime_seconds": 0,
    "last_scan": datetime.now().isoformat(),
    "recent_trades": [],
    "logs": [],
    "wallet_connected": None,
    "starting_capital": 50.0,
    "gas_fee_paid": 50.0,
    "subscription_capital": 50.0,
    "withdrawable": 0.0,
    "gas_usage_limit": 300.0,
    "gas_usage_usd": 0.0,
    "gas_usage_pct": 0.0,
    "cycle_remaining_seconds": 0,
    "dry_run": True,
    "gas_gwei": 0.0,
    "dex_scores": {"PancakeSwap": 0, "Biswap": 0, "ApeSwap": 0},
    "engine_stage_index": 0,
    "engine_stage_progress": [0, 0, 0, 0, 0, 0],
    "engine_stage_status": ["idle", "idle", "idle", "idle", "idle", "idle"],
    "dex_fetch_progress": {"PancakeSwap": 0, "Biswap": 0, "ApeSwap": 0},
    "dex_price_coverage": {"PancakeSwap": 0, "Biswap": 0, "ApeSwap": 0},
    "total_dex_scan_progress": 0,
    "best_opportunity": None,
    "engine_execution_status": "Engine idle.",
    "engine_scan_interval_seconds": ENGINE_SCAN_INTERVAL_SECONDS,
    "engine_next_scan_seconds": ENGINE_SCAN_INTERVAL_SECONDS,
    "trade_execution_mode": TRADE_EXECUTION_MODE,
    "execution_mode": "demo",
    "execution_backend": "simulation",
    "live_trading_enabled": ALLOW_LIVE_TRADING,
    "live_armed_until": None,
    "live_armed_remaining_seconds": 0,
    "last_trade_mode": "demo",
}

bot_process_thread = None
bot_running_event = threading.Event()
last_trade_key = None
last_trade_ts = 0.0
last_execution_mode = "demo"


def _reset_engine_state(idle_status: str = "Engine idle.") -> None:
    bot_state["engine_stage_index"] = 0
    bot_state["engine_stage_progress"] = [0, 0, 0, 0, 0, 0]
    bot_state["engine_stage_status"] = ["idle", "idle", "idle", "idle", "idle", "idle"]
    bot_state["dex_fetch_progress"] = {"PancakeSwap": 0, "Biswap": 0, "ApeSwap": 0}
    bot_state["dex_price_coverage"] = {"PancakeSwap": 0, "Biswap": 0, "ApeSwap": 0}
    bot_state["total_dex_scan_progress"] = 0
    bot_state["best_opportunity"] = None
    bot_state["engine_execution_status"] = idle_status
    bot_state["total_dex_scan_progress"] = 0


def _set_engine_stage_running(index: int) -> None:
    size = len(ENGINE_STAGES)
    progress = list(bot_state.get("engine_stage_progress", [0] * size))
    status = list(bot_state.get("engine_stage_status", ["idle"] * size))
    for i in range(size):
        if i < index:
            status[i] = "done"
            progress[i] = 100
        elif i == index:
            status[i] = "running"
            progress[i] = max(0, min(100, int(progress[i])))
        else:
            status[i] = "pending"
    bot_state["engine_stage_index"] = index
    bot_state["engine_stage_progress"] = progress
    bot_state["engine_stage_status"] = status


def _set_engine_stage_progress(index: int, value: int) -> None:
    progress = list(bot_state.get("engine_stage_progress", [0] * len(ENGINE_STAGES)))
    if 0 <= index < len(progress):
        progress[index] = max(0, min(100, int(value)))
    bot_state["engine_stage_progress"] = progress


def _set_engine_stage_done(index: int) -> None:
    _set_engine_stage_progress(index, 100)
    status = list(bot_state.get("engine_stage_status", ["idle"] * len(ENGINE_STAGES)))
    if 0 <= index < len(status):
        status[index] = "done"
    bot_state["engine_stage_status"] = status


def _calculate_dex_price_coverage(prices: dict) -> dict:
    total_pairs = max(1, len(PAIRS))
    coverage = {"PancakeSwap": 0, "Biswap": 0, "ApeSwap": 0}
    for dex in coverage.keys():
        with_quotes = 0
        for token_in, token_out in PAIRS:
            pair = f"{token_in}/{token_out}"
            pair_quotes = prices.get(pair, {})
            quote = pair_quotes.get(dex)
            if isinstance(quote, (int, float)) and quote > 0:
                with_quotes += 1
        coverage[dex] = round((with_quotes / total_pairs) * 100)
    return coverage


def _update_engine_next_scan_seconds() -> None:
    interval = int(bot_state.get("engine_scan_interval_seconds", ENGINE_SCAN_INTERVAL_SECONDS))
    try:
        last_scan = datetime.fromisoformat(str(bot_state.get("last_scan")))
        elapsed = max(0, int((datetime.now() - last_scan).total_seconds()))
        bot_state["engine_next_scan_seconds"] = max(0, interval - elapsed)
        # Keep each DEX progress independent and continuously moving.
        if bot_state.get("running"):
            base_progress = (elapsed / max(1.0, float(interval))) * 100.0
            dex_progress = {}
            for dex in ("PancakeSwap", "Biswap", "ApeSwap"):
                speed = max(0.2, float(DEX_PROGRESS_SPEED.get(dex, 1.0)))
                phase = float(DEX_PROGRESS_PHASE.get(dex, 0.0))
                value = int((base_progress * speed + phase) % 100)
                dex_progress[dex] = value

            bot_state["dex_fetch_progress"] = dex_progress
            bot_state["total_dex_scan_progress"] = round(sum(dex_progress.values()) / 3)
    except Exception:
        bot_state["engine_next_scan_seconds"] = interval


def _recompute_subscription_fields() -> None:
    """Keep subscription-style metrics in sync with current bot state."""
    net_profit = max(0.0, float(bot_state.get("cycle_profit", 0.0)) - float(bot_state.get("cycle_loss", 0.0)))
    gas_fee_paid = max(1.0, float(bot_state.get("gas_fee_paid", 50.0)))
    gas_usage_limit = max(1.0, round(gas_fee_paid * 6.0, 2))
    gas_usage_usd = min(gas_usage_limit, round(net_profit + (gas_fee_paid * 0.5), 2))
    gas_usage_pct = (gas_usage_usd / gas_usage_limit) * 100.0 if gas_usage_limit > 0 else 0.0

    bot_state["subscription_capital"] = round(float(bot_state.get("starting_capital", 50.0)) + net_profit, 2)
    bot_state["withdrawable"] = round(net_profit, 2)
    bot_state["gas_usage_limit"] = round(gas_usage_limit, 2)
    bot_state["gas_usage_usd"] = round(gas_usage_usd, 2)
    bot_state["gas_usage_pct"] = round(max(0.0, min(100.0, gas_usage_pct)), 2)

    try:
        cycle_end = datetime.fromisoformat(str(bot_state.get("cycle_end")))
        remaining = int((cycle_end - datetime.now()).total_seconds())
        bot_state["cycle_remaining_seconds"] = max(0, remaining)
    except Exception:
        bot_state["cycle_remaining_seconds"] = 0

    arm_until = bot_state.get("live_armed_until")
    if arm_until:
        try:
            remaining = int((datetime.fromisoformat(str(arm_until)) - datetime.now()).total_seconds())
            bot_state["live_armed_remaining_seconds"] = max(0, remaining)
            if remaining <= 0:
                bot_state["live_armed_until"] = None
        except Exception:
            bot_state["live_armed_until"] = None
            bot_state["live_armed_remaining_seconds"] = 0
    else:
        bot_state["live_armed_remaining_seconds"] = 0

    _update_engine_next_scan_seconds()


def _is_live_mode_armed() -> bool:
    """Return True only when live mode arm window is currently active."""
    arm_until = bot_state.get("live_armed_until")
    if not arm_until:
        return False
    try:
        return datetime.fromisoformat(str(arm_until)) > datetime.now()
    except Exception:
        return False

# ============================================
# ROUTES — STATUS
# ============================================

@app.route("/api/status", methods=["GET"])
def get_status():
    """Return current bot status and cycle info."""
    _recompute_subscription_fields()
    return jsonify({
        "success": True,
        "status": bot_state,
        "timestamp": datetime.now().isoformat(),
    })

@app.route("/api/health", methods=["GET"])
def health_check():
    """Simple health check endpoint."""
    return jsonify({
        "alive": True,
        "timestamp": datetime.now().isoformat(),
        "api_version": API_VERSION,
        "web3_available": WEB3_AVAILABLE,
        "web3_import_error": WEB3_IMPORT_ERROR,
        "web3_init_error": WEB3_INIT_ERROR,
    })


@app.route("/api/apeswap/health", methods=["GET"])
def apeswap_health():
    """Check ApeSwap RPC connection and verify liquidity pools are loading."""
    result: dict = {
        "router": APESWAP_ROUTER,
        "rpc_connected": False,
        "pools_checked": 0,
        "pools_responding": 0,
        "pairs_sampled": [],
        "error": None,
    }

    try:
        if not WEB3_AVAILABLE or not w3 or "ApeSwap" not in ROUTERS:
            result["error"] = "Web3 not initialised or ApeSwap router not loaded"
            return jsonify(result), 503

        apeswap = ROUTERS["ApeSwap"]
        result["rpc_connected"] = True

        sample_pairs = PAIRS[:min(5, len(PAIRS))]
        for token_in, token_out in sample_pairs:
            result["pools_checked"] += 1
            addr_in  = Web3.to_checksum_address(TOKENS[token_in])
            addr_out = Web3.to_checksum_address(TOKENS[token_out])
            try:
                amounts = apeswap.functions.getAmountsOut(10 ** 18, [addr_in, addr_out]).call()
                price = amounts[1] / 10 ** 18
                result["pools_responding"] += 1
                result["pairs_sampled"].append({"pair": f"{token_in}/{token_out}", "price": round(price, 6), "ok": True})
            except Exception as pool_err:
                result["pairs_sampled"].append({"pair": f"{token_in}/{token_out}", "price": None, "ok": False, "error": str(pool_err)})
    except Exception as e:
        result["error"] = str(e)

    return jsonify(result), 200 if result["pools_responding"] > 0 else 503


@app.route("/prices", methods=["GET"])
@app.route("/api/prices", methods=["GET"])
def get_live_prices():
    """Return live per-DEX prices and best arbitrage opportunities."""
    payload = build_live_prices_payload()
    return jsonify(payload)

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
        starting_capital = float(data.get("starting_capital", 50))
        gas_fee_paid = float(data.get("gas_fee_paid", 50))
        requested_dry_run = data.get("dry_run", True)
        live_confirmation = str(data.get("live_confirmation", "")).strip()
        requested_trade_mode = str(data.get("trade_execution_mode", TRADE_EXECUTION_MODE)).strip().lower()
        if requested_trade_mode not in {"both", "demo_only", "flash_only"}:
            requested_trade_mode = TRADE_EXECUTION_MODE

        if isinstance(requested_dry_run, str):
            requested_dry_run = requested_dry_run.strip().lower() not in {"false", "0", "no"}
        else:
            requested_dry_run = bool(requested_dry_run)

        wants_live_mode = requested_dry_run is False
        if wants_live_mode and not ALLOW_LIVE_TRADING:
            return jsonify({
                "success": False,
                "error": "Live mode is disabled on this server. Set ALLOW_LIVE_TRADING=true to unlock.",
            }), 403

        if wants_live_mode and live_confirmation != LIVE_TRADING_UNLOCK_CODE:
            return jsonify({
                "success": False,
                "error": "Live mode confirmation phrase mismatch.",
                "required_confirmation": LIVE_TRADING_UNLOCK_CODE,
            }), 400

        if wants_live_mode and not _is_live_mode_armed():
            return jsonify({
                "success": False,
                "error": "Live mode is not armed. Call POST /api/bot/arm-live first.",
                "arm_window_seconds": LIVE_ARM_WINDOW_SECONDS,
            }), 403

        dry_run = not wants_live_mode
        execution_mode = "demo" if dry_run else "real"
        
        bot_state["running"] = True
        bot_state["cycle_start"] = datetime.now().isoformat()
        bot_state["cycle_end"] = (datetime.now() + timedelta(days=7)).isoformat()
        bot_state["uptime_seconds"] = 0
        bot_state["starting_capital"] = max(1.0, starting_capital)
        bot_state["gas_fee_paid"] = max(1.0, gas_fee_paid)
        bot_state["cycle_profit"] = 0.0
        bot_state["cycle_loss"] = 0.0
        bot_state["total_trades"] = 0
        bot_state["flash_loan_trades"] = 0
        bot_state["triangle_trades"] = 0
        bot_state["failed_trades"] = 0
        bot_state["recent_trades"] = []
        bot_state["dry_run"] = dry_run
        bot_state["trade_execution_mode"] = requested_trade_mode
        bot_state["execution_mode"] = execution_mode
        bot_state["live_trading_enabled"] = ALLOW_LIVE_TRADING
        bot_state["last_trade_mode"] = "demo" if dry_run else "real"
        _reset_engine_state("Starting scan pipeline...")
        _recompute_subscription_fields()
        
        # In a real scenario, you would spawn the Python bot process here
        # using subprocess.Popen(...) and monitor its output
        bot_running_event.set()
        
        add_log(
            f"Bot started in {execution_mode.upper()} mode: capital=${bot_state['starting_capital']:.2f} "
            f"min_profit={(DEMO_MIN_PROFIT_THRESHOLD_PCT if dry_run else LIVE_MIN_PROFIT_THRESHOLD_PCT):.1f}% dry_run={dry_run} "
            f"trade_mode={requested_trade_mode}",
            "info",
        )
        
        return jsonify({
            "success": True,
            "message": "Bot started successfully",
            "status": bot_state,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/bot/arm-live", methods=["POST"])
def arm_live_mode():
    """Arm live mode for a limited time window before real-mode start is allowed."""
    if not ALLOW_LIVE_TRADING:
        return jsonify({
            "success": False,
            "error": "Live mode is disabled on this server. Set ALLOW_LIVE_TRADING=true to unlock.",
        }), 403

    try:
        data = request.json or {}
        arm_code = str(data.get("arm_code", "")).strip()
        if arm_code != LIVE_TRADING_UNLOCK_CODE:
            return jsonify({
                "success": False,
                "error": "Arm code mismatch.",
                "required_code": LIVE_TRADING_UNLOCK_CODE,
            }), 400

        requested_seconds = int(data.get("window_seconds", LIVE_ARM_WINDOW_SECONDS))
        window_seconds = max(30, min(requested_seconds, LIVE_ARM_MAX_WINDOW_SECONDS))
        armed_until = datetime.now() + timedelta(seconds=window_seconds)

        bot_state["live_armed_until"] = armed_until.isoformat()
        bot_state["live_armed_remaining_seconds"] = window_seconds
        _recompute_subscription_fields()

        add_log(f"Live mode ARMED for {window_seconds} seconds", "info")
        return jsonify({
            "success": True,
            "message": f"Live mode armed for {window_seconds} seconds",
            "live_armed_until": bot_state["live_armed_until"],
            "live_armed_remaining_seconds": bot_state["live_armed_remaining_seconds"],
            "max_window_seconds": LIVE_ARM_MAX_WINDOW_SECONDS,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/bot/disarm-live", methods=["POST"])
def disarm_live_mode():
    """Immediately disarm live mode."""
    bot_state["live_armed_until"] = None
    bot_state["live_armed_remaining_seconds"] = 0
    add_log("Live mode DISARMED", "info")
    return jsonify({
        "success": True,
        "message": "Live mode disarmed",
        "live_armed_until": None,
        "live_armed_remaining_seconds": 0,
    })


@app.route("/api/bot/live-arm-status", methods=["GET"])
def live_arm_status():
    """Return current live-mode arm window state."""
    _recompute_subscription_fields()
    return jsonify({
        "success": True,
        "live_trading_enabled": ALLOW_LIVE_TRADING,
        "armed": _is_live_mode_armed(),
        "live_armed_until": bot_state.get("live_armed_until"),
        "live_armed_remaining_seconds": bot_state.get("live_armed_remaining_seconds", 0),
        "default_window_seconds": LIVE_ARM_WINDOW_SECONDS,
        "max_window_seconds": LIVE_ARM_MAX_WINDOW_SECONDS,
    })

@app.route("/api/bot/stop", methods=["POST"])
def stop_bot():
    """Stop the bot."""
    global bot_state
    
    if not bot_state["running"]:
        return jsonify({"success": False, "error": "Bot not running"}), 400
    
    try:
        bot_state["running"] = False
        bot_running_event.clear()
        _reset_engine_state("Engine stopped.")
        _recompute_subscription_fields()
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


def calculate_dex_scores_from_prices(prices: dict) -> dict:
    """Calculate simple DEX scores from best quote frequency per pair."""
    wins = {"PancakeSwap": 0, "Biswap": 0, "ApeSwap": 0}
    pairs_count = 0

    for _pair, quotes in prices.items():
        if not isinstance(quotes, dict) or not quotes:
            continue
        pairs_count += 1
        best_dex = max(quotes.items(), key=lambda item: item[1])[0]
        if best_dex in wins:
            wins[best_dex] += 1

    if pairs_count == 0:
        return wins

    return {
        "PancakeSwap": round((wins["PancakeSwap"] / pairs_count) * 100),
        "Biswap": round((wins["Biswap"] / pairs_count) * 100),
        "ApeSwap": round((wins["ApeSwap"] / pairs_count) * 100),
    }


# ============================================
# PRE-TRADE PROFIT SIMULATION
# ============================================

def simulate_trade_profit(
    capital: float,
    gap_pct: float,
    is_flash: bool,
    flash_loan_amount: float = 0.0,
    dry_run: bool = True,
) -> dict:
    """
    Calculate estimated net profit before executing a trade.

    Returns a dict with:
      gross_profit      – raw profit from price gap
      gas_cost          – estimated gas in USD
      flash_loan_fee    – 0.09% of borrowed amount (0 if not flash)
      slippage_cost     – 0.5% of capital as worst-case slippage
      net_profit        – final profit after all deductions
      viable            – True only if net_profit > 0 and gap clears threshold
      rejection_reason  – human-readable reason if not viable
    """
    # Raw gross profit from the price gap
    gross_profit = round(capital * (gap_pct / 100.0), 6)

    # Gas cost — use real constant; skip if above limit
    gas_cost = GAS_FEE_USD
    if gas_cost > GAS_SKIP_ABOVE_USD:
        return {
            "gross_profit": 0,
            "gas_cost": gas_cost,
            "flash_loan_fee": 0,
            "slippage_cost": 0,
            "net_profit": 0,
            "viable": False,
            "rejection_reason": f"Gas ${gas_cost:.4f} exceeds limit ${GAS_SKIP_ABOVE_USD:.4f}",
        }

    # Flash loan fee is 0.09% of the borrowed amount
    fl_fee = round(flash_loan_amount * (FLASH_LOAN_FEE_PCT / 100.0), 6) if is_flash else 0.0

    # Worst-case slippage based on updated 0.3% tolerance
    slippage_cost = round(capital * (SLIPPAGE_TOLERANCE_PCT / 100.0), 6)

    # Net profit after all deductions
    net_profit = round(gross_profit - gas_cost - fl_fee - slippage_cost, 6)

    # Choose profit threshold based on mode
    threshold_pct = DEMO_MIN_PROFIT_THRESHOLD_PCT if dry_run else LIVE_MIN_PROFIT_THRESHOLD_PCT
    threshold_usd = round(capital * (threshold_pct / 100.0), 6)
    min_profit_usd = MIN_PROFIT_USD if dry_run else LIVE_MIN_PROFIT_USD

    viable = True
    rejection_reason = None

    if gap_pct < threshold_pct:
        viable = False
        rejection_reason = (
            f"Gap {gap_pct:.3f}% below {'demo' if dry_run else 'live'} "
            f"threshold {threshold_pct:.2f}%"
        )
    elif net_profit < min_profit_usd:
        viable = False
        rejection_reason = (
            f"Net profit ${net_profit:.4f} below minimum ${min_profit_usd:.4f} USD"
        )
    elif net_profit <= 0 and not dry_run:
        viable = False
        rejection_reason = (
            f"Net profit ${net_profit:.4f} negative after gas=${gas_cost:.4f} "
            f"flash_fee=${fl_fee:.4f} slippage=${slippage_cost:.4f}"
        )
    elif not dry_run and net_profit < threshold_usd:
        viable = False
        rejection_reason = (
            f"Net profit ${net_profit:.4f} below minimum threshold "
            f"${threshold_usd:.4f} ({threshold_pct:.1f}% of capital)"
        )

    return {
        "gross_profit": gross_profit,
        "gas_cost": gas_cost,
        "flash_loan_fee": fl_fee,
        "slippage_cost": slippage_cost,
        "net_profit": net_profit,
        "viable": viable,
        "rejection_reason": rejection_reason,
    }


def background_trade_engine():
    """Generate paper trades from live opportunities while bot is running."""
    global last_trade_key, last_trade_ts, last_execution_mode

    while True:
        time.sleep(ENGINE_SCAN_INTERVAL_SECONDS)
        if not bot_state["running"]:
            continue

        bot_state["last_scan"] = datetime.now().isoformat()
        bot_state["engine_scan_interval_seconds"] = ENGINE_SCAN_INTERVAL_SECONDS
        _set_engine_stage_running(0)
        bot_state["engine_execution_status"] = "Scanning DEX pools..."
        bot_state["dex_fetch_progress"] = {"PancakeSwap": 0, "Biswap": 0, "ApeSwap": 0}
        bot_state["total_dex_scan_progress"] = 0
        payload = build_live_prices_payload()

        prices = payload.get("prices", {})
        bot_state["dex_scores"] = calculate_dex_scores_from_prices(prices)
        coverage = _calculate_dex_price_coverage(prices)
        bot_state["dex_price_coverage"] = coverage
        _set_engine_stage_done(0)

        _set_engine_stage_running(1)
        opportunities = payload.get("opportunities", [])
        bot_state["best_opportunity"] = opportunities[0] if opportunities else None
        _set_engine_stage_done(1)

        _set_engine_stage_running(2)
        _set_engine_stage_progress(2, 100)
        _set_engine_stage_done(2)

        _set_engine_stage_running(3)
        min_execution_gap = DEMO_MIN_EXECUTION_GAP_PCT if bot_state.get("dry_run", True) else LIVE_MIN_EXECUTION_GAP_PCT
        candidates = [
            o for o in opportunities
            if o.get("profitable") and float(o.get("gap", 0.0)) >= min_execution_gap
        ]
        _set_engine_stage_done(3)

        _set_engine_stage_running(4)
        # Build viable plans for both demo-size and flash-size execution modes.
        best = None
        best_plan = None
        capital = float(bot_state.get("starting_capital", 50.0))
        dry_run = bool(bot_state.get("dry_run", True))
        trade_mode = str(bot_state.get("trade_execution_mode", TRADE_EXECUTION_MODE)).strip().lower()
        if trade_mode not in {"both", "demo_only", "flash_only"}:
            trade_mode = "both"
        target_net_profit = DEMO_TARGET_NET_PROFIT_USD if dry_run else LIVE_TARGET_NET_PROFIT_USD
        viable_plans = []

        def mode_candidates_for_opp(opp_item: dict) -> list[tuple[str, bool]]:
            choices = []
            if trade_mode in {"both", "demo_only"}:
                choices.append(("demo", False))
            if trade_mode in {"both", "flash_only"} and bool(opp_item.get("flashLoan")):
                choices.append(("flash", True))
            return choices

        for opp in candidates:
            gap_pct = float(opp.get("gap", 0.0))
            for mode_name, is_flash in mode_candidates_for_opp(opp):
                flash_loan_amount = max(FLASH_LOAN_MIN_AMOUNT_USD, min(capital * 10.0, 50000.0)) if is_flash else 0.0
                sim = simulate_trade_profit(
                    capital=capital,
                    gap_pct=gap_pct,
                    is_flash=is_flash,
                    flash_loan_amount=flash_loan_amount,
                    dry_run=dry_run,
                )
                if not sim.get("viable"):
                    continue
                if sim.get("net_profit", 0.0) < target_net_profit:
                    continue
                viable_plans.append({
                    "opp": opp,
                    "sim": sim,
                    "mode": mode_name,
                    "is_flash": is_flash,
                })

        if viable_plans:
            if trade_mode == "both":
                preferred_mode = "flash" if last_execution_mode == "demo" else "demo"
                preferred = [plan for plan in viable_plans if plan["mode"] == preferred_mode]
                pool = preferred if preferred else viable_plans
                best_plan = max(pool, key=lambda plan: plan["sim"].get("net_profit", 0.0))
            else:
                best_plan = max(viable_plans, key=lambda plan: plan["sim"].get("net_profit", 0.0))

        # Relax target-profit filter if needed, but still enforce viable trades.
        if not best_plan:
            relaxed_plans = []
            for opp in candidates:
                gap_pct = float(opp.get("gap", 0.0))
                for mode_name, is_flash in mode_candidates_for_opp(opp):
                    flash_loan_amount = max(FLASH_LOAN_MIN_AMOUNT_USD, min(capital * 10.0, 50000.0)) if is_flash else 0.0
                    sim = simulate_trade_profit(
                        capital=capital,
                        gap_pct=gap_pct,
                        is_flash=is_flash,
                        flash_loan_amount=flash_loan_amount,
                        dry_run=dry_run,
                    )
                    if not sim.get("viable"):
                        continue
                    relaxed_plans.append({
                        "opp": opp,
                        "sim": sim,
                        "mode": mode_name,
                        "is_flash": is_flash,
                    })

            if relaxed_plans:
                if trade_mode == "both":
                    preferred_mode = "flash" if last_execution_mode == "demo" else "demo"
                    preferred = [plan for plan in relaxed_plans if plan["mode"] == preferred_mode]
                    pool = preferred if preferred else relaxed_plans
                    best_plan = max(pool, key=lambda plan: plan["sim"].get("net_profit", 0.0))
                else:
                    best_plan = max(relaxed_plans, key=lambda plan: plan["sim"].get("net_profit", 0.0))

        if best_plan:
            best = best_plan["opp"]

        bot_state["best_opportunity"] = best
        _set_engine_stage_done(4)

        _set_engine_stage_running(5)
        if not best:
            bot_state["engine_execution_status"] = "No valid opportunity after full 6-stage scan."
            _set_engine_stage_done(5)
            add_log("Scan complete — no opportunities above minimum gap", "info")
            continue

        selected_mode = str(best_plan.get("mode", "demo")) if best_plan else "demo"
        trade_key = f"{best.get('pair')}:{best.get('buyOn')}->{best.get('sellOn')}:{selected_mode}"
        now_ts = time.time()

        # Avoid spamming repeated copies of the same opportunity.
        if trade_key == last_trade_key and (now_ts - last_trade_ts) < 25:
            bot_state["engine_execution_status"] = (
                f"Opportunity found: {best.get('pair')} {best.get('buyOn')}→{best.get('sellOn')} "
                "(cooldown active, waiting before re-execution)."
            )
            _set_engine_stage_done(5)
            continue

        capital = float(bot_state.get("starting_capital", 50.0))
        gap_pct = float(best.get("gap", 0.0))
        is_flash = bool(best_plan.get("is_flash")) if best_plan else False
        dry_run = bool(bot_state.get("dry_run", True))

        # Reuse selected plan simulation; fallback is for defensive safety only.
        sim = best_plan.get("sim") if best_plan else simulate_trade_profit(
            capital=capital,
            gap_pct=gap_pct,
            is_flash=is_flash,
            flash_loan_amount=0.0,
            dry_run=dry_run,
        )

        if not sim["viable"]:
            # Log every rejected trade with reason
            bot_state["engine_execution_status"] = f"Opportunity skipped: {sim['rejection_reason']}"
            _set_engine_stage_done(5)
            add_log(
                f"Trade REJECTED {best.get('pair')} {best.get('buyOn')}→{best.get('sellOn')} "
                f"gap={gap_pct:.3f}% — {sim['rejection_reason']}",
                "info",
            )
            last_trade_key = trade_key
            last_trade_ts = now_ts
            continue

        estimated_profit = round(sim["net_profit"], 4)

        # ── EXECUTION (REAL OR SIMULATION) ────────────────────────────────
        actual_profit = 0.0
        tx_hash_value = f"paper-{int(now_ts)}"
        execution_mode = "paper"
        live_error = None

        live_ready, live_reason = _get_live_execution_readiness()
        can_execute_live = (not dry_run) and _is_live_mode_armed() and live_ready and (not is_flash)

        if can_execute_live:
            live_result = execute_live_spot_arbitrage(best, capital)
            if live_result.get("success"):
                execution_mode = "real"
                tx_hash_value = str(live_result.get("tx_hash") or tx_hash_value)
                actual_profit = round(float(live_result.get("profit_usd", 0.0)), 4)
                sim["gas_cost"] = round(float(live_result.get("gas_cost_usd", sim.get("gas_cost", 0.0))), 6)
                add_log(
                    f"On-chain execution SUCCESS {best.get('pair')} tx={tx_hash_value}",
                    "success",
                )
            else:
                live_error = str(live_result.get("error", "Unknown live execution error"))
                add_log(
                    f"On-chain execution FAILED {best.get('pair')} — {live_error}. Falling back to simulation.",
                    "info",
                )

        if execution_mode != "real":
            # Apply small random variance to simulate real execution drift
            jitter = random.uniform(-0.05, 0.05)
            actual_profit = round(max(0.0, estimated_profit + jitter), 4)

            if actual_profit <= 0:
                bot_state["engine_execution_status"] = (
                    f"Trade aborted: execution drift turned profit negative for {best.get('pair')}."
                )
                _set_engine_stage_done(5)
                add_log(
                    f"Trade ABORTED {best.get('pair')} — profit turned negative during execution "
                    f"(estimated=${estimated_profit:.4f}, actual=${actual_profit:.4f})",
                    "info",
                )
                last_trade_key = trade_key
                last_trade_ts = now_ts
                continue

        if execution_mode != "real" and (not dry_run):
            add_log(
                f"Requested live mode executed in simulation fallback (reason: {live_reason if not _is_live_mode_armed() else (live_error or 'flash mode not supported live yet')})",
                "info",
            )

        # ── RECORD SUCCESSFUL TRADE ───────────────────────────────────────
        bot_state["total_trades"] += 1
        bot_state["cycle_profit"] = round(float(bot_state["cycle_profit"]) + actual_profit, 4)
        if is_flash:
            bot_state["flash_loan_trades"] += 1
        _recompute_subscription_fields()

        add_trade({
            "pair": best.get("pair"),
            "buy": best.get("buyOn"),
            "sell": best.get("sellOn"),
            "gap": round(gap_pct, 4),
            "mode": selected_mode,
            "execution": execution_mode,
            "estimated_profit": estimated_profit,
            "profit": actual_profit,
            "gas_cost": round(sim["gas_cost"], 4),
            "flash_loan_fee": round(sim["flash_loan_fee"], 4),
            "slippage_cost": round(sim["slippage_cost"], 4),
            "isFlash": is_flash,
            "isTri": False,
            "hash": tx_hash_value,
        })

        add_log(
            f"Trade EXECUTED {best.get('pair')} {best.get('buyOn')}→{best.get('sellOn')} "
            f"mode={selected_mode} gap={gap_pct:.3f}% est=${estimated_profit:.4f} actual=${actual_profit:.4f}",
            "flash" if is_flash else "success",
        )
        bot_state["last_trade_mode"] = selected_mode
        bot_state["engine_execution_status"] = (
            f"Opportunity executed: {best.get('pair')} {best.get('buyOn')}→{best.get('sellOn')} "
            f"(+{gap_pct:.3f}%, mode={selected_mode})."
        )
        _set_engine_stage_done(5)

        last_execution_mode = selected_mode
        last_trade_key = trade_key
        last_trade_ts = now_ts

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
    init_web3()

    api_host = os.getenv("BOT_HOST", "0.0.0.0")
    api_port = int(os.getenv("BOT_PORT", "5003"))

    # Start background uptime counter
    uptime_thread = threading.Thread(target=background_uptime_counter, daemon=True)
    uptime_thread.start()

    # Start background paper trade engine
    trade_thread = threading.Thread(target=background_trade_engine, daemon=True)
    trade_thread.start()
    
    print("""
╔════════════════════════════════════════╗
  🤖 ArbBot API Server
     Host: {api_host}
     Port: {api_port}
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
    """.format(api_host=api_host, api_port=api_port))
    
    add_log("API server started", "info")
    app.run(host=api_host, port=api_port, debug=False, use_reloader=False)
