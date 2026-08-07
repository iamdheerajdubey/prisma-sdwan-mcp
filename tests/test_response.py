import json

from prisma_sdwan_mcp_v2.response import collection_json


def test_collection_paginates_with_cursor():
    first = json.loads(collection_json("t", "s", "items", [{"id": i} for i in range(5)], limit=2))
    assert first["returned_count"] == 2
    assert first["truncated"] is True
    second = json.loads(collection_json("t", "s", "items", [{"id": i} for i in range(5)], limit=2, cursor=first["next_cursor"]))
    assert [x["id"] for x in second["items"]] == [2, 3]


def test_invalid_cursor_is_structured_error():
    result = json.loads(collection_json("t", "s", "items", [{"id": 1}], cursor="bad", limit=1))
    assert result["code"] == "invalid_cursor"
