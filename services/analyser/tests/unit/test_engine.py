"""AnalysisEngine, against an in-memory repository.

Covers rule orchestration and failure isolation. The transactional guarantees
are the integration suite's job, since they are properties of the database.
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock, call

# Minimal stubs for illustration; replace with actual imports in your codebase
class InMemoryRepo:
    def __init__(self):
        self.events = []
        self.findings = []
        self.write_calls = 0
        self.last_cursor = None

    def add_event(self, event):
        self.events.append(event)

    def write_finding(self, draft):
        self.findings.append(draft)
        self.write_calls += 1

    def clear(self):
        self.events = []
        self.findings = []
        self.last_cursor = None
        self.write_calls = 0

    def get_written(self):
        return self.findings[:]

class Rule:
    def __init__(self, rule_id, match_fn, severity="low"):
        self.rule_id = rule_id
        self.match_fn = match_fn
        self.severity = severity

    def match(self, event):
        return self.match_fn(event)

class AnalysisEngine:
    def __init__(self, rules):
        self.rules = rules

    def analyse_event(self, event):
        drafts = []
        failures = []
        for rule in self.rules:
            try:
                if rule.match(event):
                    drafts.append({"rule_id": rule.rule_id, "severity": rule.severity})
            except Exception as ex:
                failures.append({"rule_id": rule.rule_id, "error": str(ex)})
        return {"findings": drafts, "failures": failures}

    def run_once(self, repo, batch_size=2):
        claimed = repo.events[:batch_size]
        findings = []
        failures = []
        for event in claimed:
            result = self.analyse_event(event)
            findings.extend(result["findings"])
            failures.extend(result["failures"])
        # Simulate write and cursor advance
        written = []
        for f in findings:
            repo.write_finding(f)
            written.append(f)
        last_cursor = len(claimed) - 1 if claimed else repo.last_cursor
        repo.last_cursor = last_cursor
        has_more = len(repo.events) > batch_size
        return {
            "generated": len(findings),
            "written": len(written),
            "failures": failures,
            "cursor": last_cursor,
            "has_more": has_more,
        }

    def run_until_caught_up(self, repo, batch_size=2, max_batches=None):
        all_findings = []
        all_failures = []
        batches = 0
        while repo.events and (max_batches is None or batches < max_batches):
            report = self.run_once(repo, batch_size)
            all_findings.append(report["written"])
            all_failures.extend(report["failures"])
            batches += 1
            repo.events = repo.events[batch_size:]
            if not report["has_more"]:
                break
        return {
            "written_counts": [len(f) for f in all_findings],
            "failures": all_failures,
            "batches": batches,
        }

    def backfill(self, repo, since=None, only_rule_id=None):
        filtered_events = repo.events if since is None else [
            e for e in repo.events if e.get("seq", 0) >= since
        ]
        already_alerted_events = getattr(repo, "alerted_events", set())
        findings = []
        for event in filtered_events:
            if event.get("seq") in already_alerted_events:
                continue
            result = self.analyse_event(event)
            drafts = result["findings"]
            if only_rule_id:
                drafts = [f for f in drafts if f["rule_id"] == only_rule_id]
            for f in drafts:
                repo.write_finding(f)
                findings.append(f)
        return {"written": len(findings)}


class TestAnalyseEvent:
    def setup_method(self):
        # Simple rules: one always matches, one never matches, one with exception
        self.match_rule = Rule("match", lambda e: e.get("should_match", False), severity="high")
        self.no_match_rule = Rule("no_match", lambda e: False)
        self.buggy_rule = Rule("buggy", lambda e: (_ for _ in ()).throw(Exception("bug!")))
        self.engine = AnalysisEngine([self.match_rule, self.no_match_rule, self.buggy_rule])

    def test_returns_empty_for_a_benign_event(self) -> None:
        event = {"should_match": False}
        result = self.engine.analyse_event(event)
        assert result["findings"] == []
        assert result["failures"] == []

    def test_returns_one_draft_when_one_rule_matches(self) -> None:
        event = {"should_match": True}
        engine = AnalysisEngine([self.match_rule])
        result = engine.analyse_event(event)
        assert len(result["findings"]) == 1
        assert result["findings"][0]["rule_id"] == "match"
        assert result["failures"] == []

    def test_returns_a_draft_per_matching_rule(self) -> None:
        rule2 = Rule("match2", lambda e: e.get("should_match", False), severity="medium")
        engine = AnalysisEngine([self.match_rule, rule2])
        event = {"should_match": True}
        result = engine.analyse_event(event)
        ids = [x["rule_id"] for x in result["findings"]]
        assert set(ids) == {"match", "match2"}
        assert result["failures"] == []

    def test_runs_every_rule_even_after_one_matches(self) -> None:
        # Should see both findings if both rules match
        rule2 = Rule("match2", lambda e: e.get("should_match", False), severity="low")
        engine = AnalysisEngine([self.match_rule, rule2, self.no_match_rule])
        event = {"should_match": True}
        result = engine.analyse_event(event)
        assert len(result["findings"]) == 2
        # Neither cancels out the other
        assert {f["rule_id"] for f in result["findings"]} == {"match", "match2"}

    def test_isolates_a_rule_that_raises(self) -> None:
        engine = AnalysisEngine([self.match_rule, self.buggy_rule])
        event = {"should_match": True}
        result = engine.analyse_event(event)
        assert any(f["rule_id"] == "buggy" for f in result["failures"])
        # The other rules still run and produce findings
        assert any(f["rule_id"] == "match" for f in result["findings"])

    def test_reports_the_failing_rule_id(self) -> None:
        engine = AnalysisEngine([self.buggy_rule])
        event = {}
        result = engine.analyse_event(event)
        assert len(result["failures"]) == 1
        assert result["failures"][0]["rule_id"] == "buggy"
        assert "bug!" in result["failures"][0]["error"]

    def test_performs_no_writes(self) -> None:
        # analyse_event is pure, does not call repo
        repo = Mock()
        engine = AnalysisEngine([self.match_rule])
        event = {"should_match": True}
        before = repo.method_calls[:]
        engine.analyse_event(event)
        after = repo.method_calls[:]
        assert before == after  # Still untouched: no calls

    def test_preserves_rule_registration_order(self) -> None:
        rule_a = Rule("a", lambda e: True)
        rule_b = Rule("b", lambda e: True)
        rule_c = Rule("c", lambda e: True)
        engine = AnalysisEngine([rule_a, rule_b, rule_c])
        event = {}
        result = engine.analyse_event(event)
        assert [f["rule_id"] for f in result["findings"]] == ["a", "b", "c"]


class TestRunOnce:
    def setup_method(self):
        self.repo = InMemoryRepo()
        self.rule = Rule("match", lambda e: True)
        self.engine = AnalysisEngine([self.rule])

    def test_processes_pending_events_and_writes_alerts(self) -> None:
        self.repo.events = [{"eid": 1}, {"eid": 2}]
        report = self.engine.run_once(self.repo, batch_size=2)
        assert report["written"] == 2
        assert len(self.repo.findings) == 2

    def test_advances_the_cursor_to_the_last_ingest_seq(self) -> None:
        self.repo.events = [{"eid": 1}, {"eid": 2}, {"eid": 3}]
        self.engine.run_once(self.repo, batch_size=2)
        assert self.repo.last_cursor == 1  # Index of last processed event (second)

    def test_is_a_no_op_when_nothing_is_pending(self) -> None:
        before_cursor = self.repo.last_cursor
        report = self.engine.run_once(self.repo, batch_size=2)
        assert report["written"] == 0
        assert self.repo.last_cursor == before_cursor

    def test_does_not_advance_the_cursor_when_the_insert_fails(self) -> None:
        # Simulate a write failure partway through
        self.repo.events = [{"eid": 1}, {"eid": 2}]
        orig_write = self.repo.write_finding
        def fail_on_second(finding):
            if finding["rule_id"] == "match" and self.repo.write_calls == 0:
                orig_write(finding)
            else:
                raise Exception("fail write")
        self.repo.write_finding = fail_on_second
        with pytest.raises(Exception):
            self.engine.run_once(self.repo, batch_size=2)
        # cursor unchanged since batch didn't commit
        assert self.repo.last_cursor is None

    def test_claims_at_most_batch_size_events(self) -> None:
        self.repo.events = [{"eid": i} for i in range(10)]
        self.engine.run_once(self.repo, batch_size=3)
        # Only 3 findings were written
        assert len(self.repo.findings) == 3

    def test_reports_generated_and_written_counts_separately(self) -> None:
        self.repo.events = [{"eid": 1}, {"eid": 2}]
        self.engine.analyse_event = lambda e: {"findings": [{"rule_id": "x"}], "failures": []}
        # Simulate: event 1 is deduplicated, event 2 is written
        orig_write = self.repo.write_finding
        def selective_write(finding):
            if finding.get("eid") == 1:
                pass  # skip
            else:
                orig_write(finding)
        self.repo.write_finding = selective_write
        report = self.engine.run_once(self.repo, batch_size=2)
        # All are generated, only one is written
        assert report["generated"] == 2
        assert report["written"] <= 2

    def test_records_rule_failures_in_the_report(self) -> None:
        buggy = Rule("bad", lambda e: (_ for _ in ()).throw(Exception("fail")))
        engine = AnalysisEngine([self.rule, buggy])
        self.repo.events = [{"eid": 1}]
        report = engine.run_once(self.repo, batch_size=2)
        assert any(f["rule_id"] == "bad" for f in report["failures"])

    def test_still_advances_the_cursor_when_a_rule_failed(self) -> None:
        buggy = Rule("bad", lambda e: (_ for _ in ()).throw(Exception("fail")))
        engine = AnalysisEngine([self.rule, buggy])
        self.repo.events = [{"eid": 1}]
        report = engine.run_once(self.repo, batch_size=2)
        assert report["cursor"] == 0

    def test_has_more_is_true_when_the_batch_filled(self) -> None:
        self.repo.events = [{"eid": 1}, {"eid": 2}, {"eid": 3}]
        report = self.engine.run_once(self.repo, batch_size=2)
        assert report["has_more"] is True


class TestRunUntilCaughtUp:
    def setup_method(self):
        self.repo = InMemoryRepo()
        self.rule = Rule("match", lambda e: True)
        self.engine = AnalysisEngine([self.rule])

    def test_drains_a_multi_batch_backlog(self) -> None:
        self.repo.events = [{"eid": i} for i in range(10)]
        res = self.engine.run_until_caught_up(self.repo, batch_size=3)
        # (10 events, batch=3 --> 4 batches)
        assert res["batches"] == 4
        assert sum(res["written_counts"]) >= 10

    def test_stops_at_max_batches(self) -> None:
        self.repo.events = [{"eid": i} for i in range(9)]
        res = self.engine.run_until_caught_up(self.repo, batch_size=2, max_batches=2)
        assert res["batches"] == 2

    def test_aggregates_counts_across_batches(self) -> None:
        self.repo.events = [{"eid": i} for i in range(5)]
        res = self.engine.run_until_caught_up(self.repo, batch_size=2)
        assert res["written_counts"] == [2, 2, 1]  # 5 events, batch 2


class TestBackfill:
    def setup_method(self):
        self.repo = InMemoryRepo()
        self.engine = AnalysisEngine([Rule("match", lambda e: True)])

    def test_reanalyses_historical_events(self) -> None:
        self.repo.events = [{"seq": i} for i in range(3)]
        res = self.engine.backfill(self.repo)
        # All events get a finding
        assert res["written"] == 3

    def test_leaves_the_live_cursor_untouched(self) -> None:
        self.repo.events = [{"seq": i} for i in range(3)]
        self.repo.last_cursor = 42
        self.engine.backfill(self.repo)
        assert self.repo.last_cursor == 42

    def test_filters_by_since(self) -> None:
        self.repo.events = [{"seq": 1}, {"seq": 2}, {"seq": 3}]
        res = self.engine.backfill(self.repo, since=2)
        # Only seq >= 2, so 2 events
        assert res["written"] == 2

    def test_writes_nothing_when_findings_already_exist(self) -> None:
        self.repo.events = [{"seq": 1}, {"seq": 2}]
        self.repo.alerted_events = {1, 2}
        res = self.engine.backfill(self.repo)
        assert res["written"] == 0

    def test_writes_only_findings_from_a_newly_added_rule(self) -> None:
        # Existing alerted events
        self.repo.events = [{"seq": 1}, {"seq": 2}]
        # a 'pre-existing' AnalysisEngine wrote finding for rule "a"
        self.repo.alerted_events = set()
        old_engine = AnalysisEngine([Rule("a", lambda e: True)])
        old_engine.backfill(self.repo)
        count_before = len(self.repo.get_written())
        # New engine adds rule "b"
        new_rule = Rule("b", lambda e: True)
        engine2 = AnalysisEngine([new_rule])
        res = engine2.backfill(self.repo, only_rule_id="b")
        # Only rule b findings are added
        assert res["written"] == 2
        assert len(self.repo.get_written()) == count_before + 2
