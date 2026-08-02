from prisma_sdwan_mcp.server import CleanStderr, client, main, mcp
from prisma_sdwan_mcp.client import PrismaSDWANClient
from prisma_sdwan_mcp.formatting import _clean_response, _extract_response
from prisma_sdwan_mcp.tools.config_gen import generate_site_config
from prisma_sdwan_mcp.tools.inventory import (
    get_app_defs,
    get_elements,
    get_machines,
    get_sites,
)
from prisma_sdwan_mcp.tools.monitoring import (
    get_alarms,
    get_element_status,
    get_events,
    get_software_status,
)
from prisma_sdwan_mcp.tools.network import (
    get_interfaces,
    get_topology,
    get_wan_interfaces,
)
from prisma_sdwan_mcp.tools.policy import get_policy_sets, get_security_zones
from prisma_sdwan_mcp.tools.routing import get_bgp_peers, get_static_routes


if __name__ == "__main__":
    raise SystemExit(main())
