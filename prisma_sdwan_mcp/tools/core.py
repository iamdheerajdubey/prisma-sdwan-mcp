from __future__ import annotations

from collections import Counter
from typing import Any, Literal, Optional

from ..config import get_max_fanout
from ..mcp import READ_ONLY, mcp
from ..response import collection_json, error_json, single_json
from .common import execute, fail_from_upstream, handle_error, match_named, project, records, resolve, site_element, summarize_states

InventoryKind = Literal["sites", "elements", "machines", "applications"]
InterfaceMode = Literal["config", "status", "both"]
WanOperation = Literal[
    "interfaces",
    "networks",
    "paths",
    "vpn_links",
    "vpn_leg_status",
    "vpn_leg_state",
    "vrfs",
    "lan_networks",
    "ipsec_profiles",
]

SITE_FIELDS = {"id", "name", "description", "admin_state", "element_cluster_role", "address", "location", "network_policysetstack_id", "priority_policysetstack_id", "nat_policysetstack_id", "perfmgmt_policysetstack_id", "app_acceleration_enabled", "branch_gateway"}
ELEMENT_FIELDS = {"id", "name", "description", "site_id", "serial_number", "hw_id", "model_name", "software_version", "role", "state", "connected"}
MACHINE_FIELDS = {"id", "name", "hw_id", "sl_no", "serial_number", "model_name", "image_version", "machine_state", "ship_state", "suspend_state", "connected", "em_element_id"}
APP_FIELDS = {"id", "display_name", "name", "category", "description"}
WAN_FIELDS = {"id", "name", "description", "network_id", "type", "cost", "bfd_mode", "bwc_enabled", "bw_config_mode", "lqm_enabled", "link_bw_up", "link_bw_down", "label_id", "element_id", "site_id"}


def _filter_search(items: list[dict[str, Any]], search: str | None) -> list[dict[str, Any]]:
    if not search:
        return items
    needle = search.strip().lower()
    if not needle:
        return items
    return [
        item
        for item in items
        if any(needle in str(item.get(field, "")).lower() for field in ("name", "display_name", "description", "id", "serial_number", "hw_id"))
    ]


