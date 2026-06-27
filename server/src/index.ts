import express from 'express';
import cors from 'cors';
import { BinanceOrderbookBridge } from './orderbook.js';

const app = express();
const port = process.env.PORT ? Number(process.env.PORT) : 4000;

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

app.listen(port, () => {
  console.log(`[server] backend listening on http://localhost:${port}`);
});
