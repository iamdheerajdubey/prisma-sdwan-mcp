import json
from datetime import datetime

import pytest

from prisma_sdwan_mcp import formatting
from prisma_sdwan_mcp.formatting import (
    ERROR_CODES,
    build_envelope,
    collection_response,
    monitor_body,
    project_record,
    single_response,
    structured_error,
)
from prisma_sdwan_mcp.limits import LIMITS
from prisma_sdwan_mcp.resources import contract_resource


def test_large_collection_is_budgeted_and_pages_to_completion():
    items = [{"id": index, "payload": "x" * 900} for index in range(5000)]
    budget = 4096
    cursor = None
    seen = []

    while True:
        payload_text = build_envelope("synthetic", "Synthetic records", "items", items, budget, cursor)
        assert len(payload_text.encode("utf-8")) <= budget
        payload = json.loads(payload_text)
        seen.extend(item["id"] for item in payload["items"])
        if not payload["truncated"]:
            break
        cursor = payload["next_cursor"]

    assert len(seen) == len(items)
    assert seen == list(range(5000))


def test_budget_truncation_identifies_the_applied_limit():
    payload = json.loads(
        build_envelope(
            "synthetic",
            "Synthetic records",
            "items",
            [{"id": index, "payload": "x" * 900} for index in range(20)],
            4096,
        )
    )

    assert payload["truncated"] is True
    assert payload["limits_applied"][0]["limit"] == "response_bytes"


def test_collection_envelope_keys_and_cursor_are_conditional():
    complete = json.loads(
        build_envelope("synthetic", "Synthetic records", "items", [{"id": 1}], 4096)
    )
    required = {
        "tool",
        "summary",
        "items",
        "truncated",
        "total_count",
        "returned_count",
        "retrieved_at",
    }
    assert required <= complete.keys()
    assert "next_cursor" not in complete

    truncated = json.loads(
        build_envelope(
            "synthetic",
            "Synthetic records",
            "items",
            [{"id": index, "payload": "x" * 900} for index in range(20)],
            4096,
        )
    )
    assert required <= truncated.keys()
    assert truncated["truncated"] is True
    assert truncated["next_cursor"]


def test_malformed_cursor_is_a_structured_error():
    payload = json.loads(
        build_envelope("synthetic", "Synthetic records", "items", [{"id": 1}], 4096, "bad")
    )

    assert payload["code"] == "invalid_cursor"
    assert payload["tool"] == "synthetic"
    assert payload["status_code"] == 400


def test_binary_malformed_cursor_is_a_structured_error():
    payload = json.loads(
        build_envelope("synthetic", "Synthetic records", "items", [{"id": 1}], 4096, "%%%")
    )

    assert payload["code"] == "invalid_cursor"


def test_explicit_zero_budget_is_rejected():
    payload = json.loads(
        build_envelope("synthetic", "Synthetic records", "items", [], 0)
    )

    assert payload["code"] == "invalid_budget"


def test_oversized_item_returns_identifiers_not_truncated_json():
    item = {"id": "large-1", "name": "large", "payload": "x" * 10000}
    payload_text = build_envelope("synthetic", "Synthetic records", "items", [item], 512)
    payload = json.loads(payload_text)

    assert len(payload_text.encode("utf-8")) <= 512
    assert payload["items"] == [{"id": "large-1", "name": "large"}]
    assert payload["error"]["code"] == "item_too_large"


def test_monitor_body_uses_interval_without_end_time():
    body = monitor_body("2026-08-01T00:00:00Z", 3600, ["BandwidthUsage"], {"site_id": "site-1"})

    assert body == {
        "start_time": "2026-08-01T00:00:00Z",
        "interval": 3600,
        "metrics": ["BandwidthUsage"],
        "filter": {"site_id": "site-1"},
    }
    assert "end_time" not in body


