from typing import Optional

from .. import registry
from ..formatting import build_envelope, collection_response, error_json, internal_error


mcp = registry.mcp

PREFIX_ENDPOINTS = {
    "reachable": ("bgppeers_reachableprefixes", "v2.1"),
    "advertised": ("bgppeers_advertisedprefixes", "v2.1"),
    "discovered": ("bgppeers_discoveredprefixes", "v2.2"),
}


def _validate_ids(site_id: str, element_id: str, tool: str) -> str | None:
    if not site_id or not site_id.strip():
        return error_json("invalid_argument", "site_id is required and cannot be empty", tool, 400)
    if not element_id or not element_id.strip():
        return error_json("invalid_argument", "element_id is required and cannot be empty", tool, 400)
    return None


def _validate_limit(limit: int | None, tool: str) -> str | None:
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        return error_json("invalid_limit", "limit must be at least 1", tool, 400)
    return None


def _items_or_empty(data):
    if data is None or data == {}:
        return []
    return data if isinstance(data, list) else [data]


def _prefix_counts(items: list) -> tuple[int, int, bool]:
    """Return (reachable_count, filtered_count, indicator_seen).

    Filtered prefixes are counted from a truthy ``filtered`` field or a
    status/state literal indicating inbound-policy rejection. If no item
    carries any such indicator, filtered_count is unconfirmed and
    indicator_seen is False.
    """
    reachable = len(items)
    filtered = 0
    indicator_seen = False
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_filtered = item.get("filtered")
        status = str(item.get("status") or item.get("state") or "").lower()
        if raw_filtered is not None or item.get("status") is not None or item.get("state") is not None:
            indicator_seen = True
        if raw_filtered in (True, "true", "yes", 1, "1"):
            filtered += 1
        elif status in {"filtered", "denied", "rejected"}:
            filtered += 1
    return reachable, filtered, indicator_seen


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_bgp_peers(
    site_id: str,
    element_id: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve projected BGP peer configuration.

    Args:
        site_id: Site ID.
        element_id: Element ID.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum peers to return.

    Returns:
        A compact, budgeted BGP peer collection.

    Examples:
        - get_bgp_peers(site_id="site123", element_id="elem456")
    """
    tool = "get_bgp_peers"
    invalid = _validate_ids(site_id, element_id, tool)
    if invalid:
        return invalid
    invalid = _validate_limit(limit, tool)
    if invalid:
        return invalid
    try:
        data = registry.client.call_sdk(registry.client.sdk.get.bgppeers, site_id.strip(), element_id.strip())
        return collection_response(
            tool,
            f"BGP peers for element '{element_id}' at site '{site_id}'",
            "bgp_peers",
            data,
            cursor=cursor,
            limit=limit,
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_static_routes(
    site_id: str,
    element_id: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve projected static routes for an element.

    Args:
        site_id: Site ID.
        element_id: Element ID.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum routes to return.

    Returns:
        A compact, budgeted static-route collection.

    Examples:
        - get_static_routes(site_id="site123", element_id="elem456")
    """
    tool = "get_static_routes"
    invalid = _validate_ids(site_id, element_id, tool)
    if invalid:
        return invalid
    invalid = _validate_limit(limit, tool)
    if invalid:
        return invalid
    try:
        data = registry.client.call_sdk(
            registry.client.sdk.get.staticroutes, site_id.strip(), element_id.strip()
        )
        return collection_response(
            tool,
            f"Static routes for element '{element_id}' at site '{site_id}'",
            "static_routes",
            data,
            cursor=cursor,
            limit=limit,
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_bgp_status(
    site_id: str,
    element_id: str,
    include_prefixes: bool = False,
) -> str:
    """Retrieve BGP session state and established counts.

    Args:
        site_id: Site ID.
        element_id: Element ID.
        include_prefixes: When True, fetch reachable/filtered prefix counts
            per peer and flag any Established peer silently receiving zero
            reachable prefixes with ``established_zero_prefixes: true``.

    Returns:
        BGP sessions with established and not-established counts.

    Examples:
        - get_bgp_status(site_id="site123", element_id="elem456")
        - get_bgp_status(site_id="site123", element_id="elem456", include_prefixes=True)
    """
    tool = "get_bgp_status"
    invalid = _validate_ids(site_id, element_id, tool)
    if invalid:
        return invalid
    try:
        data = registry.client.call_sdk(
            registry.client.sdk.get.bgppeers_status, site_id.strip(), element_id.strip()
        )
        if isinstance(data, dict) and "error" in data:
            return collection_response(tool, "BGP status unavailable", "peers", data)
        peers = _items_or_empty(data)
        established = 0
        for peer in peers:
            state = str(
                peer.get("state")
                or peer.get("status")
                or peer.get("session_state")
                or peer.get("bgp_state")
                or ""
            ).lower()
            if state in {"established", "up", "connected"}:
                established += 1
        extra = {
            "established_count": established,
            "not_established_count": len(peers) - established,
        }
        indicator_seen = True
        if include_prefixes:
            zero_prefix_peers = 0
            indicator_seen = False
            for peer in peers:
                peer_id = peer.get("id") or peer.get("peer_id")
                if not peer_id:
                    continue
                prefixes = registry.client.call_sdk(
                    registry.client.sdk.get.bgppeers_reachableprefixes,
                    site_id.strip(),
                    element_id.strip(),
                    peer_id,
                    api_version="v2.1",
                )
                if isinstance(prefixes, dict) and "error" in prefixes:
                    peer["prefix_error"] = prefixes["error"]
                    continue
                reachable, filtered, seen = _prefix_counts(_items_or_empty(prefixes))
                indicator_seen = indicator_seen or seen
                peer["reachable_prefix_count"] = reachable
                peer["filtered_prefix_count"] = filtered
                peer["established_zero_prefixes"] = established and reachable == 0
                if peer["established_zero_prefixes"]:
                    zero_prefix_peers += 1
            extra["zero_prefix_peers"] = zero_prefix_peers
            extra["prefix_indicator_unobserved"] = not indicator_seen
        summary = (
            f"No BGP peers configured for element '{element_id}'"
            if not peers
            else f"BGP status: {established} established, {len(peers) - established} not established"
        )
        return build_envelope(
            tool,
            summary,
            "peers",
            peers,
            extra=extra,
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_bgp_prefixes(
    site_id: str,
    element_id: str,
    bgppeer_id: str,
    prefix_type: str = "reachable",
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve prefixes for a BGP peer by type.

    Args:
        site_id: Site ID.
        element_id: Element ID.
        bgppeer_id: BGP peer ID.
        prefix_type: One of ``reachable`` (default; includes prefixes
            rejected by inbound policy filters), ``advertised``, or
            ``discovered``.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum prefixes to return.

    Returns:
        A compact, budgeted prefix collection. A non-empty ``discovered``
        list is passed through raw with ``schema_unconfirmed: true`` since
        its item schema has never been observed live.

    Examples:
        - get_bgp_prefixes(site_id="site123", element_id="elem456", bgppeer_id="peer789")
        - get_bgp_prefixes(site_id="site123", element_id="elem456", bgppeer_id="peer789", prefix_type="advertised")
    """
    tool = "get_bgp_prefixes"
    invalid = _validate_ids(site_id, element_id, tool)
    if invalid:
        return invalid
    if not bgppeer_id or not bgppeer_id.strip():
        return error_json("invalid_argument", "bgppeer_id is required and cannot be empty", tool, 400)
    prefix_type = (prefix_type or "").strip().lower()
    if prefix_type not in PREFIX_ENDPOINTS:
        return error_json(
            "invalid_argument",
            "prefix_type must be one of 'reachable', 'advertised', 'discovered'",
            tool,
            400,
        )
    invalid = _validate_limit(limit, tool)
    if invalid:
        return invalid
    try:
        endpoint, api_version = PREFIX_ENDPOINTS[prefix_type]
        method = getattr(registry.client.sdk.get, endpoint)
        data = registry.client.call_sdk(
            method,
            site_id.strip(),
            element_id.strip(),
            bgppeer_id.strip(),
            api_version=api_version,
        )
        extra = {"prefix_type": prefix_type}
        if prefix_type == "discovered":
            extra["schema_unconfirmed"] = True
        return collection_response(
            tool,
            f"{prefix_type.capitalize()} prefixes for BGP peer '{bgppeer_id}'",
            "prefixes",
            data,
            cursor=cursor,
            limit=limit,
            extra=extra,
        )
    except Exception as error:
        return internal_error(tool, error)
