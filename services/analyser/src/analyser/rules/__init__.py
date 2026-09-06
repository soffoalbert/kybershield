"""Rule registry.

Adding a detection is one new module plus one entry in :func:`default_rules`.
"""

from __future__ import annotations

from analyser.rules.base import Rule, RuleContext
from analyser.rules.domain_allowlist import DomainAllowlistRule
from analyser.rules.download_and_execute import DownloadAndExecuteRule
from analyser.rules.privileged_tool_call import PrivilegedToolCallRule
from analyser.rules.rapid_secret_reads import RapidSecretReadsRule
from analyser.rules.secret_file_access import SecretFileAccessRule

__all__ = [
    "DomainAllowlistRule",
    "DownloadAndExecuteRule",
    "PrivilegedToolCallRule",
    "RapidSecretReadsRule",
    "Rule",
    "RuleContext",
    "SecretFileAccessRule",
    "default_rules",
]


def default_rules() -> list[Rule]:
    """Return the rules the analyser runs, in evaluation order.

    Order does not affect results (rules are independent), but it does affect
    the order alerts are written within a batch, which keeps output stable
    across runs and therefore diffable in tests.
    """
    raise NotImplementedError
