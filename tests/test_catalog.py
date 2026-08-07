from prisma_sdwan_mcp.catalog import CapabilityCatalog


def test_catalog_counts_and_domains():
    catalog = CapabilityCatalog()
    assert catalog.registry_action_count == 308
    assert catalog.compat_action_count == 8
    assert catalog.action_count == 316
    assert len([d for d in catalog.domains() if d["domain"] != "curated"]) == 18


def test_important_capabilities_exist():
    catalog = CapabilityCatalog()
    for action_id in (
        "sites_devices.sites",
        "sites_devices.elements",
        "sites_devices.interfaces",
        "routing_bgp_ospf.bgppeers",
        "routing_bgp_ospf.ospfconfigs_ospfdiscoveredneighbors",
        "vpn_wan.waninterfaces",
        "security_policies.ngfwsecuritypolicyrules",
        "platform_specialized.prismasase_connections_status",
        "compat.topology",
        "compat.monitor_flows",
    ):
        assert catalog.has(action_id), action_id


def test_resource_aliases_point_to_real_actions():
    catalog = CapabilityCatalog()
    for kind in catalog.resource_kinds():
        alias = catalog.resource_alias(kind)
        assert catalog.has(alias["action_id"]), (kind, alias)
