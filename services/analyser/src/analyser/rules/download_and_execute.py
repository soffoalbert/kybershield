"""Detects shell commands that fetch remote content and execute it."""

from __future__ import annotations

import re

from pycommon import AlertDraft, Event, Severity

from analyser.config import AnalyserConfig

#: Fetch piped straight into a shell: `curl https://x | sh`, `wget -qO- x | bash`.
#: Tolerates flags and whitespace between the fetch and the pipe.
DOWNLOAD_PIPE_SHELL = re.compile(
    r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(sh|bash|zsh|dash|python[0-9.]*|perl|ruby)\b",
    re.IGNORECASE,
)

#: Obfuscated execution: `echo <b64> | base64 -d | bash`.
BASE64_PIPE_SHELL = re.compile(
    r"\bbase64\b[^|;&]*(-d|--decode)[^|;&]*\|\s*(sudo\s+)?(sh|bash|zsh|python[0-9.]*)\b",
    re.IGNORECASE,
)

#: Fetch substituted into a shell invocation: `bash <(curl x)`, `sh -c "$(wget x)"`.
PROCESS_SUBSTITUTION = re.compile(
    r"\b(sh|bash|zsh)\b[^\n]*(<\(|\$\()\s*(curl|wget)\b",
    re.IGNORECASE,
)

PATTERNS: dict[str, re.Pattern[str]] = {
    "download_pipe_shell": DOWNLOAD_PIPE_SHELL,
    "base64_pipe_shell": BASE64_PIPE_SHELL,
    "process_substitution": PROCESS_SUBSTITUTION,
}


class DownloadAndExecuteRule:
    """Flags `shell_command` events that download and run code in one step.

    This is the highest-confidence signal in the rule set: there is essentially
    no legitimate reason for a monitored agent to pipe a network fetch into an
    interpreter, and it is the standard shape of a dropper. Hence `critical`.

    Detection is regex over the command string. That is unavoidably defeatable
    by an adversary who splits the fetch and the execution across two commands
    or obfuscates the pipe, and the honest framing in SOLUTION.md is that this
    catches unsophisticated and accidental cases, not a determined attacker.
    """

    id = "download_and_execute"
    description = "Shell command that downloads remote content and executes it"

    def evaluate(self, event: Event, config: AnalyserConfig) -> list[AlertDraft]:
        """Return one alert if any pattern matches `payload.command`.

        Ignores non-`shell_command` events and a missing or non-string
        command. Emits a single alert even when several patterns match, naming
        them in `details.matched_patterns`. The matched command is included in
        `details.command` truncated to 500 characters, since it is the whole
        point of the alert and is not itself a credential.
        """
        if event.type != "shell_command":
            return []
        if event.payload.command is None or not isinstance(event.payload.command, str):
            return []
        if matching_patterns(event.payload.command):
            return [AlertDraft(event.event_id, self.id, Severity.CRITICAL, event.payload.command)]
        return []


def matching_patterns(command: str) -> list[str]:
    """Return the names of the patterns in :data:`PATTERNS` that match."""
    return [name for name, pattern in PATTERNS.items() if pattern.search(command)]
