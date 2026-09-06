"""Insights service configuration."""

from __future__ import annotations

from functools import lru_cache

from pycommon import BaseServiceSettings
from pydantic import Field


class InsightsConfig(BaseServiceSettings):
    """Environment-driven insights settings."""

    port: int = 8002

    #: Window applied when a request omits `since`. The brief's "last 24 hours"
    #: default, made configurable. Bounded here rather than per request, so a
    #: bad value fails the container at boot instead of every query.
    default_window_hours: int = Field(default=24, gt=0)

    #: Page size when the caller does not specify one.
    default_page_size: int = Field(default=50, gt=0)
    #: Ceiling on `limit`, so one request cannot ask for the entire table.
    max_page_size: int = Field(default=500, gt=0)

    #: How many entries `top_rules` carries in an agent summary.
    top_rules_limit: int = Field(default=5, gt=0)


@lru_cache(maxsize=1)
def get_config() -> InsightsConfig:
    """Return the process-wide config, parsed once.

    Cached so FastAPI dependencies observe the same instance.
    """
    # BaseSettings reads the environment itself; passing `os.environ` as kwargs
    # would hand it uppercase keys that match no field.
    return InsightsConfig()
