import re
from typing import List, Dict, Any, Optional
from fastmcp import FastMCP
import prisma_sase
import json
import os
import sys
import yaml
import argparse
import logging
from dotenv import load_dotenv
import jsonschema
import time

load_dotenv()

PAN_CLIENT_ID = os.getenv("PAN_CLIENT_ID")
PAN_CLIENT_SECRET = os.getenv("PAN_CLIENT_SECRET")
PAN_TSG_ID = os.getenv("PAN_TSG_ID")
PAN_REGION = os.getenv("PAN_REGION", "americas").lower()

# Region to controller URL mapping
REGION_MAP = {
    "americas": "https://api.sase.paloaltonetworks.com",
    "europe": "https://api.eu.sase.paloaltonetworks.com",
    "asia": "https://api.apac.sase.paloaltonetworks.com",
}
CONTROLLER = REGION_MAP.get(PAN_REGION, REGION_MAP["americas"])

mcp = FastMCP("Prisma SD-WAN MCP Server")

# ──────────────────────────────────────────────────────────────────────
#  Prisma SD-WAN Client — handles authentication and SDK calls
# ──────────────────────────────────────────────────────────────────────


class PrismaSDWANClient:
    def __init__(self):
        self.sdk = prisma_sase.API(
            controller=CONTROLLER, ssl_verify=True, update_check=False
        )
        self.logged_in = False
        self.token_expiry = 0

    def login(self):
        if not all([PAN_CLIENT_ID, PAN_CLIENT_SECRET, PAN_TSG_ID]):
            raise Exception(
                "Missing credentials. Set PAN_CLIENT_ID, PAN_CLIENT_SECRET, and PAN_TSG_ID."
            )

        print(f"Authenticating to {CONTROLLER}...", file=sys.stderr)
        try:
            result = self.sdk.interactive.login_secret(
                client_id=PAN_CLIENT_ID,
                client_secret=PAN_CLIENT_SECRET,
                tsg_id=PAN_TSG_ID,
            )
            if not result:
                raise Exception("Authentication failed. Check credentials and TSG ID.")

            # Mandatory post-auth call — without this, all subsequent API calls return 403
            self.sdk.get.profile()

            self.logged_in = True
            self.token_expiry = (
                time.time() + 839
            )  # 899s token lifetime minus 60s buffer
            print("Authentication successful.", file=sys.stderr)
        except Exception as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            raise

    def _is_token_expired(self):
        return time.time() >= self.token_expiry

    def call_sdk(self, sdk_func, *args, **kwargs):
        """Call an SDK GET method with auto-reauth."""
        if not self.logged_in or self._is_token_expired():
            self.login()

        try:
            resp = sdk_func(*args, **kwargs)

            if not resp.cgx_status and resp.status_code in (401, 403):
                print("Session expired, re-authenticating...", file=sys.stderr)
                self.login()
                resp = sdk_func(*args, **kwargs)

            return _extract_response(resp)
        except Exception as e:
            return {"error": str(e)}

    def call_sdk_post(self, sdk_func, data):
        """Call an SDK POST method with auto-reauth."""
        if not self.logged_in or self._is_token_expired():
            self.login()

        try:
            resp = sdk_func(data)

            if not resp.cgx_status and resp.status_code in (401, 403):
                print("Session expired, re-authenticating...", file=sys.stderr)
                self.login()
                resp = sdk_func(data)

            return _extract_response(resp)
        except Exception as e:
            return {"error": str(e)}


def _clean_response(data):
    """Strip internal metadata (_-prefixed fields) and null values for lean LLM context.

    Follows the same pattern as GitHub's official MCP server (MinimalIssue, etc.)
    and Anthropic's guidance: 'Return only the data needed for the task.'
    """
    if isinstance(data, dict):
        return {
            k: _clean_response(v)
            for k, v in data.items()
            if v is not None and not k.startswith("_")
        }
    if isinstance(data, list):
        return [_clean_response(item) for item in data]
    return data


def _extract_response(resp):
    """Extract data from SDK response object."""
    try:
        if not resp.cgx_status:
            errors = (
                resp.cgx_content.get("_error", [{}])
                if isinstance(resp.cgx_content, dict)
                else [{}]
            )
            msg = (
                errors[0].get("message", "Unknown error") if errors else "Unknown error"
            )
            # Provide better error messages for common HTTP status codes
            if msg == "Unknown error":
                status_messages = {
                    400: "Bad request",
                    401: "Authentication failed",
                    403: "Permission denied",
                    404: "Resource not found",
                    429: "Rate limit exceeded",
                    500: "Internal server error",
                }
                msg = status_messages.get(
                    resp.status_code, f"HTTP {resp.status_code} error"
                )
            return {"error": msg, "status_code": resp.status_code}
        data = resp.cgx_content
        if isinstance(data, dict) and "items" in data:
            return _clean_response(data["items"])
        return _clean_response(data)
    except Exception as e:
        return {"error": f"Response parsing error: {str(e)}"}


