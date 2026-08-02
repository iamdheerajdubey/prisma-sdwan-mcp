import json
import os
from pathlib import Path

import pytest

import prisma_sdwan_mcp_server as server
from prisma_sdwan_mcp import registry
from prisma_sdwan_mcp.config import get_max_response_bytes
from prisma_sdwan_mcp.tools.config_gen import generate_site_config
from prisma_sdwan_mcp.tools.inventory import (
    get_app_defs,
    get_elements,
    get_machines,
    get_sites,
)
from prisma_sdwan_mcp.tools.monitoring import (
    get_alarms,
    get_element_status,
    get_events,
    get_flows,
    get_interface_status,
    get_link_metrics,
    get_probe_metrics,
    get_software_status,
)
from prisma_sdwan_mcp.tools.network import (
    get_basenet_topology,
    get_interfaces,
    get_site_paths,
    get_topology,
    get_wan_interfaces,
    get_vpnlink_state,
    get_vpnlink_status,
)
from prisma_sdwan_mcp.tools.policy import (
    get_path_groups,
    get_policy_sets,
    get_security_zones,
    get_service_labels,
    get_wan_networks,
)
from prisma_sdwan_mcp.tools.resolve import (
    find_app,
    find_element,
    find_machine,
    find_path_group,
    find_policy_set,
    find_security_zone,
    find_service_label,
    find_site,
    find_wan_network,
    resolve_path,
)
from prisma_sdwan_mcp.tools.routing import (
    get_bgp_peers,
    get_bgp_prefixes,
    get_bgp_status,
    get_static_routes,
)


# Point these at real IDs in your own tenant via env vars when running
# `pytest -m live` locally; the defaults are inert placeholders.
SITE_ID = os.getenv("TEST_LIVE_SITE_ID", "0")
ELEMENT_ID = os.getenv("TEST_LIVE_ELEMENT_ID", "0")
BGPPEER_ID = os.getenv("TEST_LIVE_BGPPEER_ID", "0")


def _first_vpnlink_id() -> str:
    topology = registry.client.call_sdk_post(
        registry.client.sdk.post.topology, {"type": "anynet"}
    )
    links = topology.get("links", []) if isinstance(topology, dict) else []
    for link in links:
        legs = link.get("vpnlinks", []) or [] if isinstance(link, dict) else []
        if legs:
            leg_id = legs[0] if isinstance(legs[0], str) else (legs[0].get("vpnlink_id") or legs[0].get("id"))
            if leg_id is not None:
                return str(leg_id)
    return "0"


@pytest.mark.live
def test_live_tools_return_bounded_json(tmp_path, monkeypatch):
    monkeypatch.setenv("PRISMA_MCP_OUTPUT_DIR", str(tmp_path))
    vpnlink_id = _first_vpnlink_id()
    calls = [
        ("get_sites", get_sites()),
        ("get_elements", get_elements()),
        ("get_machines", get_machines()),
        ("get_app_defs", get_app_defs()),
        ("find_site", find_site("azure")),
        ("find_element", find_element("ion")),
        ("find_app", find_app("zoom")),
        ("find_machine", find_machine("ion")),
        ("find_policy_set", find_policy_set("enterprise")),
        ("find_security_zone", find_security_zone("lan")),
        ("find_wan_network", find_wan_network("mpls")),
        ("find_path_group", find_path_group("direct")),
        ("find_service_label", find_service_label("gold")),
        ("get_topology", get_topology()),
        ("get_basenet_topology", get_basenet_topology(SITE_ID)),
        ("get_interfaces", get_interfaces(SITE_ID, ELEMENT_ID)),
        ("get_wan_interfaces", get_wan_interfaces(SITE_ID)),
        ("get_interface_status", get_interface_status(SITE_ID, ELEMENT_ID)),
        ("get_element_status", get_element_status(ELEMENT_ID)),
        ("get_software_status", get_software_status(ELEMENT_ID)),
        ("get_bgp_peers", get_bgp_peers(SITE_ID, ELEMENT_ID)),
        ("get_bgp_status", get_bgp_status(SITE_ID, ELEMENT_ID)),
        ("get_bgp_status", get_bgp_status(SITE_ID, ELEMENT_ID, include_prefixes=True)),
        ("get_bgp_prefixes", get_bgp_prefixes(SITE_ID, ELEMENT_ID, BGPPEER_ID)),
        ("get_bgp_prefixes", get_bgp_prefixes(SITE_ID, ELEMENT_ID, BGPPEER_ID, prefix_type="advertised")),
        ("get_static_routes", get_static_routes(SITE_ID, ELEMENT_ID)),
        ("get_site_paths", get_site_paths(SITE_ID)),
        ("resolve_path", resolve_path(SITE_ID, "0")),
        ("get_vpnlink_status", get_vpnlink_status(vpnlink_id)),
        ("get_vpnlink_state", get_vpnlink_state(vpnlink_id)),
        ("get_flows", get_flows(SITE_ID, hours=1)),
        ("get_flows", get_flows(SITE_ID, hours=1, raw=True, limit=20)),
        ("get_flows", get_flows(SITE_ID, hours=1, path_id="0")),
        ("get_link_metrics", get_link_metrics(SITE_ID, hours=1)),
        ("get_link_metrics", get_link_metrics(SITE_ID, hours=1, element_id=ELEMENT_ID, raw=True)),
        ("get_probe_metrics", get_probe_metrics(SITE_ID, hours=1)),
        ("get_events", get_events(limit=20)),
        ("get_events", get_events(limit=20, site_id=SITE_ID)),
        ("get_alarms", get_alarms(limit=20)),
        ("get_policy_sets", get_policy_sets()),
        ("get_security_zones", get_security_zones()),
        ("get_path_groups", get_path_groups()),
        ("get_service_labels", get_service_labels()),
        ("get_wan_networks", get_wan_networks()),
        (
            "generate_site_config",
            generate_site_config(
                "live-smoke-site",
                [{"serial_number": "live-smoke-serial"}],
                "live-smoke.yaml",
                True,
            ),
        ),
    ]

    budget = get_max_response_bytes()
    covered = {name for name, _ in calls}
    assert len(covered) == len(asyncio_tools())
    assert covered == set(asyncio_tools())
    for tool_name, result_text in calls:
        payload = json.loads(result_text)
        assert isinstance(payload, dict), tool_name
        assert len(result_text.encode("utf-8")) <= budget, tool_name
        assert payload.get("tool") == tool_name, tool_name
        if tool_name in {"get_vpnlink_status", "get_vpnlink_state"}:
            if payload.get("code") == "not_found":
                continue
            assert "truncated" in payload, tool_name
            assert "total_count" in payload, tool_name
            assert "returned_count" in payload, tool_name
        else:
            assert "truncated" in payload, tool_name
            assert "total_count" in payload, tool_name
            assert "returned_count" in payload, tool_name


def asyncio_tools():
    return [tool.name for tool in __import__("asyncio").run(server.mcp.list_tools())]
