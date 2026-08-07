from __future__ import annotations

from typing import Any, Literal, Optional

from ..config import get_max_fanout
from ..mcp import READ_ONLY, mcp
from ..response import collection_json, error_json, single_json
from .common import execute, fail_from_upstream, handle_error, project, records, site_element

RoutingOperation = Literal[
    "bgp_peers",
    "bgp_status",
    "bgp_prefixes",
    "bgp_config",
    "ospf_config",
    "ospf_neighbors",
    "ospf_prefixes",
    "static_routes",
    "route_maps",
    "prefix_lists",
    "community_lists",
    "aspath_lists",
]

DiagnosticOperation = Literal[
    "lldp_neighbors",
    "mac_table",
    "port_to_vlan",
    "vlan_to_port",
    "bfd_peers",
    "application_probe",
]


def _match_named(items: list[dict[str, Any]], value: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    needle = value.strip().lower()
    exact_id = [x for x in items if str(x.get("id", "")) == value]
    if exact_id:
        return exact_id
    exact_name = [x for x in items if any(x.get(f) is not None and str(x[f]).lower() == needle for f in fields)]
    if exact_name:
        return exact_name
    return [x for x in items if any(x.get(f) is not None and needle in str(x[f]).lower() for f in fields)]


@mcp.tool(annotations=READ_ONLY)
def get_routing(
    operation: RoutingOperation,
    element: str,
    site: Optional[str] = None,
    peer: Optional[str] = None,
    prefix_kind: Literal["reachable", "advertised", "discovered"] = "reachable",
    include_prefixes: bool = False,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect BGP, OSPF, static routes, and routing policy objects for one ION.

    Site and element accept names or IDs. ``bgp_status`` returns all peer states
    in one call where supported. ``bgp_prefixes`` resolves a specific BGP peer
    by peer ID/name/address and then retrieves reachable, advertised, or
    discovered prefixes. For ``bgp_status``, ``include_prefixes=true`` enables
    composite behavior: reachable/filtered prefix counts are added per peer
    and Established peers receiving zero reachable prefixes are flagged.
    OSPF neighbor/prefix operations enumerate OSPF configs and fan out safely.

    Args:
        operation: Which routing dataset to fetch. `bgp_peers`, `bgp_config`,
            `ospf_config`, `static_routes`, `route_maps`, `prefix_lists`,
            `community_lists`, and `aspath_lists` each return that object
            list directly. `bgp_status` returns peer session states with an
            `established` flag added. `bgp_prefixes` requires `peer` and
            returns one peer's prefixes (see `prefix_kind`).
            `ospf_neighbors`/`ospf_prefixes` fan out across every OSPF
            config found on the element.
        element: ION element name, serial number, hardware ID, or exact
            controller ID. Required for every operation.
        site: Site name or controller ID. Optional — inferred from
            `element`'s inventory record when possible; only needed to
            disambiguate an element name that exists at more than one site.
        peer: BGP peer name, IP address, or exact ID. Required only for
            `bgp_prefixes`; resolved the same way as `element` (exact ID,
            then exact name/IP, then substring) — ambiguous or missing
            matches return a structured error with candidates instead of
            guessing. Ignored for every other operation.
        prefix_kind: For `bgp_prefixes` only: `"reachable"` (prefixes
            actually usable via this peer, the default), `"advertised"`
            (what we send the peer), or `"discovered"` (what the peer
            offered before filtering). Ignored for every other operation.
        include_prefixes: For `bgp_status` only. When true, also fetches
            per-peer reachable-prefix counts (one extra API call per peer,
            bounded by the server fan-out limit, default 100) and flags any Established
            peer with zero reachable prefixes via
            `established_zero_prefixes` — a fast way to spot a session
            that's up but not passing routes. Leave false for a quick
            status check. Ignored for every other operation.
        cursor: Opaque pagination token copied from a previous response's
            `next_cursor`. Omit on the first call.
        limit: Max items to return in this page. Omit to use the server
            default page size (50; max 200).
    """
    tool = "get_routing"
    try:
        site_id, element_id, _ = site_element(site, element)
        if not site_id or not element_id:
            return error_json("invalid_argument", "site and element must resolve to IDs", tool, 400)
        paths = {"site_id": site_id, "element_id": element_id}
        if operation == "bgp_peers":
            data = execute("routing_bgp_ospf.bgppeers", paths)
            items = records(data)
        elif operation == "bgp_config":
            data = execute("routing_bgp_ospf.bgpconfigs", paths)
            items = records(data)
        elif operation == "bgp_status":
            data = execute("routing_bgp_ospf.bgppeers_status", paths)
            items = records(data)
            established_count = 0
            for item in items:
                state = str(item.get("state") or item.get("status") or item.get("session_state") or item.get("bgp_state") or "").lower()
                is_established = state in {"established", "up", "connected"}
                item["established"] = is_established
                established_count += int(is_established)
            extra = {
                "established_count": established_count,
                "not_established_count": len(items) - established_count,
            }
            if include_prefixes:
                zero_prefix_peers = 0
                for item in items[:get_max_fanout()]:
                    peer_id = item.get("id") or item.get("peer_id")
                    if not peer_id:
                        continue
                    prefixes = execute("routing_bgp_ospf.bgppeers_reachableprefixes", {**paths, "bgppeer_id": peer_id})
                    if isinstance(prefixes, dict) and "error" in prefixes:
                        item["prefix_error"] = prefixes["error"]
                        continue
                    prefix_rows = records(prefixes)
                    # Some controller versions return one summary object rather than
                    # one record per prefix. Prefer explicit count fields when present.
                    reachable = 0
                    filtered = 0
                    if isinstance(prefixes, dict):
                        reachable = int(prefixes.get("reachable_ipv4_prefixes_count") or 0) + int(prefixes.get("reachable_ipv6_prefixes_count") or 0)
                        filtered = int(prefixes.get("filtered_ipv4_prefixes_count") or 0) + int(prefixes.get("filtered_ipv6_prefixes_count") or 0)
                    if reachable == 0 and prefix_rows:
                        first = prefix_rows[0]
                        explicit = any(k in first for k in ("reachable_ipv4_prefixes_count", "reachable_ipv6_prefixes_count"))
                        if explicit:
                            reachable = int(first.get("reachable_ipv4_prefixes_count") or 0) + int(first.get("reachable_ipv6_prefixes_count") or 0)
                            filtered = int(first.get("filtered_ipv4_prefixes_count") or 0) + int(first.get("filtered_ipv6_prefixes_count") or 0)
                        else:
                            reachable = len(prefix_rows)
                            filtered = sum(1 for row in prefix_rows if row.get("filtered") in (True, "true", "yes", 1, "1") or str(row.get("status") or row.get("state") or "").lower() in {"filtered", "denied", "rejected"})
                    item["reachable_prefix_count"] = reachable
                    item["filtered_prefix_count"] = filtered
                    item["established_zero_prefixes"] = bool(item.get("established")) and reachable == 0
                    if item["established_zero_prefixes"]:
                        zero_prefix_peers += 1
                extra["zero_prefix_peers"] = zero_prefix_peers
                extra["prefix_fanout_capped"] = len(items) > get_max_fanout()
            return collection_json(tool, f"BGP status: {established_count} established, {len(items)-established_count} not established", "items", items, cursor=cursor, limit=limit, extra={**extra, "operation": operation, "site_id": site_id, "element_id": element_id})
        elif operation == "bgp_prefixes":
            if not peer or not peer.strip():
                return error_json("invalid_argument", "peer is required for bgp_prefixes", tool, 400)
            peers = records(execute("routing_bgp_ospf.bgppeers", paths))
            matches = _match_named(peers, peer, ("name", "peer_ip", "peer_ip_address", "ip_address"))
            if not matches:
                return error_json("not_found", f"no BGP peer matches '{peer}'", tool, 404)
            if len(matches) > 1:
                return error_json("ambiguous_match", f"{len(matches)} BGP peers match '{peer}'", tool, 409, {"candidates": project(matches, {"id", "name", "peer_ip", "peer_ip_address"})})
            peer_id = matches[0].get("id") or matches[0].get("bgppeer_id")
            if not peer_id:
                return error_json("unresolved_relationship", "matched BGP peer has no ID", tool, 409)
            action = {
                "reachable": "routing_bgp_ospf.bgppeers_reachableprefixes",
                "advertised": "routing_bgp_ospf.bgppeers_advertisedprefixes",
                "discovered": "routing_bgp_ospf.bgppeers_discoveredprefixes",
            }[prefix_kind]
            data = execute(action, {**paths, "bgppeer_id": peer_id})
            upstream = fail_from_upstream(tool, data)
            if upstream:
                return upstream
            return single_json(tool, f"BGP {prefix_kind} prefixes for peer '{peer}'", "prefixes", data, extra={"peer": project(matches, {"id", "name", "peer_ip", "peer_ip_address"})[0]})
        elif operation == "ospf_config":
            data = execute("routing_bgp_ospf.ospfconfigs", paths)
            items = records(data)
        elif operation in {"ospf_neighbors", "ospf_prefixes"}:
            configs = records(execute("routing_bgp_ospf.ospfconfigs", paths))
            max_fanout = get_max_fanout()
            action = "routing_bgp_ospf.ospfconfigs_ospfdiscoveredneighbors" if operation == "ospf_neighbors" else "routing_bgp_ospf.ospfconfigs_ospfreachableprefixes"
            items = []
            for config in configs[:max_fanout]:
                config_id = config.get("id") or config.get("ospfconfig_id")
                if not config_id:
                    continue
                result = execute(action, {**paths, "ospfconfig_id": config_id})
                if isinstance(result, dict) and "error" in result:
                    items.append({"ospfconfig_id": config_id, "error": result["error"]})
                else:
                    for row in records(result):
                        items.append({"ospfconfig_id": config_id, **row})
        elif operation == "static_routes":
            data = execute("routing_bgp_ospf.staticroutes", paths)
            items = records(data)
        elif operation == "route_maps":
            data = execute("routing_bgp_ospf.routing_routemaps", paths)
            items = records(data)
        elif operation == "prefix_lists":
            data = execute("routing_bgp_ospf.routing_prefixlists", paths)
            items = records(data)
        elif operation == "community_lists":
            data = execute("routing_bgp_ospf.routing_ipcommunitylists", paths)
            items = records(data)
        elif operation == "aspath_lists":
            data = execute("routing_bgp_ospf.routing_aspathaccesslists", paths)
            items = records(data)
        else:
            return error_json("invalid_argument", f"unsupported routing operation '{operation}'", tool, 400)
        upstream = fail_from_upstream(tool, data if 'data' in locals() else None)
        if upstream and not items:
            return upstream
        return collection_json(tool, f"Routing operation '{operation}' returned {len(items)} item(s)", "items", items, cursor=cursor, limit=limit, extra={"operation": operation, "site_id": site_id, "element_id": element_id})
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_device_diagnostics(
    operation: DiagnosticOperation,
    element: str,
    site: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve common device-side diagnostic state without requiring raw API IDs.

    Covers LLDP neighbors, MAC table, switch port/VLAN mappings, BFD peers, and
    application-probe configuration. Site is inferred from the element whenever
    the element inventory record provides site_id.

    Args:
        operation: Which diagnostic to fetch. `lldp_neighbors` and
            `mac_table` need only `element`. `bfd_peers`, `port_to_vlan`,
            `vlan_to_port`, and `application_probe` also need a resolvable
            `site` (explicit, or inferred from the element's inventory
            record) — if neither is available, these four return an error
            rather than guessing. `port_to_vlan`/`vlan_to_port` additionally
            require a switch-capable element model; on other models the
            controller rejects the read with a "does not support switch
            configuration" message, which means wrong device type, not a
            failed lookup — don't retry it against the same element.
        element: ION element name, serial number, hardware ID, or exact
            controller ID. Always required.
        site: Site name or controller ID. Optional for `lldp_neighbors`/
            `mac_table`; required (explicit or inferable from `element`)
            for `bfd_peers`, `port_to_vlan`, `vlan_to_port`, and
            `application_probe`.
        cursor: Opaque pagination token copied from a previous response's
            `next_cursor`. Omit on the first call.
        limit: Max items to return in this page. Omit to use the server
            default page size (50; max 200).
    """
    tool = "get_device_diagnostics"
    try:
        site_id, element_id, _ = site_element(site, element)
        if not element_id:
            return error_json("invalid_argument", "element is required", tool, 400)
        if operation == "lldp_neighbors":
            data = execute("device_diagnostics.lldp_neighbors_status", {"element_id": element_id})
        elif operation == "mac_table":
            data = execute("device_diagnostics.mac_addresses_status", {"element_id": element_id})
        elif operation == "bfd_peers":
            if not site_id:
                return error_json("invalid_argument", "site could not be inferred for BFD lookup", tool, 400)
            data = execute("device_diagnostics.bfdpeers", {"site_id": site_id})
        else:
            if not site_id:
                return error_json("invalid_argument", "site could not be inferred for this diagnostic", tool, 400)
            action = {
                "port_to_vlan": "device_diagnostics.port_vlan_members",
                "vlan_to_port": "device_diagnostics.vlan_port_members",
                "application_probe": "device_diagnostics.application_probe",
            }[operation]
            data = execute(action, {"site_id": site_id, "element_id": element_id})
        upstream = fail_from_upstream(tool, data)
        if upstream:
            return upstream
        items = records(data)
        return collection_json(tool, f"Diagnostic '{operation}' returned {len(items)} item(s)", "items", items, cursor=cursor, limit=limit, extra={"operation": operation, "site_id": site_id, "element_id": element_id})
    except Exception as exc:
        return handle_error(tool, exc)