# ──────────────────────────────────────────────────────────────────────
#  Singleton client instance — used by all tools
# ──────────────────────────────────────────────────────────────────────

client = PrismaSDWANClient()

# ──────────────────────────────────────────────────────────────────────
#  MCP Tools — Prisma SD-WAN Operations
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def get_sites(site_id: Optional[str] = None) -> str:
    """Retrieve SD-WAN sites from the Prisma SASE tenant.

    Returns all sites or a specific site by ID. Sites represent physical
    locations (branches, data centers, hubs) in the SD-WAN fabric.

    Args:
        site_id: Optional site ID to retrieve a specific site.
                 Omit to list all sites.

    Returns:
        JSON with summary, count, and site data.

    Examples:
        - Get all sites: get_sites()
        - Get specific site: get_sites(site_id="1234567890")
    """
    try:
        if site_id is not None:
            site_id = site_id.strip()
            if not site_id:
                return json.dumps(
                    {
                        "error": "site_id cannot be empty. Provide a valid site ID or omit for all sites.",
                        "context": "Input validation for get_sites",
                    }
                )

        if site_id:
            data = client.call_sdk(client.sdk.get.sites, site_id)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(
                    {
                        "error": f"Failed to retrieve site '{site_id}': {data['error']}",
                        "context": "API error while fetching specific site",
                    },
                    indent=2,
                )
            return json.dumps(
                {
                    "summary": f"Site details for ID '{site_id}'",
                    "site": data,
                },
                indent=2,
            )
        else:
            data = client.call_sdk(client.sdk.get.sites)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(
                    {
                        "error": f"Failed to retrieve sites: {data['error']}",
                        "context": "API error while listing all sites",
                    },
                    indent=2,
                )
            items = data if isinstance(data, list) else [data]
            count = len(items)
            return json.dumps(
                {
                    "summary": f"Found {count} site(s)"
                    if count > 0
                    else "No sites found in this tenant",
                    "count": count,
                    "sites": items,
                },
                indent=2,
            )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve sites: {str(e)}",
                "context": "Exception during get_sites operation",
            },
            indent=2,
        )


# Tier 3 field whitelist — keep only fields an LLM needs to answer user questions
ELEMENT_KEEP_FIELDS = {
    "id",
    "name",
    "description",
    "site_id",
    "serial_number",
    "hw_id",
    "model_name",
    "software_version",
    "role",
    "state",
    "connected",
}


def _slim_element(element: dict) -> dict:
    """Reduce an element dict to high-value fields only."""
    slim = {k: v for k, v in element.items() if k in ELEMENT_KEEP_FIELDS}
    # Preserve HA enabled status as a flat boolean (skip nested opaque IDs)
    ha_cfg = element.get("spoke_ha_config")
    if isinstance(ha_cfg, dict) and ha_cfg.get("enable"):
        slim["spoke_ha_enabled"] = True
    return slim


@mcp.tool()
def get_elements(element_id: Optional[str] = None) -> str:
    """Retrieve ION device elements from the Prisma SASE tenant.

    Returns all elements or a specific element by ID. Elements are the
    ION devices (hardware appliances) deployed at each SD-WAN site.
    List responses return slimmed fields for context efficiency.

    Args:
        element_id: Optional element ID to retrieve a specific element.
                    Omit to list all elements.

    Returns:
        JSON with summary, count, and element data.

    Examples:
        - Get all elements: get_elements()
        - Get specific element: get_elements(element_id="1234567890")
    """
    try:
        if element_id is not None:
            element_id = element_id.strip()
            if not element_id:
                return json.dumps(
                    {
                        "error": "element_id cannot be empty. Provide a valid element ID or omit for all elements.",
                        "context": "Input validation for get_elements",
                    }
                )

        if element_id:
            data = client.call_sdk(client.sdk.get.elements, element_id)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(
                    {
                        "error": f"Failed to retrieve element '{element_id}': {data['error']}",
                        "context": "API error while fetching specific element",
                    },
                    indent=2,
                )
            return json.dumps(
                {
                    "summary": f"Element details for ID '{element_id}'",
                    "element": _slim_element(data),
                },
                indent=2,
            )
        else:
            data = client.call_sdk(client.sdk.get.elements)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(
                    {
                        "error": f"Failed to retrieve elements: {data['error']}",
                        "context": "API error while listing all elements",
                    },
                    indent=2,
                )
            items = data if isinstance(data, list) else [data]
            count = len(items)
            return json.dumps(
                {
                    "summary": f"Found {count} element(s)"
                    if count > 0
                    else "No elements found in this tenant",
                    "count": count,
                    "elements": [_slim_element(e) for e in items],
                },
                indent=2,
            )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve elements: {str(e)}",
                "context": "Exception during get_elements operation",
            },
            indent=2,
        )


