"""Shared building blocks for the KyberShield Python services.

Exists so the analyser and insights services agree on entity shapes, severity
ordering, and connection setup instead of each maintaining their own copy.
"""

from pycommon.db import Database, dict_row_factory
from pycommon.entities import (
    Alert,
    AlertDraft,
    Event,
    EventType,
    Severity,
)
from pycommon.errors import ValidationFailed, install_error_handlers
from pycommon.settings import BaseServiceSettings, configure_logging

__all__ = [
    "Alert",
    "AlertDraft",
    "BaseServiceSettings",
    "Database",
    "Event",
    "EventType",
    "Severity",
    "ValidationFailed",
    "configure_logging",
    "dict_row_factory",
    "install_error_handlers",
]
