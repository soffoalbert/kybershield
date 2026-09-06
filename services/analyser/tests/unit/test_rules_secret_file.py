"""SecretFileAccessRule."""

from __future__ import annotations

import pytest


class TestSecretFileAccessRule:
    def test_fires_on_dotenv_read(self) -> None:
        """A read of /app/.env produces one high-severity alert."""
        pytest.skip("TODO: implement")

    def test_fires_on_aws_credentials(self) -> None:
        """A read of ~/.aws/credentials fires."""
        pytest.skip("TODO: implement")

    def test_fires_on_ssh_private_key(self) -> None:
        """A read of /root/.ssh/id_rsa fires."""
        pytest.skip("TODO: implement")

    def test_fires_on_nested_path(self) -> None:
        """A pattern buried deep in a path still matches, e.g.
        /var/lib/app/config/.env.production."""
        pytest.skip("TODO: implement")

    def test_fires_on_suffixed_secret_file(self) -> None:
        """Substring matching catches id_rsa.bak, which a basename equality
        check would miss. This is the reason for substring over parsing."""
        pytest.skip("TODO: implement")

    def test_match_is_case_insensitive(self) -> None:
        """/APP/.ENV fires, since filesystems and agents vary in casing."""
        pytest.skip("TODO: implement")

    def test_ignores_ordinary_file(self) -> None:
        """A read of /etc/hosts produces nothing."""
        pytest.skip("TODO: implement")

    def test_ignores_non_file_read_event(self) -> None:
        """A shell_command whose text happens to contain .env is not this
        rule's concern; the download_and_execute rule owns commands."""
        pytest.skip("TODO: implement")

    def test_ignores_missing_path(self) -> None:
        """A file_read with no payload.path returns [] rather than raising."""
        pytest.skip("TODO: implement")

    def test_ignores_non_string_path(self) -> None:
        """A path that arrives as a number or a list returns [] rather than
        raising, so a malformed payload cannot stall the batch."""
        pytest.skip("TODO: implement")

    def test_emits_one_alert_when_several_patterns_match(self) -> None:
        """/root/.ssh/id_rsa matches both .ssh/ and id_rsa but yields a single
        alert, with both named in details.matched_patterns. One finding should
        not be counted twice."""
        pytest.skip("TODO: implement")

    def test_alert_fields_are_populated(self) -> None:
        """event_id, agent_id, rule id, and a summary naming the path are all
        set on the draft."""
        pytest.skip("TODO: implement")

    def test_respects_configured_patterns(self) -> None:
        """A custom secret_path_patterns list replaces the defaults rather than
        extending them."""
        pytest.skip("TODO: implement")


class TestMatchesSecretPath:
    def test_returns_every_matching_pattern(self) -> None:
        """Returns all matches, not just the first."""
        pytest.skip("TODO: implement")

    def test_returns_empty_for_no_match(self) -> None:
        pytest.skip("TODO: implement")

    def test_handles_empty_pattern_list(self) -> None:
        pytest.skip("TODO: implement")