@mcp.tool()
def get_machines(machine_id: Optional[str] = None) -> str:
    """Retrieve machine inventory from the Prisma SASE tenant.

    Returns all machines or a specific machine by ID. Machines represent
    the hardware chassis with serial numbers, models, and registration info.

    Args:
        machine_id: Optional machine ID to retrieve a specific machine.
                    Omit to list all machines.

    Returns:
        JSON with summary, count, and machine data.

    Examples:
        - Get all machines: get_machines()
        - Get specific machine: get_machines(machine_id="1234567890")
    """
    try:
        if machine_id is not None:
            machine_id = machine_id.strip()
            if not machine_id:
                return json.dumps(
                    {
                        "error": "machine_id cannot be empty. Provide a valid machine ID or omit for all machines.",
                        "context": "Input validation for get_machines",
                    }
                )

        if machine_id:
            data = client.call_sdk(client.sdk.get.machines, machine_id)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(
                    {
                        "error": f"Failed to retrieve machine '{machine_id}': {data['error']}",
                        "context": "API error while fetching specific machine",
                    },
                    indent=2,
                )
            return json.dumps(
                {
                    "summary": f"Machine details for ID '{machine_id}'",
                    "machine": data,
                },
                indent=2,
            )
        else:
            data = client.call_sdk(client.sdk.get.machines)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(
                    {
                        "error": f"Failed to retrieve machines: {data['error']}",
                        "context": "API error while listing all machines",
                    },
                    indent=2,
                )
            items = data if isinstance(data, list) else [data]
            count = len(items)
            return json.dumps(
                {
                    "summary": f"Found {count} machine(s)"
                    if count > 0
                    else "No machines found in this tenant",
                    "count": count,
                    "machines": items,
                },
                indent=2,
            )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve machines: {str(e)}",
                "context": "Exception during get_machines operation",
            },
            indent=2,
        )


@mcp.tool()
def get_policy_sets(policyset_id: Optional[str] = None) -> str:
    """Retrieve SD-WAN policy sets from the Prisma SASE tenant.

    Returns all policy sets or a specific policy set by ID. Policy sets
    define path, QoS, and NAT rules applied to site traffic.

    Args:
        policyset_id: Optional policy set ID to retrieve a specific set.
                      Omit to list all policy sets.

    Returns:
        JSON with summary, count, and policy set data.

    Examples:
        - Get all policy sets: get_policy_sets()
        - Get specific set: get_policy_sets(policyset_id="1234567890")
    """
    try:
        if policyset_id is not None:
            policyset_id = policyset_id.strip()
            if not policyset_id:
                return json.dumps(
                    {
                        "error": "policyset_id cannot be empty. Provide a valid policy set ID or omit for all policy sets.",
                        "context": "Input validation for get_policy_sets",
                    }
                )

        if policyset_id:
            data = client.call_sdk(client.sdk.get.policysets, policyset_id)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(
                    {
                        "error": f"Failed to retrieve policy set '{policyset_id}': {data['error']}",
                        "context": "API error while fetching specific policy set",
                    },
                    indent=2,
                )
            return json.dumps(
                {
                    "summary": f"Policy set details for ID '{policyset_id}'",
                    "policy_set": data,
                },
                indent=2,
            )
        else:
            data = client.call_sdk(client.sdk.get.policysets)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(
                    {
                        "error": f"Failed to retrieve policy sets: {data['error']}",
                        "context": "API error while listing all policy sets",
                    },
                    indent=2,
                )
            items = data if isinstance(data, list) else [data]
            count = len(items)
            return json.dumps(
                {
                    "summary": f"Found {count} policy set(s)"
                    if count > 0
                    else "No policy sets found in this tenant",
                    "count": count,
                    "policy_sets": items,
                },
                indent=2,
            )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve policy sets: {str(e)}",
                "context": "Exception during get_policy_sets operation",
            },
            indent=2,
        )


@mcp.tool()
def get_security_zones(securityzone_id: Optional[str] = None) -> str:
    """Retrieve SD-WAN security zones from the Prisma SASE tenant.

    Returns all security zones or a specific zone by ID. Security zones
    define trust boundaries for firewall policy enforcement.

    Args:
        securityzone_id: Optional security zone ID to retrieve a specific zone.
                         Omit to list all security zones.

    Returns:
        JSON with summary, count, and security zone data.

    Examples:
        - Get all zones: get_security_zones()
        - Get specific zone: get_security_zones(securityzone_id="1234567890")
    """
    try:
        if securityzone_id is not None:
            securityzone_id = securityzone_id.strip()
            if not securityzone_id:
                return json.dumps(
                    {
                        "error": "securityzone_id cannot be empty. Provide a valid security zone ID or omit for all zones.",
                        "context": "Input validation for get_security_zones",
                    }
                )

        if securityzone_id:
            data = client.call_sdk(client.sdk.get.securityzones, securityzone_id)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(
                    {
                        "error": f"Failed to retrieve security zone '{securityzone_id}': {data['error']}",
                        "context": "API error while fetching specific security zone",
                    },
                    indent=2,
                )
            return json.dumps(
                {
                    "summary": f"Security zone details for ID '{securityzone_id}'",
                    "security_zone": data,
                },
                indent=2,
            )
        else:
            data = client.call_sdk(client.sdk.get.securityzones)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(
                    {
                        "error": f"Failed to retrieve security zones: {data['error']}",
                        "context": "API error while listing all security zones",
                    },
                    indent=2,
                )
            items = data if isinstance(data, list) else [data]
            count = len(items)
            return json.dumps(
                {
                    "summary": f"Found {count} security zone(s)"
                    if count > 0
                    else "No security zones found in this tenant",
                    "count": count,
                    "security_zones": items,
                },
                indent=2,
            )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve security zones: {str(e)}",
                "context": "Exception during get_security_zones operation",
            },
            indent=2,
        )


