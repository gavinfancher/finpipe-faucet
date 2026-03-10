import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import redis.asyncio as aioredis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from aiokafka import AIOKafkaConsumer

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger(__name__)

BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
TOPIC = os.getenv("KAFKA_TOPIC", "stocks-aggs")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
MAX_SUBS = int(os.getenv("MAX_SUBS", "100"))
RECONCILE_INTERVAL = int(os.getenv("RECONCILE_INTERVAL", "30"))  # seconds

# File that stores the ticker list — survives Redis wipes and full stack restarts
TICKERS_FILE = Path(os.getenv("TICKERS_FILE", "/data/tickers.json"))

WORKER_URLS = [
    f"http://{addr}"
    for addr in os.getenv(
        "WORKER_ADDRS", "localhost:8001,localhost:8002,localhost:8003"
    ).split(",")
]

# Redis key: hash of {ticker -> worker_url}
TICKER_WORKER_KEY = "finpipe:ticker_worker"

redis_client: aioredis.Redis | None = None
http_client: httpx.AsyncClient | None = None


# ── Ticker file persistence ──────────────────────────────────────────────────

def _load_tickers_file() -> list[str]:
    try:
        return json.loads(TICKERS_FILE.read_text())
    except FileNotFoundError:
        return []


async def _flush_tickers_file() -> None:
    """Read current tickers from Redis and write to disk."""
    mapping = await redis_client.hgetall(TICKER_WORKER_KEY)
    tickers = sorted(k.decode() for k in mapping.keys())
    TICKERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TICKERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(tickers, indent=2))
    tmp.replace(TICKERS_FILE)


# ── Startup restore ──────────────────────────────────────────────────────────

async def restore_from_file() -> None:
    """
    On startup:
    - Redis intact (normal restart): nothing to do, Redis is already correct.
    - Redis empty (wiped): reload from file, re-subscribe everything, rebuild Redis.
    """
    existing = await redis_client.hgetall(TICKER_WORKER_KEY)
    if existing:
        logger.info("restore: Redis has %d subscriptions, nothing to do", len(existing))
        return

    tickers = _load_tickers_file()
    if not tickers:
        logger.info("restore: no tickers file found, starting fresh")
        return

    logger.info("restore: Redis empty, reloading %d tickers from %s", len(tickers), TICKERS_FILE)
    for ticker in tickers:
        try:
            worker_url = await pick_worker()
            resp = await http_client.put(f"{worker_url}/internal/subscribe/{ticker}")
            resp.raise_for_status()
            await redis_client.hset(TICKER_WORKER_KEY, ticker, worker_url)
        except Exception as e:
            logger.warning("restore: failed to re-subscribe %s: %s", ticker, e)

    logger.info("restore: done")


# ── Worker helpers ───────────────────────────────────────────────────────────

def normalize(ticker: str) -> str:
    ticker = ticker.upper().strip()
    if not ticker.startswith("A."):
        ticker = f"A.{ticker}"
    return ticker


async def worker_counts() -> dict[str, int]:
    mapping = await redis_client.hgetall(TICKER_WORKER_KEY)
    counts = {url: 0 for url in WORKER_URLS}
    for worker_bytes in mapping.values():
        url = worker_bytes.decode()
        if url in counts:
            counts[url] += 1
    return counts


async def pick_worker() -> str:
    counts = await worker_counts()
    eligible = {url: n for url, n in counts.items() if n < MAX_SUBS}
    if not eligible:
        raise HTTPException(
            status_code=503,
            detail=f"All workers are at capacity ({MAX_SUBS} subs each).",
        )
    return min(eligible, key=eligible.get)


# ── WebSocket broadcast ──────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self.connections.discard(ws)

    async def broadcast(self, data: dict):
        dead = set()
        for ws in self.connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        self.connections -= dead


manager = ConnectionManager()
prices: dict[str, dict] = {}


async def kafka_broadcast_loop():
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id="ws-broadcast",
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="latest",
    )
    await consumer.start()
    try:
        async for msg in consumer:
            prices[msg.value["symbol"]] = msg.value
            if manager.connections:
                await manager.broadcast(msg.value)
    finally:
        await consumer.stop()


# ── Reconciliation loop ──────────────────────────────────────────────────────

