from __future__ import annotations

import json

from . import runtime
from .mcp import mcp
from .response import CONTRACT_VERSION
from .tools.core import get_inventory, get_topology
from .tools.policies_security import get_policies


@mcp.resource("prisma-v2://contract", mime_type="application/json")
def contract_resource() -> str:
    return json.dumps(
        {
            "contract_version": CONTRACT_VERSION,
            "architecture": "semantic tools -> resolver/workflow -> registry executor -> Prisma SASE SDK",
            "registry_actions": runtime.catalog.registry_action_count,
            "compat_actions": runtime.catalog.compat_action_count,
            "central_secret_redaction": True,
            "ambiguity_policy": "never auto-pick multiple name matches",
        },
        separators=(",", ":"),
    )


@mcp.resource("prisma-v2://domains", mime_type="application/json")
def domains_resource() -> str:
    return json.dumps(runtime.catalog.domains(), separators=(",", ":"))


@mcp.resource("prisma-v2://sites", mime_type="application/json")
def sites_resource() -> str:
    return get_inventory(kind="sites")


@mcp.resource("prisma-v2://topology", mime_type="application/json")
def topology_resource() -> str:
    return get_topology()


@mcp.resource("prisma-v2://policy/network", mime_type="application/json")
def network_policy_resource() -> str:
    return get_policies(family="network", operation="sets")
