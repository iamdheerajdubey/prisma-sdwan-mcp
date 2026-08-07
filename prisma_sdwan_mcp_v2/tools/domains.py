from __future__ import annotations

from typing import Literal, Optional

from ..mcp import READ_ONLY, mcp
from ..response import collection_json, error_json, single_json
from .common import execute, fail_from_upstream, handle_error, records, resolve, site_element

NetworkServiceOperation = Literal[
    "dns_services",
    "dns_profiles",
    "dns_roles",
    "dhcp_servers",
    "ntp",
    "ntp_status",
    "syslog_profiles",
    "syslog_servers",
    "snmp_agents",
    "snmp_traps",
    "tacacs_profiles",
    "tacacs_servers",
    "radius",
]
MulticastOperation = Literal[
    "config",
    "dynamic_rps",
    "rps",
    "peer_groups",
    "protocol_parameters",
    "source_rps",
    "source_site_config",
    "wan_status",
    "routes",
    "igmp_memberships",
]
IPFIXOperation = Literal[
    "config",
    "collectors",
    "filters",
    "profiles",
    "templates",
    "global_prefixes",
    "local_prefixes",
]
CellularOperation = Literal["modules", "module_images", "apn_profiles", "firmware_status", "machine_modules"]
SoftwareOperation = Literal["element_state", "element_status", "machine_upgrade", "upgrade_status", "site_templates", "template_deployments"]
IdentityOperation = Literal[
    "directory_service",
    "directory_status",
    "directory_users",
    "directory_groups",
    "active_user_ips",
    "tenant_users",
    "element_users",
    "element_user_access",
]
ServiceConnectionOperation = Literal[
    "tenant_connections",
    "site_connections",
    "endpoints",
    "binding_maps",
    "service_labels",
    "element_extensions",
    "site_extensions",
    "tenant_extensions",
]
PrismaAccessOperation = Literal[
    "site_config",
    "connections",
    "connection_status",
    "connection_config",
    "advertised_prefixes",
    "reachable_prefixes",
    "pa_networks",
    "integration_status",
    "adem_site_config",
    "adem_status",
]
PlatformOperation = Literal[
    "tenant",
    "licenses",
    "skus",
    "machines",
    "machine_system_status",
    "machine_software",
    "reports",
    "external_ca",
    "otp_access",
    "hub_service_endpoints",
]


def _finish(tool: str, operation: str, data, cursor: str | None, limit: int | None, extra: dict | None = None) -> str:
    upstream = fail_from_upstream(tool, data)
    if upstream:
        return upstream
    items = records(data)
    if items:
        return collection_json(tool, f"Operation '{operation}' returned {len(items)} item(s)", "items", items, cursor=cursor, limit=limit, extra=extra)
    return single_json(tool, f"Operation '{operation}'", "result", data, extra=extra)


