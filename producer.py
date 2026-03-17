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

import websockets
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONSUMER_URL = os.getenv("CONSUMER_URL", "ws://localhost:9000/stream")

# State mirrored from the consumer
ticks: dict = {}
subscriptions: list[str] = []

# Connected UI browser clients
ui_clients: set[WebSocket] = set()

# Live connection to the consumer
_consumer_ws: websockets.ClientConnection | None = None


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
                async for raw in ws:
                    msg = json.loads(raw)
                    msg_type = msg.get("type")
                    if msg_type == "snapshot":
                        ticks = msg["ticks"]
                    elif msg_type == "tickers":
                        subscriptions = msg["tickers"]
                    elif msg_type == "tick":
                        tick = msg["tick"]
                        ticks[tick["ticker"]] = tick
                    await broadcast_ui(msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("consumer: disconnected (%s), retrying in 3s", e)
            _consumer_ws = None
        await asyncio.sleep(3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_producer())
    yield
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


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


@app.get("/health")
def health():
    return {
        "status": "ok",
        "consumer_connected": _consumer_ws is not None,
        "subscriptions": subscriptions,
        "tick_count": len(ticks),
        "ui_clients": len(ui_clients),
    }
