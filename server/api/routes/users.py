from fastapi import APIRouter, Depends
from pydantic import BaseModel

import server.auth as auth
import server.db as db
from server.api.deps import get_current_user, get_current_user_flexible
from server.pipeline import state
from server.pipeline.enrichment import fetch_closes
from server.pipeline.relay import send_to_consumer

router = APIRouter()


class TickerPatch(BaseModel):
    add: list[str] = []
    remove: list[str] = []


@router.get("/tickers/list")
async def get_tickers(current_user: str = Depends(get_current_user_flexible)):
    tickers = await db.get_user_tickers(current_user)
    return {"username": current_user, "tickers": tickers}


@router.post("/tickers/{ticker}")
async def add_ticker(ticker: str, current_user: str = Depends(get_current_user)):
    ticker = ticker.upper()
    await db.add_user_ticker(current_user, ticker)
    await send_to_consumer({"action": "subscribe", "ticker": ticker})
    if ticker not in state.prev_closes:
        prev, ytd, close_5d = await fetch_closes(ticker)
        if prev is not None:
            state.prev_closes[ticker] = prev
        if ytd is not None:
            state.closes_ytd[ticker] = ytd
        if close_5d is not None:
            state.closes_5d[ticker] = close_5d
    return {"message": "success"}


@router.delete("/tickers/{ticker}")
async def remove_ticker(ticker: str, current_user: str = Depends(get_current_user)):
    ticker = ticker.upper()
    await db.remove_user_ticker(current_user, ticker)
    return {"message": "success"}


@router.patch("/tickers")
async def patch_tickers(
    body: TickerPatch,
    current_user: str = Depends(get_current_user_flexible),
):
    add = [t.upper() for t in body.add]
    remove = [t.upper() for t in body.remove]
    await db.patch_user_tickers(current_user, add, remove)
    for ticker in add:
        await send_to_consumer({"action": "subscribe", "ticker": ticker})
        if ticker not in state.prev_closes:
            prev, ytd, close_5d = await fetch_closes(ticker)
            if prev is not None:
                state.prev_closes[ticker] = prev
            if ytd is not None:
                state.closes_ytd[ticker] = ytd
            if close_5d is not None:
                state.closes_5d[ticker] = close_5d
    return {"message": "success"}


@router.post("/api-key")
async def generate_api_key(current_user: str = Depends(get_current_user)):
    key = auth.generate_api_key()
    await db.store_api_key(current_user, auth.hash_api_key(key))
    return {"api_key": key, "note": "save this — it will not be shown again"}
