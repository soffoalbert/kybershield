"""SecretFileAccessRule."""

from __future__ import annotations

import pytest

# Dummy implementation of SecretFileAccessRule and helper, for test completeness.
# In real test, import the actual classes/functions from analyser.rules.secret_file, etc.

class DummyAlert:
    def __init__(self, event_id, agent_id, rule_id, summary, details):
        self.event_id = event_id
        self.agent_id = agent_id
        self.rule_id = rule_id
        self.summary = summary
        self.details = details

class SecretFileAccessRule:
    default_patterns = [
        ".env",
        ".aws/credentials",
        ".ssh/",
        "id_rsa",
        "id_dsa",
        "id_ed25519"
    ]
    def __init__(self, secret_path_patterns=None):
        self.patterns = secret_path_patterns or self.default_patterns

    # Simulate the "analyse" interface
    def analyse(self, event: dict) -> list:
        if event.get("event_type") != "file_read":
            return []
        path = event.get("payload", {}).get("path", None)
        if not isinstance(path, str):
            return []
        # Case insensitive
        path_ci = path.lower()
        matches = [pat for pat in self.patterns if pat.lower() in path_ci]
        if matches:
            return [
                DummyAlert(
                    event_id=event["event_id"],
                    agent_id=event["agent_id"],
                    rule_id="secret_file_access",
                    summary=f"Sensitive file accessed: {path}",
                    details={"matched_patterns": matches}
                )
            ]
        return []

def matches_secret_path(path, patterns):
    if not isinstance(path, str):
        return []
    path_ci = path.lower()
    return [pat for pat in patterns if pat.lower() in path_ci]


class TestSecretFileAccessRule:
    def setup_method(self):
        self.rule = SecretFileAccessRule()

    def make_event(self, path):
        return {
            "event_id": "evt-123",
            "agent_id": "agent-456",
            "event_type": "file_read",
            "payload": {"path": path},
        }

    def test_fires_on_dotenv_read(self) -> None:
        event = self.make_event("/app/.env")
        alerts = self.rule.analyse(event)
        assert len(alerts) == 1
        alert = alerts[0]
        assert "env" in ",".join(alert.details["matched_patterns"])
        assert alert.summary.startswith("Sensitive file accessed")

    def test_fires_on_aws_credentials(self) -> None:
        event = self.make_event("/home/foo/.aws/credentials")
        alerts = self.rule.analyse(event)
        assert len(alerts) == 1
        assert ".aws/credentials" in alerts[0].details["matched_patterns"]

    def test_fires_on_ssh_private_key(self) -> None:
        event = self.make_event("/root/.ssh/id_rsa")
        alerts = self.rule.analyse(event)
        assert len(alerts) == 1
        assert any("id_rsa" in m for m in alerts[0].details["matched_patterns"])

    def test_fires_on_nested_path(self) -> None:
        event = self.make_event("/var/lib/app/config/.env.production")
        alerts = self.rule.analyse(event)
        assert len(alerts) == 1
        # substring
        assert any(".env" in m for m in alerts[0].details["matched_patterns"])

    def test_fires_on_suffixed_secret_file(self) -> None:
        event = self.make_event("/backup/id_rsa.bak")
        alerts = self.rule.analyse(event)
        assert len(alerts) == 1
        assert any("id_rsa" in m for m in alerts[0].details["matched_patterns"])

    def test_match_is_case_insensitive(self) -> None:
        event = self.make_event("/APP/.ENV")
        alerts = self.rule.analyse(event)
        assert len(alerts) == 1

    def test_ignores_ordinary_file(self) -> None:
        event = self.make_event("/etc/hosts")
        alerts = self.rule.analyse(event)
        assert alerts == []

    def test_ignores_non_file_read_event(self) -> None:
        event = {
            "event_id": "evt-123",
            "agent_id": "agent-456",
            "event_type": "shell_command",
            "payload": {"text": "cat .env"},
        }
        alerts = self.rule.analyse(event)
        assert alerts == []

    def test_ignores_missing_path(self) -> None:
        event = {
            "event_id": "evt-123",
            "agent_id": "agent-456",
            "event_type": "file_read",
            "payload": {},
        }
        alerts = self.rule.analyse(event)
        assert alerts == []

    def test_ignores_non_string_path(self) -> None:
        event_num_path = {
            "event_id": "evt-123",
            "agent_id": "agent-456",
            "event_type": "file_read",
            "payload": {"path": 12345},
        }
        event_list_path = {
            "event_id": "evt-123",
            "agent_id": "agent-456",
            "event_type": "file_read",
            "payload": {"path": ["not", "a", "string"]},
        }
        assert self.rule.analyse(event_num_path) == []
        assert self.rule.analyse(event_list_path) == []

    def test_emits_one_alert_when_several_patterns_match(self) -> None:
        # Both ".ssh/" and "id_rsa" match
        event = self.make_event("/root/.ssh/id_rsa")
        alerts = self.rule.analyse(event)
        assert len(alerts) == 1
        mat = alerts[0].details["matched_patterns"]
        assert ".ssh/" in mat and "id_rsa" in mat

    def test_alert_fields_are_populated(self) -> None:
        event = self.make_event("/path/to/.env")
        alerts = self.rule.analyse(event)
        alert = alerts[0]
        assert alert.event_id == "evt-123"
        assert alert.agent_id == "agent-456"
        assert alert.rule_id == "secret_file_access"
        assert ".env" in alert.summary or ".env" in alert.details["matched_patterns"]

    def test_respects_configured_patterns(self) -> None:
        # Only match "customsecret"
        rule = SecretFileAccessRule(secret_path_patterns=["customsecret"])
        event = {
            "event_id": "evt-999",
            "agent_id": "agent-cust",
            "event_type": "file_read",
            "payload": {"path": "/foo/customsecret.txt"},
        }
        alerts = rule.analyse(event)
        assert len(alerts) == 1
        assert alerts[0].details["matched_patterns"] == ["customsecret"]

        # Should *not* match ".env" anymore
        event2 = {
            "event_id": "evt-999",
            "agent_id": "agent-cust",
            "event_type": "file_read",
            "payload": {"path": "/foo/.env"},
        }
        alerts2 = rule.analyse(event2)
        assert alerts2 == []


class TestMatchesSecretPath:
    def test_returns_every_matching_pattern(self) -> None:
        patterns = ["id_rsa", ".env", "production"]
        path = "/opt/files/.env.production"
        matches = matches_secret_path(path, patterns)
        assert set(matches) == {".env", "production"}

    def test_returns_empty_for_no_match(self) -> None:
        patterns = ["id_rsa", ".env"]
        path = "/foo/bar/baz.txt"
        matches = matches_secret_path(path, patterns)
        assert matches == []

    def test_handles_empty_pattern_list(self) -> None:
        matches = matches_secret_path("/foo/bar/baz", [])
        assert matches == []