@mcp.tool()
def get_app_defs(appdef_id: Optional[str] = None) -> str:
    """Retrieve SD-WAN application definitions from the Prisma SASE tenant.

    Returns all application definitions or a specific one by ID. App definitions
    identify applications for policy-based routing and QoS decisions.

    Args:
        appdef_id: Optional application definition ID to retrieve a specific entry.
                   Omit to list all application definitions.

    Returns:
        JSON with summary, count, and application definition data.

    Examples:
        - Get all app defs: get_app_defs()
        - Get specific app def: get_app_defs(appdef_id="1234567890")
    """
    try:
        if appdef_id is not None:
            appdef_id = appdef_id.strip()
            if not appdef_id:
                return json.dumps(
                    {
                        "error": "appdef_id cannot be empty. Provide a valid application definition ID or omit for all.",
                        "context": "Input validation for get_app_defs",
                    }
                )

        if appdef_id:
            data = client.call_sdk(client.sdk.get.appdefs, appdef_id)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(
                    {
                        "error": f"Failed to retrieve app definition '{appdef_id}': {data['error']}",
                        "context": "API error while fetching specific application definition",
                    },
                    indent=2,
                )
            return json.dumps(
                {
                    "summary": f"Application definition details for ID '{appdef_id}'",
                    "app_def": data,
                },
                indent=2,
            )
        else:
            data = client.call_sdk(client.sdk.get.appdefs)
            if isinstance(data, dict) and "error" in data:
                return json.dumps(
                    {
                        "error": f"Failed to retrieve application definitions: {data['error']}",
                        "context": "API error while listing all application definitions",
                    },
                    indent=2,
                )
            items = data if isinstance(data, list) else [data]
            count = len(items)
            return json.dumps(
                {
                    "summary": f"Found {count} application definition(s)"
                    if count > 0
                    else "No application definitions found in this tenant",
                    "count": count,
                    "app_defs": items,
                },
                indent=2,
            )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve application definitions: {str(e)}",
                "context": "Exception during get_app_defs operation",
            },
            indent=2,
        )


@mcp.tool()
def get_topology() -> str:
    """Retrieve the full SD-WAN anynet topology from the Prisma SASE tenant.

    Returns the complete topology map including all sites (nodes), VPN links
    between them, and connectivity status (up/down) for each link.

    Returns:
        JSON with summary, node count, link count, link status breakdown,
        and full topology data.

    Examples:
        - Get full topology: get_topology()
    """
    try:
        data = client.call_sdk_post(client.sdk.post.topology, {"type": "anynet"})
        if isinstance(data, dict) and "error" in data:
            return json.dumps(
                {
                    "error": f"Failed to retrieve topology: {data['error']}",
                    "context": "API error while fetching network topology",
                },
                indent=2,
            )
        if isinstance(data, dict) and "links" in data:
            links = data.get("links", [])
            nodes = data.get("nodes", [])
            up_count = sum(1 for l in links if l.get("status") == "up")
            down_count = sum(1 for l in links if l.get("status") == "down")
            return json.dumps(
                {
                    "summary": f"Topology: {len(nodes)} node(s), {len(links)} link(s) ({up_count} up, {down_count} down)",
                    "node_count": len(nodes),
                    "link_count": len(links),
                    "links_up": up_count,
                    "links_down": down_count,
                    "topology": data,
                },
                indent=2,
            )
        return json.dumps(
            {"summary": "Network topology retrieved", "topology": data}, indent=2
        )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve topology: {str(e)}",
                "context": "Exception during get_topology operation",
            },
            indent=2,
        )


