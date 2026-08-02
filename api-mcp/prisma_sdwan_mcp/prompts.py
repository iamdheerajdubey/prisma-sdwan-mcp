"""MCP prompts: canned, discoverable troubleshooting workflows. Each one
returns an instruction message telling the calling agent which of this
server's own tools to call, in what order, and why — the workflow
knowledge lives here once instead of being reconstructed from scratch by
every agent that connects to this server.
"""

from __future__ import annotations

from . import registry


mcp = registry.mcp


@mcp.prompt
def diagnose_vpn_link_down(site_hint: str) -> str:
    """Guided triage for a NETWORK_ANYNETLINK_DOWN / SITE_CONNECTIVITY_DEGRADED alert.

    Args:
        site_hint: Site name or substring from the alert message (e.g. the
            text on one side of the "<->" in the alert's message field).
    """
    return (
        f"Triage a down/degraded anynet link at a site matching '{site_hint}'. "
        "Use this server's own tools, in this order:\n\n"
        f'1. find_site(name="{site_hint}") to resolve the name to a site_id. '
        "If more than one site matches, ask which one before continuing.\n"
        "2. get_basenet_topology(site_id) to find the anynet link(s) at this "
        "site and each link's vpnlinks[] leg IDs. Match the alert's "
        "anynetlink_id against each link's anynet_link_id field — not "
        "path_id, which is a different identifier on the same object.\n"
        "3. For every leg ID found: get_vpnlink_status(vpnlink_id) for the "
        "live active/usable/link_up flags, and get_vpnlink_state(vpnlink_id) "
        "to rule out an admin-disabled leg (enabled: false) before treating "
        "it as a real outage.\n"
        "4. get_events(site_id=site_id, start_time=..., end_time=...) and "
        "get_alarms(site_id=site_id, start_time=..., end_time=...), windowed "
        "tightly around the alert's happenedOn timestamp. An unwindowed call "
        "only returns the most recent N records and can miss the incident "
        "entirely. An alarm with cleared=false is still open right now.\n"
        "5. get_wan_interfaces(site_id) to see which underlay circuit the "
        "failing leg rides on, for correlation with the flapping pattern.\n\n"
        "Report which leg is down, since when, whether it is still open as "
        "of the most recent alarm query, and which underlay circuit is "
        "implicated. Do not guess a human-readable failure reason (e.g. "
        "'BFD Failure', 'Administratively Down') — get_vpnlink_status only "
        "exposes boolean state, not that reason string; getting it requires "
        "device CLI access, which this tool does not have (see cli-mcp if "
        "that's available in this deployment)."
    )


@mcp.prompt
def diagnose_link_quality(site_hint: str) -> str:
    """Guided triage for a "circuit feels degraded" complaint (loss, jitter,
    choppy voice, slow but not down) — as distinct from a hard link-down
    alert, which diagnose_vpn_link_down covers.

    Args:
        site_hint: Site name or substring naming the affected site.
    """
    return (
        f"Triage a link-quality complaint at a site matching '{site_hint}'. "
        "Use this server's own tools, then cli-mcp if it is available in "
        "this deployment:\n\n"
        f'1. find_site(name="{site_hint}") to resolve the name to a '
        "site_id. If more than one site matches, ask which one before "
        "continuing.\n"
        "2. get_link_metrics(site_id) for the controller's own recorded "
        "LQM history per WAN path — latency, jitter, packet loss, and MOS.\n"
        "3. get_probe_metrics(site_id) for synthetic probe history against "
        "whatever targets are configured. It can corroborate or contradict "
        "get_link_metrics; report both, do not average or discard either.\n"
        "4. get_wan_interfaces(site_id) to map the flagged path/link to its "
        "underlying interface, for step 5.\n"
        "5. If cli-mcp is available and steps 2-3 point at a specific "
        "interface: run_commands with a bounded ping (e.g. "
        "'ping <interface> <destination>') on that exact interface, to "
        "confirm the degradation is still happening right now rather than "
        "resolved. This step sends real packets — it is not a read-only "
        "call.\n\n"
        "Report what each source showed, including disagreement between "
        "them, and whether live testing (if run) confirmed or contradicted "
        "the historical data. Do not decide a numeric loss/jitter threshold "
        "constitutes 'degraded' — report the measured values and let the "
        "caller judge against their own SLA."
    )


@mcp.prompt
def audit_site_inventory(site_hint: str | None = None) -> str:
    """Guided HA/inventory audit for one site, or the whole tenant.

    Args:
        site_hint: Optional site name substring to scope the audit to one
            site. Omit to audit every site in the tenant.
    """
    if site_hint:
        scope = f"the site matching '{site_hint}'"
        first_step = f'1. find_site(name="{site_hint}") to resolve the site_id.'
    else:
        scope = "every site in the tenant"
        first_step = "1. get_sites() to list every site."

    return (
        f"Audit {scope}. Steps:\n\n"
        f"{first_step}\n"
        "2. get_elements() to list all elements — this endpoint has no "
        "site_id filter upstream, so filter the returned list client-side by "
        "each element's own site_id field (or use the "
        "prisma://site/{site_id}/elements resource, which does this "
        "filtering already).\n"
        "3. For each element with a spoke_ha_config, confirm both cluster "
        "members are present, connected, and have distinct priority values "
        "(higher priority wins the active role).\n"
        "4. Flag as findings: any site that looks HA by naming/model but has "
        "only one bound element, any disconnected element, and any cluster "
        "with duplicate priority values."
    )
