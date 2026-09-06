"""Detects tool calls requesting elevated privileges or broad filesystem access."""

from __future__ import annotations

import re

from pycommon import AlertDraft, Event, Severity

from analyser.rules.base import RuleContext

#: Privilege escalation in a tool argument.
PRIVILEGE_PATTERNS: dict[str, re.Pattern[str]] = {
    "sudo": re.compile(r"\bsudo\b", re.IGNORECASE),
    "su_root": re.compile(r"\bsu\s+(-\s+)?root\b", re.IGNORECASE),
    "world_writable_chmod": re.compile(r"\bchmod\s+(-R\s+)?0?777\b", re.IGNORECASE),
    "setuid": re.compile(r"\bchmod\s+[ug]\+s\b", re.IGNORECASE),
}

#: Paths whose use as a tool argument implies unscoped filesystem reach.
BROAD_PATHS: tuple[str, ...] = ("/", "/*", "/etc", "/root", "/home", "/var", "~", "**")


class PrivilegedToolCallRule:
    """Flags `tool_call` events asking for root or whole-filesystem scope.

    Two distinct signals share one rule because they share a remediation: an
    agent that needs `sudo` or wants to walk `/` has been handed a tool grant
    that is too wide.

    Argument inspection is recursive over nested dicts and lists, since tool
    schemas routinely nest the interesting value a level or two down
    (`{"options": {"flags": ["--sudo"]}}`).
    """

    id = "privileged_tool_call"
    description = "Tool call requesting elevated privileges or broad filesystem access"

    def evaluate(self, event: Event, ctx: RuleContext) -> list[AlertDraft]:
        """Return one alert if the call requests privilege or broad scope.

        Ignores non-`tool_call` events. Emits at most one alert, with
        `details.signals` naming every match and `details.tool` naming the
        called tool. Returns `[]` when `payload.args` is absent or empty.
        """
        raise NotImplementedError


def collect_string_values(value: object, *, max_depth: int = 6) -> list[str]:
    """Flatten every string reachable inside a nested structure.

    Walks dicts and lists to `max_depth`, which bounds the work done on a
    hostile deeply-nested payload. Non-string scalars are stringified so that
    a path arriving as a Path-like or a number is still inspected.
    """
    raise NotImplementedError


def find_privilege_signals(values: list[str]) -> list[str]:
    """Return the names of :data:`PRIVILEGE_PATTERNS` matched by any value."""
    raise NotImplementedError


def find_broad_paths(values: list[str]) -> list[str]:
    """Return the :data:`BROAD_PATHS` entries a value equals exactly.

    Exact match, not substring: `/etc/hosts` is a specific file and should not
    be reported as broad `/etc` access.
    """
    raise NotImplementedError
