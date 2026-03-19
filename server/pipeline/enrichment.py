"""
Previous day close fetching and tick enrichment.
"""

import asyncio
import logging
from datetime import date, datetime, timezone

import httpx
import pandas_market_calendars as mcal

from server.config import MASSIVE_API_KEY
from server.pipeline import state

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(
    base_url="https://api.massive.com",
    headers={"Authorization": f"Bearer {MASSIVE_API_KEY}"},
    timeout=10.0,
)

_cal = mcal.get_calendar("NYSE")


def _trading_dates(n_back: int = 5) -> tuple[date, date, date]:
    """Return (prev_trading_day, n_days_ago, ytd_start) using the NYSE calendar."""
    today = date.today()
    ytd_start = date(today.year, 1, 1)
    schedule = _cal.schedule(start_date=str(ytd_start), end_date=str(today))
    trading_days = schedule.index.normalize().date.tolist()
    # Exclude today if market is still open or hasn't settled
    completed = [d for d in trading_days if d < today]
    prev = completed[-1]
    n_ago = completed[-(n_back + 1)] if len(completed) > n_back else completed[0]
    ytd = completed[0]
    return prev, n_ago, ytd


async def _fetch_closes(
    ticker: str, prev_date: date, date_5d: date, ytd_date: date
) -> tuple[float | None, float | None, float | None]:
    """Fetch daily bars for the three specific mcal dates.
    Returns (prev_close, close_5d_ago, ytd_close).
    """
    try:
        r = await _http.get(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{ytd_date}/{prev_date}",
            params={"adjusted": "true", "sort": "asc", "limit": 300},
        )
        r.raise_for_status()
        results = r.json().get("results") or []
        if not results:
            return None, None, None
        bars_by_date = {
            datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc).date(): b["c"]
            for b in results
        }
        return bars_by_date.get(prev_date), bars_by_date.get(date_5d), bars_by_date.get(ytd_date)
    except Exception as e:
        logger.warning("closes fetch failed for %s: %s", ticker, e)
    return None, None, None


async def load_prev_closes(tickers: list[str]):
    prev_date, date_5d, ytd_date = _trading_dates(n_back=5)
    logger.info("fetching closes: prev=%s 5d=%s ytd=%s", prev_date, date_5d, ytd_date)
    results = await asyncio.gather(
        *[_fetch_closes(t, prev_date, date_5d, ytd_date) for t in tickers]
    )
    loaded = 0
    for ticker, (prev, close_5d, ytd) in zip(tickers, results):
        if prev is not None:
            state.prev_closes[ticker] = prev
            loaded += 1
            logger.info("prev close: %s = %.4f", ticker, prev)
        else:
            logger.warning("prev close: %s = not found", ticker)
        if close_5d is not None:
            state.closes_5d[ticker] = close_5d
        if ytd is not None:
            state.closes_ytd[ticker] = ytd
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