def _parse_iso(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def test_envelope_and_single_response_carry_iso_retrieved_at():
    envelope = json.loads(build_envelope("synthetic", "s", "items", [{"id": 1}], 4096))
    single = json.loads(single_response("synthetic", "s", "item", {"id": 1}, 4096))

    assert _parse_iso(envelope["retrieved_at"])
    assert _parse_iso(single["retrieved_at"])


def test_structured_error_marks_transient_failures_retryable():
    rate_limited = structured_error("upstream_error", "m", "t", 429)
    assert rate_limited["code"] == "rate_limited"
    assert rate_limited["retryable"] is True
    assert structured_error("upstream_error", "m", "t", 503)["retryable"] is True
    assert structured_error("upstream_error", "m", "t", 400)["retryable"] is False
    assert structured_error("upstream_error", "m", "t", None)["retryable"] is False
    assert "status_code" not in structured_error("upstream_error", "m", "t", None)
    for code in ("invalid_argument", "invalid_limit", "invalid_cursor", "invalid_budget"):
        assert structured_error(code, "m", "t", 500)["retryable"] is False
    assert structured_error("not_found", "m", "t", 404)["retryable"] is False


def test_structured_error_rejects_unknown_codes_and_contract_lists_enforced_codes():
    with pytest.raises(ValueError, match="unknown error code"):
        structured_error("invented_code", "m", "t")

    payload = json.loads(contract_resource())
    assert set(payload["error_codes"]) == set(ERROR_CODES)
    assert set(payload["limits"]) == set(LIMITS)
    assert "retrieved_at" in payload["frozen_envelope_keys"]


def test_rate_limit_error_preserves_retry_accounting():
    payload = json.loads(
        collection_response(
            "synthetic",
            "Unavailable",
            "items",
            {
                "error": "rate limited",
                "status_code": 429,
                "retry_count": 3,
                "elapsed_seconds": 2.5,
            },
            budget=4096,
        )
    )

    assert payload["code"] == "rate_limited"
    assert payload["retryable"] is True
    assert payload["retry_count"] == 3
    assert payload["elapsed_seconds"] == 2.5


def test_limits_registry_entries_are_recoverable_or_explain_their_reason():
    assert all(limit.recovery or limit.reason for limit in LIMITS.values())
    assert {
        "response_bytes",
        "events_limit",
        "alarms_limit",
        "relative_hours",
        "flow_digest_sample",
        "raw_flow_limit",
        "top_talkers",
        "identifying_value",
        "retry_attempts",
        "retry_wall_seconds",
        "cli_connect_timeout",
        "cli_read_timeout",
        "cli_pagination_pages",
        "cli_error_length",
        "cli_output_bytes",
        "leg_resolution",
    } == set(LIMITS)


def test_projected_fields_reported_only_when_a_projection_is_applied():
    record = {"id": "1", "name": "n", "dropped": "x"}

    projected = json.loads(
        collection_response("synthetic", "s", "items", [record], {"id", "name"}, budget=4096)
    )
    unprojected = json.loads(
        collection_response("synthetic", "s", "items", [record], None, budget=4096)
    )

    assert projected["projected_fields"] == ["id", "name"]
    assert "dropped" not in projected["items"][0]
    assert "projected_fields" not in unprojected


def test_recursion_guard_returns_budget_error_not_invalid_limit(monkeypatch):
    real = formatting.compact_json
    calls = {"n": 0}

    def inflating(data):
        # let the fit probe pass, then make the final serialization look oversized so
        # the retry path is reached with exactly one selected item (limit would be 0)
        calls["n"] += 1
        text = real(data)
        if isinstance(data, dict) and "returned_count" in data and calls["n"] > 1:
            return text + " " * 10000
        return text

    monkeypatch.setattr(formatting, "compact_json", inflating)
    payload = json.loads(build_envelope("synthetic", "s", "items", [{"id": 1}], 4096))

    assert payload["code"] == "response_budget_too_small"


def test_unprojected_records_keep_upstream_fields():
    event = {
        "code": "NETWORK_ANYNETLINK_DOWN",
        "entity_ref": "element/el-1",
        "info": {"reason": "keepalive-timeout", "empty": None},
        "vendor_noise": "keep me",
    }

    unprojected = json.loads(
        collection_response("synthetic", "s", "events", [event], None, budget=4096)
    )

    assert unprojected["events"][0]["code"] == "NETWORK_ANYNETLINK_DOWN"
    assert unprojected["events"][0]["entity_ref"] == "element/el-1"
    assert unprojected["events"][0]["info"] == {"reason": "keepalive-timeout"}
    assert unprojected["events"][0]["vendor_noise"] == "keep me"
    assert "projected_fields" not in unprojected

def test_every_error_code_in_the_source_is_registered():
    """The closed set is only closed if nothing in the source escapes it.

    structured_error raises on an unregistered code, and callers wrap tools in
    a broad `except Exception` -- so an unregistered code does not surface as a
    loud failure, it silently degrades an actionable 400 into a generic
    `internal_error` marked `retryable: True`. That tells a caller to retry a
    request that can never succeed. This test is what makes the raise safe.
    """
    import re
    from pathlib import Path

    from prisma_sdwan_mcp.formatting import ERROR_CODES

    source_root = Path(__file__).resolve().parents[1] / "prisma_sdwan_mcp"
    pattern = re.compile(r"(?:error_json|structured_error)\(\s*[\"']([a-z_]+)[\"']")
    used = set()
    for path in source_root.rglob("*.py"):
        used |= set(pattern.findall(path.read_text(encoding="utf-8")))

    assert used, "found no error codes in the source -- the scan pattern is wrong"
    assert used <= ERROR_CODES, (
        f"error codes used in source but missing from ERROR_CODES: "
        f"{sorted(used - ERROR_CODES)}"
    )


def test_details_cannot_overwrite_reserved_error_fields():
    payload = structured_error(
        "partial_response",
        "some families failed",
        "find_policy_set",
        207,
        details={
            "code": "hijacked",
            "retryable": "yes",
            "tool": "other_tool",
            "status_code": 999,
            "family_errors": {"priority": "boom"},
        },
    )

    assert payload["code"] == "partial_response"
    assert payload["retryable"] is False
    assert payload["tool"] == "find_policy_set"
    assert payload["status_code"] == 207
    assert payload["family_errors"] == {"priority": "boom"}