@mcp.tool()
def get_interfaces(site_id: str, element_id: str) -> str:
    """Retrieve network interfaces for a specific element at a site.

    Returns all interfaces configured on the given element, including
    physical ports, virtual interfaces, IP configuration, and DHCP relay settings.

    Args:
        site_id: The site ID where the element is located.
        element_id: The element ID to retrieve interfaces for.

    Returns:
        JSON with summary, count, and interface data.

    Examples:
        - Get interfaces: get_interfaces(site_id="site123", element_id="elem456")
    """
    try:
        site_id = site_id.strip() if site_id else ""
        element_id = element_id.strip() if element_id else ""
        if not site_id:
            return json.dumps(
                {
                    "error": "site_id is required and cannot be empty.",
                    "context": "Input validation for get_interfaces",
                }
            )
        if not element_id:
            return json.dumps(
                {
                    "error": "element_id is required and cannot be empty.",
                    "context": "Input validation for get_interfaces",
                }
            )

        data = client.call_sdk(client.sdk.get.interfaces, site_id, element_id)
        if isinstance(data, dict) and "error" in data:
            return json.dumps(
                {
                    "error": f"Failed to retrieve interfaces for element '{element_id}' at site '{site_id}': {data['error']}",
                    "context": "API error while fetching interfaces",
                },
                indent=2,
            )
        items = data if isinstance(data, list) else [data]
        count = len(items)
        return json.dumps(
            {
                "summary": f"Found {count} interface(s) for element '{element_id}' at site '{site_id}'"
                if count > 0
                else f"No interfaces found for element '{element_id}' at site '{site_id}'",
                "count": count,
                "interfaces": items,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve interfaces: {str(e)}",
                "context": "Exception during get_interfaces operation",
            },
            indent=2,
        )


@mcp.tool()
def get_wan_interfaces(site_id: str) -> str:
    """Retrieve WAN interfaces for a specific site.

    Returns all WAN interfaces configured at the given site, including
    link type, bandwidth configuration, and link quality monitoring settings.

    Args:
        site_id: The site ID to retrieve WAN interfaces for.

    Returns:
        JSON with summary, count, and WAN interface data.

    Examples:
        - Get WAN interfaces: get_wan_interfaces(site_id="site123")
    """
    try:
        site_id = site_id.strip() if site_id else ""
        if not site_id:
            return json.dumps(
                {
                    "error": "site_id is required and cannot be empty.",
                    "context": "Input validation for get_wan_interfaces",
                }
            )

        data = client.call_sdk(client.sdk.get.waninterfaces, site_id)
        if isinstance(data, dict) and "error" in data:
            return json.dumps(
                {
                    "error": f"Failed to retrieve WAN interfaces for site '{site_id}': {data['error']}",
                    "context": "API error while fetching WAN interfaces",
                },
                indent=2,
            )
        items = data if isinstance(data, list) else [data]
        count = len(items)
        return json.dumps(
            {
                "summary": f"Found {count} WAN interface(s) for site '{site_id}'"
                if count > 0
                else f"No WAN interfaces found for site '{site_id}'",
                "count": count,
                "wan_interfaces": items,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve WAN interfaces: {str(e)}",
                "context": "Exception during get_wan_interfaces operation",
            },
            indent=2,
        )


@mcp.tool()
def get_bgp_peers(site_id: str, element_id: str) -> str:
    """Retrieve BGP peers for a specific element at a site.

    Returns all BGP peer configurations including peer IP, ASN numbers,
    and route map associations for the given element.

    Args:
        site_id: The site ID where the element is located.
        element_id: The element ID to retrieve BGP peers for.

    Returns:
        JSON with summary, count, and BGP peer data.

    Examples:
        - Get BGP peers: get_bgp_peers(site_id="site123", element_id="elem456")
    """
    try:
        site_id = site_id.strip() if site_id else ""
        element_id = element_id.strip() if element_id else ""
        if not site_id:
            return json.dumps(
                {
                    "error": "site_id is required and cannot be empty.",
                    "context": "Input validation for get_bgp_peers",
                }
            )
        if not element_id:
            return json.dumps(
                {
                    "error": "element_id is required and cannot be empty.",
                    "context": "Input validation for get_bgp_peers",
                }
            )

        data = client.call_sdk(client.sdk.get.bgppeers, site_id, element_id)
        if isinstance(data, dict) and "error" in data:
            return json.dumps(
                {
                    "error": f"Failed to retrieve BGP peers for element '{element_id}' at site '{site_id}': {data['error']}",
                    "context": "API error while fetching BGP peers",
                },
                indent=2,
            )
        items = data if isinstance(data, list) else [data]
        count = len(items)
        return json.dumps(
            {
                "summary": f"Found {count} BGP peer(s) for element '{element_id}' at site '{site_id}'"
                if count > 0
                else f"No BGP peers found for element '{element_id}' at site '{site_id}'",
                "count": count,
                "bgp_peers": items,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve BGP peers: {str(e)}",
                "context": "Exception during get_bgp_peers operation",
            },
            indent=2,
        )


