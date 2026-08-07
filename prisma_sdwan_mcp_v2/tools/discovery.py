from __future__ import annotations

from typing import Any, Literal, Optional

from .. import runtime
from ..catalog import RegistryError
from ..config import allow_unverified_compat, expert_tool_enabled, get_max_page_size
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

    Args:
        name: Site name or controller ID. Exact ID match wins first, then
            exact name match (case-insensitive), then falls back to a
            substring match. Multiple hits are never auto-picked — check
            `ambiguous` in the result and call again with a more specific
            name or the exact `id` from `sites`.
        cursor: Opaque pagination token copied from a previous response's
            `next_cursor`. Omit on the first call.
        limit: Max matches to return in this page. Omit to use the server
            default page size.
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

    Args:
        name: Element name, serial number, hardware ID, or exact controller
            ID. Exact ID match wins first, then exact name/serial/hw_id
            match (case-insensitive), then substring. Multiple hits are
            never auto-picked — check `ambiguous` and re-call with a more
            specific value or the exact `id`.
        cursor: Opaque pagination token copied from a previous response's
            `next_cursor`. Omit on the first call.
        limit: Max matches to return in this page. Omit to use the server
            default page size.
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

    Args:
        kind: Which object type to search. One of: `machine`, `application`,
            `security_zone`, `wan_network`, `path_group`, `service_label`,
            `vrf`, `network_policy`, `priority_policy`, `nat_policy`,
            `security_policy`, `performance_policy`, or `policy` to search
            all five policy-set families at once (each match is tagged with
            its `policy_family`). Use `find_site`/`find_element` instead for
            sites or ION elements — this tool does not cover those.
        name: Object name or exact controller ID. Exact ID match wins first,
            then exact name match (case-insensitive), then substring.
            Multiple hits are never auto-picked — check `ambiguous` and
            re-call with a more specific value or the exact `id`.
        cursor: Opaque pagination token copied from a previous response's
            `next_cursor`. Omit on the first call.
        limit: Max matches to return in this page. Omit to use the server
            default page size.
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


# The catalog is fixed, bounded metadata, not API payload, so it is listed under its
# own budget instead of the response cap meant to keep large Prisma results out of
# context. list_capabilities exposes no cursor by design, so a truncated listing would
# make the dropped actions permanently unreachable rather than merely paginated.
# Largest domain today serializes to ~28 KB.
CATALOG_LISTING_BUDGET = 256 * 1024


@mcp.tool(annotations=READ_ONLY)
def list_capabilities(
    domain: Optional[str] = None,
    method: Optional[Literal["GET", "POST"]] = None,
) -> str:
    """Browse the v2 capability catalog when no semantic tool fits the request.

    This is the discovery companion to ``read_capability``. Normal operator
    workflows should prefer semantic tools. Call with no arguments to list
    every domain and its action count. Call again with ``domain`` set to one
    of the returned identifiers to list every action in that domain — each
    entry carries the full execution contract (``action_id``, ``http_method``,
    ``path_parameters``, ``body_schema``) that ``read_capability`` needs, with
    no truncation.

    Args:
        domain: A domain identifier returned by a prior no-argument call
            (e.g. ``"sites_devices"``, ``"security_policies"``). Omit to
            list every domain instead of one domain's actions.
        method: Filter one domain's actions to only ``"GET"`` or only
            ``"POST"``. Ignored (and has no effect) when `domain` is omitted.
    """
    tool = "list_capabilities"
    try:
        if domain is None:
            domains = runtime.catalog.domains()
            entries = [
                {
                    "domain": d["domain"],
                    "title": d["title"],
                    "description": d["description"],
                    "action_count": d["action_count"],
                    "next_call": f'list_capabilities(domain="{d["domain"]}")',
                }
                for d in domains
            ]
            return collection_json(
                tool,
                f"{len(entries)} domain(s) in the capability catalog",
                "domains",
                entries,
                limit=get_max_page_size(),
                budget=CATALOG_LISTING_BUDGET,
                extra={
                    "registry_actions": runtime.catalog.registry_action_count,
                    "compat_actions": runtime.catalog.compat_action_count,
                },
            )
        try:
            matches = runtime.catalog.list_actions(domain, method)
        except RegistryError:
            valid_domains = sorted(d["domain"] for d in runtime.catalog.domains())
            return error_json(
                "invalid_argument",
                f"unknown domain '{domain}'",
                tool,
                400,
                {"valid_domains": valid_domains},
            )
        return collection_json(
            tool,
            f"{len(matches)} action(s) in domain '{domain}'",
            "capabilities",
            matches,
            limit=get_max_page_size(),
            budget=CATALOG_LISTING_BUDGET,
            extra={"domain": domain, "action_count": len(matches)},
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

    Prefer the semantic tools first. Use ``list_capabilities`` to discover an
    action_id. Parameters are validated against the registry and every response
    passes through central recursive secret redaction and response-size limits.

    Curated actions that still need live verification are blocked here by
    default; set MCP_ALLOW_UNVERIFIED_COMPAT=true only after completing the
    validation checklist shipped with this project.

    Args:
        action_id: Exact action identifier from `list_capabilities`, e.g.
            ``"sites_devices.sites"``. Not a free-text search term.
        path_parameters: One key per required/optional path parameter that
            action's `list_capabilities` entry lists under
            ``path_parameters`` (e.g. ``{"site_id": "..."}``). Omit or use
            ``{}`` for actions with none. Unknown keys are rejected.
        body: JSON object matching that action's ``body_schema``. Only
            meaningful for ``POST`` actions — passing any non-empty body to
            a ``GET`` action is rejected.
        cursor: Opaque pagination token copied from a previous response's
            `next_cursor`. Only applies when the result is a list.
        limit: Max items to return in this page when the result is a list.
            Omit to use the server default page size.
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
                "this curated capability is blocked from generic execution until live validation is completed",
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

    By design, unresolved IDs are reported explicitly rather than guessed.

    Args:
        site: Site name or controller ID that owns this path. Must resolve
            to exactly one site — an ambiguous or unknown name returns an
            error listing the candidates instead of guessing.
        path_id: The opaque path/interface/link ID to resolve, typically
            copied from a `path_id`, `interface_id`, or `id` field in the
            output of a routing/WAN tool such as `get_wan` or `get_routing`.
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
