"""OpenAPI metadata for the analyser.

FastAPI generates the document and serves Swagger UI at `/docs` and ReDoc at
`/redoc` with no extra dependency. What it cannot infer is the prose: what the
service is for, what each group of endpoints does, and the operational
caveats a reader needs. That lives here so `create_app()` stays a one-liner:

    app = FastAPI(lifespan=lifespan, **APP_METADATA)
"""

from __future__ import annotations

from typing import Any

DESCRIPTION = """
Rule-based risk analysis over ingested agent activity.

**How it runs.** A background poller drains new events every
`POLL_INTERVAL_SECONDS`. The endpoints here are for forcing a pass and
inspecting configuration; they are not the primary execution path. The same
operations are available as a CLI (`python -m analyser run-once`).

**Ordering.** The poller claims work by `ingest_seq`, the monotonic arrival
sequence, never by event timestamp. An event that arrives late carrying an old
timestamp still gets a fresh high sequence number, so it is picked up on the
next pass rather than being skipped.

**Idempotency.** Alerts are unique on `(event_id, rule)`, so re-running
analysis over the same events writes nothing. That is what makes
`/v1/analyze/backfill` safe to call repeatedly.

**Authentication.** Every `/v1` route requires an operator API key, presented
as `Authorization: Bearer <secret>` exactly as the ingestion service expects
one. The credential set is separate, though: `OPERATOR_API_KEYS` rather than
ingestion's `API_KEYS`, so an agent's ingest key cannot reach these endpoints.
A missing, malformed, or unknown key is `401 {"error": "unauthorized"}` in
every case, with nothing in the body to say which. `/healthz` is open, so an
orchestrator can probe it without credentials.
"""

TAGS_METADATA: list[dict[str, Any]] = [
    {
        "name": "analysis",
        "description": "Trigger analysis passes. Normally handled by the background poller.",
    },
    {
        "name": "rules",
        "description": "Inspect the registered detections and their effective thresholds.",
    },
    {
        "name": "health",
        "description": "Liveness, database reachability, and poller state.",
    },
]

#: Spread into the FastAPI constructor.
APP_METADATA: dict[str, Any] = {
    "title": "KyberShield Analyser API",
    "description": DESCRIPTION,
    "version": "0.1.0",
    "openapi_tags": TAGS_METADATA,
    "docs_url": "/docs",
    "redoc_url": "/redoc",
    "openapi_url": "/openapi.json",
    "servers": [{"url": "http://localhost:8001", "description": "Local Docker Compose"}],
}
