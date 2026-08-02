from collections import Counter
from typing import Optional

from .. import registry
from ..formatting import (
    ELEMENT_KEEP_FIELDS,
    MACHINE_KEEP_FIELDS,
    SITE_KEEP_FIELDS,
    collection_response,
    bounded_response,
    error_json,
    internal_error,
    project_items,
    single_response,
)


mcp = registry.mcp


def _slim_element(element: dict) -> dict:
    return {key: value for key, value in element.items() if key in ELEMENT_KEEP_FIELDS}


def _slim_site(site: dict) -> dict:
    slim = {key: value for key, value in site.items() if key in SITE_KEEP_FIELDS}
    address = site.get("address")
    if isinstance(address, dict):
        if address.get("city"):
            slim["city"] = address["city"]
        if address.get("country"):
            slim["country"] = address["country"]
    location = site.get("location")
    if isinstance(location, dict):
        if location.get("latitude") is not None:
            slim["latitude"] = location["latitude"]
        if location.get("longitude") is not None:
            slim["longitude"] = location["longitude"]
    return slim


def _validate_limit(limit: int | None, tool: str) -> str | None:
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        return error_json("invalid_limit", "limit must be at least 1", tool, 400)
    return None


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_sites(
    site_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve projected site inventory or one full site.

    Args:
        site_id: Optional site ID for an unprojected single-site lookup.
        cursor: Opaque cursor returned by a truncated list response.
        limit: Maximum list items to return.

    Returns:
        A compact, budgeted JSON response.

    Examples:
        - get_sites()
        - get_sites(site_id="1234567890")
    """
    tool = "get_sites"
    if site_id is not None:
        site_id = site_id.strip()
        if not site_id:
            return error_json("invalid_argument", "site_id cannot be empty", tool, 400)
    invalid_limit = _validate_limit(limit, tool)
    if invalid_limit:
        return invalid_limit
    try:
        if site_id:
            data = registry.client.call_sdk(registry.client.sdk.get.sites, site_id)
            return single_response(tool, f"Site details for ID '{site_id}'", "site", data)
        data = registry.client.call_sdk(registry.client.sdk.get.sites)
        if isinstance(data, dict) and "error" in data:
            return collection_response(tool, "Sites retrieved", "sites", data)
        slim_items = [_slim_site(item) for item in (data if isinstance(data, list) else [data])]
        return collection_response(
            tool,
            "Sites retrieved",
            "sites",
            slim_items,
            None,
            cursor,
            limit,
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
def get_elements(
    element_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve slim element inventory or one full element.

    Args:
        element_id: Optional element ID for an unprojected single-element lookup.
        cursor: Opaque cursor returned by a truncated list response.
        limit: Maximum list items to return.

    Returns:
        A compact, budgeted JSON response.

    Examples:
        - get_elements()
        - get_elements(element_id="1234567890")
    """
    tool = "get_elements"
    if element_id is not None:
        element_id = element_id.strip()
        if not element_id:
            return error_json("invalid_argument", "element_id cannot be empty", tool, 400)
    invalid_limit = _validate_limit(limit, tool)
    if invalid_limit:
        return invalid_limit
    try:
        if element_id:
            data = registry.client.call_sdk(registry.client.sdk.get.elements, element_id)
            return single_response(tool, f"Element details for ID '{element_id}'", "element", data)
        data = registry.client.call_sdk(registry.client.sdk.get.elements)
        if isinstance(data, dict) and "error" in data:
            return collection_response(tool, "Elements retrieved", "elements", data)
        slim_items = [_slim_element(item) for item in (data if isinstance(data, list) else [data])]
        return collection_response(
            tool,
            "Elements retrieved",
            "elements",
            slim_items,
            None,
            cursor,
            limit,
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
def get_machines(
    machine_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve projected machine inventory or one full machine.

    Args:
        machine_id: Optional machine ID for an unprojected single-machine lookup.
        cursor: Opaque cursor returned by a truncated list response.
        limit: Maximum list items to return.

    Returns:
        A compact, budgeted JSON response.

    Examples:
        - get_machines()
        - get_machines(machine_id="1234567890")
    """
    tool = "get_machines"
    if machine_id is not None:
        machine_id = machine_id.strip()
        if not machine_id:
            return error_json("invalid_argument", "machine_id cannot be empty", tool, 400)
    invalid_limit = _validate_limit(limit, tool)
    if invalid_limit:
        return invalid_limit
    try:
        if machine_id:
            data = registry.client.call_sdk(registry.client.sdk.get.machines, machine_id)
            return single_response(tool, f"Machine details for ID '{machine_id}'", "machine", data)
        data = registry.client.call_sdk(registry.client.sdk.get.machines)
        return collection_response(
            tool,
            "Machines retrieved",
            "machines",
            data,
            MACHINE_KEEP_FIELDS,
            cursor,
            limit,
        )
    except Exception as error:
        return internal_error(tool, error)


_APPDEF_FIELDS = {"id", "display_name", "category", "app_type"}


def _appdef_projection(item: dict) -> dict:
    projected = {
        key: item.get(key)
        for key in _APPDEF_FIELDS
    }
    if projected.get("display_name") is None:
        projected["display_name"] = item.get("name") or item.get("app_name")
    return projected


def _appdef_matches(item: dict, search: str | None, category: str | None) -> bool:
    if category and str(item.get("category", "")).lower() != category.lower():
        return False
    if search:
        needle = search.lower()
        values = (
            item.get("id"),
            item.get("name"),
            item.get("display_name"),
            item.get("app_name"),
        )
        return any(needle in str(value).lower() for value in values if value is not None)
    return True


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_app_defs(
    search: Optional[str] = None,
    category: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Search application definitions without dumping the full catalog.

    Args:
        search: Optional case-insensitive name, display-name, or ID search.
        category: Optional exact category filter.
        cursor: Opaque cursor returned by a truncated search response.
        limit: Maximum matching records to return.

    Returns:
        A category histogram and guidance when unfiltered, or projected matches.

    Examples:
        - get_app_defs()
        - get_app_defs(search="office")
        - get_app_defs(category="real-time")
    """
    tool = "get_app_defs"
    search = search.strip() if search else None
    category = category.strip() if category else None
    invalid_limit = _validate_limit(limit, tool)
    if invalid_limit:
        return invalid_limit
    try:
        data = registry.client.call_sdk(registry.client.sdk.get.appdefs)
        if isinstance(data, dict) and "error" in data:
            return collection_response(tool, "Application definitions unavailable", "app_defs", data)
        records = data if isinstance(data, list) else [data]
        if not search and not category:
            histogram = Counter(str(item.get("category", "uncategorized")) for item in records)
            payload = {
                "tool": tool,
                "summary": "Application catalog is intentionally not returned unfiltered",
                "categories": dict(sorted(histogram.items())),
                "guidance": "Supply search or category to retrieve projected application definitions.",
                "truncated": False,
                "total_count": 0,
                "returned_count": 0,
            }
            return bounded_response(tool, payload)
        matches = [_appdef_projection(item) for item in records if _appdef_matches(item, search, category)]
        return collection_response(
            tool,
            f"Found {len(matches)} matching application definition(s)",
            "app_defs",
            matches,
            None,
            cursor,
            limit,
        )
    except Exception as error:
        return internal_error(tool, error)
