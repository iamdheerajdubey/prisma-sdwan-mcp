# Prisma SD-WAN MCP Server

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![Status](https://img.shields.io/badge/status-unofficial-orange)
![Platform](https://img.shields.io/badge/platform-prisma%20sd--wan-green)

> **Disclaimer:** This project is a personal work developed independently for educational and open-source purposes. It is not an official product of Palo Alto Networks, Inc. or any of its affiliates. All trademarks, service marks, and company names are the property of their respective owners.

---

A robust **Model Context Protocol (MCP)** server for **Palo Alto Networks Prisma SD-WAN**.

This server bridges the gap between AI agents (like Claude, Gemini, or custom LLMs) and your Prisma SD-WAN fabric. It enables secure, read-only access to operational data, allowing agents to perform tasks like inventory audits, health checks, topology analysis, and policy verification through natural language.

## Table of Contents

- [About](#about)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Client Integration](#client-integration)
- [Available Tools](#available-tools)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## About

The Prisma SD-WAN MCP Server abstracts the complexity of the Prisma SASE API into clean, semantic tools that AI models can understand and call autonomously. Instead of navigating REST endpoints, pagination, and token management, your AI agent simply asks for what it needs.

**Core Design Principles:**

- **Safety First** ... Designed as a **read-only** interface. The only write operation is `generate_site_config`, which produces a local YAML file. No changes are pushed to your Prisma SD-WAN tenant.
- **Simplified Context** ... Raw API responses are parsed, projected, compacted, and byte-budgeted, keeping LLM context windows lean and focused.
- **Multi-Transport** ... Supports **Stdio** (for Claude Desktop and local clients), **SSE** (for remote/web agents), and **Streamable HTTP**.
- **Container Ready** ... Ships with a production-ready Dockerfile for consistent deployments.
- **Auto-Reauthentication** ... Handles OAuth2 token refresh transparently. Tokens last 15 minutes; the server re-authenticates before they expire.

## Features

| Category | Capabilities |
| --- | --- |
| **Site Management** | List all SD-WAN sites, retrieve individual site details and configurations |
| **Element Inventory** | View ION devices, their status, hardware details, and software versions |
| **Network Topology** | Retrieve the full SD-WAN topology graph showing site-to-site connectivity |
| **Interfaces** | Inspect LAN and WAN interfaces per site and element |
| **Routing** | Query BGP peer configurations and static routes per element |
| **Policy & Security** | Inspect network, priority, NGFW, and NAT policy families, stacks, security zones, path groups, service labels, and WAN networks |
| **Events & Alarms** | Query recent events and retrieve active alarms filtered by severity |
| **Applications** | Browse application definitions used across the fabric |
| **Config Generation** | Generate validated site configuration YAML files from template data |

## Prerequisites

- **Python 3.10+**
- A **Prisma SASE tenant** with API access enabled
- A **Service Account** with at least read-only privileges
- Service Account credentials:
  - Client ID
  - Client Secret
  - TSG ID (Tenant Service Group)

### Creating a Service Account

1. Log in to the [Prisma SASE Portal](https://apps.paloaltonetworks.com)
2. Navigate to **Settings > Identity & Access > Service Accounts**
3. Create a new service account with the **Prisma SD-WAN** app and a read-only role
4. Note down the **Client ID**, **Client Secret**, and your **TSG ID**

## Installation

### From Source

```bash
git clone <repo-url>
cd prisma-sdwan
pip install -r requirements.txt
```

### Using Docker

```bash
docker build -t prisma-sdwan-mcp .
```

## Configuration

### Environment Variables

| Variable | Description | Required |
| --- | --- | --- |
| `PAN_CLIENT_ID` | Service Account Client ID (e.g., `name@tsg.iam.panserviceaccount.com`) | Yes |
| `PAN_CLIENT_SECRET` | Service Account Client Secret | Yes |
| `PAN_TSG_ID` | Tenant Service Group ID | Yes |
| `PAN_REGION` | Advisory label only; the SDK derives the tenant region at login | No |
| `PAN_CONTROLLER` | Optional controller override for private or QA environments | No |
| `PRISMA_MCP_MAX_RESPONSE_BYTES` | Maximum serialized tool response size (default: `40960`) | No |
| `PRISMA_MCP_OUTPUT_DIR` | Sandbox directory for generated YAML (default: current working directory) | No |

### .env File

Create a `.env` file in the `prisma-sdwan/` directory:

```ini
PAN_CLIENT_ID=myaccount@1234567890.iam.panserviceaccount.com
PAN_CLIENT_SECRET=abc123-your-secret-here
PAN_TSG_ID=1234567890
PAN_REGION=americas
# PAN_CONTROLLER=https://api.sase.paloaltonetworks.com
PRISMA_MCP_MAX_RESPONSE_BYTES=40960
# PRISMA_MCP_OUTPUT_DIR=
```

`PAN_REGION` does not select a hostname. The service uses the single controller
`https://api.sase.paloaltonetworks.com` unless `PAN_CONTROLLER` is set, then logs
the region returned by the SDK after login.

> **Security Note:** Never commit your `.env` file to version control. It's already included in `.gitignore`.

## Usage

The server supports three transport modes depending on how your AI client connects.

### Stdio Mode (Default)

Best for local integrations like Claude Desktop or CLI-based MCP clients.

```bash
python prisma_sdwan_mcp_server.py --transport stdio
```

### SSE Mode

Best for remote or web-based AI agents.

```bash
python prisma_sdwan_mcp_server.py --transport sse --host 0.0.0.0 --port 8000
```

### Streamable HTTP Mode

```bash
python prisma_sdwan_mcp_server.py --transport streamable-http --host 0.0.0.0 --port 8000
```

### Docker

```bash
# Stdio mode (default)
docker run -i --rm \
  -e PAN_CLIENT_ID=myaccount@tsg.iam.panserviceaccount.com \
  -e PAN_CLIENT_SECRET=your-secret \
  -e PAN_TSG_ID=1234567890 \
  prisma-sdwan-mcp --transport stdio

# SSE mode with port mapping
docker run -d --rm \
  -p 8000:8000 \
  -e PAN_CLIENT_ID=myaccount@tsg.iam.panserviceaccount.com \
  -e PAN_CLIENT_SECRET=your-secret \
  -e PAN_TSG_ID=1234567890 \
  prisma-sdwan-mcp --transport sse --host 0.0.0.0 --port 8000
```

## Client Integration

### Claude Desktop

Add the following to your Claude Desktop MCP configuration file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "prisma-sdwan": {
      "command": "python",
      "args": [
        "/absolute/path/to/prisma_sdwan_mcp_server.py",
        "--transport",
        "stdio"
      ],
      "env": {
        "PAN_CLIENT_ID": "myaccount@tsg.iam.panserviceaccount.com",
        "PAN_CLIENT_SECRET": "your-secret",
        "PAN_TSG_ID": "1234567890"
      }
    }
  }
}
```

With Docker:

```json
{
  "mcpServers": {
    "prisma-sdwan": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "PAN_CLIENT_ID",
        "-e", "PAN_CLIENT_SECRET",
        "-e", "PAN_TSG_ID",
        "prisma-sdwan-mcp",
        "--transport", "stdio"
      ],
      "env": {
        "PAN_CLIENT_ID": "myaccount@tsg.iam.panserviceaccount.com",
        "PAN_CLIENT_SECRET": "your-secret",
        "PAN_TSG_ID": "1234567890"
      }
    }
  }
}
```

### Gemini CLI

Add to your `settings.json`:

```json
{
  "mcpServers": {
    "prisma-sdwan": {
      "command": "python",
      "args": [
        "/absolute/path/to/prisma_sdwan_mcp_server.py",
        "--transport",
        "stdio"
      ],
      "env": {
        "PAN_CLIENT_ID": "myaccount@tsg.iam.panserviceaccount.com",
        "PAN_CLIENT_SECRET": "your-secret",
        "PAN_TSG_ID": "1234567890"
      }
    }
  }
}
```

### OpenCode / Other MCP Clients

Any MCP-compatible client can connect using the stdio transport. Point it at `prisma_sdwan_mcp_server.py` with the `--transport stdio` argument and supply the required environment variables.

## Available Tools

All tools return JSON-formatted data optimized for LLM consumption.

| Tool Name | Description | Parameters |
| --- | --- | --- |
| `get_sites` | Projected site inventory or one full site | `site_id`, `cursor`, `limit` (optional) |
| `get_elements` | Projected ION element inventory or one full element | `element_id`, `cursor`, `limit` (optional) |
| `get_machines` | Projected hardware inventory or one full machine | `machine_id`, `cursor`, `limit` (optional) |
| `get_app_defs` | Search projected application definitions or inspect the category histogram | `search`, `category`, `cursor`, `limit` (optional) |
| `find_site` | Resolve a site name/display name to site IDs by substring (capped at 50) | `name`, `cursor`, `limit` (optional) |
| `find_element` | Resolve an ION element name to element IDs by substring (capped at 50) | `name`, `cursor`, `limit` (optional) |
| `find_app` | Resolve an application name to app-definition IDs by substring (capped at 50) | `name`, `cursor`, `limit` (optional) |
| `find_machine` | Resolve a machine name to machine IDs by substring (capped at 50) | `name`, `cursor`, `limit` (optional) |
| `find_policy_set` | Resolve a policy-set name to IDs across all families (capped at 50) | `name`, `cursor`, `limit` (optional) |
| `find_security_zone` | Resolve a security-zone name to IDs by substring (capped at 50) | `name`, `cursor`, `limit` (optional) |
| `find_wan_network` | Resolve a WAN network name to IDs by substring (capped at 50) | `name`, `cursor`, `limit` (optional) |
| `find_path_group` | Resolve a path-group name to IDs by substring (capped at 50) | `name`, `cursor`, `limit` (optional) |
| `find_service_label` | Resolve a service-label name to IDs by substring (capped at 50) | `name`, `cursor`, `limit` (optional) |
| `get_topology` | Summarize anynet links or return bounded filtered detail | `detail`, `site_id`, `status`, `cursor`, `limit` (optional) |
| `get_basenet_topology` | Site-scoped basenet (underlay) view derived from anynet legs, with element/interface fields | `site_id`, `cursor`, `limit` (optional) |
| `get_interfaces` | Projected LAN and WAN interfaces for an element | `site_id`, `element_id`, `cursor`, `limit` (optional) |
| `get_wan_interfaces` | Projected WAN interfaces for a site | `site_id`, `cursor`, `limit` (optional) |
| `get_interface_status` | Operational status for one or every interface on an element | `site_id`, `element_id`, `interface_id` (optional) |
| `get_element_status` | Operational status and health of an ION element | `element_id` |
| `get_software_status` | Software version, upgrade state, and image details | `element_id` |
| `get_bgp_peers` | BGP peer configuration for an element | `site_id`, `element_id`, `cursor`, `limit` (optional) |
| `get_bgp_status` | BGP session state with established/not-established counts; optional per-peer prefix counts | `site_id`, `element_id`, `include_prefixes` (optional) |
| `get_bgp_prefixes` | Reachable/advertised/discovered prefixes for a BGP peer | `site_id`, `element_id`, `bgppeer_id`, `prefix_type` (optional), `cursor`, `limit` (optional) |
| `get_static_routes` | Static route table for an element | `site_id`, `element_id`, `cursor`, `limit` (optional) |
| `get_site_paths` | AnyNet paths incident to one site | `site_id`, `cursor`, `limit` (optional) |
| `resolve_path` | Resolve a bare path_id into a circuit descriptor (anynet leg or WAN interface) | `site_id`, `path_id` |
| `get_vpnlink_status` | Per-leg VPN link operational state (`active`/`usable`/`link_up`, endpoints, cipher) | `vpnlink_id` |
| `get_vpnlink_state` | Per-leg VPN link admin state (`enabled`) and `al_id` join key to topology | `vpnlink_id` |
| `get_flows` | Flow summary digest (total, by app/path/action, top talkers) or raw drill-down; server-side filters | `site_id`, `hours` (optional), `limit` (optional), `cursor` (optional), `raw` (optional), `page` (optional), `app` (optional), `element_id` (optional), `path_id` (optional), `waninterface_id` (optional) |
| `get_link_metrics` | Bandwidth series and link-quality availability for a site; optional element/raw | `site_id`, `hours` (optional), `element_id` (optional), `raw` (optional) |
| `get_probe_metrics` | Probe measurement availability for a site | `site_id`, `hours` (optional) |
| `get_events` | Recent projected events across critical, major, and minor severity; optional scoping | `limit` (optional), `cursor` (optional), `site_id` (optional), `element_id` (optional), `severity` (optional), `start_time` (optional), `end_time` (optional), `last` (optional) |
| `get_alarms` | Recent projected major and critical alarms; optional scoping | `limit` (optional), `cursor` (optional), `site_id` (optional), `element_id` (optional), `severity` (optional), `start_time` (optional), `end_time` (optional), `last` (optional) |
| `get_policy_sets` | Policy sets from network, priority, NGFW, and NAT families | `kind`, `include_stacks`, `policyset_id`, `cursor`, `limit` (optional) |
| `get_security_zones` | Security zone definitions across the fabric | `securityzone_id`, `cursor`, `limit` (optional) |
| `get_path_groups` | Path-group reference data | `pathgroup_id`, `cursor`, `limit` (optional) |
| `get_service_labels` | Service-label reference data | `servicelabel_id`, `cursor`, `limit` (optional) |
| `get_wan_networks` | WAN provider-network reference data | `wannetwork_id`, `cursor`, `limit` (optional) |
| `generate_site_config` | Generate a validated sandboxed site configuration YAML file | `site_id`, `elements`, `filename` (optional), `overwrite` (optional) |

### Resources

Read-only, attachable snapshots for clients that support browsing/attaching
MCP resources directly (as opposed to a tool call). Each one delegates to
the matching tool above, so there's one code path per data type either way.

| URI | Description |
| --- | --- |
| `prisma://sites` | Same as `get_sites()` with no arguments. |
| `prisma://topology` | Same as `get_topology()` with no arguments. |
| `prisma://policy-sets` | Same as `get_policy_sets()` with no arguments. |
| `prisma://site/{site_id}/elements` | Elements at one site — fetches the full tenant element list and filters client-side by `site_id`, since the SDK has no server-side filter for this. |

### Prompts

Discoverable, canned troubleshooting workflows. Each one returns an
instruction message naming which tools to call, in what order, and why —
not a tool call itself.

| Name | Args | Purpose |
| --- | --- | --- |
| `diagnose_vpn_link_down` | `site_hint` | Triage a `NETWORK_ANYNETLINK_DOWN` / `SITE_CONNECTIVITY_DEGRADED` alert: resolve the site, match the anynet leg, check status/state, pull a tightly-windowed event/alarm history, and correlate the underlay circuit. |
| `audit_site_inventory` | `site_hint` (optional) | Audit HA configuration and connectivity for one site or the whole tenant. |

### Response budgeting and breaking shapes

Every tool returns compact JSON capped by `PRISMA_MCP_MAX_RESPONSE_BYTES` (40 KB
by default). Collection responses include `truncated`, `total_count`,
`returned_count`, and an opaque `next_cursor` when more records remain. Pass that
cursor back with `limit` to continue. Collections project fields for operator
questions; single-record lookups retain full detail.

Three response shapes intentionally changed:

- `get_app_defs()` returns a category histogram and search guidance. Use
  `search="office"` or `category="business"` to retrieve projected records.
- `get_topology()` returns counts, status breakdowns, and not-up links. Use
  `detail="full"` with `site_id` or `status` to retrieve bounded arrays.
- `get_policy_sets()` queries the populated network, priority, NGFW, and NAT
  families. Use `kind` to select one family and `include_stacks=true` for its
  stack records.
- `get_flows()` now returns a summary digest by default (total matched,
  breakdown by application/path/action, top 10 talkers by bytes). Pass
  `raw=True` with `page`/`limit` (default 50, max 200) for drilled individual
  records; `app`, `element_id`, `path_id`, and `waninterface_id` are
  server-side filters.

`find_*` tools never auto-pick: ambiguous names return all matches (capped at
50 with a refine hint), and `resolve_path` marks unresolvable paths with
`resolved: false` plus a reason.

`get_link_metrics` combines confirmed `BandwidthUsage` utilization with
`LqmLatencyPointMetric`, `LqmPktLossPointMetric`, `LqmJitterPointMetric`, and
`LqmMosPointMetric` snapshots. `get_probe_metrics` uses the confirmed
`ProbeLatencyPointMetric`, `ProbeJitterPointMetric`, and
`ProbePktLossPointMetric` catalogs. LQM and probe requests use the API-required
`start_time` plus `interval` shape and omit `end_time`.

### Example Prompts

Once connected, try asking your AI agent:

- *"Show me all sites in the SD-WAN fabric."*
- *"What ION devices are deployed and what software versions are they running?"*
- *"Pull the BGP peers for the element at site DC-West."*
- *"Are there any critical alarms right now?"*
- *"Show me the full network topology."*
- *"Generate a site config YAML for site ID 12345."*
- *"List all WAN interfaces at the headquarters site."*

## Architecture

```
┌──────────────────┐         ┌──────────────────────┐         ┌─────────────────────┐
│   AI Agent       │  MCP    │  Prisma SD-WAN MCP   │  REST   │  Prisma SASE API    │
│  (Claude, etc.)  │◄──────►│  Server               │◄──────►│  api.sase.palo...   │
│                  │  stdio/ │  prisma_sdwan_mcp_    │  HTTPS  │                     │
│                  │  SSE    │  server.py            │         │                     │
└──────────────────┘         └──────────────────────┘         └─────────────────────┘
```

The server acts as a translation layer:

1. The AI agent calls an MCP tool (e.g., `get_sites`)
2. The server maps that call to the appropriate Prisma SASE REST API endpoint
3. It handles authentication, pagination, and error recovery automatically
4. The response is parsed, simplified, and returned as clean JSON

**Key Implementation Details:**

- **Package architecture** ... the compatibility entry point imports the `prisma_sdwan_mcp` package, whose tools are grouped by domain
- **OAuth2 authentication** via `prisma_sase` SDK with automatic token refresh
- **Auto-reauth** on 401/403 responses or token expiry
- **Config validation** using package-local JSON Schema (`schema.json`) for generated YAML files

## Troubleshooting

| Problem | Likely Cause | Fix |
| --- | --- | --- |
| `Connection refused` or timeout | No internet connectivity to Prisma SASE API | Verify you can reach `api.sase.paloaltonetworks.com` from your host |
| `Authentication failed` | Incorrect credentials | Double-check `PAN_CLIENT_ID`, `PAN_CLIENT_SECRET`, and `PAN_TSG_ID` |
| `403 Forbidden` | Insufficient permissions | Ensure the service account role includes SD-WAN read access |
| `Token expired` errors | Shouldn't happen (auto-refresh) | If persistent, restart the server. Tokens are refreshed every 15 minutes automatically |
| `ModuleNotFoundError: prisma_sase` | Missing dependency | Run `pip install prisma-sase` |
| Empty responses | Tenant has no data | Verify your TSG ID matches a tenant with active SD-WAN sites |
| `Region mismatch` | Stale per-region hostname configuration | Leave `PAN_REGION` advisory; use `PAN_CONTROLLER` only for an explicit private or QA controller |

### Debug Logging

Server logs are written to stderr. To capture them:

```bash
python prisma_sdwan_mcp_server.py --transport stdio 2>debug.log
```

## Contributing

Contributions are welcome! Here's how to get started:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-new-tool`)
3. Follow existing code conventions (package modules, `@mcp.tool()` pattern)
4. Test against a live or mock Prisma SASE tenant
5. Submit a Pull Request with a clear description of your changes

When adding new tools:
- Place them in the package module matching their domain and follow the `@mcp.tool()` decorator pattern
- Return compact, budgeted responses through the shared formatting helpers
- Keep collection responses projected and single-item lookups detailed

## License

This project is licensed under the [MIT License](LICENSE).
