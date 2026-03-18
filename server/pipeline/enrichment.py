"""
Previous day close fetching and tick enrichment.
"""

import asyncio
import logging
from datetime import date, datetime, timezone

import httpx

from server.config import MASSIVE_API_KEY
from server.pipeline import state

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(
    base_url="https://api.massive.com",
    headers={"Authorization": f"Bearer {MASSIVE_API_KEY}"},
    timeout=10.0,
)


async def fetch_prev_close(ticker: str) -> float | None:
    prev, _, _ = await fetch_closes(ticker)
    return prev


async def fetch_closes(ticker: str) -> tuple[float | None, float | None, float | None]:
    """Fetch daily bars from Jan 1 to today.
    Returns (prev_close, ytd_close, close_5d_ago).
    """
    today = date.today()
    jan1 = date(today.year, 1, 1)
    try:
        r = await _http.get(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{jan1}/{today}",
            params={"adjusted": "true", "sort": "asc", "limit": 300},
        )
        r.raise_for_status()
        results = r.json().get("results") or []
        if not results:
            return None, None, None
        # Drop today's partial bar if the last bar's date is today
        last_bar_date = datetime.fromtimestamp(results[-1]["t"] / 1000, tz=timezone.utc).date()
        bars = results[:-1] if last_bar_date == today else results
        prev     = bars[-1]["c"] if bars else None
        ytd      = bars[0]["c"]  if bars else None
        close_5d = bars[-6]["c"] if len(bars) >= 6 else None
        return prev, ytd, close_5d
    except Exception as e:
        logger.warning("closes fetch failed for %s: %s", ticker, e)
    return None, None, None


async def load_prev_closes(tickers: list[str]):
    results = await asyncio.gather(*[fetch_closes(t) for t in tickers])
    loaded = 0
    for ticker, (prev, ytd, close_5d) in zip(tickers, results):
        if prev is not None:
            state.prev_closes[ticker] = prev
            loaded += 1
            logger.info("prev close: %s = %.4f", ticker, prev)
        else:
            logger.warning("prev close: %s = not found", ticker)
        if ytd is not None:
            state.closes_ytd[ticker] = ytd
        if close_5d is not None:
            state.closes_5d[ticker] = close_5d
    logger.info("prev closes loaded for %d/%d tickers", loaded, len(tickers))


def enrich_tick(tick: dict) -> dict:
    """Recalculate change/changePct/perf from reference closes."""
    price = tick["price"]
    ticker = tick["ticker"]

    prev = state.prev_closes.get(ticker)
    if prev:
        change = price - prev
        tick["change"] = round(change, 4)
        tick["changePct"] = round(change / prev * 100, 4)
        tick["prevClose"] = prev

    close_5d = state.closes_5d.get(ticker)
    if close_5d:
        tick["perf5d"] = round((price - close_5d) / close_5d * 100, 4)

    close_ytd = state.closes_ytd.get(ticker)
    if close_ytd:
        tick["perfYtd"] = round((price - close_ytd) / close_ytd * 100, 4)

    return tick
