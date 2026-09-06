"""Authentication on the insights endpoints.

This service will hand a caller every finding in the estate, so the interesting
assertions are the negative ones: that each route actually refuses an
unaccredited request, and that the refusal says nothing useful to someone
probing it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pycommon import Database

from insights.config import get_config
from tests.conftest import OPERATOR_KEYS

#: Every route that requires a credential. Parametrised rather than asserted
#: one by one, so a route added without a dependency fails here.
PROTECTED = [
    "/v1/alerts",
    "/v1/agents/agent-alpha/summary",
    "/v1/agents/agent-alpha/timeline",
]


@pytest.fixture
def anonymous(db: Database, db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client carrying no credential, unlike the shared `client` fixture."""
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("OPERATOR_API_KEYS", OPERATOR_KEYS)
    get_config.cache_clear()

    from insights.api import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    get_config.cache_clear()


class TestUnauthenticated:
    @pytest.mark.parametrize("path", PROTECTED)
    def test_refuses_a_request_with_no_credential(
        self, anonymous: TestClient, path: str
    ) -> None:
        assert anonymous.get(path).status_code == 401

    @pytest.mark.parametrize("path", PROTECTED)
    def test_refuses_an_unknown_key(self, anonymous: TestClient, path: str) -> None:
        response = anonymous.get(path, headers={"Authorization": "Bearer not-a-real-key"})

        assert response.status_code == 401

    def test_refuses_a_non_bearer_scheme(self, anonymous: TestClient) -> None:
        response = anonymous.get("/v1/alerts", headers={"Authorization": "Basic dGVzdDp0ZXN0"})

        assert response.status_code == 401

    def test_answers_the_same_envelope_the_ingestion_service_does(
        self, anonymous: TestClient
    ) -> None:
        """`{"error": "unauthorized"}` and nothing else. A client parses one
        error shape across all three services, and the body must not say which
        part of the credential was wrong."""
        response = anonymous.get("/v1/alerts")

        assert response.json() == {"error": "unauthorized"}

    def test_does_not_distinguish_a_missing_key_from_a_wrong_one(
        self, anonymous: TestClient
    ) -> None:
        """Identical status and body, so probing the endpoint reveals nothing
        about whether a guessed key exists."""
        missing = anonymous.get("/v1/alerts")
        wrong = anonymous.get("/v1/alerts", headers={"Authorization": "Bearer wrong"})

        assert (missing.status_code, missing.json()) == (wrong.status_code, wrong.json())


class TestAuthenticated:
    @pytest.mark.parametrize("path", PROTECTED)
    def test_admits_a_configured_key(self, client: TestClient, path: str) -> None:
        """The `client` fixture carries the operator credential."""
        assert client.get(path).status_code == 200


class TestHealthIsOpen:
    def test_healthz_needs_no_credential(self, anonymous: TestClient) -> None:
        """Left unauthenticated on purpose: the Compose healthcheck and any
        orchestrator probe it, and neither should need a secret to ask whether
        the process is alive."""
        assert anonymous.get("/healthz").status_code == 200
