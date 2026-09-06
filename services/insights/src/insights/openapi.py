"""OpenAPI metadata for the insights service.

FastAPI serves Swagger UI at `/docs` and ReDoc at `/redoc` automatically, and
derives request and response schemas from the pydantic models in `models.py`.
This module supplies the prose it cannot infer, so `create_app()` stays:

    app = FastAPI(lifespan=lifespan, **APP_METADATA)

This is the document a teammate would generate a dashboard client from, so the
response models carry the contract and the text below carries the semantics.
"""

from __future__ import annotations

from typing import Any

DESCRIPTION = """
Read-only queries over agent events and the alerts raised against them.

**Time windows.** Every endpoint accepts `since` and `until` as ISO-8601
timestamps, or a `window` shorthand (`30m`, `24h`, `7d`). Omitting all three
falls back to the last `DEFAULT_WINDOW_HOURS`, which is 24. Bounds are
inclusive, and the resolved range is echoed back on the summary endpoint so a
caller never has to infer what was measured.

**Pagination.** List endpoints return a `Page` envelope of
`{items, total, limit, offset}`. `total` counts every match, not just the
current page, so a dashboard can size a paginator from one request. `limit` is
clamped to `MAX_PAGE_SIZE` rather than rejected.

**Severity.** Ordered `low < medium < high < critical`. `severity_min=high`
returns high and critical.

**Empty results are not errors.** An unknown `agent_id` returns an empty page
or a zeroed summary with `200`, not `404`: the question was well-formed and the
answer is "nothing".

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
        "name": "alerts",
        "description": "Query the alert feed with time, agent, rule, and severity filters.",
    },
    {
        "name": "agents",
        "description": (
            "Per-agent views: an aggregate risk summary, and a timeline merging "
            "that agent's events and alerts into one ordered stream."
        ),
    },
    {
        "name": "health",
        "description": "Liveness and database reachability.",
    },
]

#: Spread into the FastAPI constructor.
APP_METADATA: dict[str, Any] = {
    "title": "KyberShield Insights API",
    "description": DESCRIPTION,
    "version": "0.1.0",
    "openapi_tags": TAGS_METADATA,
    "docs_url": "/docs",
    "redoc_url": "/redoc",
    "openapi_url": "/openapi.json",
    "servers": [{"url": "http://localhost:8002", "description": "Local Docker Compose"}],
}