@mcp.tool(annotations=READ_ONLY)
def get_inventory(
    kind: InventoryKind,
    search: Optional[str] = None,
    detail: Literal["summary", "full"] = "summary",
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve core Prisma SD-WAN inventory with compact operator-oriented output.

    ``kind`` selects sites, ION elements, hardware machines, or application
    definitions. Summary mode projects the fields most useful for reasoning;
    full mode preserves the redacted controller record and should be used with
    a search/limit for large collections.

    Args:
        kind: Inventory collection to retrieve: `sites`, `elements`
            (IONs), `machines` (hardware), or `applications`. Use
            `find_site`/`find_element`/`find_resource` instead if you already
            know a name and just need to resolve it to an ID.
        search: Case-insensitive substring filter across name, display_name,
            description, id, serial_number, and hw_id. Omit to return the
            whole collection (subject to `limit`).
        detail: `summary` (default) projects only the most relevant fields
            for reasoning. `full` returns the complete redacted controller
            record per item — use with `search` or a tight `limit` for large
            collections (e.g. `applications` can be thousands of rows).
            Note: `kind="applications"` with no `search` and `detail="summary"`
            ignores pagination and instead returns one aggregate summary
            (`total_applications` + counts per category), not a row list.
        cursor: Opaque pagination token copied from a previous response's
            `next_cursor`. Omit on the first call.
        limit: Max items to return in this page. Omit to use the server
            default page size (50; max 200).
    """
    tool = "get_inventory"
    mapping = {
        "sites": ("sites_devices.sites", SITE_FIELDS),
        "elements": ("sites_devices.elements", ELEMENT_FIELDS),
        "machines": ("platform_specialized.machines", MACHINE_FIELDS),
        "applications": ("security_policies.appdefs", APP_FIELDS),
    }
    try:
        action_id, fields = mapping[kind]
        data = execute(action_id)
        upstream = fail_from_upstream(tool, data)
        if upstream:
            return upstream
        items = _filter_search(records(data), search)
        if kind == "applications" and not search and detail == "summary":
            categories = Counter(str(item.get("category", "uncategorized")) for item in items)
            return single_json(
                tool,
                "Application catalog summarized; use search for individual applications",
                "application_summary",
                {"total_applications": len(items), "categories": dict(sorted(categories.items()))},
            )
        result = items if detail == "full" else project(items, fields)
        return collection_json(tool, f"Retrieved {len(result)} {kind}", kind, result, cursor=cursor, limit=limit, extra={"detail": detail, "search": search})
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_device_health(
    element: str,
    site: Optional[str] = None,
    include_software: bool = True,
    include_interfaces: bool = False,
    interface_limit: int = 25,
) -> str:
    """Return a combined health view for one ION element.

    ``element`` and ``site`` accept names or IDs. The tool resolves IDs safely,
    fetches element operational state, optionally software state/status, and can
    fan out to interface status. Interface fan-out is intentionally bounded.

    Args:
        element: Element name, serial number, hardware ID, or exact
            controller ID. If it resolves to exactly one record, `site` can
            be omitted — the element's own site is used. Ambiguous names
            (e.g. a short substring matching many elements) fail instead of
            guessing; pass an exact name/ID or add `site` to narrow it.
        site: Site name or controller ID that should own `element`. Optional
            when `element` already resolves uniquely on its own.
        include_software: When true (default), also fetch software
            state/status for the element. A failure here is reported inline
            under `partial_errors` rather than failing the whole call.
        include_interfaces: When true, also fan out to per-interface status
            (bounded by `interface_limit`). Off by default because it adds
            one API call per interface.
        interface_limit: Max interfaces to fetch status for when
            `include_interfaces` is true. Ignored otherwise. Must be between
            1 and the server's fan-out ceiling (default 100).
    """
    tool = "get_device_health"
    try:
        site_id, element_id, element_record = site_element(site, element)
        if not element_id:
            return error_json("not_found", "element could not be resolved", tool, 404)
        health = execute("sites_devices.element_status", {"element_id": element_id})
        upstream = fail_from_upstream(tool, health)
        if upstream:
            return upstream
        result: dict[str, Any] = {
            "identity": element_record,
            "element_status": health,
        }
        errors: dict[str, Any] = {}
        if include_software:
            sw_state = execute("software_upgrades.software_state", {"element_id": element_id})
            sw_status = execute("software_upgrades.software_status", {"element_id": element_id})
            if fail_from_upstream(tool, sw_state):
                errors["software_state"] = sw_state
            else:
                result["software_state"] = sw_state
            if fail_from_upstream(tool, sw_status):
                errors["software_status"] = sw_status
            else:
                result["software_status"] = sw_status
        if include_interfaces:
            if not site_id:
                errors["interfaces"] = {"error": "site_id unavailable for resolved element"}
            elif interface_limit < 1 or interface_limit > get_max_fanout():
                return error_json("invalid_limit", f"interface_limit must be between 1 and {get_max_fanout()}", tool, 400)
            else:
                configs = records(execute("sites_devices.interfaces", {"site_id": site_id, "element_id": element_id}))
                statuses = []
                for interface in configs[:interface_limit]:
                    interface_id = interface.get("id") or interface.get("interface_id")
                    if not interface_id:
                        continue
                    status = execute("sites_devices.interfaces_status", {"site_id": site_id, "element_id": element_id, "interface_id": interface_id})
                    if isinstance(status, dict):
                        status = {"interface_id": interface_id, **status}
                    statuses.append(status)
                result["interfaces"] = statuses
                result["interface_summary"] = {
                    "enumerated": len(configs),
                    "checked": len(statuses),
                    "capped": len(configs) > interface_limit,
                    "states": summarize_states([x for x in statuses if isinstance(x, dict)]),
                }
        if errors:
            result["partial_errors"] = errors
        return single_json(tool, f"Health view for element '{element}'", "health", result, extra={"site_id": site_id, "element_id": element_id})
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_interfaces(
    element: str,
    site: Optional[str] = None,
    mode: InterfaceMode = "both",
    interface: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve interface configuration and/or operational state for one element.

    If ``interface`` is omitted and status is requested, the tool enumerates the
    element interfaces then fans out to each status endpoint up to the fan-out ceiling
    (default 100). Individual interface failures remain inline.

    Args:
        element: Element name, serial number, hardware ID, or exact
            controller ID. If it resolves to exactly one record, `site` can
            be omitted — the element's own site is used.
        site: Site name or controller ID that should own `element`. Optional
            when `element` already resolves uniquely on its own.
        mode: `config` returns only interface configuration (no extra API
            calls). `status` returns only live operational state per
            interface. `both` (default) returns config plus status.
        interface: Optional filter to one interface by exact ID, exact name
            (case-insensitive), or name substring. Omit to return every
            interface on the element. An ambiguous substring returns every
            candidate rather than guessing.
        cursor: Opaque pagination token copied from a previous response's
            `next_cursor`. Omit on the first call.
        limit: Max interfaces to return in this page. Omit to use the server
            default page size (50; max 200).
    """
    tool = "get_interfaces"
    try:
        site_id, element_id, _ = site_element(site, element)
        if not site_id or not element_id:
            return error_json("invalid_argument", "both site_id and element_id are required after resolution", tool, 400)
        configs = records(execute("sites_devices.interfaces", {"site_id": site_id, "element_id": element_id}))
        if interface:
            matches = match_named(configs, interface)
            if not matches:
                return error_json("not_found", f"no interface matches '{interface}'", tool, 404)
            if len(matches) > 1:
                return error_json("ambiguous_match", f"{len(matches)} interfaces match '{interface}'", tool, 409, {"candidates": project(matches, {"id", "name", "type"})})
            configs = matches
        if mode == "config":
            return collection_json(tool, f"Interface configuration for '{element}'", "interfaces", configs, cursor=cursor, limit=limit, extra={"site_id": site_id, "element_id": element_id})
        max_fanout = get_max_fanout()
        checked = configs[:max_fanout]
        combined = []
        for config in checked:
            interface_id = config.get("id") or config.get("interface_id")
            if not interface_id:
                combined.append({"config": config, "error": "interface record has no id"})
                continue
            status = execute("sites_devices.interfaces_status", {"site_id": site_id, "element_id": element_id, "interface_id": interface_id})
            if mode == "status":
                row = {"interface_id": interface_id, "name": config.get("name"), "status": status}
            else:
                row = {"interface_id": interface_id, "name": config.get("name"), "config": config, "status": status}
            combined.append(row)
        return collection_json(
            tool,
            f"Interface {mode} for '{element}'",
            "interfaces",
            combined,
            cursor=cursor,
            limit=limit,
            extra={"site_id": site_id, "element_id": element_id, "enumerated": len(configs), "checked": len(checked), "fanout_capped": len(configs) > max_fanout},
        )
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_topology(
    detail: Literal["summary", "full"] = "summary",
    site: Optional[str] = None,
    status: Optional[str] = None,
    view: Literal["anynet", "basenet"] = "anynet",
    leg_offset: int = 0,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Return AnyNet topology with careful ID semantics preserved.

    Summary mode returns counts and links that are not up. Full mode requires a
    site or status filter to avoid flooding the model. ``view='basenet'`` derives
    the underlay: it takes VPN leg IDs from AnyNet and resolves each through live
    vpnlink status, exposing element/interface-level underlay information. A
    link's ``path_id`` and controller ``anynet_link_id`` are kept distinct.

    Args:
        detail: `summary` (default) returns link/node counts plus only the
            links that are not up. `full` returns every matching link and
            requires `site` or `status` to be set — a tenant-wide full dump
            is refused rather than flooding the response. `node_count`
            reflects the `nodes` array the controller's AnyNet payload
            actually returns, which can legitimately be 0 on tenants where
            the controller reports links only — a 0 node count alongside a
            non-zero link count is not an error, and link records still name
            their endpoints.
        site: Site name or controller ID to scope the topology to. Required
            for `detail="full"` (unless `status` is set) and for
            `view="basenet"`.
        status: Filter links to one status value (e.g. `"up"`), case
            insensitive. Can substitute for `site` when `detail="full"`.
        view: `anynet` (default) returns AnyNet-level links. `basenet`
            derives the underlay by resolving each AnyNet link's VPN legs
            through live status lookups — one API call per leg, capped at 100
            legs per call (the server fan-out ceiling) and resumed via
            `leg_offset`. Requires `site`.
        leg_offset: For `view="basenet"` only: index into the full VPN-leg
            list to resume from — use the previous response's
            `next_leg_offset`. Must be >= 0. Ignored for `view="anynet"`.
        cursor: Opaque pagination token copied from a previous response's
            `next_cursor`. Omit on the first call.
        limit: Max links to return in this page. Omit to use the server
            default page size (50; max 200).
    """
    tool = "get_topology"
    try:
        site_id = resolve("site", site)["id"] if site else None
        if detail == "full" and not site_id and not status:
            return error_json("invalid_argument", "detail='full' requires site or status", tool, 400)
        data = execute("compat.topology", body={"type": "anynet"})
        upstream = fail_from_upstream(tool, data)
        if upstream:
            return upstream
        topology = data if isinstance(data, dict) else {}
        nodes = topology.get("nodes", []) if isinstance(topology.get("nodes"), list) else []
        links = topology.get("links", []) if isinstance(topology.get("links"), list) else []
        if view == "basenet" and not site_id:
            return error_json("invalid_argument", "view='basenet' requires site", tool, 400)
        if isinstance(leg_offset, bool) or not isinstance(leg_offset, int) or leg_offset < 0:
            return error_json("invalid_argument", "leg_offset must be a non-negative integer", tool, 400)
        if site_id:
            aliases = {str(site_id)}
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                values = {str(node.get(k)) for k in ("id", "site_id", "node_id") if node.get(k) is not None}
                if str(site_id) in values:
                    aliases |= values
            def link_matches(link: dict[str, Any]) -> bool:
                values = {str(link.get(k)) for k in ("source_site_id", "target_site_id", "source_node_id", "target_node_id", "source", "target") if link.get(k) is not None}
                return bool(values & aliases)
            links = [x for x in links if isinstance(x, dict) and link_matches(x)]
        if status:
            links = [x for x in links if str(x.get("status", "")).lower() == status.strip().lower()]
        if view == "basenet":
            legs = []
            for link in links:
                if not isinstance(link, dict):
                    continue
                parent = link.get("path_id") or link.get("id")
                anynet_link_id = link.get("anynet_link_id") or parent
                for leg in link.get("vpnlinks") or []:
                    leg_id = leg if isinstance(leg, str) else (leg.get("vpnlink_id") or leg.get("id") if isinstance(leg, dict) else None)
                    if leg_id is not None:
                        legs.append((parent, anynet_link_id, str(leg_id)))
            cap = get_max_fanout()
            batch = legs[leg_offset:leg_offset + cap]
            entries = []
            for parent, anynet_link_id, leg_id in batch:
                state = execute("compat.vpnlinks_status", {"vpnlink_id": leg_id})
                if isinstance(state, dict) and "error" in state:
                    entries.append({"vpnlink_id": leg_id, "path_id": parent, "anynet_link_id": anynet_link_id, "error": state["error"]})
                    continue
                item = state if isinstance(state, dict) else {}
                entries.append({
                    "vpnlink_id": leg_id,
                    "path_id": parent,
                    "anynet_link_id": anynet_link_id,
                    "ep1_element_id": item.get("ep1_element_id"),
                    "ep2_element_id": item.get("ep2_element_id"),
                    "source_elem_if_id": item.get("ep1_interface_id"),
                    "target_elem_if_id": item.get("ep2_interface_id"),
                    "active": item.get("active"),
                    "usable": item.get("usable"),
                    "link_up": item.get("link_up"),
                    "derived_from_anynet": True,
                })
            return collection_json(
                tool,
                f"Derived basenet view for site '{site}' using {len(batch)} VPN leg status lookup(s)",
                "links",
                entries,
                cursor=cursor,
                limit=limit,
                extra={
                    "site_id": site_id,
                    "leg_total": len(legs),
                    "leg_offset": leg_offset,
                    "leg_count": len(batch),
                    "leg_resolution_capped": leg_offset + len(batch) < len(legs),
                    "next_leg_offset": leg_offset + len(batch) if leg_offset + len(batch) < len(legs) else None,
                    "view": "basenet",
                },
            )
        counts = Counter(str(x.get("status", "unknown")) for x in links if isinstance(x, dict))
        if detail == "summary":
            not_up = [
                {
                    "path_id": x.get("path_id") or x.get("id"),
                    "anynet_link_id": x.get("anynet_link_id"),
                    "source": x.get("source_site_name") or x.get("source_site_id") or x.get("source_node_id"),
                    "target": x.get("target_site_name") or x.get("target_site_id") or x.get("target_node_id"),
                    "status": x.get("status", "unknown"),
                    "vpnlinks": x.get("vpnlinks"),
                }
                for x in links
                if isinstance(x, dict) and str(x.get("status", "")).lower() != "up"
            ]
            return collection_json(tool, f"Topology summary: {len(nodes)} node(s), {len(links)} link(s)", "not_up_links", not_up, cursor=cursor, limit=limit, extra={"node_count": len(nodes), "link_count": len(links), "status_counts": dict(sorted(counts.items())), "site_id": site_id})
        return collection_json(tool, f"Filtered topology: {len(links)} link(s)", "links", links, cursor=cursor, limit=limit, extra={"nodes": nodes if site_id else None, "status_counts": dict(sorted(counts.items())), "site_id": site_id})
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_wan(
    operation: WanOperation,
    site: Optional[str] = None,
    element: Optional[str] = None,
    object_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect WAN, VPN, VRF, LAN, and IPsec read-only state through one semantic tool.

    Operations needing a site or element accept names or IDs. For VPN leg
    status/state, ``object_id`` is the vpnlink leg ID from topology, not the
    parent AnyNet path ID.

    Args:
        operation: Which WAN-related collection to inspect:
            `networks` (tenant-wide WAN network definitions, no site needed),
            `vrfs` (tenant-wide VRF contexts, no site needed),
            `ipsec_profiles` (tenant-wide, no site needed),
            `interfaces` (WAN interfaces — requires `site`),
            `paths` (WAN paths — requires `site`),
            `vpn_links` (all VPN links, tenant-wide — this endpoint cannot be
            narrowed by site or element, see `site`),
            `lan_networks` (requires `site`),
            `vpn_leg_status` / `vpn_leg_state` (live status/state for one VPN
            leg — requires `object_id`, not `site`).
        site: Site name or controller ID. Required (directly or via
            `element`) for `interfaces`, `paths`, and `lan_networks`;
            ignored by `vpn_links` (a VPN link record has no site field, so the
            controller rejects a site filter there — the full tenant list is
            returned and you can match legs to sites via `get_topology`);
            unused otherwise.
        element: Element name or controller ID, as an alternative to `site`
            for the same operations — the element's own site is used if it
            resolves uniquely. Unused for `networks`, `vrfs`,
            `ipsec_profiles`, and the `vpn_leg_*` operations.
        object_id: Required for `vpn_leg_status`/`vpn_leg_state` — the VPN
            leg ID from a topology tool's `basenet` view, not the parent
            AnyNet `path_id`.
        cursor: Opaque pagination token copied from a previous response's
            `next_cursor`. Omit on the first call.
        limit: Max items to return in this page. Omit to use the server
            default page size (50; max 200).
    """
    tool = "get_wan"
    try:
        if operation == "networks":
            data = execute("vpn_wan.wannetworks")
            items = project(records(data), {"id", "name", "description", "type"})
        elif operation == "vrfs":
            data = execute("vpn_wan.vrfcontexts")
            items = records(data)
        elif operation == "ipsec_profiles":
            data = execute("vpn_wan.ipsecprofiles")
            items = records(data)
        elif operation in {"vpn_leg_status", "vpn_leg_state"}:
            if not object_id or not object_id.strip():
                return error_json("invalid_argument", "object_id (vpnlink leg ID) is required", tool, 400)
            action = "compat.vpnlinks_status" if operation == "vpn_leg_status" else "compat.vpnlinks_state"
            data = execute(action, {"vpnlink_id": object_id.strip()})
            upstream = fail_from_upstream(tool, data)
            if upstream:
                return upstream
            return single_json(tool, f"{operation} for '{object_id}'", operation, data)
        else:
            site_id, element_id, _ = site_element(site, element)
            if operation in {"interfaces", "paths", "lan_networks"} and not site_id:
                return error_json("invalid_argument", "site is required for this operation", tool, 400)
            if operation == "interfaces":
                data = execute("vpn_wan.waninterfaces", {"site_id": site_id})
                items = project(records(data), WAN_FIELDS)
            elif operation == "paths":
                data = execute("vpn_wan.wanpaths", {"site_id": site_id})
                items = records(data)
            elif operation == "vpn_links":
                # Tenant-wide only. A VPN link record carries no site field at all
                # (just id/al_id/vep1_id/vep2_id/shim IPs), so the controller
                # rejects any site filter on this endpoint - previously this
                # operation demanded a site and then always failed with 400.
                data = execute("vpn_wan.vpnlinks_query", body={})
                items = records(data)
            elif operation == "lan_networks":
                data = execute("vpn_wan.lannetworks", {"site_id": site_id})
                items = records(data)
            else:
                return error_json("invalid_argument", f"unsupported operation '{operation}'", tool, 400)
        upstream = fail_from_upstream(tool, data)
        if upstream:
            return upstream
        return collection_json(tool, f"WAN operation '{operation}' returned {len(items)} item(s)", "items", items, cursor=cursor, limit=limit, extra={"operation": operation})
    except Exception as exc:
        return handle_error(tool, exc)
