import json

from prisma_sdwan_mcp.formatting import build_envelope, monitor_body


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