import asyncio
import json

from aiokafka import AIOKafkaConsumer

from producer import BOOTSTRAP_SERVERS, TOPIC

cumulative: dict[str, float] = {}


async def main():
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id="volume-consumer",
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="latest",
    )
    await consumer.start()
    print(f"Listening on '{TOPIC}'...\n")
    try:
        async for msg in consumer:
            data = msg.value
            sym = data["symbol"]
            vol = data.get("volume", 0)
            cumulative[sym] = cumulative.get(sym, 0) + vol
            print(f"{sym:6}  tick={vol:>10,.0f}  cumulative={cumulative[sym]:>14,.0f}")
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
