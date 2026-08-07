from __future__ import annotations

from .mcp import mcp


@mcp.prompt
def diagnose_vpn_link_down(site_hint: str) -> str:
    """Guided triage for an AnyNet/VPN link down or degraded alert."""
    return (
        f"Investigate a VPN/AnyNet issue at a site matching '{site_hint}'.\n\n"
        "1. Use find_site and stop for clarification if the result is ambiguous.\n"
        "2. Use get_topology(detail='full', site=<site>) and keep path_id, anynet_link_id, and vpnlink leg IDs distinct.\n"
        "3. For each suspect leg use get_wan(operation='vpn_leg_status', object_id=<leg>) and get_wan(operation='vpn_leg_state', object_id=<leg>). Admin enabled=false is not the same as an outage.\n"
        "4. Use get_monitoring(operation='events') and get_monitoring(operation='alarms') with start_time/end_time around the incident. Unwindowed event calls can miss older incidents.\n"
        "5. Use get_wan(operation='interfaces', site=<site>) and resolve_path for underlay correlation.\n"
        "Report observed state and timestamps. Do not invent a human failure reason that the API did not provide."
    )


@mcp.prompt
def diagnose_link_quality(site_hint: str) -> str:
    """Guided triage for loss, jitter, latency, or poor application experience."""
    return (
        f"Investigate link quality at a site matching '{site_hint}'.\n\n"
        "1. Resolve the site with find_site.\n"
        "2. Use get_monitoring(operation='link_metrics', site=<site>) for recorded LQM/path telemetry.\n"
        "3. Use get_monitoring(operation='probe_metrics', site=<site>) for configured synthetic probes. Report disagreement rather than hiding it.\n"
        "4. Use get_wan(operation='interfaces', site=<site>) and resolve_path to map path IDs to circuits.\n"
        "5. Treat controller metrics as recorded telemetry, not proof that the symptom is still happening this second."
    )


@mcp.prompt
def diagnose_routing_neighbor(site_hint: str, element_hint: str, protocol: str = "bgp") -> str:
    """Guided BGP/OSPF neighbor triage."""
    proto = protocol.strip().lower()
    return (
        f"Investigate {proto.upper()} on site '{site_hint}', element '{element_hint}'.\n\n"
        "1. Resolve site and element; do not continue on ambiguous matches.\n"
        + (
            "2. Use get_routing(operation='bgp_peers'), then get_routing(operation='bgp_status').\n"
            "3. For a suspect peer use get_routing(operation='bgp_prefixes', prefix_kind='reachable'/'advertised'/'discovered').\n"
            if proto == "bgp"
            else "2. Use get_routing(operation='ospf_config'), then get_routing(operation='ospf_neighbors') and get_routing(operation='ospf_prefixes').\n"
        )
        + "4. Correlate with get_monitoring(operation='events') in the incident window.\n"
        "Report controller-observed state; do not infer a missing neighbor cause without evidence."
    )


@mcp.prompt
def audit_site(site_hint: str) -> str:
    """Inventory and operational audit for one site."""
    return (
        f"Audit the site matching '{site_hint}'.\n\n"
        "1. find_site. If ambiguous, ask for an exact site.\n"
        "2. get_inventory(kind='elements') and keep only elements whose site_id matches.\n"
        "3. For each element use get_device_health(include_software=true).\n"
        "4. Use get_wan(operation='interfaces'), get_routing(operation='bgp_status') when BGP is configured, and get_network_services for NTP/DNS where relevant.\n"
        "5. Summarize disconnected devices, down interfaces, software issues, routing problems, and unresolved IDs separately."
    )
