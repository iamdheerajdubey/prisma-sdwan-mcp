from typing import Callable, Optional

from .. import registry
from ..formatting import build_envelope, collection_response, error_json, internal_error


mcp = registry.mcp

FIND_CAP = 50


def _validate_name(name: str, tool: str) -> str | None:
    if not name or not name.strip():
        return error_json("invalid_argument", "name is required and cannot be empty", tool, 400)
    return None


def _matches(name: str, item: dict, *fields: str) -> bool:
    lowered = name.lower()
    return any(
        item.get(field) is not None and lowered in str(item[field]).lower()
        for field in fields
    )


def _match_count_summary(tool_key: str, name: str, count: int) -> tuple[str, bool]:
    if count == 0:
        return f"No {tool_key} match name '{name}'", False
    if count == 1:
        return f"One {tool_key} matches name '{name}'", False
    return (
        f"{count} {tool_key} match name '{name}'; caller must disambiguate by ID",
        True,
    )


def _find_response(
    tool: str,
    key: str,
    label: str,
    name: str,
    records: list,
    match_fields: tuple[str, ...],
    cursor: Optional[str],
    limit: Optional[int],
    extra: Optional[dict] = None,
) -> str:
    matches = [
        record
        for record in records
        if isinstance(record, dict) and _matches(name, record, *match_fields)
    ]
    total = len(matches)
    capped = len(matches) > FIND_CAP
    selected = matches[:FIND_CAP]
    if total == 0:
        summary = f"No {label} match name '{name}'"
        ambiguous = False
    elif total == 1:
        summary = f"One {label} matches name '{name}'"
        ambiguous = False
    else:
        summary = f"{total} {label} match name '{name}'"
        ambiguous = True
    if capped:
        summary += f"; returning the first {FIND_CAP} — refine your search"
    payload_extra = {
        "match_count": total,
        "ambiguous": ambiguous,
        "capped": capped,
    }
    if capped:
        payload_extra["refine_hint"] = (
            f"refine the search; the first {FIND_CAP} candidates are shown"
        )
    if extra:
        payload_extra.update(extra)
    return build_envelope(
        tool,
        summary,
        key,
        selected,
        cursor=cursor,
        limit=limit,
        extra=payload_extra,
    )


