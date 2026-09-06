"""Authentication on the analyser endpoints.

The stakes here are writes rather than reads: `/v1/analyze/backfill` puts the
entire event history back through every rule. The negative assertions are the
point — that an unaccredited caller cannot trigger that, and that the refusal
tells them nothing.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pycommon import Database

from analyser.config import get_config
from tests.integration.conftest import OPERATOR_KEYS, seed_event

#: Every route that requires a credential, with the verb it answers.
#: Parametrised rather than asserted one by one, so a route added without a
#: dependency fails here.
PROTECTED = [
    ("post", "/v1/analyze/run"),
    ("post", "/v1/analyze/backfill"),
    ("get", "/v1/rules"),
]


@pytest.fixture
def anonymous(db: Database, db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client carrying no credential, unlike the shared `client` fixture."""
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("POLLER_ENABLED", "false")
    monkeypatch.setenv("LISTEN_ENABLED", "false")
    monkeypatch.setenv("OPERATOR_API_KEYS", OPERATOR_KEYS)
    get_config.cache_clear()

    from analyser.api import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    get_config.cache_clear()


class TestUnauthenticated:
    @pytest.mark.parametrize(("verb", "path"), PROTECTED)
    def test_refuses_a_request_with_no_credential(
        self, anonymous: TestClient, verb: str, path: str
    ) -> None:
        assert anonymous.request(verb, path, json={}).status_code == 401

    @pytest.mark.parametrize(("verb", "path"), PROTECTED)
    def test_refuses_an_unknown_key(self, anonymous: TestClient, verb: str, path: str) -> None:
        response = anonymous.request(
            verb, path, json={}, headers={"Authorization": "Bearer not-a-real-key"}
        )

        assert response.status_code == 401

    def test_answers_the_same_envelope_the_ingestion_service_does(
        self, anonymous: TestClient
    ) -> None:
        """`{"error": "unauthorized"}` and nothing else, so a client parses one
        error shape across all three services."""
        response = anonymous.get("/v1/rules")

        assert response.json() == {"error": "unauthorized"}

    def test_a_refused_backfill_does_not_run(
        self, anonymous: TestClient, db: Database
    ) -> None:
        """The dependency has to reject before the handler, not alongside it: a
        401 that still re-analysed history would be worse than no auth, because
        it would look safe."""
        seed_event(db, event_id="auth-evt-1", payload={"path": "/app/.env"})

        assert anonymous.post("/v1/analyze/backfill", json={}).status_code == 401
        with db.transaction() as cur:
            written = cur.execute("SELECT count(*) AS n FROM alerts").fetchone()
        assert written["n"] == 0


class TestAuthenticated:
    @pytest.mark.parametrize(("verb", "path"), PROTECTED)
    def test_admits_a_configured_key(self, client: TestClient, verb: str, path: str) -> None:
        """The `client` fixture carries the operator credential."""
        assert client.request(verb, path, json={}).status_code == 200


class TestHealthIsOpen:
    def test_healthz_needs_no_credential(self, anonymous: TestClient) -> None:
        """Left unauthenticated on purpose: the Compose healthcheck and any
        orchestrator probe it, and neither should need a secret to ask whether
        the process is alive."""
        assert anonymous.get("/healthz").status_code == 200
