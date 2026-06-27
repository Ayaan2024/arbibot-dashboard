/**
 * API client for the ArbBot Flask backend.
 * This module provides functions to communicate with the bot API.
 */

const API_BASE: string =
  (import.meta as any).env?.VITE_API_URL ||
  (typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:5003`
    : "http://127.0.0.1:5003");

export const API = {
  // Status endpoints
  async getStatus() {
    const res = await fetch(`${API_BASE}/api/status`);
    return res.json();
  },

  async getHealth() {
    const res = await fetch(`${API_BASE}/api/health`);
    return res.json();
  },

  // Bot control
  async startBot(startingCapital = 50, dryRun = false, options = {}) {
    const res = await fetch(`${API_BASE}/api/bot/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ starting_capital: startingCapital, dry_run: dryRun, ...options }),
    });
    return res.json();
  },

  async stopBot() {
    const res = await fetch(`${API_BASE}/api/bot/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    return res.json();
  },

  // Trades and logs
  async getTrades(limit = 20) {
    const res = await fetch(`${API_BASE}/api/trades?limit=${limit}`);
    return res.json();
  },

  async getLogs(limit = 50) {
    const res = await fetch(`${API_BASE}/api/logs?limit=${limit}`);
    return res.json();
  },

  async getLiveScan() {
    const res = await fetch(`${API_BASE}/api/live/scan`);
    return res.json();
  },

  // Wallet
  async connectWallet(walletAddress, signature = null) {
    const res = await fetch(`${API_BASE}/api/wallet/connect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ address: walletAddress, signature }),
    });
    return res.json();
  },

  async disconnectWallet() {
    const res = await fetch(`${API_BASE}/api/wallet/disconnect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    return res.json();
  },

  async getCurrentWallet() {
    const res = await fetch(`${API_BASE}/api/wallet/current`);
    return res.json();
  },

  async withdrawProfits(amount, destinationAddress) {
    const res = await fetch(`${API_BASE}/api/withdraw`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount, destination_address: destinationAddress }),
    });
    return res.json();
  },

  // Trade simulation
  async simulateTrade(buyDex, sellDex, tokenIn, tokenOut, amount) {
    const res = await fetch(`${API_BASE}/api/trade/simulate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        buy_dex: buyDex,
        sell_dex: sellDex,
        token_in: tokenIn,
        token_out: tokenOut,
        amount,
      }),
    });
    return res.json();
  },
};

export default API;
