"""Insights service configuration."""

from __future__ import annotations

from functools import lru_cache

from pycommon import BaseServiceSettings


class InsightsConfig(BaseServiceSettings):
    """Environment-driven insights settings."""

    port: int = 8002

    #: Window applied when a request omits `since`. The brief's "last 24 hours"
    #: default, made configurable.
    default_window_hours: int = 24

    #: Page size when the caller does not specify one.
    default_page_size: int = 50
    #: Ceiling on `limit`, so one request cannot ask for the entire table.
    max_page_size: int = 500

    #: How many entries `top_rules` carries in an agent summary.
    top_rules_limit: int = 5


@lru_cache(maxsize=1)
def get_config() -> InsightsConfig:
    """Return the process-wide config, parsed once."""
    raise NotImplementedError
