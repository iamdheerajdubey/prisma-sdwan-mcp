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
cp .env.example .env           # five settings; everything else has a code default

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

Device-dependent behaviour is regression-tested without hardware: `tests/fixtures/ion/direct_*.txt` holds bytes captured verbatim from a live ION 1200 (6.3.6-b9), and `tests/test_ion_replay.py` replays them through the real code path with no device attached. It is an ordinary part of the run above — no marker, no hardware.

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

`run_commands` is the one exception: it runs a policy-approved batch of ION CLI commands over SSH directly against the device, not the controller API, so it is annotated `ACTIVE_DIAGNOSTIC` (not `READ_ONLY`) — the `ping`/`tcpping`/`dig` diagnostics it permits send real packets from the device. It still touches no controller write endpoint, changes no device configuration, and the server still holds no state between calls; only the read-only *claim* changes, not the mutation boundary itself. See `prisma_sdwan_mcp/cli/{policy,ssh,address,redact}.py` and `docs/ION_CLI_RESEARCH.md`.

### Secret redaction — two redactors, deliberately

`safety.py` redacts by dict **key**: any key containing password/secret/token/session ID/private key/passphrase/SNMP community string becomes `[REDACTED]`. Every registry-executed response goes through it; keep new API response paths routed through it.

It is structurally incapable of helping the CLI lane. Device output arrives as one text blob under the key `output`, which is not a sensitive name, so the recursive walk descends to the string and returns it untouched — verified, and asserted in `tests/test_cli_redact.py` so the day `safety.py` grows text handling this gets reconsidered. `cli/redact.py` does pattern-level redaction on the text itself and runs in `cli/ssh.py` after truncation and after error classification, so neither decision is made on rewritten text.

A result whose text changed carries `redacted: true`, or a fully redacted value would be indistinguishable from output the device never produced.

### CLI lane specifics

- **Addressing** (`cli/address.py`): element name → site → element → interfaces → live management address. Filters `used_for` to `controller`/`lan`, requires `operational_state == "up"`, and excludes RFC 6598 shared address space (100.64.0.0/10) — Prisma uses that range for service-link and tunnel endpoints. Never guesses: several candidates raise `ResolutionError` carrying them.
- **Credentials are configuration-only.** `run_commands(commands, element, host, site)` takes no credential, port or known_hosts argument. A tool argument is model-visible and lands in the conversation transcript. There was a second per-call path once and the two sources disagreed about what "not set" meant; one source removed the class of bug.
- **Error taxonomy**: `unreachable`, `host_key`, `authentication`, `rate_limited`, `connection`. `rate_limited` is the only retryable one — a live ION resets roughly the fifth SSH session opened in quick succession, and unlike every other connection failure it clears on its own.
- **Reading device output is where the bugs live.** Six defects were found only against real hardware (see `docs/LIVE_VALIDATION.md`): ANSI escapes in the prompt made the read terminate on the command echo, the prompt carries a trailing ``, the device echoes prompt+command twice above its error text. Change `cli/ssh.py` only with `tests/test_ion_replay.py` green — it replays the captured device bytes in `tests/fixtures/ion/` through the real path and is mutation-verified.

## Key env vars (see `.env.example`, read via `config.py`)

`PAN_CLIENT_ID`, `PAN_CLIENT_SECRET`, `PAN_TSG_ID`, `PAN_CONTROLLER`, `MCP_MAX_RESPONSE_BYTES`, `MCP_DEFAULT_PAGE_SIZE`, `MCP_MAX_PAGE_SIZE`, `MCP_MAX_FANOUT`, `MCP_EXPERT_TOOL_ENABLED`, `MCP_ALLOW_UNVERIFIED_COMPAT`.

`.env.example` holds **five** settings and nothing else: `PAN_CLIENT_ID`, `PAN_CLIENT_SECRET`, `PAN_TSG_ID`, `ION_USERNAME`, `ION_PASSWORD`. Every other variable has a working default in `config.py` and is documented in `docs/CONFIGURATION.md`. Do not re-add defaults to `.env.example`: a value written in two places only drifts, and a variable no code reads is worse than none — it reads as a knob, and whoever sets it will wonder why nothing happens.

ION CLI (unset means `run_commands` fails closed with `configuration_error` before any network activity): `ION_USERNAME`, `ION_PASSWORD` or `ION_PRIVATE_KEY`, `ION_KNOWN_HOSTS`, `ION_SSH_PORT`, `ION_PROBE_TIMEOUT`, `ION_CONNECT_TIMEOUT`, `ION_READ_TIMEOUT`, `ION_MAX_OUTPUT_BYTES`, `ION_MAX_COMMANDS`. The longer `PRISMA_ION_*` spellings still work.

`config.py` loads `.env` by explicit path from the repository root, not by searching upward from the current working directory — a bare `load_dotenv()` silently loads nothing when the server is started from elsewhere. `PRISMA_ENV_FILE` redirects it. Real environment variables always win.

## Files to read first

1. `docs/ARCHITECTURE.md`
2. `docs/TOOL_CATALOG.md`
3. `docs/LIVE_VALIDATION.md` — what real hardware disagreed with, and how
4. `docs/CONFIGURATION.md` — every setting that is not in `.env.example`

## Workflow note

This repo uses OpenSpec (`openspec/`) for spec-driven changes — proposals/tasks/specs live under `openspec/changes/<change-id>/`, archived ones under `openspec/changes/archive/`. The `/opsx:*` slash commands (propose/apply/archive/explore) drive this workflow.
