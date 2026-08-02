import asyncio

import prisma_sdwan_mcp_server as server


EXPECTED_SIGNATURES = {
    "generate_site_config": ({"elements", "filename", "overwrite", "site_id"}, {"site_id", "elements"}),
    "get_sites": ({"cursor", "limit", "site_id"}, set()),
    "get_elements": ({"cursor", "element_id", "limit"}, set()),
    "get_machines": ({"cursor", "limit", "machine_id"}, set()),
    "get_app_defs": ({"category", "cursor", "limit", "search"}, set()),
    "get_element_status": ({"element_id"}, {"element_id"}),
    "get_software_status": ({"element_id"}, {"element_id"}),
    "get_events": ({"cursor", "element_id", "end_time", "last", "limit", "severity", "site_id", "start_time"}, set()),
    "get_alarms": ({"cursor", "element_id", "end_time", "last", "limit", "severity", "site_id", "start_time"}, set()),
    "get_interface_status": ({"element_id", "interface_id", "site_id"}, {"site_id", "element_id"}),
    "get_flows": ({"app", "cursor", "element_id", "end_time", "hours", "limit", "page", "path_id", "raw", "site_id", "start_time", "waninterface_id"}, {"site_id"}),
    "get_link_metrics": ({"element_id", "end_time", "hours", "raw", "site_id", "start_time"}, {"site_id"}),
    "get_probe_metrics": ({"end_time", "hours", "site_id", "start_time"}, {"site_id"}),
    "get_topology": ({"cursor", "detail", "limit", "site_id", "status"}, set()),
    "get_interfaces": ({"cursor", "element_id", "limit", "site_id"}, {"site_id", "element_id"}),
    "get_wan_interfaces": ({"cursor", "limit", "site_id"}, {"site_id"}),
    "get_site_paths": ({"cursor", "limit", "site_id"}, {"site_id"}),
    "get_policy_sets": ({"cursor", "include_stacks", "kind", "limit", "policyset_id"}, set()),
    "get_security_zones": ({"cursor", "limit", "securityzone_id"}, set()),
    "get_path_groups": ({"cursor", "limit", "pathgroup_id"}, set()),
    "get_service_labels": ({"cursor", "limit", "servicelabel_id"}, set()),
    "get_wan_networks": ({"cursor", "limit", "wannetwork_id"}, set()),
    "get_bgp_peers": ({"cursor", "element_id", "limit", "site_id"}, {"site_id", "element_id"}),
    "get_static_routes": ({"cursor", "element_id", "limit", "site_id"}, {"site_id", "element_id"}),
    "get_bgp_status": ({"element_id", "include_prefixes", "site_id"}, {"site_id", "element_id"}),
    "get_bgp_prefixes": ({"bgppeer_id", "cursor", "element_id", "limit", "prefix_type", "site_id"}, {"site_id", "element_id", "bgppeer_id"}),
    "find_site": ({"cursor", "limit", "name"}, {"name"}),
    "find_element": ({"cursor", "limit", "name"}, {"name"}),
    "find_app": ({"cursor", "limit", "name"}, {"name"}),
    "find_machine": ({"cursor", "limit", "name"}, {"name"}),
    "find_security_zone": ({"cursor", "limit", "name"}, {"name"}),
    "find_wan_network": ({"cursor", "limit", "name"}, {"name"}),
    "find_path_group": ({"cursor", "limit", "name"}, {"name"}),
    "find_service_label": ({"cursor", "limit", "name"}, {"name"}),
    "find_policy_set": ({"cursor", "limit", "name"}, {"name"}),
    "resolve_path": ({"path_id", "site_id"}, {"path_id", "site_id"}),
    "get_vpnlink_status": ({"vpnlink_id"}, {"vpnlink_id"}),
    "get_vpnlink_state": ({"vpnlink_id"}, {"vpnlink_id"}),
    "get_basenet_topology": ({"cursor", "leg_offset", "limit", "site_id"}, {"site_id"}),
}


def test_tool_names_and_argument_signatures():
    tools = asyncio.run(server.mcp.list_tools())
    actual = {
        tool.name: (
            set(tool.parameters.get("properties", {})),
            set(tool.parameters.get("required", [])),
        )
        for tool in tools
    }

    assert actual == EXPECTED_SIGNATURES