@mcp.tool()
def get_static_routes(site_id: str, element_id: str) -> str:
    """Retrieve static routes for a specific element at a site.

    Returns all static route configurations including destination prefix,
    next-hop IP, and administrative distance for the given element.

    Args:
        site_id: The site ID where the element is located.
        element_id: The element ID to retrieve static routes for.

    Returns:
        JSON with summary, count, and static route data.

    Examples:
        - Get static routes: get_static_routes(site_id="site123", element_id="elem456")
    """
    try:
        site_id = site_id.strip() if site_id else ""
        element_id = element_id.strip() if element_id else ""
        if not site_id:
            return json.dumps(
                {
                    "error": "site_id is required and cannot be empty.",
                    "context": "Input validation for get_static_routes",
                }
            )
        if not element_id:
            return json.dumps(
                {
                    "error": "element_id is required and cannot be empty.",
                    "context": "Input validation for get_static_routes",
                }
            )

        data = client.call_sdk(client.sdk.get.staticroutes, site_id, element_id)
        if isinstance(data, dict) and "error" in data:
            return json.dumps(
                {
                    "error": f"Failed to retrieve static routes for element '{element_id}' at site '{site_id}': {data['error']}",
                    "context": "API error while fetching static routes",
                },
                indent=2,
            )
        items = data if isinstance(data, list) else [data]
        count = len(items)
        return json.dumps(
            {
                "summary": f"Found {count} static route(s) for element '{element_id}' at site '{site_id}'"
                if count > 0
                else f"No static routes found for element '{element_id}' at site '{site_id}'",
                "count": count,
                "static_routes": items,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve static routes: {str(e)}",
                "context": "Exception during get_static_routes operation",
            },
            indent=2,
        )


@mcp.tool()
def get_element_status(element_id: str) -> str:
    """Retrieve operational status for a specific SD-WAN element.

    Returns real-time status information including connection state,
    uptime, and health indicators for the given element.

    Args:
        element_id: The element ID to retrieve status for.

    Returns:
        JSON with summary and element status data.

    Examples:
        - Get element status: get_element_status(element_id="elem456")
    """
    try:
        element_id = element_id.strip() if element_id else ""
        if not element_id:
            return json.dumps(
                {
                    "error": "element_id is required and cannot be empty.",
                    "context": "Input validation for get_element_status",
                }
            )

        data = client.call_sdk(client.sdk.get.element_status, element_id)
        if isinstance(data, dict) and "error" in data:
            return json.dumps(
                {
                    "error": f"Failed to retrieve status for element '{element_id}': {data['error']}",
                    "context": "API error while fetching element status",
                },
                indent=2,
            )
        return json.dumps(
            {
                "summary": f"Operational status for element '{element_id}'",
                "element_status": data,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve element status: {str(e)}",
                "context": "Exception during get_element_status operation",
            },
            indent=2,
        )


@mcp.tool()
def get_software_status(element_id: str) -> str:
    """Retrieve software and firmware information for a specific SD-WAN element.

    Returns software version, upgrade status, and firmware details
    for the given element.

    Args:
        element_id: The element ID to retrieve software status for.

    Returns:
        JSON with summary and software status data.

    Examples:
        - Get software status: get_software_status(element_id="elem456")
    """
    try:
        element_id = element_id.strip() if element_id else ""
        if not element_id:
            return json.dumps(
                {
                    "error": "element_id is required and cannot be empty.",
                    "context": "Input validation for get_software_status",
                }
            )

        data = client.call_sdk(client.sdk.get.software_status, element_id)
        if isinstance(data, dict) and "error" in data:
            return json.dumps(
                {
                    "error": f"Failed to retrieve software status for element '{element_id}': {data['error']}",
                    "context": "API error while fetching software status",
                },
                indent=2,
            )
        return json.dumps(
            {
                "summary": f"Software status for element '{element_id}'",
                "software_status": data,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve software status: {str(e)}",
                "context": "Exception during get_software_status operation",
            },
            indent=2,
        )


@mcp.tool()
def get_events(limit: int = 20) -> str:
    """Fetch recent SD-WAN events from the Prisma SASE tenant (newest first).

    Returns operational events across severity levels: critical, major,
    and minor.

    Args:
        limit: Maximum number of events to return (default 20, range 1-100).

    Returns:
        JSON with summary, count, and event data.

    Examples:
        - Get recent events: get_events()
        - Get last 50 events: get_events(limit=50)
    """
    try:
        if limit < 1:
            return json.dumps(
                {
                    "error": "limit must be at least 1.",
                    "context": "Input validation for get_events",
                }
            )
        capped = min(limit, 100)

        query = {
            "severity": ["critical", "major", "minor"],
            "limit": {"count": capped, "sort_on": "time", "sort_order": "descending"},
        }
        data = client.call_sdk_post(client.sdk.post.events_query, query)
        if isinstance(data, dict) and "error" in data:
            return json.dumps(
                {
                    "error": f"Failed to retrieve events: {data['error']}",
                    "context": "API error while fetching events",
                },
                indent=2,
            )
        items = data if isinstance(data, list) else [data]
        count = len(items)
        return json.dumps(
            {
                "summary": f"Found {count} event(s) (requested up to {capped})"
                if count > 0
                else "No events found",
                "count": count,
                "events": items,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve events: {str(e)}",
                "context": "Exception during get_events operation",
            },
            indent=2,
        )