def _simple_find(
    tool: str,
    key: str,
    label: str,
    name: str,
    fetch: Callable,
    match_fields: tuple[str, ...],
    projection: set[str],
    cursor: Optional[str],
    limit: Optional[int],
) -> str:
    invalid = _validate_name(name, tool)
    if invalid:
        return invalid
    try:
        data = fetch()
        if isinstance(data, dict) and "error" in data:
            return collection_response(tool, f"{label} lookup unavailable", key, data)
        records = data if isinstance(data, list) else [data]
        from ..formatting import project_items

        projected = project_items(records, projection)
        return _find_response(tool, key, label, name.strip(), projected, match_fields, cursor, limit)
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool()
def find_site(
    name: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Resolve a site name to site IDs by case-insensitive substring match.

    Args:
        name: Substring to match against site name or display name.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum matching sites to return.

    Returns:
        Every matching site with its ID; never a single auto-picked record.
        The candidate list is capped at 50 with a refine hint beyond it.

    Examples:
        - find_site(name="amsterdam")
    """
    return _simple_find(
        "find_site",
        "sites",
        "site",
        name,
        lambda: registry.client.call_sdk(registry.client.sdk.get.sites),
        ("name", "display_name"),
        {"id", "name", "display_name"},
        cursor,
        limit,
    )


@mcp.tool()
def find_element(
    name: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Resolve an element (ION device) name to element IDs by substring match.

    Args:
        name: Substring to match against element name.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum matching elements to return.

    Returns:
        Every matching element with its element ID and site ID; never a
        single auto-picked record. The candidate list is capped at 50.

    Examples:
        - find_element(name="IAZ3")
    """
    return _simple_find(
        "find_element",
        "elements",
        "element",
        name,
        lambda: registry.client.call_sdk(registry.client.sdk.get.elements),
        ("name",),
        {"id", "name", "site_id"},
        cursor,
        limit,
    )


@mcp.tool()
def find_app(
    name: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Resolve an application name to application-definition IDs.

    Args:
        name: Substring to match against application display name.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum matching definitions to return.

    Returns:
        Every matching application definition with its ID, capped at 50
        candidates with a refine hint so the response stays within the
        byte budget even for huge catalogs.

    Examples:
        - find_app(name="zoom")
    """
    return _simple_find(
        "find_app",
        "app_defs",
        "application definition",
        name,
        lambda: registry.client.call_sdk(registry.client.sdk.get.appdefs),
        ("display_name",),
        {"id", "display_name", "category"},
        cursor,
        limit,
    )


@mcp.tool()
def find_machine(
    name: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Resolve a machine (hardware) name to machine IDs by substring match.

    Args:
        name: Substring to match against machine name.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum matching machines to return.

    Returns:
        Every matching machine with its ID, capped at 50 candidates.

    Examples:
        - find_machine(name="ion-5200-01")
    """
    return _simple_find(
        "find_machine",
        "machines",
        "machine",
        name,
        lambda: registry.client.call_sdk(registry.client.sdk.get.machines),
        ("name",),
        {"id", "name"},
        cursor,
        limit,
    )


@mcp.tool()
def find_security_zone(
    name: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Resolve a security-zone name to IDs by case-insensitive substring match.

    Args:
        name: Substring to match against security-zone name.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum matching zones to return.

    Returns:
        Every matching security zone with its ID, capped at 50 candidates.

    Examples:
        - find_security_zone(name="lan")
    """
    return _simple_find(
        "find_security_zone",
        "security_zones",
        "security zone",
        name,
        lambda: registry.client.call_sdk(registry.client.sdk.get.securityzones),
        ("name",),
        {"id", "name"},
        cursor,
        limit,
    )


@mcp.tool()
def find_wan_network(
    name: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Resolve a WAN network name to IDs by case-insensitive substring match.

    Args:
        name: Substring to match against WAN network name.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum matching networks to return.

    Returns:
        Every matching WAN network with its ID, capped at 50 candidates.

    Examples:
        - find_wan_network(name="MPLS")
    """
    return _simple_find(
        "find_wan_network",
        "wan_networks",
        "WAN network",
        name,
        lambda: registry.client.call_sdk(registry.client.sdk.get.wannetworks),
        ("name",),
        {"id", "name"},
        cursor,
        limit,
    )


@mcp.tool()
def find_path_group(
    name: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Resolve a path-group name to IDs by case-insensitive substring match.

    Args:
        name: Substring to match against path-group name.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum matching path groups to return.

    Returns:
        Every matching path group with its ID, capped at 50 candidates.

    Examples:
        - find_path_group(name="direct")
    """
    return _simple_find(
        "find_path_group",
        "path_groups",
        "path group",
        name,
        lambda: registry.client.call_sdk(registry.client.sdk.get.pathgroups),
        ("name",),
        {"id", "name"},
        cursor,
        limit,
    )


@mcp.tool()
def find_service_label(
    name: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Resolve a service-label name to IDs by case-insensitive substring match.

    Args:
        name: Substring to match against service-label name.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum matching labels to return.

    Returns:
        Every matching service label with its ID, capped at 50 candidates.

    Examples:
        - find_service_label(name="gold")
    """
    return _simple_find(
        "find_service_label",
        "service_labels",
        "service label",
        name,
        lambda: registry.client.call_sdk(registry.client.sdk.get.servicelabels),
        ("name",),
        {"id", "name"},
        cursor,
        limit,
    )


POLICY_SET_ENDPOINTS = (
    ("network", "networkpolicysets"),
    ("priority", "prioritypolicysets"),
    ("ngfw", "ngfwsecuritypolicysets"),
    ("nat", "natpolicysets"),
)


@mcp.tool()
def find_policy_set(
    name: str,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Resolve a policy-set name to IDs by case-insensitive substring match.

    Searches the network, priority, NGFW, and NAT policy-set families; each
    match carries its policy family.

    Args:
        name: Substring to match against policy-set name.
        cursor: Opaque cursor returned by a truncated response.
        limit: Maximum matching policy sets to return.

    Returns:
        Every matching policy set with its ID and family, capped at 50
        candidates; never a single auto-picked record.

    Examples:
        - find_policy_set(name="enterprise")
    """
    invalid = _validate_name(name, tool := "find_policy_set")
    if invalid:
        return invalid
    try:
        combined = []
        family_errors = {}
        for family, endpoint in POLICY_SET_ENDPOINTS:
            method = getattr(registry.client.sdk.get, endpoint, None)
            if method is None:
                family_errors[family] = f"SDK endpoint '{endpoint}' is unavailable"
                continue
            data = registry.client.call_sdk(method)
            if isinstance(data, dict) and "error" in data:
                family_errors[family] = data["error"]
                continue
            records = data if isinstance(data, list) else [data]
            combined.extend(
                {**record, "policy_family": family}
                for record in records
                if isinstance(record, dict)
            )
        extra = {"family_errors": family_errors} if family_errors else None
        return _find_response(
            "find_policy_set",
            "policy_sets",
            "policy set",
            name.strip(),
            combined,
            ("name",),
            cursor,
            limit,
            extra,
        )
    except Exception as error:
        return internal_error("find_policy_set", error)


def _first_value(item: dict, *names: str):
    for name in names:
        value = item.get(name)
        if value is not None:
            return value
    return None


def _anynet_transport(link: dict) -> str:
    remote_site_id = link.get("remote_site_id")
    if remote_site_id is not None and str(remote_site_id) not in ("0", "", "None"):
        return "private_wan"
    source_site = _first_value(link, "source_site_id", "source_site_name", "source_node_id")
    target_site = _first_value(link, "target_site_id", "target_site_name", "target_node_id")
    if (
        source_site is not None
        and target_site is not None
        and str(source_site) != str(target_site)
    ):
        return "private_wan"
    return "internet"


def _link_entry(link: dict) -> dict:
    return {
        "path_id": link.get("path_id") or link.get("id"),
        "resolved": True,
        "kind": "anynet_link",
        "transport": _anynet_transport(link),
        "source": link.get("source_site_name")
        or link.get("source_site_id")
        or link.get("source_node_id"),
        "target": link.get("target_site_name")
        or link.get("target_site_id")
        or link.get("target_node_id"),
        "status": link.get("status"),
    }


def _leg_entry(link: dict, leg: dict) -> dict:
    return {
        "path_id": leg.get("vpnlink_id") or leg.get("id"),
        "resolved": True,
        "kind": "vpnlink_leg",
        "transport": _anynet_transport(link),
        "parent_path_id": link.get("path_id") or link.get("id"),
        "ep1": {
            "site_id": _first_value(leg, "ep1_site_id", "source_site_id"),
            "element_id": _first_value(leg, "ep1_element_id", "source_element_id", "source_node_id"),
            "interface_id": _first_value(leg, "ep1_interface_id", "source_interface_id"),
        },
        "ep2": {
            "site_id": _first_value(leg, "ep2_site_id", "target_site_id", "destination_site_id"),
            "element_id": _first_value(leg, "ep2_element_id", "target_element_id", "target_node_id"),
            "interface_id": _first_value(leg, "ep2_interface_id", "target_interface_id", "destination_interface_id"),
        },
    }


@mcp.tool()
def resolve_path(site_id: str, path_id: str) -> str:
    """Resolve a bare path_id into a human-readable circuit descriptor.

    Handles direct-internet WAN interfaces (via the site's WAN interfaces)
    and anynet vpnlink legs (via the anynet topology). A path that matches
    nothing appears with ``resolved: false`` and a reason; it is never
    silently dropped or invented.

    Args:
        site_id: Site ID the path belongs to.
        path_id: Path or leg ID as reported by get_link_metrics or get_flows.

    Returns:
        A resolved circuit/path descriptor or an explicit unresolved entry.

    Examples:
        - resolve_path(site_id="site123", path_id="1730000000000000000")
    """
    tool = "resolve_path"
    site_id = site_id.strip() if site_id else ""
    path_id = path_id.strip() if path_id else ""
    if not site_id:
        return error_json("invalid_argument", "site_id is required and cannot be empty", tool, 400)
    if not path_id:
        return error_json("invalid_argument", "path_id is required and cannot be empty", tool, 400)
    try:
        wan_data = registry.client.call_sdk(registry.client.sdk.get.waninterfaces, site_id)
        wan_items = []
        if not (isinstance(wan_data, dict) and "error" in wan_data):
            wan_items = wan_data if isinstance(wan_data, list) else [wan_data]

        topology = {}
        topo_data = registry.client.call_sdk_post(
            registry.client.sdk.post.topology, {"type": "anynet"}
        )
        if isinstance(topo_data, dict) and "error" not in topo_data:
            topology = topo_data if isinstance(topo_data, dict) else {}
        links = topology.get("links", []) if isinstance(topology.get("links", []), list) else []

        entries = []
        resolved = False
        for wan in wan_items:
            if not isinstance(wan, dict):
                continue
            wan_id = _first_value(wan, "id", "interface_id")
            if wan_id is not None and str(wan_id) == path_id:
                entries.append(
                    {
                        "path_id": path_id,
                        "resolved": True,
                        "kind": "wan_interface",
                        "transport": "internet",
                        "name": _first_value(wan, "name", "interface_name"),
                        "site_id": site_id,
                        "element_id": _first_value(wan, "element_id"),
                    }
                )
                resolved = True
                break

        if not resolved:
            for link in links:
                if not isinstance(link, dict):
                    continue
                link_path_id = link.get("path_id") or link.get("id")
                if link_path_id is not None and str(link_path_id) == path_id:
                    entries.append(_link_entry(link))
                    resolved = True
                    break
                for leg in link.get("vpnlinks", []) or []:
                    if isinstance(leg, str):
                        if leg == path_id:
                            entries.append(
                                {
                                    "path_id": path_id,
                                    "resolved": True,
                                    "kind": "vpnlink_leg",
                                    "transport": _anynet_transport(link),
                                    "parent_path_id": link.get("path_id") or link.get("id"),
                                }
                            )
                            resolved = True
                            break
                        continue
                    if not isinstance(leg, dict):
                        continue
                    leg_id = leg.get("vpnlink_id") or leg.get("id")
                    if leg_id is not None and str(leg_id) == path_id:
                        entries.append(_leg_entry(link, leg))
                        resolved = True
                        break
                if resolved:
                    break

        if not resolved:
            entries.append(
                {
                    "path_id": path_id,
                    "resolved": False,
                    "reason": "no anynet link, vpnlink leg, or WAN interface matches this path_id",
                }
            )

        return build_envelope(
            tool,
            f"Path '{path_id}' resolved for site '{site_id}'"
            if resolved
            else f"Path '{path_id}' could not be resolved for site '{site_id}'",
            "paths",
            entries,
            extra={"resolved_count": sum(1 for entry in entries if entry.get("resolved"))},
        )
    except Exception as error:
        return internal_error(tool, error)
