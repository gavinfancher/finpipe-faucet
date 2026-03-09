import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from aiokafka import AIOKafkaConsumer

from client import client, handle_msg
import producer
from producer import BOOTSTRAP_SERVERS, TOPIC


def normalize(ticker: str) -> str:
    ticker = ticker.upper().strip()
    if not ticker.startswith("A."):
        ticker = f"A.{ticker}"
    return ticker


class ConnectionManager:
    def __init__(self):
        self.connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self.connections.discard(ws)

    async def broadcast(self, data: dict):
        disconnected = set()
        for ws in self.connections:
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.add(ws)
        self.connections -= disconnected


manager = ConnectionManager()
prices: dict[str, dict] = {}


async def kafka_broadcast_loop():
    """Consume from Kafka, update snapshot, and broadcast to all connected WebSocket clients."""
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await producer.start()
    ws_task = asyncio.create_task(client.connect(handle_msg))
    flush_task = asyncio.create_task(producer.flush_loop())
    broadcast_task = asyncio.create_task(kafka_broadcast_loop())
    yield
    await client.close()
    ws_task.cancel()
    flush_task.cancel()
    broadcast_task.cancel()
    try:
        await asyncio.gather(ws_task, flush_task, broadcast_task)
    except asyncio.CancelledError:
        pass
    await producer.stop()


app = FastAPI(lifespan=lifespan)


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
def get_subscriptions():
    return {"subscriptions": sorted(client.scheduled_subs)}


@app.put("/subscriptions/{ticker}")
def add_ticker(ticker: str):
    client.subscribe(normalize(ticker))
    return {"subscriptions": sorted(client.scheduled_subs)}


@app.put("/subscriptions")
def add_tickers(tickers: list[str]):
    for t in tickers:
        client.subscribe(normalize(t))
    return {"subscriptions": sorted(client.scheduled_subs)}


@app.delete("/subscriptions/{ticker}")
def remove_ticker(ticker: str):
    sub = normalize(ticker)
    if sub not in client.scheduled_subs:
        raise HTTPException(status_code=404, detail=f"{ticker!r} not subscribed")
    client.unsubscribe(sub)
    return {"subscriptions": sorted(client.scheduled_subs)}


@app.delete("/subscriptions")
def remove_tickers(tickers: list[str]):
    for t in tickers:
        client.unsubscribe(normalize(t))
    return {"subscriptions": sorted(client.scheduled_subs)}
