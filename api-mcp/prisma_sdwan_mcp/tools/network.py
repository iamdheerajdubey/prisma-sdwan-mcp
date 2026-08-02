from collections import Counter
from typing import Optional

from .. import registry
from ..formatting import (
    INTERFACE_KEEP_FIELDS,
    WAN_INTERFACE_KEEP_FIELDS,
    _clean_response,
    build_envelope,
    collection_response,
    error_json,
    internal_error,
)


mcp = registry.mcp

LEG_RESOLUTION_CAP = 100


def _validate_limit(limit: int | None, tool: str) -> str | None:
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        return error_json("invalid_limit", "limit must be at least 1", tool, 400)
    return None


def _endpoint_values(link: dict, prefix: str) -> set[str]:
    values = set()
    for name in (
        f"{prefix}_site_id",
        f"{prefix}_node_id",
        f"{prefix}_site_name",
        f"{prefix}_name",
        prefix,
    ):
        value = link.get(name)
        if isinstance(value, dict):
            for nested_name in ("id", "site_id", "node_id", "name"):
                if value.get(nested_name) is not None:
                    values.add(str(value[nested_name]))
        elif value is not None:
            values.add(str(value))
    return values


def _link_matches_values(link: dict, expected_values: set[str]) -> bool:
    return bool(
        expected_values
        & (
            _endpoint_values(link, "source")
            | _endpoint_values(link, "target")
            | _endpoint_values(link, "destination")
        )
    )


def _link_matches_site(link: dict, site_id: str) -> bool:
    return _link_matches_values(link, {str(site_id)})


def _site_aliases(site_id: str) -> set[str]:
    aliases = {str(site_id)}
    get_api = getattr(registry.client.sdk, "get", None)
    sites_method = getattr(get_api, "sites", None)
    if sites_method is None:
        return aliases
    site = registry.client.call_sdk(sites_method, site_id)
    if isinstance(site, dict) and "error" not in site:
        for field in ("id", "name", "display_name", "site_name"):
            if site.get(field) is not None:
                aliases.add(str(site[field]))
    return aliases


def _node_matches_site(node: dict, site_id: str) -> bool:
    expected = str(site_id)
    return any(
        str(node.get(name)) == expected
        for name in ("id", "site_id", "node_id", "name", "site_name")
        if node.get(name) is not None
    )


