"""Read-only MCP resources: attachable data snapshots, browsable in a
client without needing a tool call first. Each one delegates to the same
tool function that already talks to the SDK and shapes the response, so
there is exactly one code path per data type — resources are just a
different way in.
"""

from __future__ import annotations

import json

from . import registry
from .tools.inventory import get_elements, get_sites
from .tools.network import get_topology
from .tools.policy import get_policy_sets


mcp = registry.mcp


@mcp.resource("prisma://sites", mime_type="application/json")
def sites_resource() -> str:
    """Full projected site inventory, for direct attach without a tool call."""
    return get_sites()


@mcp.resource("prisma://topology", mime_type="application/json")
def topology_resource() -> str:
    """Anynet topology summary (same as get_topology() with default args)."""
    return get_topology()


@mcp.resource("prisma://policy-sets", mime_type="application/json")
def policy_sets_resource() -> str:
    """All policy sets: network, priority, NGFW, and NAT."""
    return get_policy_sets()


@mcp.resource("prisma://site/{site_id}/elements", mime_type="application/json")
def site_elements_resource(site_id: str) -> str:
    """Elements at one site.

    get_elements has no site_id filter upstream (the SDK's elements
    endpoint returns the whole tenant), so this fetches the full list once
    and filters client-side by site_id, same as any caller doing
    per-site element lookups today has to.
    """
    raw = get_elements()
    try:
        payload = json.loads(raw)
    except ValueError:
        return raw
    items = payload.get("elements")
    if not isinstance(items, list):
        return raw
    filtered = [item for item in items if str(item.get("site_id")) == str(site_id)]
    payload["elements"] = filtered
    payload["returned_count"] = len(filtered)
    payload["truncated"] = False
    return json.dumps(payload)
