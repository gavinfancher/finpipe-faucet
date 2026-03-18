"""
Previous day close fetching and tick enrichment.
"""

import asyncio
import logging
from functools import partial

from massive.rest import RESTClient

from server.config import MASSIVE_API_KEY
from server.pipeline import state

logger = logging.getLogger(__name__)

rest = RESTClient(api_key=MASSIVE_API_KEY, num_pools=20)


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
            state.prev_closes[ticker] = close
            logger.info("prev close: %s = %.4f", ticker, close)
        else:
            logger.warning("prev close: %s = not found", ticker)
    logger.info(
        "prev closes loaded for %d/%d tickers",
        sum(v is not None for v in closes),
        len(tickers),
    )


def enrich_tick(tick: dict) -> dict:
    """Recalculate change/changePct from prev day close."""
    prev = state.prev_closes.get(tick["ticker"])
    if prev:
        change = tick["price"] - prev
        tick["change"] = round(change, 4)
        tick["changePct"] = round(change / prev * 100, 4)
        tick["prevClose"] = prev
    return tick
