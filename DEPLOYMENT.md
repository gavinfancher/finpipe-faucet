# Deployment Guide

## Architecture

```
User HTTP/WS
     │
     ▼
┌──────────────────────────────────────────────┐
│  api  (port 8000)                            │
│  • GET/PUT/DELETE /subscriptions             │
│  • GET /workers  (load view)                 │
│  • WS  /ws       (live prices)               │
│  • Reads Redis to route sub commands         │
│  • Kafka consumer → broadcasts to WS clients │
└──────────┬───────────────────────────────────┘
           │ internal HTTP (subscribe/unsubscribe)
    ┌──────┼──────┬──────────────┐
    ▼      ▼      ▼
┌────────┐ ┌────────┐ ┌────────┐
│worker-1│ │worker-2│ │worker-3│  each: max 100 Massive subs
│port8001│ │port8001│ │port8001│  all publish to Kafka
└────────┘ └────────┘ └────────┘
                │
          Redpanda (Kafka)
          stocks-aggs topic
                │
          ┌─────┴──────┐
          │  Redis     │  stores: {ticker → worker_url}
          └────────────┘
```

When you `PUT /subscriptions/AAPL`, the API:
1. Checks Redis — is AAPL already assigned? Skip if so.
2. Finds the worker with the lowest sub count (that is under MAX_SUBS).
3. Calls `PUT http://ws-worker-N:8001/internal/subscribe/A.AAPL`.
4. Stores `A.AAPL → http://ws-worker-N:8001` in Redis.

All workers publish enriched messages to the same Kafka topic. The API's
single Kafka consumer fans those out to every connected WebSocket client.

---

## Prerequisites

- Docker Engine 24+ and Docker Compose v2 (`docker compose version`)
- A Massive API key

---

## Step 1 — Environment file

```bash
cp .env.example .env
```

Edit `.env` and set your key:

```
MASSIVE_API_KEY=your_key_here
```

---

## Step 2 — Build images

```bash
docker compose build
```

This builds two images:
- `finpipe-stream-api` — public-facing FastAPI (Dockerfile.api)
- `finpipe-stream-ws-worker-1/2/3` — Massive WS workers (Dockerfile.worker)

---

## Step 3 — Start the stack

```bash
docker compose up -d
```

Startup order (enforced by healthchecks):
1. Redpanda + Redis start first
2. Three ws-workers start once Redpanda is healthy
3. API starts once all three workers pass their healthcheck

Check everything is up:

```bash
docker compose ps
```

All services should show `healthy` or `running`. The first boot takes ~30s
while Redpanda initialises.

---

## Step 4 — Check the API is ready

```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl http://localhost:8000/workers
# Shows each worker with count: 0
```

---

## Step 5 — Add subscriptions

Single ticker:

```bash
curl -X PUT http://localhost:8000/subscriptions/AAPL
```

Bulk (up to 300 across 3 workers):

```bash
curl -X PUT http://localhost:8000/subscriptions \
  -H "Content-Type: application/json" \
  -d '["AAPL","MSFT","GOOGL","AMZN","TSLA","NVDA"]'
```

Tickers are distributed round-robin to the least-loaded worker automatically.

---

## Step 6 — Verify load distribution

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

---

## Step 7 — View live prices

Open `index.html` directly in your browser (it connects to `ws://localhost:8000/ws`):

```bash
open index.html        # macOS
xdg-open index.html    # Linux
```

---

## Step 8 — Remove subscriptions

```bash
# Single
curl -X DELETE http://localhost:8000/subscriptions/AAPL

# Bulk
curl -X DELETE http://localhost:8000/subscriptions \
  -H "Content-Type: application/json" \
  -d '["AAPL","MSFT"]'
```

---

## Monitoring

| URL | What it shows |
|-----|---------------|
| `http://localhost:8000/workers` | Sub count per worker |
| `http://localhost:8000/subscriptions` | All active tickers |
| `http://localhost:8080` | Redpanda Console (Kafka topics, messages) |
| `docker compose logs -f ws-worker-1` | Worker logs |
| `docker compose logs -f api` | API logs |

Inspect the Redis subscription map directly:

```bash
docker compose exec redis redis-cli hgetall finpipe:ticker_worker
```

---

## Scaling to more workers

1. Add a new service block in `docker-compose.yml`:

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

2. Add `ws-worker-4:8001` to the `WORKER_ADDRS` env var on the `api` service.

3. Apply:

```bash
docker compose up -d --no-deps ws-worker-4 api
```

New subscriptions will automatically flow to the new worker.

---

## Troubleshooting

**API can't connect to workers**
```bash
docker compose exec api curl http://ws-worker-1:8001/health
```

**Workers not connecting to Massive**
```bash
docker compose logs ws-worker-1
# Look for "connected" or API key errors
```

**Subscription persistence across full restarts**

There are two layers of persistence:

| Layer | Survives | Purpose |
|---|---|---|
| `api_data` volume (`/data/tickers.json`) | everything including Redis wipe | canonical ticker list |
| Redis (`finpipe:ticker_worker`) | container restarts | runtime assignment cache |

On every `PUT`/`DELETE` the API writes the current ticker list to
`/data/tickers.json`. On startup, if Redis is empty, the API reads that file
and re-subscribes all tickers across workers automatically.

The reconciliation loop (default every 30s) handles the case where a worker
restarts mid-run — it re-pushes any subs that Redis thinks are active but the
worker lost. Tune with `RECONCILE_INTERVAL` on the `api` service.

```bash
# Watch restore + reconcile activity
docker compose logs -f api | grep -E "restore|reconcile"

# Inspect the tickers file directly
docker compose exec api cat /data/tickers.json

# Inspect Redis state
docker compose exec redis redis-cli hgetall finpipe:ticker_worker
```

To intentionally reset all subscriptions:
```bash
docker compose exec api rm /data/tickers.json
docker compose exec redis redis-cli del finpipe:ticker_worker
docker compose restart api
```

**Stop the stack**
```bash
docker compose down           # keep volumes
docker compose down -v        # wipe Redpanda + Redis data too
```

---

## Production notes

- Replace Redpanda with a managed Kafka (Confluent Cloud, Redpanda Cloud) —
  update `KAFKA_BOOTSTRAP_SERVERS` on all services.
- Replace the Redis container with a managed Redis (AWS ElastiCache, Redis
  Cloud) with AOF persistence so the subscription map survives restarts.
- The `/internal/*` worker endpoints must not be exposed publicly — keep them
  on the internal Docker network only (use `expose:` not `ports:`).
- Add auth middleware to the `/subscriptions` API before exposing it publicly.
- Set `MAX_SUBS` to match whatever your Massive plan allows per connection.
