# KyberShield Agent Risk Monitor (MVP)

Local MVP that ingests AI agent activity events, analyses them against security rules, and exposes risk insights.

Three services over one PostgreSQL database:

| Service     | Stack                        | Port | Responsibility                                          |
| ----------- | ---------------------------- | ---- | ------------------------------------------------------- |
| `ingestion` | Node.js 22, Fastify 5, TS    | 3000 | Authenticated, idempotent event intake                   |
| `analyser`  | Python 3.12, FastAPI         | 8001 | Rule-based risk analysis, background poller + manual run |
| `insights`  | Python 3.12, FastAPI + Typer | 8002 | Read-only alert queries, agent summaries, timelines      |

## Quick start

```bash
cp .env.example .env
make up          # build + start postgres, ingestion, analyser, insights
make seed        # post a realistic mixed event stream
open http://localhost:8002/docs
```

## Interactive API docs

Every service serves browsable, try-it-out OpenAPI 3.1 documentation:

| Service     | Swagger UI                     | ReDoc                           | Raw document                          |
| ----------- | ------------------------------ | ------------------------------- | ------------------------------------- |
| `ingestion` | http://localhost:3000/docs     | —                               | http://localhost:3000/docs/json       |
| `analyser`  | http://localhost:8001/docs     | http://localhost:8001/redoc     | http://localhost:8001/openapi.json    |
| `insights`  | http://localhost:8002/docs     | http://localhost:8002/redoc     | http://localhost:8002/openapi.json    |

The ingestion endpoints require a key, so click **Authorize** in its Swagger UI and paste a secret from `API_KEYS` (`dev-secret-key` with the defaults) before using *Try it out*. The analyser and insights services are unauthenticated.

The analyser polls every 5 seconds by default, so alerts appear a few seconds after seeding. To force a pass:

```bash
curl -X POST http://localhost:8001/v1/analyze/run
```

## Verifying it works

```bash
# Submit an event
curl -X POST http://localhost:3000/v1/events \
  -H 'Authorization: Bearer dev-secret-key' \
  -H 'Content-Type: application/json' \
  -d '{
        "event_id": "evt-demo-1",
        "agent_id": "agent-alpha",
        "timestamp": "2026-08-25T10:00:00Z",
        "type": "file_read",
        "payload": { "path": "/home/app/.aws/credentials" },
        "tags": ["demo"]
      }'
# -> 201 {"eventId":"evt-demo-1","status":"created"}

# Replay it: stored once, reported as a duplicate
curl -X POST http://localhost:3000/v1/events ... # same body
# -> 200 {"eventId":"evt-demo-1","status":"duplicate"}

# Read the resulting alerts
curl 'http://localhost:8002/v1/alerts?agent_id=agent-alpha'
curl 'http://localhost:8002/v1/agents/agent-alpha/summary?window=24h'
curl 'http://localhost:8002/v1/agents/agent-alpha/timeline'
```

## API surface

### Ingestion (`:3000`)

Authentication: `Authorization: Bearer <secret>`, where secrets come from the `API_KEYS` environment variable as `clientId:secret` pairs.

| Method | Path                | Notes                                                     |
| ------ | ------------------- | --------------------------------------------------------- |
| `POST` | `/v1/events`        | Single event. `201` created, `200` duplicate.              |
| `POST` | `/v1/events/batch`  | Up to 100 events. `207` with a per-event result array.     |
| `GET`  | `/healthz`          | Liveness, no auth.                                         |
| `GET`  | `/readyz`           | Readiness including a database probe, no auth.             |

Errors: `400` validation, `401` bad or missing key, `413` body over `BODY_LIMIT_BYTES`, `503` database unavailable.

### Analyser (`:8001`)

| Method | Path                    | Notes                                              |
| ------ | ----------------------- | -------------------------------------------------- |
| `POST` | `/v1/analyze/run`       | Run one batch now, returns a `RunReport`.           |
| `POST` | `/v1/analyze/backfill`  | Re-run rules over history, optional `since`.        |
| `GET`  | `/v1/rules`             | List registered rules and their configuration.      |
| `GET`  | `/healthz`              | Liveness plus poller state.                         |

Also available as a CLI inside the container:

```bash
docker compose exec analyser python -m analyser run-once
docker compose exec analyser python -m analyser backfill --since 2026-08-01T00:00:00Z
docker compose exec analyser python -m analyser list-rules
```

### Insights (`:8002`)

| Method | Path                                  | Notes                                                    |
| ------ | ------------------------------------- | -------------------------------------------------------- |
| `GET`  | `/v1/alerts`                          | Defaults to the last 24h. Filters below.                  |
| `GET`  | `/v1/agents/{agent_id}/summary`       | `window` accepts `1h`, `24h`, `7d`, or explicit bounds.   |
| `GET`  | `/v1/agents/{agent_id}/timeline`      | Events and alerts merged, ordered by time.                |
| `GET`  | `/healthz`                            | Liveness.                                                 |

`/v1/alerts` filters: `since`, `until`, `agent_id`, `rule`, `severity_min`, `limit`, `offset`. Responses are a `Page` envelope of `{items, total, limit, offset}`.

CLI mirror:

```bash
docker compose exec insights python -m insights alerts --agent-id agent-alpha
docker compose exec insights python -m insights summary agent-alpha --window 24h
docker compose exec insights python -m insights timeline agent-alpha --json
```

## Detection rules

| Rule id                 | Severity   | Fires on                                                       |
| ----------------------- | ---------- | -------------------------------------------------------------- |
| `secret_file_access`    | `high`     | Paths containing `.env`, `id_rsa`, `.aws/credentials`, `.ssh/`  |
| `domain_allowlist`      | `medium`   | `http_request` to a host outside `ALLOWED_DOMAINS`              |
| `download_and_execute`  | `critical` | `curl`/`wget` piped to a shell, `base64 -d` piped to a shell    |

Three rules, one per event type of interest (`file_read`, `http_request`,
`shell_command`). All are stateless: each sees a single event and the config,
never storage.

Thresholds and the allowlist are environment-configured; see `.env.example`.

## Local development

```bash
make install          # npm install + editable Python installs
make test             # every suite
make test-ingestion   # vitest
make test-analyser    # pytest
make test-insights    # pytest
```

Integration tests need a running database:

```bash
docker compose up -d postgres
```

## Database

Schema lives in [db/migrations/001_init.sql](db/migrations/001_init.sql) and is applied by Postgres' `docker-entrypoint-initdb.d` on a fresh volume. There is no incremental migration tool, so schema changes require a reset:

```bash
make db-reset
make psql       # interactive shell
```

## Design and trade-offs

See [SOLUTION.md](SOLUTION.md).
