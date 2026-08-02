# PRISMA-MCP

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Status](https://img.shields.io/badge/status-unofficial-orange)
![Platform](https://img.shields.io/badge/platform-prisma%20sd--wan-green)

> **Disclaimer:** This project is a personal work developed independently for educational and open-source purposes. It is not an official product of Palo Alto Networks, Inc. or any of its affiliates. All trademarks, service marks, and company names are the property of their respective owners.

Two complementary, independently-runnable **Model Context Protocol (MCP)** servers for **Palo Alto Networks Prisma SD-WAN**, packaged together because they cover the two ways an agent needs to reach the fabric: the cloud controller API, and the device CLI directly.

| | [`api-mcp/`](api-mcp/) | [`cli-mcp/`](cli-mcp/) |
| --- | --- | --- |
| Transport to the fabric | Prisma SASE / SD-WAN REST API | SSH (Netmiko) straight to the ION |
| Auth model | Service-account credentials, loaded once from `.env` | Credentials supplied per call by the caller, never stored |
| Surface | 39 semantic, read-only tools (inventory, topology, monitoring, policy, routing, config export) | One generic tool, `run_commands`, for a fixed allow-list of read-only ION CLI command families (`dump`, `inspect`) |
| Docs | [api-mcp/README.md](api-mcp/README.md) | [cli-mcp/README.md](cli-mcp/README.md), [cli-mcp/RESEARCH.md](cli-mcp/RESEARCH.md) |

[`webtester/`](webtester/) is a browser UI for exercising `api-mcp`'s tools interactively — a third top-level piece, run separately from either server (see [webtester/README.md](webtester/README.md)).

## Why two servers instead of one

They don't share a trust boundary. `api-mcp` holds a long-lived service-account credential and talks to the controller. `cli-mcp` never holds a credential at all — the caller passes `host`/`username`/`password` (or an inline private key) on every single call, and the server opens a fresh SSH session per request with strict host-key checking. Collapsing them into one process would mean either the CLI tool inherits the API server's stored credential (wrong — it doesn't need one and shouldn't be able to reach one), or the API server starts accepting per-call SSH creds (wrong — it doesn't do SSH). Keeping them as separate deployables keeps each one's blast radius honest.

Run whichever one (or both) a given agent needs; nothing in either depends on the other being present.

## Quick start

```powershell
# API server (needs a Prisma SD-WAN service account — see api-mcp/README.md)
cd api-mcp
python -m pip install -r requirements.txt
python prisma_sdwan_mcp_server.py

# CLI passthrough server (no stored credentials — see cli-mcp/README.md)
cd ../cli-mcp
python -m pip install -r requirements.txt
python prisma_sdwan_cli_mcp_server.py
```

## License

MIT — see [LICENSE](LICENSE).
