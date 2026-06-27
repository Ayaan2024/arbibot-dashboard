import { WebSocket } from 'ws';
import { OrderbookState, OrderbookDiff, TickerSnapshot } from './types.js';

const BINANCE_WS_BASE = 'wss://stream.binance.com:9443/ws';
const SUBSCRIBE = 'SUBSCRIBE';
const PAIRS = [
  'bnbusdt',
  'ethusdt',
  'adausdt',
  'cakeusdt',
  'busdusdt'
];

function parseBookDiff(msg: any): OrderbookDiff | null {
  if (msg.e !== 'depthUpdate' || !msg.s) return null;
  return {
    eventTime: msg.E,
    symbol: msg.s,
    bids: msg.b || [],
    asks: msg.a || []
  };
}

export class BinanceOrderbookBridge {
  private ws: WebSocket | null = null;
  private state = new Map<string, OrderbookState>();
  private callbacks: Array<() => void> = [];

  constructor() {
    PAIRS.forEach(symbol => {
      this.state.set(symbol.toUpperCase(), {
        symbol: symbol.toUpperCase(),
        bids: new Map(),
        asks: new Map(),
        bestBid: '0',
        bestAsk: '0'
      });
    });
  }

  start() {
    this.ws = new WebSocket(BINANCE_WS_BASE);
    this.ws.on('open', () => {
      const params = PAIRS.map(pair => `${pair}@depth@100ms`);
      this.ws?.send(JSON.stringify({ method: SUBSCRIBE, params, id: 1 }));
      console.log('[bridge] subscribed to', params.join(', '));
    });

    this.ws.on('message', (data) => {
      try {
        const msg = JSON.parse(data.toString());
        const diff = parseBookDiff(msg);
        if (diff) {
          this.applyDiff(diff);
          this.emitUpdate();
        }
      } catch (error) {
        console.error('[bridge] parse error', error);
      }
    });

    this.ws.on('close', () => {
      console.warn('[bridge] websocket closed, reconnecting in 2s');
      setTimeout(() => this.start(), 2000);
    });

    this.ws.on('error', (error) => {
      console.error('[bridge] websocket error', error);
    });
  }

  private applyDiff(diff: OrderbookDiff) {
    const symbol = diff.symbol.toUpperCase();
    const state = this.state.get(symbol);
    if (!state) return;

    diff.bids.forEach(([price, qty]) => {
      if (qty === '0' || qty === '0.00000000') state.bids.delete(price);
      else state.bids.set(price, qty);
    });

    diff.asks.forEach(([price, qty]) => {
      if (qty === '0' || qty === '0.00000000') state.asks.delete(price);
      else state.asks.set(price, qty);
    });

    state.bestBid = [...state.bids.keys()].sort((a, b) => parseFloat(b) - parseFloat(a))[0] || '0';
    state.bestAsk = [...state.asks.keys()].sort((a, b) => parseFloat(a) - parseFloat(b))[0] || '0';
    this.state.set(symbol, state);
  }

  getSnapshot() {
    return Array.from(this.state.values()).map(state => ({
      symbol: state.symbol,
      bid: state.bestBid,
      ask: state.bestAsk,
      bidQty: state.bids.get(state.bestBid) ?? '0',
      askQty: state.asks.get(state.bestAsk) ?? '0'
    }));
  }

  onUpdate(callback: () => void) {
    this.callbacks.push(callback);
  }

  private emitUpdate() {
    this.callbacks.forEach(cb => cb());
  }
}