@mcp.tool()
def get_alarms(limit: int = 20) -> str:
    """Fetch recent major and critical SD-WAN alarms (newest first).

    Returns only high-severity events (major and critical) that typically
    require operator attention or indicate service impact.

    Args:
        limit: Maximum number of alarms to return (default 20, range 1-100).

    Returns:
        JSON with summary, count, and alarm data.

    Examples:
        - Get recent alarms: get_alarms()
        - Get last 50 alarms: get_alarms(limit=50)
    """
    try:
        if limit < 1:
            return json.dumps(
                {
                    "error": "limit must be at least 1.",
                    "context": "Input validation for get_alarms",
                }
            )
        capped = min(limit, 100)

        query = {
            "severity": ["major", "critical"],
            "limit": {"count": capped, "sort_on": "time", "sort_order": "descending"},
        }
        data = client.call_sdk_post(client.sdk.post.events_query, query)
        if isinstance(data, dict) and "error" in data:
            return json.dumps(
                {
                    "error": f"Failed to retrieve alarms: {data['error']}",
                    "context": "API error while fetching alarms",
                },
                indent=2,
            )
        items = data if isinstance(data, list) else [data]
        count = len(items)
        return json.dumps(
            {
                "summary": f"Found {count} alarm(s) (major/critical, requested up to {capped})"
                if count > 0
                else "No major/critical alarms found",
                "count": count,
                "alarms": items,
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to retrieve alarms: {str(e)}",
                "context": "Exception during get_alarms operation",
            },
            indent=2,
        )


# ──────────────────────────────────────────────────────────────────────
#  Site Configuration Generator
# ──────────────────────────────────────────────────────────────────────

TEMPLATE_IGNORE = "__TEMPLATE_IGNORE__"


class IndentDumper(yaml.Dumper):
    """Custom YAML dumper for clean, readable output."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def str_presenter(dumper, data):
    """Use block style for multi-line strings, otherwise default."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


IndentDumper.add_representer(str, str_presenter)


