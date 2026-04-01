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
- **Simplified Context** ... Raw API responses are parsed and trimmed to the fields that matter, keeping LLM context windows lean and focused.
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
| **Policy & Security** | View policy set definitions and security zone assignments |
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
pip install fastmcp prisma-sase python-dotenv pyyaml jsonschema
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
| `PAN_REGION` | API region: `americas` or `europe` (default: `americas`) | No |

### .env File

Create a `.env` file in the `prisma-sdwan/` directory:

```ini
PAN_CLIENT_ID=myaccount@1234567890.iam.panserviceaccount.com
PAN_CLIENT_SECRET=abc123-your-secret-here
PAN_TSG_ID=1234567890
PAN_REGION=americas
```

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
| `get_sites` | List all SD-WAN sites or retrieve a specific site by ID | `site_id` (optional) |
| `get_elements` | List all ION device elements or a specific element | `element_id` (optional) |
| `get_machines` | Hardware inventory: chassis serial numbers, models, and machine details | `machine_id` (optional) |
| `get_interfaces` | LAN and WAN interfaces for a given element at a site | `site_id`, `element_id` |
| `get_wan_interfaces` | WAN interface configurations for a site | `site_id` |
| `get_policy_sets` | SD-WAN policy set definitions (path, QoS, NAT rules) | None |
| `get_security_zones` | Security zone definitions across the fabric | None |
| `get_bgp_peers` | BGP peer configurations for a specific element at a site | `site_id`, `element_id` |
| `get_static_routes` | Static route table for an element | `site_id`, `element_id` |
| `get_element_status` | Operational status and health of an ION element | `element_id` |
| `get_software_status` | Software version, upgrade state, and image details | `element_id` |
| `get_app_defs` | Application definitions used in policy and reporting | None |
| `get_topology` | Full SD-WAN anynet topology graph (nodes, links, and status) | None |
| `get_events` | Recent events across all severity levels (critical, major, minor) | `limit` (optional, default: 20) |
| `get_alarms` | Active major and critical alarms | `limit` (optional, default: 20) |
| `generate_site_config` | Generate a validated site configuration YAML file | `site_id`, `elements`, `filename` (optional), `overwrite` (optional) |

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

- **Single-file architecture** ... all logic lives in `prisma_sdwan_mcp_server.py`
- **OAuth2 authentication** via `prisma_sase` SDK with automatic token refresh
- **Auto-reauth** on 401/403 responses or token expiry
- **Config validation** using JSON Schema (`schema.json`) for generated YAML files

## Troubleshooting

| Problem | Likely Cause | Fix |
| --- | --- | --- |
| `Connection refused` or timeout | No internet connectivity to Prisma SASE API | Verify you can reach `api.sase.paloaltonetworks.com` from your host |
| `Authentication failed` | Incorrect credentials | Double-check `PAN_CLIENT_ID`, `PAN_CLIENT_SECRET`, and `PAN_TSG_ID` |
| `403 Forbidden` | Insufficient permissions | Ensure the service account role includes SD-WAN read access |
| `Token expired` errors | Shouldn't happen (auto-refresh) | If persistent, restart the server. Tokens are refreshed every 15 minutes automatically |
| `ModuleNotFoundError: prisma_sase` | Missing dependency | Run `pip install prisma-sase` |
| Empty responses | Tenant has no data | Verify your TSG ID matches a tenant with active SD-WAN sites |
| `Region mismatch` | Wrong API region | Set `PAN_REGION=europe` if your tenant is in the EU region |

### Debug Logging

Server logs are written to stderr. To capture them:

```bash
python prisma_sdwan_mcp_server.py --transport stdio 2>debug.log
```

## Contributing

Contributions are welcome! Here's how to get started:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-new-tool`)
3. Follow existing code conventions (single-file architecture, `@mcp.tool()` pattern)
4. Test against a live or mock Prisma SASE tenant
5. Submit a Pull Request with a clear description of your changes

When adding new tools:
- Place them in `prisma_sdwan_mcp_server.py` following the `@mcp.tool()` decorator pattern
- Return `json.dumps(data, indent=2)` from every tool
- Keep responses trimmed to essential fields for LLM context efficiency

## License

This project is licensed under the [MIT License](LICENSE).
