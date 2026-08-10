# Prisma SD-WAN MCP v2

Registry-first MCP server for Palo Alto Networks Prisma SD-WAN.

## How it's built

```text
AI / operator
     |
26 semantic MCP tools -----------------------+
     |                                       |
name/ID resolver + workflow logic     run_commands (ION CLI over SSH)
     |                                       |
registry-driven capability executor   command policy -> address resolution
     |                                  -> reachability probe -> Netmiko
308 generated registry actions               |
+ 8 clearly labeled curated additions       ION device
     |
Prisma SASE SDK
```

The source registry is not rewritten. It's loaded as the API source of truth, with a small override file layered on top for human aliases and response-safety rules.

## AI-visible tool count: 27

The aim is not one tool per API. The aim is one tool per common operator intent, with a controlled escape hatch for rare APIs.

- **Discovery / resolution (6):** `find_site`, `find_element`, `find_resource`, `list_capabilities`, `read_capability`, `resolve_path`
- **Core network operations (5):** `get_inventory`, `get_device_health`, `get_interfaces`, `get_topology`, `get_wan`
- **Routing / diagnostics / monitoring (3):** `get_routing`, `get_device_diagnostics`, `get_monitoring`
- **Policy / security (2):** `get_policies`, `get_security`
- **Service/domain families (9):** `get_network_services`, `get_multicast`, `get_ipfix`, `get_cellular`, `get_software`, `get_identity`, `get_service_connections`, `get_prisma_access`, `get_platform`
- **Local automation output (1):** `generate_site_config`
- **ION CLI passthrough (1):** `run_commands` — the one tool that is not read-only; see below

`read_capability` provides guarded access to every source-registry action, so an API does not need a dedicated MCP tool to remain available.

## Core design principles

- Human name -> controller ID resolution.
- Exact match preferred over substring match.
- Multiple matches are returned; the server never silently picks one.
- Element records can supply `site_id` automatically.
- Workflow tools can combine several API calls.
- `resolve_path` never invents a circuit mapping.
- Authentication refresh and bounded 429/5xx retries.
- Cursor pagination and response byte limits.
- Full tool descriptions are shipped to the model.
- Compact list output; richer single-object/workflow output.
- Local site-config generation remains separate from network mutation.

## Safeguards

### Central secret redaction

Every registry-executed response passes through recursive redaction. Keys containing password, secret, token, session ID, private key, passphrase, SNMP community string, and similar values are replaced with `[REDACTED]`.

This is important because the source registry includes schemas that can expose authentication material.

### Expert capability gate

The generated registry contains 308 read-only actions. `read_capability` can execute them by `action_id`, but it validates:

1. capability exists;
2. required path parameters are present;
3. unknown path parameters are rejected;
4. POST body is checked against normalized registry schema hints;
5. response is redacted and size-limited.

### Curated registry additions

Eight useful SDK calls are not represented in the generated 308-action registry:

- topology
- event query
- flow monitor
- bandwidth monitor metrics
- LQM point metrics
- probe point metrics
- VPN-link status
- VPN-link state

They are stored in `prisma_sdwan_mcp/data/curated_capabilities.json` rather than hidden in tool code. All eight were validated against a live tenant, so `read_capability` executes them directly. A future curated action added without live validation is blocked by default until it is verified.

See `docs/LIVE_VALIDATION.md`.

## ION CLI passthrough (`run_commands`)

The one tool that reaches the **device** instead of the controller API, over SSH — and the one tool that is not annotated read-only, because the `ping`/`tcpping`/`dig` diagnostics it permits send real packets from the ION. Everything else it permits (`dump`, `inspect`) is display-only; everything not explicitly matched is denied fail-closed, with no deny list. See `docs/ION_CLI_RESEARCH.md` and the `prisma-cli://policy` resource for the exact allowed forms.

**This is a second, materially different network requirement.** The rest of this server only needs outbound HTTPS to the Prisma SASE controller. `run_commands` additionally needs outbound SSH connectivity from wherever this server runs to each ION's management address. A deployment that has one does not necessarily have the other — a container with no route to branch management networks will get a fast, explicit `device_unreachable` error rather than a hang or a misleading auth failure.

**SSH host-key checking is always strict.** The target device's host key must already be present in the `known_hosts` file before `run_commands` is called — e.g. via one prior interactive `ssh` login, or `ssh-keyscan`. There is no auto-trust, ever, including as a retry after failure.

**Credentials are configuration-only.** The tool signature is:

```text
run_commands(commands, element=None, host=None, site=None)
```

Credentials, SSH port and the `known_hosts` path are read from the server's environment and can never be passed as tool arguments. That is deliberate: a tool argument is authored by the model and lands in the conversation transcript. Set `ION_USERNAME` plus one of `ION_PASSWORD` / `ION_PRIVATE_KEY`; with neither set, every call fails closed with `configuration_error` before any resolution, probe, or connection is attempted.

Everything else — SSH port, probe/connect/read timeouts, output byte ceiling, commands per batch — has a working default. See `docs/CONFIGURATION.md` to change one. The older `PRISMA_ION_*` spellings still work; the short `ION_*` names are canonical.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
```

`.env` is six settings and no more:

```text
PAN_CLIENT_ID          # controller
PAN_CLIENT_SECRET
PAN_TSG_ID
ION_USERNAME           # device SSH (run_commands); blank disables the tool
ION_PASSWORD
ION_IP                 # diagnostic probe only -- the server ignores it
```

Every other setting has a working default in code. `docs/CONFIGURATION.md` is the full list if you ever need to change one.

## Run

stdio:

```bash
prisma-sdwan-mcp --transport stdio
```

streamable HTTP:

```bash
prisma-sdwan-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

Docker:

```bash
docker build -t prisma-sdwan-mcp .
docker run --rm --env-file .env prisma-sdwan-mcp
```

## Tests included

Dependency-free core tests validate:

- registry load/counts;
- action references;
- name/ID resolution and ambiguity behavior;
- generic GET/POST dispatch;
- registry schema normalization;
- recursive secret redaction;
- cursor pagination.

Run (234 tests, no live tenant needed):

```bash
PYTHONPATH=. python -m pytest -q
```

Live tenant/API validation is intentionally separate. Follow `docs/LIVE_VALIDATION.md` before production cutover.

## Diagnostic probe (`probe/`)

`probe/run_probe.py` drives this server against a real ION and writes the evidence — raw device
output, findings, and what it trusted — into `probe/results/<run id>/`. It only sends commands the
policy already permits and configures nothing on the device. It captures full raw device output on
purpose, so point it at a device you are willing to expose.

`probe/replay.py` needs no device: it replays captured device bytes through the real code path, so
read-termination and parsing bugs can be reproduced and fixed without another trip to the lab.

See `probe/README.md`.

## Files to read first

1. `docs/ARCHITECTURE.md`
2. `docs/CONFIGURATION.md`
3. `docs/TOOL_CATALOG.md`
4. `docs/LIVE_VALIDATION.md`
