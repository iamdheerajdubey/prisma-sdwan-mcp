import json

from prisma_sdwan_mcp.response import collection_json, single_json


def test_oversize_single_object_is_outlined_not_stubbed(monkeypatch):
    """A single object cannot be paged, so describe it instead of dropping it."""
    monkeypatch.setenv("MCP_MAX_RESPONSE_BYTES", "4096")
    blob = {
        "window": {"start": "t0", "end": "t1"},
        "links": [{"path_id": f"p{i}", "admin_up": True} for i in range(600)],
    }
    payload = json.loads(single_json("t", "s", "result", blob))
    assert payload["truncated"] is True
    assert payload["result"]["window"] == {"start": "t0", "end": "t1"}  # small values kept verbatim
    assert payload["result"]["links"]["count"] == 600                   # big ones described
    assert payload["result"]["links"]["bytes"] > 0
    assert "path_id" in payload["result"]["links"]["item_fields"]
    assert "warning" in payload


def test_collection_paginates_with_cursor():
    first = json.loads(collection_json("t", "s", "items", [{"id": i} for i in range(5)], limit=2))
    assert first["returned_count"] == 2
    assert first["truncated"] is True
    second = json.loads(collection_json("t", "s", "items", [{"id": i} for i in range(5)], limit=2, cursor=first["next_cursor"]))
    assert [x["id"] for x in second["items"]] == [2, 3]


def test_invalid_cursor_is_structured_error():
    result = json.loads(collection_json("t", "s", "items", [{"id": 1}], cursor="bad", limit=1))
    assert result["code"] == "invalid_cursor"


def test_cursor_from_another_tool_is_rejected():
    first = json.loads(collection_json("tool_a", "s", "items", [{"id": i} for i in range(5)], limit=2))
    other = json.loads(collection_json("tool_b", "s", "items", [{"id": i} for i in range(5)], limit=2, cursor=first["next_cursor"]))
    assert other["code"] == "invalid_cursor"


def _wide(count, **overrides):
    """Records wide enough to trip the compaction threshold.

    Values must vary per record: a field with the same value everywhere is
    hoisted losslessly into shared_fields and never reaches the lossy pass.
    """
    out = []
    for i in range(count):
        record = {
            "id": f"id-{i}",
            "name": f"device-{i}",
            "state": f"bound-{i}",
            "correlation_id": f"{i}" + "c" * 120,
            "policy_info": f"{i}" + "p" * 120,
            "entity_ref": f"{i}" + "e" * 120,
        }
        record.update(overrides)
        out.append(record)
    return out


def test_small_response_is_left_alone():
    payload = json.loads(collection_json("t", "s", "items", [{"id": 1, "junk": "x"}], limit=10))
    assert payload["items"] == [{"id": 1, "junk": "x"}]
    assert "omitted_fields" not in payload


def test_wide_health_records_are_compacted_and_disclose_what_was_held():
    payload = json.loads(collection_json("t", "s", "items", _wide(60), limit=200))
    assert set(payload["omitted_fields"]) == {"policy_info", "entity_ref"}
    assert "omitted_fields_reason" in payload
    # identity (including *_id joins) and condition always survive
    assert set(payload["items"][0]) == {"id", "name", "state", "correlation_id"}


def test_detail_full_disables_compaction():
    payload = json.loads(collection_json("t", "s", "items", _wide(60), limit=200, detail="full"))
    assert "omitted_fields" not in payload
    assert "correlation_id" in payload["items"][0]


def test_dominant_field_is_never_held_back():
    """A field that is most of the record IS the record (service binding maps)."""
    records = [{"id": f"id-{i}", "name": f"map-{i}", "state": f"up-{i}", "service_bindings": f"{i}" + "b" * 4000} for i in range(20)]
    payload = json.loads(collection_json("t", "s", "items", records, limit=200))
    assert "service_bindings" in payload["items"][0]


def test_content_only_records_are_not_stripped_to_identifiers():
    """No condition field means this is a content read, not a health read."""
    records = [{"id": f"id-{i}", "name": f"app-{i}", "category": f"{i}" + "c" * 200, "ports": f"{i}" + "p" * 200} for i in range(60)]
    payload = json.loads(collection_json("t", "s", "items", records, limit=200))
    assert "omitted_fields" not in payload
    assert "category" in payload["items"][0]


def test_lossless_passes_keep_every_value():
    records = _wide(60, tenant_id="same-for-all", unused=None)
    payload = json.loads(collection_json("t", "s", "items", records, limit=200))
    assert payload["shared_fields"]["tenant_id"] == "same-for-all"   # hoisted, not lost
    assert "unused" in payload["omitted_empty_fields"]               # empty everywhere


# --- match_named: exact wins over substring ------------------------------

from prisma_sdwan_mcp.tools.common import match_named

# Interface names as a real ion 5200 reports them: bare numbers, plus
# service links whose names embed those same digits.
REAL_INTERFACE_NAMES = [
    {"id": "i1", "name": "1"},
    {"id": "i15", "name": "15"},
    {"id": "i17", "name": "17"},
    {"id": "i1315", "name": "1315"},
    {"id": "isl", "name": "MEMPHISHQ_1785862894648014296_ACT_SL"},
]


def test_exact_name_wins_over_substring():
    assert [x["id"] for x in match_named(REAL_INTERFACE_NAMES, "1")] == ["i1"]
    assert [x["id"] for x in match_named(REAL_INTERFACE_NAMES, "17")] == ["i17"]


def test_exact_id_wins_over_everything():
    assert [x["id"] for x in match_named(REAL_INTERFACE_NAMES, "i15")] == ["i15"]


def test_substring_is_the_fallback_not_the_default():
    matches = match_named(REAL_INTERFACE_NAMES, "13")
    assert {x["id"] for x in matches} == {"i1315"}
    assert {x["id"] for x in match_named(REAL_INTERFACE_NAMES, "MEMPHIS")} == {"isl"}


def test_match_is_case_insensitive_and_trims():
    assert [x["id"] for x in match_named(REAL_INTERFACE_NAMES, "  memphishq_1785862894648014296_act_sl ")] == ["isl"]


def test_multi_field_match_checks_each_field_independently():
    apps = [{"id": "a1", "display_name": "Office 365", "name": "office365"}, {"id": "a2", "display_name": "Office 365 Login", "name": "o365-login"}]
    assert [x["id"] for x in match_named(apps, "office365", ("display_name", "name"))] == ["a1"]
    assert {x["id"] for x in match_named(apps, "office", ("display_name", "name"))} == {"a1", "a2"}