@mcp.tool()
def get_topology(
    detail: str = "summary",
    site_id: Optional[str] = None,
    status: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Summarize the anynet topology or return filtered detail.

    Args:
        detail: ``summary`` by default or ``full`` for filtered arrays.
        site_id: Optional site or endpoint filter for full detail.
        status: Optional link status filter for full detail.
        cursor: Opaque cursor for a detailed link page.
        limit: Maximum detailed links to return.

    Returns:
        A compact topology summary or filtered nodes and links.

    Examples:
        - get_topology()
        - get_topology(detail="full", site_id="site123")
    """
    tool = "get_topology"
    if detail not in {"summary", "full"}:
        return error_json("invalid_argument", "detail must be 'summary' or 'full'", tool, 400)
    if site_id is not None:
        site_id = site_id.strip()
        if not site_id:
            return error_json("invalid_argument", "site_id cannot be empty", tool, 400)
    if status is not None:
        status = status.strip().lower()
        if not status:
            return error_json("invalid_argument", "status cannot be empty", tool, 400)
    invalid_limit = _validate_limit(limit, tool)
    if invalid_limit:
        return invalid_limit
    if detail == "full" and not site_id and not status:
        return error_json(
            "invalid_argument",
            "detail='full' requires site_id or status to bound the topology",
            tool,
            400,
        )
    try:
        site_values = _site_aliases(site_id) if site_id else set()
        data = registry.client.call_sdk_post(
            registry.client.sdk.post.topology, {"type": "anynet"}
        )
        if isinstance(data, dict) and "error" in data:
            return collection_response(tool, "Topology unavailable", "links", data)
        topology = data if isinstance(data, dict) else {}
        links = topology.get("links", []) if isinstance(topology.get("links", []), list) else []
        nodes = topology.get("nodes", []) if isinstance(topology.get("nodes", []), list) else []
        status_counts = Counter(str(link.get("status", "unknown")) for link in links)
        if detail == "summary":
            not_up = [
                {
                    "path_id": link.get("path_id") or link.get("id"),
                    "source": link.get("source_site_name") or link.get("source_site_id") or link.get("source_node_id"),
                    "target": link.get("target_site_name") or link.get("target_site_id") or link.get("target_node_id"),
                    "status": link.get("status", "unknown"),
                }
                for link in links
                if str(link.get("status", "")).lower() != "up"
            ]
            return build_envelope(
                tool,
                f"Topology summary: {len(nodes)} node(s), {len(links)} link(s)",
                "not_up_links",
                not_up,
                cursor=cursor,
                limit=limit,
                extra={
                    "node_count": len(nodes),
                    "link_count": len(links),
                    "status_counts": dict(sorted(status_counts.items())),
                },
            )

        filtered_links = links
        if site_id:
            filtered_links = [link for link in filtered_links if _link_matches_values(link, site_values)]
        if status:
            filtered_links = [link for link in filtered_links if str(link.get("status", "")).lower() == status]
        filtered_nodes = nodes
        if site_id:
            filtered_nodes = [node for node in nodes if _node_matches_site(node, site_id)]
        return build_envelope(
            tool,
            f"Filtered topology detail: {len(filtered_nodes)} node(s), {len(filtered_links)} link(s)",
            "links",
            filtered_links,
            cursor=cursor,
            limit=limit,
            extra={
                "nodes": [_clean_response(node) for node in filtered_nodes],
                "node_count": len(filtered_nodes),
                "link_count": len(filtered_links),
                "status_counts": dict(
                    sorted(Counter(str(link.get("status", "unknown")) for link in filtered_links).items())
                ),
            },
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool()
def get_interfaces(
    site_id: str,
    element_id: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve projected interfaces for an element at a site.

    Args:
        site_id: Site ID.
        element_id: Element ID.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum interfaces to return.

    Returns:
        A compact, budgeted interface collection.

    Examples:
        - get_interfaces(site_id="site123", element_id="elem456")
    """
    tool = "get_interfaces"
    site_id = site_id.strip() if site_id else ""
    element_id = element_id.strip() if element_id else ""
    if not site_id:
        return error_json("invalid_argument", "site_id is required and cannot be empty", tool, 400)
    if not element_id:
        return error_json("invalid_argument", "element_id is required and cannot be empty", tool, 400)
    invalid_limit = _validate_limit(limit, tool)
    if invalid_limit:
        return invalid_limit
    try:
        data = registry.client.call_sdk(registry.client.sdk.get.interfaces, site_id, element_id)
        return collection_response(
            tool,
            f"Interfaces for element '{element_id}' at site '{site_id}'",
            "interfaces",
            data,
            INTERFACE_KEEP_FIELDS,
            cursor,
            limit,
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool()
def get_wan_interfaces(
    site_id: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve projected WAN interfaces for a site.

    Args:
        site_id: Site ID.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum WAN interfaces to return.

    Returns:
        A compact, budgeted WAN interface collection.

    Examples:
        - get_wan_interfaces(site_id="site123")
    """
    tool = "get_wan_interfaces"
    site_id = site_id.strip() if site_id else ""
    if not site_id:
        return error_json("invalid_argument", "site_id is required and cannot be empty", tool, 400)
    invalid_limit = _validate_limit(limit, tool)
    if invalid_limit:
        return invalid_limit
    try:
        data = registry.client.call_sdk(registry.client.sdk.get.waninterfaces, site_id)
        return collection_response(
            tool,
            f"WAN interfaces for site '{site_id}'",
            "wan_interfaces",
            data,
            WAN_INTERFACE_KEEP_FIELDS,
            cursor,
            limit,
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool()
def get_site_paths(
    site_id: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Return anynet paths incident to one site.

    Args:
        site_id: Site or topology node ID.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum paths to return.

    Returns:
        Paths with up/down counts and a summary distinguishing no paths from
        an ID absent from the topology.

    Examples:
        - get_site_paths(site_id="site123")
    """
    tool = "get_site_paths"
    site_id = site_id.strip() if site_id else ""
    if not site_id:
        return error_json("invalid_argument", "site_id is required and cannot be empty", tool, 400)
    invalid = _validate_limit(limit, tool)
    if invalid:
        return invalid
    try:
        site_values = _site_aliases(site_id)
        data = registry.client.call_sdk_post(
            registry.client.sdk.post.topology, {"type": "anynet"}
        )
        if isinstance(data, dict) and "error" in data:
            return collection_response(tool, "Topology unavailable", "paths", data)
        topology = data if isinstance(data, dict) else {}
        links = topology.get("links", []) if isinstance(topology.get("links", []), list) else []
        nodes = topology.get("nodes", []) if isinstance(topology.get("nodes", []), list) else []
        paths = [link for link in links if _link_matches_values(link, site_values)]
        site_present = any(
            _node_matches_site(node, alias) for alias in site_values for node in nodes
        ) or bool(paths)
        up_count = sum(1 for link in paths if str(link.get("status", "")).lower() == "up")
        down_count = len(paths) - up_count
        summary = (
            f"Site '{site_id}' is not present in the topology"
            if not site_present
            else f"Found {len(paths)} path(s) for site '{site_id}' ({up_count} up, {down_count} down)"
            if paths
            else f"No paths found for site '{site_id}'"
        )
        return build_envelope(
            tool,
            summary,
            "paths",
            paths,
            cursor=cursor,
            limit=limit,
            extra={
                "site_present": site_present,
                "up_count": up_count,
                "down_count": down_count,
            },
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool()
def get_vpnlink_status(vpnlink_id: str) -> str:
    """Retrieve per-leg VPN link operational state.

    Exposes the three distinct live flags ``active``, ``usable``, and
    ``link_up`` separately, plus both endpoints' site/element/interface IDs,
    the negotiated cipher, and keepalive configuration.

    Args:
        vpnlink_id: VPN link leg ID (from an anynet link's ``vpnlinks[]``
            in ``get_topology``, not the anynet link's own ``path_id``).

    Returns:
        The leg's operational state, or a structured error for an unknown ID.

    Examples:
        - get_vpnlink_status(vpnlink_id="leg123")
    """
    tool = "get_vpnlink_status"
    vpnlink_id = vpnlink_id.strip() if vpnlink_id else ""
    if not vpnlink_id:
        return error_json("invalid_argument", "vpnlink_id is required and cannot be empty", tool, 400)
    try:
        data = registry.client.call_sdk(
            registry.client.sdk.get.vpnlinks_status, vpnlink_id, api_version="v2.2"
        )
        if isinstance(data, dict) and "error" in data:
            if data.get("status_code") == 404:
                return error_json(
                    "not_found",
                    f"no VPN link leg with id '{vpnlink_id}' exists",
                    tool,
                    404,
                )
            return error_json("upstream_error", data["error"], tool, data.get("status_code"))
        item = data if isinstance(data, dict) else {}
        keep = {
            "active": item.get("active"),
            "usable": item.get("usable"),
            "link_up": item.get("link_up"),
            "cipher": item.get("common_cipher"),
            "keepalive": {
                "ep1": {
                    "interval": item.get("ep1_keep_alive_interval"),
                    "failure_count": item.get("ep1_keep_alive_failure_count"),
                },
                "ep2": {
                    "interval": item.get("ep2_keep_alive_interval"),
                    "failure_count": item.get("ep2_keep_alive_failure_count"),
                },
            },
        }
        for prefix in ("ep1", "ep2"):
            for suffix in ("site_id", "element_id", "interface_id"):
                key = f"{prefix}_{suffix}"
                keep[key] = item.get(key)
        return build_envelope(
            tool,
            f"VPN link leg '{vpnlink_id}' status",
            "vpnlink_status",
            [keep],
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool()
def get_vpnlink_state(vpnlink_id: str) -> str:
    """Retrieve a VPN link leg's administrative state.

    Args:
        vpnlink_id: VPN link leg ID (from an anynet link's ``vpnlinks[]``
            in ``get_topology``, not the anynet link's own ``path_id``).

    Returns:
        The leg's ``enabled`` admin flag plus ``al_id``, the parent anynet
        link's ``path_id`` join key back to ``get_topology``.

    Examples:
        - get_vpnlink_state(vpnlink_id="leg123")
    """
    tool = "get_vpnlink_state"
    vpnlink_id = vpnlink_id.strip() if vpnlink_id else ""
    if not vpnlink_id:
        return error_json("invalid_argument", "vpnlink_id is required and cannot be empty", tool, 400)
    try:
        data = registry.client.call_sdk(
            registry.client.sdk.get.vpnlinks_state, vpnlink_id, api_version="v2.0"
        )
        if isinstance(data, dict) and "error" in data:
            if data.get("status_code") == 404:
                return error_json(
                    "not_found",
                    f"no VPN link leg with id '{vpnlink_id}' exists",
                    tool,
                    404,
                )
            return error_json("upstream_error", data["error"], tool, data.get("status_code"))
        item = data if isinstance(data, dict) else {}
        keep = {"enabled": item.get("enabled"), "al_id": item.get("al_id")}
        return build_envelope(
            tool,
            f"VPN link leg '{vpnlink_id}' administrative state",
            "vpnlink_state",
            [keep],
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool()
def get_basenet_topology(
    site_id: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Return site-scoped basenet (underlay) topology entries.

    The topology API rejects a ``basenet`` query type on the production
    tenant (``400 Invalid topology query``), so the basenet view is derived
    live: the anynet topology is fetched and every vpnlink leg of the links
    incident to the site is resolved through the per-leg vpnlink status
    endpoint, yielding the element- and interface-level fields the basenet
    view provides (`element_id`, `source_elem_if_id`, `target_elem_if_id`,
    `anynet_link_id`, `in_use`). Entries are marked ``derived_from_anynet``.

    Args:
        site_id: Site or topology node ID.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum entries to return.

    Returns:
        Incident basenet entries with element/interface fields, counts, and a
        summary distinguishing no paths from an ID absent from the topology.

    Examples:
        - get_basenet_topology(site_id="site123")
    """
    tool = "get_basenet_topology"
    site_id = site_id.strip() if site_id else ""
    if not site_id:
        return error_json("invalid_argument", "site_id is required and cannot be empty", tool, 400)
    invalid = _validate_limit(limit, tool)
    if invalid:
        return invalid
    try:
        site_values = _site_aliases(site_id)
        data = registry.client.call_sdk_post(
            registry.client.sdk.post.topology, {"type": "anynet"}
        )
        if isinstance(data, dict) and "error" in data:
            return collection_response(tool, "Basenet topology unavailable", "links", data)
        topology = data if isinstance(data, dict) else {}
        links = topology.get("links", []) if isinstance(topology.get("links", []), list) else []
        nodes = topology.get("nodes", []) if isinstance(topology.get("nodes", []), list) else []
        incident = [link for link in links if _link_matches_values(link, site_values)]
        site_present = any(
            _node_matches_site(node, alias) for alias in site_values for node in nodes
        ) or bool(incident)
        entries = []
        leg_resolution_capped = False
        resolved_legs = 0
        for link in incident:
            if not isinstance(link, dict):
                continue
            anynet_link_id = link.get("path_id") or link.get("id")
            for leg in link.get("vpnlinks", []) or []:
                leg_id = leg if isinstance(leg, str) else (leg.get("vpnlink_id") or leg.get("id"))
                if leg_id is None:
                    continue
                if resolved_legs >= LEG_RESOLUTION_CAP:
                    leg_resolution_capped = True
                    continue
                resolved_legs += 1
                status = registry.client.call_sdk(
                    registry.client.sdk.get.vpnlinks_status, leg_id, api_version="v2.2"
                )
                if isinstance(status, dict) and "error" in status:
                    entries.append(
                        {
                            "vpnlink_id": str(leg_id),
                            "anynet_link_id": anynet_link_id,
                            "error": status["error"],
                        }
                    )
                    continue
                item = status if isinstance(status, dict) else {}
                entries.append(
                    {
                        "vpnlink_id": str(leg_id),
                        "anynet_link_id": anynet_link_id,
                        "element_id": item.get("ep1_element_id") or item.get("ep2_element_id"),
                        "source_elem_if_id": item.get("ep1_interface_id"),
                        "target_elem_if_id": item.get("ep2_interface_id"),
                        "in_use": item.get("active"),
                        "active": item.get("active"),
                        "usable": item.get("usable"),
                        "link_up": item.get("link_up"),
                    }
                )
        summary = (
            f"Site '{site_id}' is not present in the topology"
            if not site_present
            else f"Found {len(entries)} basenet leg(s) for site '{site_id}' ({len(incident)} anynet link(s))"
            if entries
            else f"No basenet legs found for site '{site_id}'"
        )
        return build_envelope(
            tool,
            summary,
            "links",
            entries,
            cursor=cursor,
            limit=limit,
            extra={
                "site_present": site_present,
                "anynet_link_count": len(incident),
                "leg_count": len(entries),
                "leg_resolution_capped": leg_resolution_capped,
                "derived_from_anynet": True,
            },
        )
    except Exception as error:
        return internal_error(tool, error)
