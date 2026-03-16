# finpipe-stream

Real-time equity price streaming pipeline. Connects to the [Massive](https://massive.com) WebSocket feed, enriches data, fans it through Kafka, and broadcasts to clients over WebSocket.

## Architecture

```
                    ┌─────────────────────────────────────────┐
User HTTP/WS ──────►│  api  :8000                             │
                    │  PUT/DELETE /subscriptions               │
                    │  GET /workers  (load view)               │
                    │  WS  /ws       (live prices)             │
                    │                                          │
                    │  Reads Redis to route sub commands       │
                    │  Kafka consumer → broadcasts to clients  │
                    │  Writes tickers.json on every change     │
                    └───────────────┬─────────────────────────┘
                                    │ internal HTTP
               ┌────────────────────┼────────────────────┐
               ▼                    ▼                    ▼
      ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
      │  ws-worker-1 │   │  ws-worker-2 │   │  ws-worker-3 │
      │  ≤100 subs   │   │  ≤100 subs   │   │  ≤100 subs   │
      │  Massive WS  │   │  Massive WS  │   │  Massive WS  │
      └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
             └──────────────────┼──────────────────┘
                                │ publish
                          ┌─────▼──────┐
                          │  Redpanda  │  stocks-aggs topic
                          └─────┬──────┘
                                │ consume
                          ┌─────▼──────┐      ┌───────────┐
                          │  api Kafka │      │   Redis   │
                          │  consumer  │      │  {ticker  │
                          └────────────┘      │→ worker}  │
                                              └───────────┘
```

**How subscription routing works:**

`PUT /subscriptions/AAPL` hits the API, which:
1. Checks Redis — already assigned? Skip.
2. Finds the worker with the lowest sub count (under MAX_SUBS).
3. Calls `PUT http://ws-worker-N:8001/internal/subscribe/A.AAPL`.
4. Stores `A.AAPL → http://ws-worker-N:8001` in Redis.
5. Writes the full ticker list to `/data/tickers.json` (persistent volume).

All workers publish enriched messages to the same Kafka topic. The API's Kafka consumer fans those out to every connected WebSocket client.

**Persistence layers:**

| Layer | Survives | Role |
|---|---|---|
| Redis | container restarts | runtime assignment cache (`{ticker → worker}`) |
| `tickers.json` (Docker volume) | Redis wipes, full stack restarts | canonical ticker list |

On startup the API checks Redis first. If empty, it reloads from `tickers.json` and re-subscribes everything. A reconciliation loop (default every 30s) re-pushes any subs a restarted worker lost.

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) + Docker Compose v2
- A [Massive](https://massivefinancial.com) API key

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env and set MASSIVE_API_KEY
```

### 2. Build images

```bash
docker compose build
```

### 3. Start the stack

```bash
docker compose up -d
```

Startup order is enforced by healthchecks: Redpanda and Redis come up first, then the three workers, then the API. First boot takes ~30s while Redpanda initialises.

```bash
docker compose ps   # all services should show "healthy" or "running"
```

### 4. Add subscriptions

```bash
# Single ticker
curl -X PUT http://localhost:8000/subscriptions/AAPL

# Bulk (distributed evenly across workers)
curl -X PUT http://localhost:8000/subscriptions \
  -H "Content-Type: application/json" \
  -d '["AAPL","MSFT","GOOGL","AMZN","TSLA","NVDA"]'
```

### 5. Check load distribution

```bash
curl http://localhost:8000/workers
```

```json
{
  "http://ws-worker-1:8001": {"count": 2, "max_subs": 100, "tickers": ["A.AAPL","A.MSFT"]},
  "http://ws-worker-2:8001": {"count": 2, "max_subs": 100, "tickers": ["A.GOOGL","A.AMZN"]},
  "http://ws-worker-3:8001": {"count": 2, "max_subs": 100, "tickers": ["A.TSLA","A.NVDA"]}
}
```

### 6. View live prices

Open `index.html` in your browser — it connects to `ws://localhost:8000/ws` and renders a live price table.

### 7. Remove subscriptions

```bash
curl -X DELETE http://localhost:8000/subscriptions/AAPL

curl -X DELETE http://localhost:8000/subscriptions \
  -H "Content-Type: application/json" \
  -d '["AAPL","MSFT"]'
```

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/subscriptions` | List all active tickers |
| `PUT` | `/subscriptions/{ticker}` | Subscribe a ticker |
| `PUT` | `/subscriptions` | Subscribe multiple tickers (JSON array body) |
| `DELETE` | `/subscriptions/{ticker}` | Unsubscribe a ticker |
| `DELETE` | `/subscriptions` | Unsubscribe multiple tickers |
| `GET` | `/workers` | Sub count and tickers per worker |
| `GET` | `/health` | Health check |
| `WS` | `/ws` | Live price stream |

## Monitoring

| URL | What it shows |
|---|---|
| `http://localhost:8080` | Redpanda Console (topics, messages, consumer groups) |
| `http://localhost:8000/workers` | Sub count per worker |
| `http://localhost:8000/subscriptions` | All active tickers |

```bash
# Logs
docker compose logs -f api
docker compose logs -f ws-worker-1

# Inspect Redis state directly
docker compose exec redis redis-cli hgetall finpipe:ticker_worker

# Inspect the persistent tickers file
docker compose exec api cat /data/tickers.json
```

## Scaling

To add a fourth worker, add a new service in `docker-compose.yml`:

```yaml
  ws-worker-4:
    build:
      context: .
      dockerfile: Dockerfile.worker
    environment:
      WORKER_ID: ws-worker-4
      WORKER_PORT: "8001"
      KAFKA_BOOTSTRAP_SERVERS: redpanda:9092
      MAX_SUBS: "100"
      MASSIVE_API_KEY: ${MASSIVE_API_KEY}
    depends_on:
      redpanda:
        condition: service_healthy
    expose:
      - "8001"
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8001/health')\""]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
```

Then add `ws-worker-4:8001` to `WORKER_ADDRS` on the `api` service and apply:

```bash
docker compose up -d --no-deps ws-worker-4 api
```

New subscriptions will automatically flow to the new worker.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MASSIVE_API_KEY` | — | **Required.** Massive WebSocket API key |
| `MAX_SUBS` | `100` | Max subscriptions per worker |
| `RECONCILE_INTERVAL` | `30` | Seconds between worker reconciliation passes |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:19092` | Kafka broker address |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `WORKER_ADDRS` | `localhost:8001,...` | Comma-separated worker `host:port` list |
| `TICKERS_FILE` | `/data/tickers.json` | Path to persistent ticker list |
