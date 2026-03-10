import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

import producer
from client import client, handle_msg

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger(__name__)

WORKER_ID = os.getenv("WORKER_ID", "worker-1")
MAX_SUBS = int(os.getenv("MAX_SUBS", "100"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await producer.start()
    ws_task = asyncio.create_task(client.connect(handle_msg))
    flush_task = asyncio.create_task(producer.flush_loop())
    yield
    await client.close()
    ws_task.cancel()
    flush_task.cancel()
    try:
        await asyncio.gather(ws_task, flush_task)
    except asyncio.CancelledError:
        pass
    await producer.stop()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "worker_id": WORKER_ID}


@app.get("/internal/status")
def status():
    return {
        "worker_id": WORKER_ID,
        "count": len(client.scheduled_subs),
        "max_subs": MAX_SUBS,
        "tickers": sorted(client.scheduled_subs),
    }


@app.put("/internal/subscribe/{ticker}")
def subscribe(ticker: str):
    client.subscribe(ticker)
    return {
        "worker_id": WORKER_ID,
        "ticker": ticker,
        "count": len(client.scheduled_subs),
    }


@app.delete("/internal/subscribe/{ticker}")
def unsubscribe(ticker: str):
    client.unsubscribe(ticker)
    return {
        "worker_id": WORKER_ID,
        "ticker": ticker,
        "count": len(client.scheduled_subs),
    }


if __name__ == "__main__":
    port = int(os.getenv("WORKER_PORT", "8001"))
    uvicorn.run("worker_app:app", host="0.0.0.0", port=port, log_config=None)
