import os
from pathlib import Path

from dotenv import load_dotenv

from massive import WebSocketClient
from massive.websocket.models import Feed, Market, WebSocketMessage
from massive.websocket.models.models import EquityAgg

import producer
from transforms import enrich


load_dotenv(Path(__file__).parent / ".env")

client = WebSocketClient(
    api_key=os.getenv("MASSIVE_API_KEY"),
    feed=Feed.Delayed,
    market=Market.Stocks,
)


async def handle_msg(msgs: list[WebSocketMessage]):
    for m in msgs:
        if isinstance(m, EquityAgg) and m.symbol and m.close is not None:
            enriched = enrich(m)
            if enriched:
                await producer.publish(m.symbol, enriched.to_dict())
