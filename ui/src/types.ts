export interface StockTick {
  ticker: string;
  price: number;
  open: number;
  change: number;
  changePct: number;
  prevClose?: number;
  perf5d?: number;
  perfYtd?: number;
  timestamp: number;
  volume?: number;
}

export interface SnapshotMessage {
  type: "snapshot";
  ticks: Record<string, StockTick>;
}

export interface TickersMessage {
  type: "tickers";
  tickers: string[];
}

export interface TickMessage {
  type: "tick";
  tick: StockTick;
}

export type ServerMessage = SnapshotMessage | TickersMessage | TickMessage;
