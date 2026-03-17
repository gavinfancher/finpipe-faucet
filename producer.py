"""
Producer: connects to the consumer and serves data to the UI.

Relays ticks from the consumer to all connected UI browser clients.
Exposes REST endpoints so the UI can manage subscriptions.

Run: uv run uvicorn producer:app --port 8080 --host 0.0.0.0
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

import websockets
import db
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from massive.rest import RESTClient

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONSUMER_URL = os.getenv("CONSUMER_URL", "ws://localhost:9000/stream")

rest = RESTClient(api_key=os.getenv("MASSIVE_API_KEY"), num_pools=20)

# State mirrored from the consumer
ticks: dict = {}
subscriptions: list[str] = []

# Previous day close cache: { "AAPL": 213.49, ... }
prev_closes: dict[str, float] = {}

# Tickers to subscribe on first consumer connect (loaded from DB at startup)
_startup_tickers: list[str] = []

# Connected UI browser clients
ui_clients: set[WebSocket] = set()

# Live connection to the consumer
_consumer_ws: websockets.ClientConnection | None = None


async def fetch_prev_close(ticker: str) -> float | None:
    loop = asyncio.get_event_loop()
    try:
        aggs = await loop.run_in_executor(
            None, partial(rest.get_previous_close_agg, ticker)
        )
        if aggs:
            return aggs[0].close
    except Exception as e:
        logger.warning("prev close fetch failed for %s: %s", ticker, e)
    return None


async def load_prev_closes(tickers: list[str]):
    closes = await asyncio.gather(*[fetch_prev_close(t) for t in tickers])
    for ticker, close in zip(tickers, closes):
        if close is not None:
            prev_closes[ticker] = close
            logger.info("prev close: %s = %.4f", ticker, close)
        else:
            logger.warning("prev close: %s = not found", ticker)
    logger.info("prev closes loaded for %d/%d tickers", sum(v is not None for v in closes), len(tickers))


def enrich_tick(tick: dict) -> dict:
    """Recalculate change/changePct from prev day close and attach prevClose."""
    prev = prev_closes.get(tick["ticker"])
    if prev:
        change = tick["price"] - prev
        tick["change"] = round(change, 4)
        tick["changePct"] = round(change / prev * 100, 4)
        tick["prevClose"] = prev
    return tick


async def broadcast_ui(data: dict):
    dead = set()
    for ws in ui_clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.add(ws)
    ui_clients.difference_update(dead)


async def send_to_consumer(data: dict):
    if _consumer_ws is not None:
        try:
            await _consumer_ws.send(json.dumps(data))
        except Exception as e:
            logger.error("send_to_consumer failed: %s", e)


async def run_producer():
    global _consumer_ws, ticks, subscriptions
    while True:
        try:
            logger.info("consumer: connecting to %s", CONSUMER_URL)
            async with websockets.connect(CONSUMER_URL) as ws:
                _consumer_ws = ws
                logger.info("consumer: connected")
                # Warm startup: subscribe to all tickers from DB
                for ticker in _startup_tickers:
                    await ws.send(json.dumps({"action": "subscribe", "ticker": ticker}))
                async for raw in ws:
                    msg = json.loads(raw)
                    msg_type = msg.get("type")
                    if msg_type == "snapshot":
                        enriched = {k: enrich_tick(v) for k, v in msg["ticks"].items()}
                        ticks = enriched
                        msg["ticks"] = enriched
                    elif msg_type == "tickers":
                        subscriptions = msg["tickers"]
                    elif msg_type == "tick":
                        tick = enrich_tick(msg["tick"])
                        ticks[tick["ticker"]] = tick
                        msg["tick"] = tick
                    await broadcast_ui(msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("consumer: disconnected (%s), retrying in 3s", e)
            _consumer_ws = None
        await asyncio.sleep(3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_tickers
    await db.init()
    _startup_tickers = await db.get_all_tickers()
    logger.info("startup: loaded %d tickers from db", len(_startup_tickers))
    if _startup_tickers:
        await load_prev_closes(_startup_tickers)
    task = asyncio.create_task(run_producer())
    yield
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    await db.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    ui_clients.add(ws)
    logger.info("UI client connected, pool=%d", len(ui_clients))
    try:
        if ticks:
            await ws.send_json({"type": "snapshot", "ticks": ticks})
        await ws.send_json({"type": "tickers", "tickers": subscriptions})
        while True:
            await ws.receive_text()
    except Exception:
        pass
    finally:
        ui_clients.discard(ws)
        logger.info("UI client disconnected, pool=%d", len(ui_clients))


@app.get("/subscriptions")
def get_subscriptions():
    return {"subscriptions": subscriptions}


@app.put("/subscriptions/{ticker}")
async def add_subscription(ticker: str):
    await send_to_consumer({"action": "subscribe", "ticker": ticker})
    return {"status": "subscribe requested", "ticker": ticker.upper()}


@app.delete("/subscriptions/{ticker}")
async def remove_subscription(ticker: str):
    await send_to_consumer({"action": "unsubscribe", "ticker": ticker})
    return {"status": "unsubscribe requested", "ticker": ticker.upper()}


@app.get("/users/{username}/tickers")
async def get_user_tickers(username: str):
    tickers = await db.get_user_tickers(username)
    return {"tickers": tickers}


@app.put("/users/{username}/tickers/{ticker}")
async def add_user_ticker(username: str, ticker: str):
    ticker = ticker.upper()
    tickers = await db.add_user_ticker(username, ticker)
    await send_to_consumer({"action": "subscribe", "ticker": ticker})
    # Fetch prev close for this ticker if we don't have it yet
    if ticker not in prev_closes:
        close = await fetch_prev_close(ticker)
        if close is not None:
            prev_closes[ticker] = close
    return {"tickers": tickers}


@app.delete("/users/{username}/tickers/{ticker}")
async def remove_user_ticker(username: str, ticker: str):
    ticker = ticker.upper()
    tickers = await db.remove_user_ticker(username, ticker)
    # Keep the global subscription active — other users may still want this ticker
    return {"tickers": tickers}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "consumer_connected": _consumer_ws is not None,
        "subscriptions": subscriptions,
        "tick_count": len(ticks),
        "ui_clients": len(ui_clients),
        "prev_closes_cached": len(prev_closes),
    }


@app.get("/debug/prev-closes")
def debug_prev_closes():
    return prev_closes
