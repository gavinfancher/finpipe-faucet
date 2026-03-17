# finpipe-stream

Real-time equity price streaming. Connects to the Massive WebSocket feed and serves live tick data to a browser UI.

## Architecture

```
Massive API → consumer (port 9000) → producer (port 8080) → UI (port 5173)
```

- **consumer** — subscribes to Massive, streams ticks to the producer
- **producer** — relays ticks to browser clients, exposes REST API for managing subscriptions
- **ui** — React + Vite dashboard showing live prices, change, and volume

## Setup

```bash
cp .env.example .env
# add your MASSIVE_API_KEY to .env
uv sync
cd ui && npm install
```

## Run

```bash
uv run python main.py
```

Then open `http://localhost:5173`.

## Subscriptions API

```
GET    /subscriptions            list active tickers
PUT    /subscriptions/{ticker}   add ticker
DELETE /subscriptions/{ticker}   remove ticker
```
