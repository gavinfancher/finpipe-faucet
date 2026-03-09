import asyncio
import json

import httpx
from aiokafka import AIOKafkaConsumer
from rich.live import Live
from rich.table import Table
from rich.text import Text

from producer import BOOTSTRAP_SERVERS, TOPIC

API_URL = "http://localhost:8000"

prices: dict[str, dict] = {}
subscribed: set[str] = set()


def make_table() -> Table:
    all_tickers = sorted(subscribed | prices.keys())

    table = Table(title="Live Prices", header_style="none")
    table.add_column("Ticker", width=8)
    table.add_column("Price", justify="right", width=10)
    table.add_column("Chg", justify="right", width=8)

    for ticker in all_tickers:
        data = prices.get(ticker)
        if data is None:
            table.add_row(ticker, Text("--", style="dim"), Text("--", style="dim"))
        else:
            close = data["close"]
            pct = data.get("pct_change_from_open")
            color = "green" if (pct is not None and pct >= 0) else "red"
            pct_str = f"{pct:+.2f}%" if pct is not None else "--"
            table.add_row(ticker, Text(f"${close:.2f}", style=color), Text(pct_str, style=color))

    return table


async def poll_subscriptions():
    """Poll the API every 2s to keep subscribed set in sync."""
    async with httpx.AsyncClient() as http:
        while True:
            try:
                r = await http.get(f"{API_URL}/subscriptions")
                subs = r.json().get("subscriptions", [])
                # subs are like "A.AAPL" — strip the prefix
                subscribed.clear()
                subscribed.update(s.split(".", 1)[1] for s in subs if "." in s)
            except httpx.ConnectError:
                pass  # API not up yet, retry
            await asyncio.sleep(2)


async def consume_kafka(live: Live):
    """Consume price data from Kafka and update the display."""
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id="display-consumer",
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="latest",
    )
    await consumer.start()
    try:
        async for msg in consumer:
            prices[msg.value["symbol"]] = msg.value
            live.update(make_table())
    finally:
        await consumer.stop()


async def main():
    with Live(make_table(), refresh_per_second=4) as live:
        await asyncio.gather(
            poll_subscriptions(),
            consume_kafka(live),
        )


if __name__ == "__main__":
    asyncio.run(main())