@mcp.tool(annotations=READ_ONLY)
def get_network_services(
    operation: NetworkServiceOperation,
    site: Optional[str] = None,
    element: Optional[str] = None,
    object_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect DNS, DHCP, NTP, syslog, SNMP, TACACS+, and RADIUS read-only state.

    Site/element names are resolved to controller IDs. ``ntp_status`` accepts
    ``object_id`` as an NTP configuration ID; if omitted and exactly one NTP
    configuration exists on the element, that ID is used automatically.
    """
    tool = "get_network_services"
    try:
        site_id, element_id, _ = site_element(site, element) if (site or element) else (None, None, None)
        if operation == "dns_profiles":
            data = execute("dns_services.dnsserviceprofiles")
        elif operation == "dns_roles":
            data = execute("dns_services.dnsserviceroles")
        elif operation == "syslog_profiles":
            data = execute("platform_specialized.syslogserverprofiles")
        elif operation == "tacacs_profiles":
            data = execute("platform_specialized.tacacs_plus_profiles")
        elif operation in {"dns_services", "syslog_servers", "snmp_agents", "snmp_traps", "tacacs_servers"}:
            if not site_id or not element_id:
                return error_json("invalid_argument", "site and element are required for this operation", tool, 400)
            action = {
                "dns_services": "dns_services.dnsservices",
                "syslog_servers": "platform_specialized.syslogservers",
                "snmp_agents": "platform_specialized.snmpagents",
                "snmp_traps": "platform_specialized.snmptraps",
                "tacacs_servers": "platform_specialized.tacacs_plus_servers",
            }[operation]
            data = execute(action, {"site_id": site_id, "element_id": element_id})
        elif operation == "dhcp_servers":
            if not site_id:
                return error_json("invalid_argument", "site is required", tool, 400)
            data = execute("vpn_wan.dhcpservers", {"site_id": site_id})
        elif operation in {"ntp", "radius"}:
            if not element_id:
                return error_json("invalid_argument", "element is required", tool, 400)
            action = "platform_specialized.ntp" if operation == "ntp" else "platform_specialized.radii"
            data = execute(action, {"element_id": element_id})
        elif operation == "ntp_status":
            if not element_id:
                return error_json("invalid_argument", "element is required", tool, 400)
            ntp_id = object_id.strip() if object_id else None
            if not ntp_id:
                configs = records(execute("platform_specialized.ntp", {"element_id": element_id}))
                if len(configs) != 1:
                    return error_json("ambiguous_match", "object_id is required unless the element has exactly one NTP configuration", tool, 409, {"candidates": [{k: x.get(k) for k in ("id", "name") if x.get(k) is not None} for x in configs]})
                ntp_id = configs[0].get("id")
            data = execute("platform_specialized.ntp_status", {"element_id": element_id, "ntp_id": ntp_id})
        else:
            return error_json("invalid_argument", f"unsupported network service operation '{operation}'", tool, 400)
        return _finish(tool, operation, data, cursor, limit, {"site_id": site_id, "element_id": element_id})
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_multicast(
    operation: MulticastOperation,
    site: Optional[str] = None,
    element: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect multicast configuration, RPs, peer groups, routes, IGMP, and WAN status."""
    tool = "get_multicast"
    try:
        site_id, element_id, _ = site_element(site, element) if (site or element) else (None, None, None)
        if operation == "peer_groups":
            data = execute("multicast.multicastpeergroups")
        elif operation in {"source_rps", "source_site_config"}:
            if not site_id:
                return error_json("invalid_argument", "site is required", tool, 400)
            action = "multicast.multicastsourcesiderps" if operation == "source_rps" else "multicast.multicastsourcesiteconfigs"
            data = execute(action, {"site_id": site_id})
        elif operation in {"routes", "igmp_memberships"}:
            action = "multicast.multicastroutes_query" if operation == "routes" else "multicast.multicastigmpmemberships_query"
            body = {"query_params": {"site_id": site_id, "element_id": element_id}} if (site_id or element_id) else {}
            data = execute(action, body=body)
        else:
            if not site_id or not element_id:
                return error_json("invalid_argument", "site and element are required for this multicast operation", tool, 400)
            action = {
                "config": "multicast.multicastglobalconfigs",
                "dynamic_rps": "multicast.multicastdynamicrps",
                "rps": "multicast.multicastrps",
                "protocol_parameters": "multicast.multicastprotocolparameters",
                "wan_status": "multicast.multicastwanstatus",
            }.get(operation)
            if not action:
                return error_json("invalid_argument", f"unsupported multicast operation '{operation}'", tool, 400)
            data = execute(action, {"site_id": site_id, "element_id": element_id})
        return _finish(tool, operation, data, cursor, limit, {"site_id": site_id, "element_id": element_id})
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_ipfix(
    operation: IPFIXOperation,
    site: Optional[str] = None,
    element: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect IPFIX/flow-export configuration, collectors, filters, templates, and prefixes."""
    tool = "get_ipfix"
    try:
        site_id, element_id, _ = site_element(site, element) if (site or element) else (None, None, None)
        if operation == "config":
            if not site_id or not element_id:
                return error_json("invalid_argument", "site and element are required", tool, 400)
            data = execute("flow_monitoring_ipfix.ipfix", {"site_id": site_id, "element_id": element_id})
        elif operation == "collectors":
            data = execute("flow_monitoring_ipfix.ipfixcollectorcontexts")
        elif operation == "filters":
            data = execute("flow_monitoring_ipfix.ipfixfiltercontexts")
        elif operation == "profiles":
            data = execute("flow_monitoring_ipfix.ipfixprofiles")
        elif operation == "templates":
            data = execute("flow_monitoring_ipfix.ipfixtemplates")
        elif operation == "global_prefixes":
            data = execute("flow_monitoring_ipfix.ipfixglobalprefixes")
        elif operation == "local_prefixes":
            data = execute("flow_monitoring_ipfix.site_ipfixlocalprefixes", {"site_id": site_id}) if site_id else execute("flow_monitoring_ipfix.tenant_ipfixlocalprefixes")
        else:
            return error_json("invalid_argument", f"unsupported IPFIX operation '{operation}'", tool, 400)
        return _finish(tool, operation, data, cursor, limit, {"site_id": site_id, "element_id": element_id})
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_cellular(
    operation: CellularOperation,
    element: Optional[str] = None,
    machine: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect cellular modules, firmware status, APN profiles, and module images."""
    tool = "get_cellular"
    try:
        if operation == "module_images":
            data = execute("cellular.cellular_module_images")
        elif operation == "apn_profiles":
            data = execute("cellular.apnprofiles")
        elif operation == "firmware_status":
            data = execute("cellular.cellular_module_firmware_status_query", body={})
        elif operation == "machine_modules":
            if not machine:
                return error_json("invalid_argument", "machine is required", tool, 400)
            machine_rec = resolve("machine", machine)
            data = execute("platform_specialized.machine_cellular_modules", {"machine_id": machine_rec["id"]})
        else:
            if not element:
                return error_json("invalid_argument", "element is required", tool, 400)
            element_rec = resolve("element", element)
            data = execute("cellular.element_cellular_modules", {"element_id": element_rec["id"]})
        return _finish(tool, operation, data, cursor, limit)
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_software(
    operation: SoftwareOperation,
    element: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect element software state/status and tenant-wide upgrade/template status."""
    tool = "get_software"
    try:
        if operation in {"element_state", "element_status"}:
            if not element:
                return error_json("invalid_argument", "element is required", tool, 400)
            element_rec = resolve("element", element)
            action = "software_upgrades.software_state" if operation == "element_state" else "software_upgrades.software_status"
            data = execute(action, {"element_id": element_rec["id"]})
        else:
            action = {
                "machine_upgrade": "software_upgrades.machine_upgrade_query",
                "upgrade_status": "software_upgrades.upgrade_status_query",
                "site_templates": "software_upgrades.bulkconfigurations_sitetemplates_query",
                "template_deployments": "software_upgrades.bulkconfigurations_sitetemplates_deployments_query",
            }[operation]
            data = execute(action, body={})
        return _finish(tool, operation, data, cursor, limit)
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_identity(
    operation: IdentityOperation,
    object_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect directory/tenant identity state. Session/token fields are always redacted centrally."""
    tool = "get_identity"
    try:
        if operation == "directory_service":
            data = execute("users_identity.directoryservices")
        elif operation == "directory_status":
            data = execute("users_identity.directoryservices_status")
        elif operation == "directory_users":
            data = execute("users_identity.directoryusers")
        elif operation == "directory_groups":
            data = execute("users_identity.directoryusergroups")
        elif operation == "active_user_ips":
            data = execute("users_identity.activeuserips_query", body={})
        elif operation == "tenant_users":
            data = execute("users_identity.users")
        elif operation == "element_users":
            data = execute("users_identity.elementusers")
        elif operation == "element_user_access":
            if not object_id or not object_id.strip():
                return error_json("invalid_argument", "object_id (element user ID) is required", tool, 400)
            data = execute("users_identity.elementusers_access", {"elementuser_id": object_id.strip()})
        else:
            return error_json("invalid_argument", f"unsupported identity operation '{operation}'", tool, 400)
        return _finish(tool, operation, data, cursor, limit)
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_service_connections(
    operation: ServiceConnectionOperation,
    site: Optional[str] = None,
    element: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect service connections, endpoints, binding maps, service labels, and extensions."""
    tool = "get_service_connections"
    try:
        site_id, element_id, _ = site_element(site, element) if (site or element) else (None, None, None)
        if operation == "tenant_connections":
            data = execute("service_connections_extensions.tenant_serviceconnections")
        elif operation == "site_connections":
            if not site_id:
                return error_json("invalid_argument", "site is required", tool, 400)
            data = execute("service_connections_extensions.site_serviceconnections", {"site_id": site_id})
        elif operation == "endpoints":
            data = execute("service_connections_extensions.serviceendpoints")
        elif operation == "binding_maps":
            data = execute("service_connections_extensions.servicebindingmaps")
        elif operation == "service_labels":
            data = execute("service_connections_extensions.servicelabels")
        elif operation == "tenant_extensions":
            data = execute("service_connections_extensions.tenant_extensions")
        elif operation == "site_extensions":
            if not site_id:
                return error_json("invalid_argument", "site is required", tool, 400)
            data = execute("service_connections_extensions.site_extensions", {"site_id": site_id})
        elif operation == "element_extensions":
            if not site_id or not element_id:
                return error_json("invalid_argument", "site and element are required", tool, 400)
            data = execute("service_connections_extensions.element_extensions", {"site_id": site_id, "element_id": element_id})
        else:
            return error_json("invalid_argument", f"unsupported service connection operation '{operation}'", tool, 400)
        return _finish(tool, operation, data, cursor, limit, {"site_id": site_id, "element_id": element_id})
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_prisma_access(
    operation: PrismaAccessOperation,
    site: Optional[str] = None,
    element: Optional[str] = None,
    object_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect Prisma Access/SASE integration, connections, prefixes, and ADEM state."""
    tool = "get_prisma_access"
    try:
        site_id, element_id, _ = site_element(site, element) if (site or element) else (None, None, None)
        if operation in {"site_config", "connections", "adem_site_config", "adem_status"}:
            if not site_id:
                return error_json("invalid_argument", "site is required", tool, 400)
            action = {
                "site_config": "platform_specialized.prismaaccess_configs",
                "connections": "platform_specialized.prismasase_connections",
                "adem_site_config": "platform_specialized.demsiteconfigs",
                "adem_status": "platform_specialized.demstatus",
            }[operation]
            data = execute(action, {"site_id": site_id})
        elif operation == "connection_status":
            if not site_id or not object_id:
                return error_json("invalid_argument", "site and object_id (SASE connection ID) are required", tool, 400)
            data = execute("platform_specialized.prismasase_connections_status", {"site_id": site_id, "prismasase_connection_id": object_id})
        elif operation == "connection_config":
            data = execute("platform_specialized.prismasase_connections_configs")
        elif operation in {"advertised_prefixes", "reachable_prefixes"}:
            if not site_id or not element_id:
                return error_json("invalid_argument", "site and element are required", tool, 400)
            action = "platform_specialized.pa_advertisedprefixes" if operation == "advertised_prefixes" else "platform_specialized.pa_reachableprefixes"
            data = execute(action, {"site_id": site_id, "element_id": element_id})
        elif operation == "pa_networks":
            data = execute("platform_specialized.panetworks")
        elif operation == "integration_status":
            data = execute("platform_specialized.pasdwan_integration_status")
        else:
            return error_json("invalid_argument", f"unsupported Prisma Access operation '{operation}'", tool, 400)
        return _finish(tool, operation, data, cursor, limit, {"site_id": site_id, "element_id": element_id})
    except Exception as exc:
        return handle_error(tool, exc)


@mcp.tool(annotations=READ_ONLY)
def get_platform(
    operation: PlatformOperation,
    machine: Optional[str] = None,
    folder: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """Inspect tenant/platform metadata, licenses, SKUs, machines, and reports.

    Sensitive values in external CA or other returned objects are recursively
    redacted before leaving the server.
    """
    tool = "get_platform"
    try:
        if operation == "tenant":
            data = execute("platform_specialized.tenants")
        elif operation == "licenses":
            data = execute("platform_specialized.licenses")
        elif operation == "skus":
            data = execute("platform_specialized.skus")
        elif operation == "machines":
            data = execute("platform_specialized.machines")
        elif operation == "external_ca":
            data = execute("platform_specialized.externalcaconfigs")
        elif operation == "otp_access":
            data = execute("platform_specialized.otpaccessconfigs")
        elif operation == "hub_service_endpoints":
            data = execute("platform_specialized.tenant_hubserviceendpoints")
        elif operation in {"machine_system_status", "machine_software"}:
            if not machine:
                return error_json("invalid_argument", "machine is required", tool, 400)
            machine_rec = resolve("machine", machine)
            action = "platform_specialized.machinesystemstatus" if operation == "machine_system_status" else "platform_specialized.software"
            data = execute(action, {"machine_id": machine_rec["id"]})
        elif operation == "reports":
            body = {"folder": folder} if folder else {}
            data = execute("platform_specialized.reportsdir_query", body=body)
        else:
            return error_json("invalid_argument", f"unsupported platform operation '{operation}'", tool, 400)
        return _finish(tool, operation, data, cursor, limit)
    except Exception as exc:
        return handle_error(tool, exc)
