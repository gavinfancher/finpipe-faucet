from dataclasses import dataclass, asdict
from typing import Optional

from massive.websocket.models.models import EquityAgg


@dataclass
class EnrichedAgg:
    symbol: str
    close: float
    open: float
    high: float
    low: float
    volume: float
    vwap: Optional[float]
    # official_open_price is today's day-open (field "op" in the feed).
    # For previous-day close/open you'd need a REST lookup to backfill on startup.
    official_open_price: Optional[float]
    pct_change_from_open: Optional[float]  # (close - day_open) / day_open * 100
    timestamp_ms: Optional[int]

    def to_dict(self) -> dict:
        return asdict(self)


def enrich(agg: EquityAgg) -> Optional[EnrichedAgg]:
    if not agg.symbol or agg.close is None:
        return None

    pct_change = None
    if agg.official_open_price:
        pct_change = round(
            (agg.close - agg.official_open_price) / agg.official_open_price * 100, 4
        )

    return EnrichedAgg(
        symbol=agg.symbol,
        close=agg.close,
        open=agg.open or 0.0,
        high=agg.high or 0.0,
        low=agg.low or 0.0,
        volume=agg.volume or 0.0,
        vwap=agg.vwap,
        official_open_price=agg.official_open_price,
        pct_change_from_open=pct_change,
        timestamp_ms=agg.end_timestamp,
    )
