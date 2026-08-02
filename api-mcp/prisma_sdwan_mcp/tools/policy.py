from typing import Optional

from .. import registry
from ..formatting import collection_response, error_json, internal_error, single_response


mcp = registry.mcp


POLICY_FAMILIES = {
    "network": ("networkpolicysets", "networkpolicysetstacks"),
    "priority": ("prioritypolicysets", "prioritypolicysetstacks"),
    "ngfw": ("ngfwsecuritypolicysets", "ngfwsecuritypolicysetstacks"),
    "nat": ("natpolicysets", None),
}


def _validate_limit(limit: int | None, tool: str) -> str | None:
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        return error_json("invalid_limit", "limit must be at least 1", tool, 400)
    return None


def _fetch_sdk_method(name: str):
    return getattr(registry.client.sdk.get, name, None)


def _call_family(endpoint: str):
    method = _fetch_sdk_method(endpoint)
    if method is None:
        return {"error": f"SDK endpoint '{endpoint}' is unavailable", "status_code": 501}
    return registry.client.call_sdk(method)


@mcp.tool()
def get_policy_sets(
    kind: str = "all",
    include_stacks: bool = False,
    policyset_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve policy sets from the populated policy families.

    Args:
        kind: ``network``, ``priority``, ``ngfw``, ``nat``, or ``all``.
        include_stacks: Include matching policy-set stacks in a separate section.
        policyset_id: Optional legacy single policy-set lookup ID.
        cursor: Opaque cursor for the combined policy-set collection.
        limit: Maximum policy sets to return.

    Returns:
        Family-labeled policy sets with independent family counts and errors.

    Examples:
        - get_policy_sets()
        - get_policy_sets(kind="network", include_stacks=True)
    """
    tool = "get_policy_sets"
    kind = kind.strip().lower() if kind else ""
    if kind not in {"network", "priority", "ngfw", "nat", "all"}:
        return error_json("invalid_argument", "kind must be network, priority, ngfw, nat, or all", tool, 400)
    if policyset_id is not None:
        policyset_id = policyset_id.strip()
        if not policyset_id:
            return error_json("invalid_argument", "policyset_id cannot be empty", tool, 400)
    invalid = _validate_limit(limit, tool)
    if invalid:
        return invalid
    try:
        if policyset_id:
            legacy = _fetch_sdk_method("policysets")
            if legacy is None:
                return error_json("upstream_error", "legacy policy-set lookup is unavailable", tool, 501)
            data = registry.client.call_sdk(legacy, policyset_id)
            return single_response(tool, f"Policy set details for ID '{policyset_id}'", "policy_set", data)

        selected = POLICY_FAMILIES if kind == "all" else {kind: POLICY_FAMILIES[kind]}
        combined = []
        stacks = {}
        family_counts = {}
        family_errors = {}
        for family, (sets_endpoint, stacks_endpoint) in selected.items():
            result = _call_family(sets_endpoint)
            if isinstance(result, dict) and "error" in result:
                family_counts[family] = 0
                family_errors[family] = result["error"]
                continue
            items = result if isinstance(result, list) else [result]
            family_counts[family] = len(items)
            combined.extend({**item, "policy_family": family} if isinstance(item, dict) else {"value": item, "policy_family": family} for item in items)
            if include_stacks and stacks_endpoint:
                stack_result = _call_family(stacks_endpoint)
                if isinstance(stack_result, dict) and "error" in stack_result:
                    family_errors[f"{family}_stacks"] = stack_result["error"]
                    stacks[family] = []
                else:
                    stack_items = stack_result if isinstance(stack_result, list) else [stack_result]
                    stacks[family] = stack_items

        extra = {"family_counts": family_counts}
        if family_errors:
            extra["family_errors"] = family_errors
        if include_stacks:
            extra["stacks"] = stacks
        return collection_response(
            tool,
            f"Retrieved {len(combined)} policy set(s) across {len(selected)} family/families",
            "policy_sets",
            combined,
            cursor=cursor,
            limit=limit,
            extra=extra,
        )
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool()
def get_security_zones(
    securityzone_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve security zones.

    Args:
        securityzone_id: Optional security zone ID.
        cursor: Opaque cursor for list results.
        limit: Maximum zones to return.

    Returns:
        A compact security-zone response.

    Examples:
        - get_security_zones()
    """
    tool = "get_security_zones"
    if securityzone_id is not None:
        securityzone_id = securityzone_id.strip()
        if not securityzone_id:
            return error_json("invalid_argument", "securityzone_id cannot be empty", tool, 400)
    invalid = _validate_limit(limit, tool)
    if invalid:
        return invalid
    try:
        if securityzone_id:
            data = registry.client.call_sdk(registry.client.sdk.get.securityzones, securityzone_id)
            return single_response(tool, f"Security zone details for ID '{securityzone_id}'", "security_zone", data)
        data = registry.client.call_sdk(registry.client.sdk.get.securityzones)
        return collection_response(tool, "Security zones retrieved", "security_zones", data, cursor=cursor, limit=limit)
    except Exception as error:
        return internal_error(tool, error)


def _reference_tool(tool, key, endpoint, identifier, value, cursor, limit):
    if value is not None:
        value = value.strip()
        if not value:
            return error_json("invalid_argument", f"{identifier} cannot be empty", tool, 400)
    invalid = _validate_limit(limit, tool)
    if invalid:
        return invalid
    try:
        method = _fetch_sdk_method(endpoint)
        if method is None:
            return error_json("upstream_error", f"SDK endpoint '{endpoint}' is unavailable", tool, 501)
        data = registry.client.call_sdk(method, value) if value else registry.client.call_sdk(method)
        if value:
            return single_response(tool, f"{key} details for ID '{value}'", key[:-1], data)
        return collection_response(tool, f"{key} retrieved", key, data, cursor=cursor, limit=limit)
    except Exception as error:
        return internal_error(tool, error)


@mcp.tool()
def get_path_groups(
    pathgroup_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve path groups by optional ID."""
    return _reference_tool("get_path_groups", "path_groups", "pathgroups", "pathgroup_id", pathgroup_id, cursor, limit)


@mcp.tool()
def get_service_labels(
    servicelabel_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve service labels by optional ID."""
    return _reference_tool("get_service_labels", "service_labels", "servicelabels", "servicelabel_id", servicelabel_id, cursor, limit)


@mcp.tool()
def get_wan_networks(
    wannetwork_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve WAN networks by optional ID."""
    return _reference_tool("get_wan_networks", "wan_networks", "wannetworks", "wannetwork_id", wannetwork_id, cursor, limit)
