"""trace.py: envelope-flag detection, redaction, and ring eviction."""
from __future__ import annotations

from webui.app.trace import CallTrace, redact


def test_complete_response_is_marked_complete():
    trace = CallTrace()
    trace.record(tool="get_inventory", arguments={}, elapsed_ms=12.0, outcome="ok",
                 response={"sites": [{"id": "1"}], "truncated": False, "returned_count": 1}, raw_bytes=40)
    record = trace.list()["records"][0]
    assert record["complete"] is True
    assert record["truncated"] is False
    assert record["has_more"] is False
    assert record["fanout_capped"] is False


def test_truncated_response_is_flagged_incomplete():
    trace = CallTrace()
    trace.record(tool="get_monitoring", arguments={}, elapsed_ms=5.0, outcome="ok",
                 response={"items": [], "truncated": True}, raw_bytes=10)
    record = trace.list()["records"][0]
    assert record["truncated"] is True
    assert record["complete"] is False


def test_cursor_present_means_more_results_available():
    trace = CallTrace()
    trace.record(tool="get_inventory", arguments={}, elapsed_ms=5.0, outcome="ok",
                 response={"sites": [], "next_cursor": "abc123", "truncated": False}, raw_bytes=10)
    record = trace.list()["records"][0]
    assert record["has_more"] is True
    assert record["complete"] is False


def test_fanout_capped_flag_is_read_from_the_envelope():
    trace = CallTrace()
    trace.record(tool="get_topology", arguments={}, elapsed_ms=5.0, outcome="ok",
                 response={"links": [], "leg_resolution_capped": True}, raw_bytes=10)
    record = trace.list()["records"][0]
    assert record["fanout_capped"] is True
    assert record["complete"] is False


def test_credential_redaction_never_stores_the_raw_value():
    trace = CallTrace()
    trace.record(
        tool="run_commands",
        arguments={"host": "10.0.0.1", "password": "sekrit", "commands": ["show version"]},
        elapsed_ms=1.0,
        outcome="ok",
        response={"results": []},
        raw_bytes=5,
    )
    record = trace.list()["records"][0]
    assert record["arguments"]["password"] == "[REDACTED]"
    assert "sekrit" not in str(record)


def test_redact_recurses_through_nested_structures():
    value = {"a": {"client_secret": "shh"}, "b": [{"auth_token": "shh2"}, "keep-me"]}
    cleaned = redact(value)
    assert cleaned["a"]["client_secret"] == "[REDACTED]"
    assert cleaned["b"][0]["auth_token"] == "[REDACTED]"
    assert cleaned["b"][1] == "keep-me"


def test_failed_call_is_still_recorded():
    trace = CallTrace()
    trace.record(tool="find_site", arguments={"name": "x"}, elapsed_ms=1.0, outcome="tool_error",
                 error={"code": "not_found", "message": "no match", "tool": "find_site", "retryable": False})
    record = trace.list()["records"][0]
    assert record["outcome"] == "tool_error"
    assert record["error"]["code"] == "not_found"


def test_ring_eviction_sets_dropped_flag():
    trace = CallTrace(max_records=3)
    for i in range(5):
        trace.record(tool="find_site", arguments={"i": i}, elapsed_ms=1.0, outcome="ok", response={})
    listing = trace.list()
    assert listing["count"] == 3
    assert listing["dropped_older_records"] is True
    assert [r["arguments"]["i"] for r in listing["records"]] == [2, 3, 4]


def test_clear_resets_records_and_dropped_flag():
    trace = CallTrace(max_records=2)
    for i in range(4):
        trace.record(tool="find_site", arguments={"i": i}, elapsed_ms=1.0, outcome="ok", response={})
    trace.clear()
    listing = trace.list()
    assert listing["records"] == []
    assert listing["dropped_older_records"] is False


def test_assistant_call_carries_the_question_id():
    trace = CallTrace()
    trace.record(tool="find_site", arguments={}, elapsed_ms=1.0, outcome="ok", response={}, question_id="q-1")
    record = trace.list()["records"][0]
    assert record["question_id"] == "q-1"