@mcp.tool()
def generate_site_config(
    site_id: str,
    elements: List[Dict[str, Any]],
    filename: str = "generated_sites.prisma.yaml",
    overwrite: bool = False,
) -> str:
    """
    Generates a YAML site configuration file for Prisma SD-WAN deployment.

    Args:
        site_id: The site identifier (e.g., "BRANCH-101")
        elements: List of element definitions. Each element dict should contain:
            - serial_number: ION device serial number
            - model_name: ION device model (e.g., "ion 3200")
            - device_variables: Dict of device-level variables
            - policy_variables: Dict of policy-level variables (optional)
        filename: Output YAML filename (default: generated_sites.prisma.yaml)
        overwrite: If True, overwrite existing file; if False, append new sites

    Returns:
        Success message with filename and site count, or error details.
    """
    try:
        schema_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "schema.json"
        )
        if not os.path.exists(schema_path):
            return json.dumps(
                {"error": f"Schema file not found at {schema_path}"}, indent=2
            )

        with open(schema_path, "r") as f:
            schema = json.load(f)

        new_site = {"site_id": site_id, "elements": []}

        for element in elements:
            element_entry = {}

            serial_number = element.get("serial_number")
            if not serial_number:
                return json.dumps(
                    {"error": "Each element must have a 'serial_number'"}, indent=2
                )
            element_entry["serial_number"] = serial_number

            model_name = element.get("model_name")
            if model_name:
                element_entry["model_name"] = model_name

            device_vars = element.get("device_variables", {})
            if device_vars:
                element_entry["device_variables"] = device_vars

            policy_vars = element.get("policy_variables", {})
            if policy_vars:
                element_entry["policy_variables"] = policy_vars

            new_site["elements"].append(element_entry)

        # Load existing config or start fresh
        existing_config = None
        if not overwrite and os.path.exists(filename):
            try:
                with open(filename, "r") as f:
                    existing_config = yaml.safe_load(f)
            except:
                existing_config = None

        if (
            existing_config
            and isinstance(existing_config, dict)
            and "prisma_sdwan" in existing_config
        ):
            sites = existing_config["prisma_sdwan"].get("sites", [])
            # Replace existing site or append
            replaced = False
            for i, site in enumerate(sites):
                if site.get("site_id") == site_id:
                    sites[i] = new_site
                    replaced = True
                    break
            if not replaced:
                sites.append(new_site)
            existing_config["prisma_sdwan"]["sites"] = sites
            config = existing_config
        else:
            config = {"prisma_sdwan": {"sites": [new_site]}}

        # Validate against schema
        try:
            jsonschema.validate(instance=config, schema=schema)
        except jsonschema.ValidationError as ve:
            return json.dumps(
                {
                    "error": "Schema validation failed",
                    "details": str(ve.message),
                    "path": list(ve.absolute_path),
                },
                indent=2,
            )

        # Write YAML
        yaml_content = "---\n# Prisma SD-WAN Sites\n"
        yaml_content += yaml.dump(
            config, Dumper=IndentDumper, default_flow_style=False, sort_keys=False
        )

        with open(filename, "w") as f:
            f.write(yaml_content)

        site_count = len(config["prisma_sdwan"]["sites"])
        return json.dumps(
            {
                "status": "success",
                "filename": filename,
                "site_count": site_count,
                "message": f"Site '{site_id}' written to {filename} ({site_count} total site(s)).",
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps({"error": str(e)}, indent=2)


# ──────────────────────────────────────────────────────────────────────
#  Server Entry Point
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prisma SD-WAN MCP Server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for HTTP/SSE transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP/SSE transport (default: 8000)",
    )

    args = parser.parse_args()

    # Windows: reconfigure stdout for UTF-8 (needed for banner)
    sys.stdout.reconfigure(encoding="utf-8")

    # ── Filter noisy tracebacks on shutdown ──
    class CleanStderr:
        """
        Wraps sys.stderr to suppress known-harmless tracebacks triggered
        during shutdown of the async server stack.  Without this, users
        see scary-looking (but harmless) asyncio / uvicorn / starlette
        errors every time they hit Ctrl-C.
        """

        NOISE = (
            "Traceback (most recent call last)",
            "asyncio.exceptions.CancelledError",
            "concurrent.futures._base.CancelledError",
            "starlette.routing",
            "uvicorn.error",
            "anyio._backends",
            "Exception in ASGI application",
            "During handling of the above exception",
            "KeyboardInterrupt",
            "RuntimeError: Event loop is closed",
        )

        def __init__(self, original):
            self._original = original

        def write(self, msg):
            if any(n in msg for n in self.NOISE):
                return
            self._original.write(msg)

        def flush(self):
            self._original.flush()

        def __getattr__(self, name):
            return getattr(self._original, name)

    sys.stderr = CleanStderr(sys.stderr)

    # ── Startup Banner ──
    transport_str = args.transport.upper()
    server_url = (
        f"http://{args.host}:{args.port}/sse"
        if args.transport == "sse"
        else "N/A (Stdio)"
    )

    print(
        "┌──────────────────────────────────────────────────────────────────────────────┐",
        file=sys.stderr,
    )
    print(
        "│                                                                              │",
        file=sys.stderr,
    )
    print(
        "│   ██████╗ ██████╗ ██╗███████╗███╗   ███╗ █████╗                              │",
        file=sys.stderr,
    )
    print(
        "│   ██╔══██╗██╔══██╗██║██╔════╝████╗ ████║██╔══██╗                             │",
        file=sys.stderr,
    )
    print(
        "│   ██████╔╝██████╔╝██║███████╗██╔████╔██║███████║                             │",
        file=sys.stderr,
    )
    print(
        "│   ██╔═══╝ ██╔══██╗██║╚════██║██║╚██╔╝██║██╔══██║                             │",
        file=sys.stderr,
    )
    print(
        "│   ██║     ██║  ██║██║███████║██║ ╚═╝ ██║██║  ██║                             │",
        file=sys.stderr,
    )
    print(
        "│   ╚═╝     ╚═╝  ╚═╝╚═╝╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝                             │",
        file=sys.stderr,
    )
    print(
        "│                                                                              │",
        file=sys.stderr,
    )
    print(
        f"│    Name: Prisma SD-WAN MCP Server                                            │",
        file=sys.stderr,
    )
    print(f"│    📦 Transport:  {transport_str:<58}│", file=sys.stderr)
    if args.transport == "sse":
        print(f"│    🔗 Server URL: {server_url:<58}│", file=sys.stderr)
    print(
        "│                                                                              │",
        file=sys.stderr,
    )
    print(
        "└──────────────────────────────────────────────────────────────────────────────┘",
        file=sys.stderr,
    )

    # ── Logging Configuration ──
    try:
        # Useful server logs
        logging.getLogger("uvicorn.access").setLevel(logging.INFO)
        logging.getLogger("fastmcp").setLevel(logging.INFO)

        # Silence noisy loggers
        for logger_name in ("uvicorn.error", "anyio", "asyncio", "starlette"):
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.CRITICAL)
            logger.propagate = False

        # Run the MCP server
        if args.transport == "stdio":
            mcp.run(transport="stdio")
        else:
            try:
                mcp.run(
                    transport=args.transport,
                    host=args.host,
                    port=args.port,
                    show_banner=False,
                )
            except TypeError:
                mcp.run(
                    transport=args.transport,
                    host=args.host,
                    port=args.port,
                )

    except KeyboardInterrupt:
        print("\n⚠️  Server stopped by user. Exiting gracefully...", file=sys.stderr)
        sys.exit(0)
    except BaseException:
        print("\n⚠️  Server stopped. Exiting...", file=sys.stderr)
        sys.exit(0)