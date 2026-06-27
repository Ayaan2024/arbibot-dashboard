import express from 'express';
import cors from 'cors';
import { BinanceOrderbookBridge } from './orderbook.js';

const app = express();
const port = process.env.PORT ? Number(process.env.PORT) : 4000;
const BINANCE_REST_BASE = 'https://api.binance.com';
const DEFAULT_SYMBOLS = ['BNBUSDT', 'ETHUSDT', 'CAKEUSDT', 'XRPUSDT', 'BUSDUSDT'];

app.use(cors());
app.use(express.json());

const bridge = new BinanceOrderbookBridge();
bridge.start();

let lastSnapshot = bridge.getSnapshot();
bridge.onUpdate(() => {
  lastSnapshot = bridge.getSnapshot();
});

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', updated: Date.now() });
});

app.get('/orderbook', (_req, res) => {
  res.json({ pairs: lastSnapshot });
});

app.get('/gap', (_req, res) => {
  const pairs = lastSnapshot;
  const prices = pairs.reduce((acc, item) => {
    acc[item.symbol] = {
      bid: Number(item.bid),
      ask: Number(item.ask)
    };
    return acc;
  }, {} as Record<string, { bid: number; ask: number }>);

  res.json({ prices });
});

app.get('/proxy/binance/ticker/price', async (req, res) => {
  try {
    const symbols = typeof req.query.symbols === 'string' && req.query.symbols.trim().length > 0
      ? req.query.symbols.split(',').map(symbol => symbol.trim().toUpperCase()).filter(Boolean)
      : DEFAULT_SYMBOLS;

    const response = await fetch(`${BINANCE_REST_BASE}/api/v3/ticker/price?symbols=${encodeURIComponent(JSON.stringify(symbols))}`);
    if (!response.ok) {
      res.status(response.status).json({ error: 'Unable to fetch Binance prices' });
      return;
    }

    const data = await response.json() as Array<{ symbol: string; price: string }>;
    res.json({
      source: 'binance',
      updatedAt: Date.now(),
      prices: data.reduce((acc, item) => {
        acc[item.symbol] = Number(item.price);
        return acc;
      }, {} as Record<string, number>)
    });
  } catch (error) {
    console.error('[proxy] binance price request failed', error);
    res.status(500).json({ error: 'Proxy request failed' });
  }
});

app.get('/proxy/binance/ticker/bookTicker', async (req, res) => {
  try {
    const symbols = typeof req.query.symbols === 'string' && req.query.symbols.trim().length > 0
      ? req.query.symbols.split(',').map(symbol => symbol.trim().toUpperCase()).filter(Boolean)
      : DEFAULT_SYMBOLS;

    const response = await fetch(`${BINANCE_REST_BASE}/api/v3/ticker/bookTicker?symbols=${encodeURIComponent(JSON.stringify(symbols))}`);
    if (!response.ok) {
      res.status(response.status).json({ error: 'Unable to fetch Binance book ticker' });
      return;
    }

    const data = await response.json() as Array<{ symbol: string; bidPrice: string; askPrice: string; bidQty: string; askQty: string }>;
    res.json({
      source: 'binance',
      updatedAt: Date.now(),
      book: data
    });
  } catch (error) {
    console.error('[proxy] binance bookTicker request failed', error);
    res.status(500).json({ error: 'Proxy request failed' });
  }
});

app.listen(port, () => {
  console.log(`[server] backend listening on http://localhost:${port}`);
});
