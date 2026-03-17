import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from massive import WebSocketClient
from massive.websocket.models import Feed, Market, EquityAgg

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = WebSocketClient(
    api_key=os.getenv("MASSIVE_API_KEY"),
    feed=Feed.Delayed,
    market=Market.Stocks,
)

ticks: dict = {}
subscriptions: set[str] = set()
connections: set[WebSocket] = set()


def normalize(ticker: str) -> str:
    ticker = ticker.upper().strip()
    if not ticker.startswith("A."):
        ticker = f"A.{ticker}"
    return ticker


async def broadcast(data: dict):
    dead = set()
    for ws in connections:
        try:
            await ws.send_json(data)
        except Exception:
            dead.add(ws)
    connections.difference_update(dead)


async def handle_msg(msgs):
    logger.info("handle_msg called with %d messages", len(msgs))
    for m in msgs:
        logger.info("  msg type=%s", type(m).__name__)
        if not isinstance(m, EquityAgg):
            continue
        if m.symbol is None or m.close is None:
            continue
        display_ticker = m.symbol.removeprefix("A.")
        open_price = m.official_open_price or m.open or m.close
        change = m.close - open_price
        change_pct = (change / open_price * 100) if open_price else 0.0
        tick = {
            "ticker": display_ticker,
            "price": m.close,
            "open": open_price,
            "change": change,
            "changePct": change_pct,
            "timestamp": m.end_timestamp or 0,
            "volume": m.accumulated_volume or 0,
        }
        ticks[display_ticker] = tick
        logger.info("broadcasting tick: %s price=%s to %d clients", display_ticker, tick["price"], len(connections))
        await broadcast({"type": "tick", "tick": tick})


DEFAULT_TICKERS = ["A.SPY"]


async def run_massive():
    while True:
        try:
            logger.info("massive: connecting...")
            await client.connect(handle_msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("massive: disconnected (%s), retrying in 5s", e)
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for t in DEFAULT_TICKERS:
        subscriptions.add(t)
        client.subscribe(t)
    task = asyncio.create_task(run_massive())
    yield
    await client.close()
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


@app.websocket("/")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    connections.add(ws)
    logger.info("WS connected, pool=%d", len(connections))
    try:
        if ticks:
            await ws.send_json({"type": "snapshot", "ticks": ticks})
        display_subs = sorted(s.removeprefix("A.") for s in subscriptions)
        await ws.send_json({"type": "tickers", "tickers": display_subs})
        while True:
            await ws.receive_text()
    except Exception:
        pass
    finally:
        connections.discard(ws)
        logger.info("WS closed, pool=%d", len(connections))


@app.get("/subscriptions")
def get_subscriptions():
    return {"subscriptions": sorted(subscriptions)}


@app.put("/subscriptions/{ticker}")
async def add_subscription(ticker: str):
    sub = normalize(ticker)
    if sub not in subscriptions:
        subscriptions.add(sub)
        client.subscribe(sub)
        display_subs = sorted(s.removeprefix("A.") for s in subscriptions)
        await broadcast({"type": "tickers", "tickers": display_subs})
    return {"subscriptions": sorted(subscriptions)}


@app.delete("/subscriptions/{ticker}")
async def remove_subscription(ticker: str):
    sub = normalize(ticker)
    subscriptions.discard(sub)
    ticks.pop(sub.removeprefix("A."), None)
    client.unsubscribe(sub)
    display_subs = sorted(s.removeprefix("A.") for s in subscriptions)
    await broadcast({"type": "tickers", "tickers": display_subs})
    return {"subscriptions": sorted(subscriptions)}
