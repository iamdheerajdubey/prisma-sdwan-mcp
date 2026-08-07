from __future__ import annotations

from typing import Any, Literal, Optional

from .. import runtime
from ..config import allow_unverified_compat, expert_tool_enabled
from ..mcp import READ_ONLY, mcp
from ..response import collection_json, error_json, single_json
from .common import execute, fail_from_upstream, handle_error, records, resolve

ResourceKind = Literal[
    "machine",
    "application",
    "security_zone",
    "wan_network",
    "path_group",
    "service_label",
    "vrf",
    "network_policy",
    "priority_policy",
    "nat_policy",
    "security_policy",
    "performance_policy",
    "policy",
]


@mcp.tool(annotations=READ_ONLY)
def find_site(name: str, cursor: Optional[str] = None, limit: Optional[int] = None) -> str:
    """Resolve a human site name or exact ID without guessing.

    Returns every matching candidate. If more than one site matches, the result
    is explicitly marked ambiguous so the caller can choose an exact site.
    """
    tool = "find_site"
    try:
        _, resolver = runtime.ensure_initialized()
        result = resolver.find("site", name)
        return collection_json(
            tool,
            f"Found {len(result.matches)} site match(es) for '{name}'",
            "sites",
            result.matches,
            cursor=cursor,
            limit=limit,
            extra={"ambiguous": result.ambiguous, "match_count": len(result.matches)},
        )
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def find_element(name: str, cursor: Optional[str] = None, limit: Optional[int] = None) -> str:
    """Resolve an ION/element name or exact ID without guessing.

    The returned candidates include site_id when the controller provides it,
    allowing later tools to infer the correct site from an element.
    """
    tool = "find_element"
    try:
        _, resolver = runtime.ensure_initialized()
        result = resolver.find("element", name)
        return collection_json(
            tool,
            f"Found {len(result.matches)} element match(es) for '{name}'",
            "elements",
            result.matches,
            cursor=cursor,
            limit=limit,
            extra={"ambiguous": result.ambiguous, "match_count": len(result.matches)},
        )
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def find_resource(
    kind: ResourceKind,
    name: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Resolve common Prisma SD-WAN objects by human name or exact ID.

    Use for machines, applications, security zones, WAN networks, path groups,
    service labels, VRFs, and the major policy-set families. It never silently
    selects one object when multiple records match.
    """
    tool = "find_resource"
    try:
        _, resolver = runtime.ensure_initialized()
        if kind == "policy":
            matches = []
            for family, resolver_kind in (
                ("network", "network_policy"),
                ("priority", "priority_policy"),
                ("nat", "nat_policy"),
                ("security", "security_policy"),
                ("performance", "performance_policy"),
            ):
                found = resolver.find(resolver_kind, name)
                matches.extend({**item, "policy_family": family} for item in found.matches)
            ambiguous = len(matches) > 1
        else:
            result = resolver.find(kind, name)
            matches = result.matches
            ambiguous = result.ambiguous
        return collection_json(
            tool,
            f"Found {len(matches)} {kind} match(es) for '{name}'",
            "matches",
            matches,
            cursor=cursor,
            limit=limit,
            extra={"resource_kind": kind, "ambiguous": ambiguous, "match_count": len(matches)},
        )
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def search_capabilities(
    search: Optional[str] = None,
    domain: Optional[str] = None,
    method: Optional[Literal["GET", "POST"]] = None,
    detail: Literal["summary", "full"] = "summary",
    limit: int = 50,
) -> str:
    """Search the v2 capability catalog when no semantic tool fits the request.

    This is the discovery companion to ``read_capability``. Normal operator
    workflows should prefer semantic tools. The catalog contains the 308 source
    registry actions plus a small, labeled v1 compatibility overlay.
    """
    tool = "search_capabilities"
    try:
        if limit < 1 or limit > 100:
            return error_json("invalid_limit", "limit must be between 1 and 100", tool, 400)
        matches = runtime.catalog.search(search, domain, method, limit)
        if detail == "summary":
            matches = [
                {
                    key: item.get(key)
                    for key in ("action_id", "domain", "description", "http_method", "source", "requires_live_test")
                    if item.get(key) is not None
                }
                for item in matches
            ]
        return collection_json(
            tool,
            f"Found {len(matches)} matching capability/capabilities",
            "capabilities",
            matches,
            limit=min(limit, 100),
            extra={
                "registry_actions": runtime.catalog.registry_action_count,
                "compat_actions": runtime.catalog.compat_action_count,
            },
        )
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def read_capability(
    action_id: str,
    path_parameters: Optional[dict[str, Any]] = None,
    body: Optional[dict[str, Any]] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Execute one exact read-only registry capability as an expert escape hatch.

    Prefer the semantic tools first. Use ``search_capabilities`` to discover an
    action_id. Parameters are validated against the registry and every response
    passes through central recursive secret redaction and response-size limits.

    V1-compat actions that still need live verification are blocked here by
    default; set MCP_ALLOW_UNVERIFIED_COMPAT=true only after completing the
    validation checklist shipped with this project.
    """
    tool = "read_capability"
    if not expert_tool_enabled():
        return error_json("expert_tool_disabled", "generic registry execution is disabled by configuration", tool, 403)
    try:
        action_id = (action_id or "").strip()
        if not action_id:
            return error_json("invalid_argument", "action_id is required", tool, 400)
        action = runtime.catalog.get(action_id)
        if runtime.catalog.expert_blocked(action_id) and not allow_unverified_compat():
            return error_json(
                "requires_live_test",
                "this v1 compatibility capability is blocked from generic execution until live validation is completed",
                tool,
                403,
                {"action_id": action_id},
            )
        value = execute(action_id, path_parameters, body)
        upstream = fail_from_upstream(tool, value)
        if upstream:
            return upstream
        item_records = records(value)
        if isinstance(value, list) or item_records and len(item_records) > 1:
            return collection_json(
                tool,
                f"Executed {action_id}",
                "items",
                item_records if item_records else value,
                cursor=cursor,
                limit=limit,
                extra={"action_id": action_id, "source": action.source, "api_version": action.api_version},
            )
        return single_json(
            tool,
            f"Executed {action_id}",
            "result",
            value,
            extra={"action_id": action_id, "source": action.source, "api_version": action.api_version},
        )
    except Exception as exc:
        return handle_error(tool, exc)


def _first(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if item.get(name) is not None:
            return item[name]
    return None


def _transport(item: dict[str, Any]) -> str:
    value = _first(item, "transport", "link_type", "type")
    return str(value) if value is not None else "unknown"


@mcp.tool(annotations=READ_ONLY)
def resolve_path(site: str, path_id: str) -> str:
    """Resolve an opaque path ID to a WAN interface, AnyNet link, or VPN leg.

    This preserves one of v1's strongest troubleshooting behaviors: unresolved
    IDs are reported explicitly rather than guessed. ``site`` may be a site
    name or controller ID.
    """
    tool = "resolve_path"
    try:
        site_rec = resolve("site", site)
        site_id = str(site_rec["id"])
        path_id = (path_id or "").strip()
        if not path_id:
            return error_json("invalid_argument", "path_id is required", tool, 400)

        wan = execute("vpn_wan.waninterfaces", {"site_id": site_id})
        wan_items = records(wan) if not fail_from_upstream(tool, wan) else []
        topology = execute("compat.topology", body={"type": "anynet"})
        links = topology.get("links", []) if isinstance(topology, dict) and isinstance(topology.get("links"), list) else []
        found: list[dict[str, Any]] = []
        for item in wan_items:
            candidate = _first(item, "id", "interface_id")
            if candidate is not None and str(candidate) == path_id:
                found.append(
                    {
                        "path_id": path_id,
                        "resolved": True,
                        "kind": "wan_interface",
                        "transport": _transport(item),
                        "name": _first(item, "name", "interface_name"),
                        "site_id": site_id,
                        "element_id": item.get("element_id"),
                    }
                )
                break
        if not found:
            for link in links:
                if not isinstance(link, dict):
                    continue
                link_id = _first(link, "path_id", "id")
                if link_id is not None and str(link_id) == path_id:
                    found.append(
                        {
                            "path_id": path_id,
                            "resolved": True,
                            "kind": "anynet_link",
                            "transport": _transport(link),
                            "source": _first(link, "source_site_name", "source_site_id", "source_node_id"),
                            "target": _first(link, "target_site_name", "target_site_id", "target_node_id"),
                            "status": link.get("status"),
                        }
                    )
                    break
                for leg in link.get("vpnlinks") or []:
                    if isinstance(leg, str) and leg == path_id:
                        found.append({"path_id": path_id, "resolved": True, "kind": "vpnlink_leg", "transport": _transport(link), "parent_path_id": link_id})
                        break
                    if isinstance(leg, dict):
                        leg_id = _first(leg, "vpnlink_id", "id")
                        if leg_id is not None and str(leg_id) == path_id:
                            found.append(
                                {
                                    "path_id": path_id,
                                    "resolved": True,
                                    "kind": "vpnlink_leg",
                                    "transport": _transport(link),
                                    "parent_path_id": link_id,
                                    "ep1": {
                                        "site_id": _first(leg, "ep1_site_id", "source_site_id"),
                                        "element_id": _first(leg, "ep1_element_id", "source_element_id", "source_node_id"),
                                        "interface_id": _first(leg, "ep1_interface_id", "source_interface_id"),
                                    },
                                    "ep2": {
                                        "site_id": _first(leg, "ep2_site_id", "target_site_id", "destination_site_id"),
                                        "element_id": _first(leg, "ep2_element_id", "target_element_id", "target_node_id"),
                                        "interface_id": _first(leg, "ep2_interface_id", "target_interface_id", "destination_interface_id"),
                                    },
                                }
                            )
                            break
                if found:
                    break
        if not found:
            found = [{"path_id": path_id, "resolved": False, "reason": "no WAN interface, AnyNet link, or VPN leg matched this ID"}]
        return collection_json(tool, f"Resolved path '{path_id}'" if found[0]["resolved"] else f"Path '{path_id}' is unresolved", "paths", found, limit=1, extra={"site_id": site_id})
    except Exception as exc:
        return handle_error(tool, exc)
