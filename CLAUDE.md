# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Registry-first MCP (Model Context Protocol) server exposing Palo Alto Networks Prisma SD-WAN as 27 semantic AI tools, backed by a 316-action capability registry (308 generated + 8 curated) and the `prisma_sase` SDK, plus one ION CLI passthrough tool (`run_commands`) over SSH via `netmiko`. Python 3.11+, FastMCP.

## Commands

```bash
# Setup
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env           # then fill PAN_CLIENT_ID / PAN_CLIENT_SECRET / PAN_TSG_ID

# Test (dependency-free core suite; no live tenant needed)
PYTHONPATH=. pytest -q
PYTHONPATH=. pytest -q tests/test_resolver.py            # single file
PYTHONPATH=. pytest -q tests/test_resolver.py::test_name # single test

# Run
prisma-sdwan-mcp --transport stdio
prisma-sdwan-mcp --transport streamable-http --host 0.0.0.0 --port 8000

# Docker
docker build -t prisma-sdwan-mcp .
docker run --rm --env-file .env prisma-sdwan-mcp
```

Two pytest markers exist (`live`, `sdk`) for tests requiring a real tenant / the `prisma_sase` package — see `docs/LIVE_VALIDATION.md` before running anything against a live controller.

## Architecture

**Design rule: the registry owns API facts, semantic tools own operator meaning.** A tool must never hard-code SDK endpoint details the registry already knows.

```
AI  --intent-->  Semantic tool (prisma_sdwan_mcp/tools/*.py)
                     |
                     +--> Resolver (resolver.py): name -> ID
                     |      site name -> site_id, element name -> element_id (+ site_id), policy name -> policy_id
                     |      exact match always wins over substring match; multiple matches -> candidates returned, never a silent guess
                     |
                     +--> Workflow logic: one operator intent may fan out into several capability calls
                     v
                 CapabilityExecutor (executor.py)
                     |
                     +--> Catalog lookup (catalog.py)
                     +--> required path-parameter validation, unknown-param rejection
                     +--> POST body checked against normalized registry schema hints
                     +--> SDK method binding (client.py: lazy auth, 401/403 re-auth, bounded backoff on 429/5xx)
                     +--> recursive secret redaction (safety.py) on every response
                     +--> response.py: v2 response envelope, cursor pagination, byte-budget enforcement
                     v
                 Prisma SASE SDK
```

### Data sources loaded by `catalog.py`

- `data/mcp_registry_get_post.json` — 308 generated, read-only registry actions (source of truth for API shape; never hand-edited to add behavior).
- `data/curated_capabilities.json` — 8 hand-curated actions absent from the generated registry (topology, event query, flow monitor, bandwidth/LQM/probe point metrics, VPN-link status/state). All 8 were live-validated against a real tenant on 2026-08-07 (`docs/LIVE_VALIDATION.md` Step 6), so `requires_live_test` is now false and the `expert_blocked_by_default` list in `registry_overrides.yaml` is empty — `read_capability` can execute them directly. A future curated action that ships unverified should set `requires_live_test: true` **and** be added to `expert_blocked_by_default`, which is the list the gate actually reads; `MCP_ALLOW_UNVERIFIED_COMPAT=1` overrides it.
- `data/registry_overrides.yaml` — human aliases and safety config layered on top; does not rewrite the source registry.

Catalog discovery is **enumeration, not search**: `list_capabilities()` lists domains, `list_capabilities(domain=...)` returns every action in that domain in full every time. There is no free-text matching against descriptions.

### The 27-tool surface (`prisma_sdwan_mcp/tools/`)

Split across `discovery.py`, `core.py`, `routing_diagnostics.py`, `policies_security.py`, `domains.py`, `monitoring.py`, `config_gen.py`, `cli.py`. Registered in `server.py`. Grouped by intent, not by SDK domain:
- Discovery/resolution (6): `find_site`, `find_element`, `find_resource`, `list_capabilities`, `read_capability`, `resolve_path`
- Core network ops (5), routing/diagnostics/monitoring (3), policy/security (2), service/domain families (9), local automation output (1): `generate_site_config`
- ION CLI passthrough (1): `run_commands` — see below

`read_capability` is the escape hatch: it can execute any of the 316 registry actions by `action_id` (with the curated-action gate above), so a long-tail API doesn't need a dedicated semantic tool.

### Mutation boundary

26 of the 27 tools are read-only, including `generate_site_config`. The API executor is entirely read-only — the source registry contains no controller mutation endpoints. `generate_site_config` validates one site's device list against `data/site_config_schema.json` and returns the structured config plus formatted YAML text to the caller; it does not write to disk and does not call a Prisma mutation API. The server holds no state between calls — turning the returned config into a real file, merging it with other sites, and applying it to the network is entirely the consumer's responsibility. Network changes are expected to go through Ansible/change-control, not this server. Preserve this boundary when adding tools: never wire a new tool to a controller write endpoint, and never give this server its own persistent storage.

`run_commands` is the one exception: it runs a policy-approved batch of ION CLI commands over SSH directly against the device, not the controller API, so it is annotated `ACTIVE_DIAGNOSTIC` (not `READ_ONLY`) — the `ping`/`tcpping`/`dig` diagnostics it permits send real packets from the device. It still touches no controller write endpoint, changes no device configuration, and the server still holds no state between calls; only the read-only *claim* changes, not the mutation boundary itself. See `prisma_sdwan_mcp/cli/{policy,ssh,address}.py` and `docs/ION_CLI_RESEARCH.md`.

### Secret redaction

Every registry-executed response passes through recursive redaction (`safety.py`) before it reaches the model — keys containing password/secret/token/session ID/private key/passphrase/SNMP community string (and similar) become `[REDACTED]`. This applies unconditionally to registry/curated responses; keep new response paths routed through it.

## Key env vars (see `.env.example`, read via `config.py`)

`PAN_CLIENT_ID`, `PAN_CLIENT_SECRET`, `PAN_TSG_ID`, `PAN_CONTROLLER`, `MCP_MAX_RESPONSE_BYTES`, `MCP_DEFAULT_PAGE_SIZE`, `MCP_MAX_PAGE_SIZE`, `MCP_MAX_FANOUT`, `MCP_EXPERT_TOOL_ENABLED`, `MCP_ALLOW_UNVERIFIED_COMPAT`.

ION CLI passthrough (`run_commands`, all optional — unset means the tool always fails closed with `configuration_error`): `PRISMA_ION_USERNAME`, `PRISMA_ION_PASSWORD`, `PRISMA_ION_PRIVATE_KEY`, `PRISMA_ION_PRIVATE_KEY_PASSPHRASE`, `PRISMA_ION_SSH_PORT`, `PRISMA_ION_PROBE_TIMEOUT`, `PRISMA_ION_CONNECT_TIMEOUT`, `PRISMA_ION_READ_TIMEOUT`, `PRISMA_ION_MAX_OUTPUT_BYTES`, `PRISMA_ION_MAX_COMMANDS`.

## Files to read first

1. `docs/ARCHITECTURE.md`
2. `docs/TOOL_CATALOG.md`
3. `docs/LIVE_VALIDATION.md`

## Workflow note

This repo uses OpenSpec (`openspec/`) for spec-driven changes — proposals/tasks/specs live under `openspec/changes/<change-id>/`, archived ones under `openspec/changes/archive/`. The `/opsx:*` slash commands (propose/apply/archive/explore) drive this workflow.
