from __future__ import annotations

import json

from . import runtime
from .cli.policy import ION_DIAGNOSTIC_FORMS, ION_READ_ONLY_FAMILIES
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


@mcp.resource("prisma-v2://sites", mime_type="application/json")
def sites_resource() -> str:
    return get_inventory(kind="sites")


@mcp.resource("prisma-v2://topology", mime_type="application/json")
def topology_resource() -> str:
    return get_topology()


@mcp.resource("prisma-v2://policy/network", mime_type="application/json")
def network_policy_resource() -> str:
    return get_policies(family="network", operation="sets")


@mcp.resource("prisma-cli://policy", mime_type="application/json")
def cli_policy_resource() -> str:
    """The enforced ION CLI command policy for `run_commands`: the allowed
    command families, the allowed exact diagnostic forms, and the one
    supported output filter -- generated from the same policy.py constants
    the validator evaluates, so this can't drift out of sync with real
    enforcement."""
    return json.dumps(
        {
            "model": (
                "Every command is denied by default. A command runs only if it "
                "matches an approved family or an approved exact form below. "
                "Nothing is listed as denied because nothing needs to be: "
                "anything absent from this document is already rejected."
            ),
            "allowed_families": list(ION_READ_ONLY_FAMILIES),
            "allowed_exact_forms": list(ION_DIAGNOSTIC_FORMS),
            "output_filter": (
                "COMMAND | grep [-i|-v|-w|-F] PATTERN — at most one, "
                "immediately after a dump/inspect command"
            ),
            "notes": (
                "A bare 'dump' or 'inspect' with no arguments is denied. "
                "dump/inspect are enforced at the family level, not as a list "
                "of exact subcommands. The diagnostics are the opposite: each "
                "is one exact form matched whole, so 'debug' stays denied even "
                "though the reference documents ping/tcpping/dig on its Debug "
                "Commands pages. ping/tcpping/dig send real packets — they are "
                "not read-only. See cli/policy.py and docs/ION_CLI_RESEARCH.md."
            ),
        },
        separators=(",", ":"),
    )
