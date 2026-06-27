export interface TickerSnapshot {
  symbol: string;
  bid: string;
  ask: string;
  bidQty: string;
  askQty: string;
  lastUpdateId: number;
}

export interface OrderbookDiff {
  eventTime: number;
  symbol: string;
  bids: [string, string][];
  asks: [string, string][];
}

export interface OrderbookState {
  symbol: string;
  bids: Map<string, string>;
  asks: Map<string, string>;
  bestBid: string;
  bestAsk: string;
}
