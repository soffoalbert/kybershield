"""Configuration validation.

The bounds below used to be re-checked on every request inside
`resolve_window`. They belong at boot: a misconfigured container should fail to
start rather than answer every query with an empty or inverted range.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from insights.config import InsightsConfig

DB_URL = "postgresql://user:pass@localhost:5432/db"


class TestBounds:
    @pytest.mark.parametrize(
        "field",
        ["default_window_hours", "default_page_size", "max_page_size", "top_rules_limit"],
    )
    def test_rejects_a_non_positive_value(self, field: str) -> None:
        with pytest.raises(ValidationError):
            InsightsConfig(database_url=DB_URL, **{field: 0})

    def test_accepts_the_declared_defaults(self) -> None:
        config = InsightsConfig(database_url=DB_URL)

        assert config.default_window_hours == 24
        assert config.default_page_size == 50
        assert config.max_page_size == 500
        assert config.top_rules_limit == 5
