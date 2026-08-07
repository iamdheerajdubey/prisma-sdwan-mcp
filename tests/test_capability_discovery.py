import json

import pytest

from prisma_sdwan_mcp_v2 import runtime
from prisma_sdwan_mcp_v2.catalog import CapabilityCatalog, RegistryError
from prisma_sdwan_mcp_v2.tools.discovery import list_capabilities


def _call(**kwargs) -> dict:
    fn = getattr(list_capabilities, "fn", list_capabilities)
    return json.loads(fn(**kwargs))


def test_list_actions_returns_full_domain():
    catalog = CapabilityCatalog()
    actions = catalog.list_actions("routing_bgp_ospf")
    assert len(actions) == 20
    domain_count = next(d["action_count"] for d in catalog.domains() if d["domain"] == "routing_bgp_ospf")
    assert len(actions) == domain_count


def test_every_domain_is_fully_listable():
    catalog = CapabilityCatalog()
    for entry in catalog.domains():
        assert len(catalog.list_actions(entry["domain"])) == entry["action_count"]


def test_listed_actions_are_execution_ready():
    catalog = CapabilityCatalog()
    for action in catalog.list_actions("routing_bgp_ospf"):
        for key in ("action_id", "http_method", "path_parameters", "body_schema"):
            assert key in action


def test_unknown_domain_raises_registry_error():
    catalog = CapabilityCatalog()
    with pytest.raises(RegistryError):
        catalog.list_actions("not_a_domain")


def test_method_filter_partitions_domain():
    catalog = CapabilityCatalog()
    get_actions = catalog.list_actions("routing_bgp_ospf", method="GET")
    post_actions = catalog.list_actions("routing_bgp_ospf", method="POST")
    assert all(a["http_method"] == "GET" for a in get_actions)
    assert all(a["http_method"] == "POST" for a in post_actions)
    domain_count = next(d["action_count"] for d in catalog.domains() if d["domain"] == "routing_bgp_ospf")
    assert len(get_actions) + len(post_actions) == domain_count


def test_tool_lists_every_domain_without_truncation(monkeypatch):
    """The no-truncation guarantee lives in the tool, not the catalog.

    ``list_capabilities`` exposes no cursor, so anything ``collection_json``
    drops is unreachable rather than paginated. A shrunken response budget
    must not be able to hide actions.
    """
    monkeypatch.setenv("MCP_MAX_RESPONSE_BYTES", "8192")
    runtime.ensure_initialized()
    for entry in runtime.catalog.domains():
        payload = _call(domain=entry["domain"])
        assert payload.get("truncated") is False, entry["domain"]
        assert "next_cursor" not in payload, entry["domain"]
        assert len(payload["capabilities"]) == entry["action_count"], entry["domain"]


def test_tool_lists_every_domain_in_the_domain_index(monkeypatch):
    monkeypatch.setenv("MCP_MAX_RESPONSE_BYTES", "8192")
    runtime.ensure_initialized()
    payload = _call()
    assert payload.get("truncated") is False
    assert len(payload["domains"]) == len(runtime.catalog.domains())
    for entry in payload["domains"]:
        assert entry["next_call"] == f'list_capabilities(domain="{entry["domain"]}")'
