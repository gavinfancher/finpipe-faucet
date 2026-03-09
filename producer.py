import asyncio
import json
import logging

from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import KafkaError, TopicAlreadyExistsError

logger = logging.getLogger(__name__)

BOOTSTRAP_SERVERS = "localhost:19092"
TOPIC = "stocks-aggs"
FLUSH_INTERVAL = 0.1  # seconds — batch and send every 100ms

_producer: AIOKafkaProducer | None = None
_queue: asyncio.Queue = asyncio.Queue(maxsize=50_000)


async def _ensure_topic():
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP_SERVERS)
    await admin.start()
    try:
        await admin.create_topics([NewTopic(name=TOPIC, num_partitions=4, replication_factor=1)])
        logger.info("Created topic %s", TOPIC)
    except TopicAlreadyExistsError:
        pass
    finally:
        await admin.close()


async def start():
    global _producer
    await _ensure_topic()
    _producer = AIOKafkaProducer(
        bootstrap_servers=BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode(),
        key_serializer=lambda k: k.encode() if k else None,
        compression_type="gzip",
        linger_ms=50,
    )
    await _producer.start()
    logger.info("Kafka producer connected to %s", BOOTSTRAP_SERVERS)


async def stop():
    if _producer:
        await _producer.flush()
        await _producer.stop()


async def publish(symbol: str, data: dict):
    """Non-blocking enqueue. Drops if queue is full (backpressure)."""
    try:
        _queue.put_nowait(data)
    except asyncio.QueueFull:
        logger.warning("producer queue full, dropping message for %s", symbol)


async def flush_loop():
    """Drain the queue and send to Kafka in batches every FLUSH_INTERVAL seconds."""
    while True:
        await asyncio.sleep(FLUSH_INTERVAL)
        if _producer is None or _queue.empty():
            continue

        batch = []
        while not _queue.empty():
            try:
                batch.append(_queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        for item in batch:
            try:
                await _producer.send(TOPIC, value=item, key=item.get("symbol"))
            except KafkaError as e:
                logger.error("failed to send to kafka: %s", e)
