import asyncio
import json

from aiokafka import AIOKafkaConsumer

BOOTSTRAP_SERVERS = "localhost:19092"
TOPIC = "stocks-aggs"
GROUP_ID = "finpipe-consumer"


async def main():
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id=GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="latest",  # only new messages; change to "earliest" to replay all
    )

    await consumer.start()
    print(f"Listening on '{TOPIC}'...\n")

    try:
        async for msg in consumer:
            data = msg.value
            pct = data.get("pct_change_from_open")
            pct_str = f"{pct:+.2f}%" if pct is not None else "n/a"
            print(
                f"[{data['symbol']:6}] "
                f"${data['close']:.2f}  "
                f"{pct_str}  "
                f"vol={data['volume']:.0f}"
            )
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