async def reconcile_workers():
    """
    Periodically compare Redis assignments against each worker's live subs and
    re-push any that are missing (e.g. after a worker restart).
    """
    while True:
        await asyncio.sleep(RECONCILE_INTERVAL)
        try:
            mapping = await redis_client.hgetall(TICKER_WORKER_KEY)
            expected: dict[str, list[str]] = {url: [] for url in WORKER_URLS}
            for ticker_bytes, worker_bytes in mapping.items():
                url = worker_bytes.decode()
                if url in expected:
                    expected[url].append(ticker_bytes.decode())

            for worker_url, tickers in expected.items():
                if not tickers:
                    continue
                try:
                    resp = await http_client.get(f"{worker_url}/internal/status")
                    resp.raise_for_status()
                    live = set(resp.json().get("tickers", []))
                except Exception as e:
                    logger.warning("reconcile: could not reach %s: %s", worker_url, e)
                    continue

                for ticker in tickers:
                    if ticker not in live:
                        try:
                            await http_client.put(f"{worker_url}/internal/subscribe/{ticker}")
                            logger.info("reconcile: re-subscribed %s on %s", ticker, worker_url)
                        except Exception as e:
                            logger.warning("reconcile: failed to re-subscribe %s: %s", ticker, e)
        except Exception as e:
            logger.warning("reconcile loop error: %s", e)


# ── App lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, http_client
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=False)
    http_client = httpx.AsyncClient(timeout=5.0)
    await restore_from_file()
    broadcast_task = asyncio.create_task(kafka_broadcast_loop())
    reconcile_task = asyncio.create_task(reconcile_workers())
    yield
    broadcast_task.cancel()
    reconcile_task.cancel()
    try:
        await asyncio.gather(broadcast_task, reconcile_task)
    except asyncio.CancelledError:
        pass
    await redis_client.aclose()
    await http_client.aclose()


app = FastAPI(lifespan=lifespan)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        for data in prices.values():
            await ws.send_json(data)
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


@app.get("/subscriptions")
async def get_subscriptions():
    mapping = await redis_client.hgetall(TICKER_WORKER_KEY)
    return {"subscriptions": sorted(k.decode() for k in mapping.keys())}


@app.put("/subscriptions/{ticker}")
async def add_ticker(ticker: str):
    sub = normalize(ticker)
    existing = await redis_client.hget(TICKER_WORKER_KEY, sub)
    if not existing:
        worker_url = await pick_worker()
        resp = await http_client.put(f"{worker_url}/internal/subscribe/{sub}")
        resp.raise_for_status()
        await redis_client.hset(TICKER_WORKER_KEY, sub, worker_url)
        await _flush_tickers_file()
    mapping = await redis_client.hgetall(TICKER_WORKER_KEY)
    return {"subscriptions": sorted(k.decode() for k in mapping.keys())}


@app.put("/subscriptions")
async def add_tickers(tickers: list[str]):
    for t in tickers:
        sub = normalize(t)
        existing = await redis_client.hget(TICKER_WORKER_KEY, sub)
        if not existing:
            worker_url = await pick_worker()
            resp = await http_client.put(f"{worker_url}/internal/subscribe/{sub}")
            resp.raise_for_status()
            await redis_client.hset(TICKER_WORKER_KEY, sub, worker_url)
    await _flush_tickers_file()
    mapping = await redis_client.hgetall(TICKER_WORKER_KEY)
    return {"subscriptions": sorted(k.decode() for k in mapping.keys())}


@app.delete("/subscriptions/{ticker}")
async def remove_ticker(ticker: str):
    sub = normalize(ticker)
    worker_url_bytes = await redis_client.hget(TICKER_WORKER_KEY, sub)
    if not worker_url_bytes:
        raise HTTPException(status_code=404, detail=f"{ticker!r} not subscribed")
    await http_client.delete(f"{worker_url_bytes.decode()}/internal/subscribe/{sub}")
    await redis_client.hdel(TICKER_WORKER_KEY, sub)
    await _flush_tickers_file()
    mapping = await redis_client.hgetall(TICKER_WORKER_KEY)
    return {"subscriptions": sorted(k.decode() for k in mapping.keys())}


@app.delete("/subscriptions")
async def remove_tickers(tickers: list[str]):
    for t in tickers:
        sub = normalize(t)
        worker_url_bytes = await redis_client.hget(TICKER_WORKER_KEY, sub)
        if not worker_url_bytes:
            continue
        await http_client.delete(f"{worker_url_bytes.decode()}/internal/subscribe/{sub}")
        await redis_client.hdel(TICKER_WORKER_KEY, sub)
    await _flush_tickers_file()
    mapping = await redis_client.hgetall(TICKER_WORKER_KEY)
    return {"subscriptions": sorted(k.decode() for k in mapping.keys())}


@app.get("/workers")
async def get_workers():
    mapping = await redis_client.hgetall(TICKER_WORKER_KEY)
    tickers_by_worker: dict[str, list[str]] = {url: [] for url in WORKER_URLS}
    for ticker_bytes, worker_bytes in mapping.items():
        url = worker_bytes.decode()
        if url in tickers_by_worker:
            tickers_by_worker[url].append(ticker_bytes.decode())
    return {
        url: {
            "count": len(tickers),
            "max_subs": MAX_SUBS,
            "tickers": sorted(tickers),
        }
        for url, tickers in tickers_by_worker.items()
    }
