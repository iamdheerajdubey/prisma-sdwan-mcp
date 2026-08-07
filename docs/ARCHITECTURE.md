# MCP v2 Architecture

## Design rule

**The registry owns API facts. Semantic tools own operator meaning.**

A tool should not hard-code SDK endpoint details when the registry already knows them.

```text
AI
 |
 |  operator intent
 v
Semantic tool
 |
 +--> Resolver
 |      site name -> site ID
 |      element name -> element ID -> site ID
 |      policy name -> policy ID
 |
 +--> Workflow logic
 |      one intent may require several capabilities
 |
 v
CapabilityExecutor
 |
 +--> Registry lookup
 +--> required path validation
 +--> POST body schema-hint validation
 +--> SDK method binding
 +--> auth/retry client
 +--> recursive secret redaction
 |
 v
Prisma SASE SDK
```

## Main components

### `catalog.py`

Loads:

- `data/mcp_registry_get_post.json` — 308 generated read-only actions.
- `data/curated_capabilities.json` — 8 hand-curated actions absent from the generated registry.
- `data/registry_overrides.yaml` — human aliases and safety configuration.

It validates unique action IDs, supported methods, SDK call names, and path-parameter definitions.

Catalog discovery is enumeration, not search: the catalog is a fixed 316-entry list across 19 domains, largest domain 43 entries, well within a single response. `list_capabilities()` lists domains; `list_capabilities(domain=...)` lists every action in one, in full, every time. There is no free-text matching against descriptions — an AI's phrasing never has to guess a term that happens to appear in stored prose.

### `executor.py`

Generic API execution engine.

It does not know BGP, NAT, DNS, or Prisma Access semantics. It only knows how to execute an action contract from the registry safely.

SDK method signatures vary. The executor first uses Python signature names when available. If generated SDK wrappers are generic, it falls back to safe GET/POST positional patterns. All known registry actions are read-only.

### `resolver.py`

Converts human names into IDs. Exact IDs and exact names win over substring matches. More than one match produces candidates instead of a guess.

### `safety.py`

Runs on every registry response. Sensitive key names are recursively redacted.

### `response.py`

Provides the stable v2 response contract, cursor pagination, byte-budget enforcement, and structured errors.

### `client.py`

Handles authentication end-to-end:

- lazy login;
- token lifetime handling;
- re-authentication on 401/403;
- bounded exponential backoff for 429 and 5xx;
- retry accounting.

## Why 26 tools, not 18 or 308

### Not 308

308 tools would make model tool selection noisy and expose SDK vocabulary directly to AI.

### Not exactly 18 domains

Registry domains are useful for catalog organization, but they do not map cleanly to operator intent. Example: troubleshooting a VPN problem can require topology, WAN, events, and monitoring data across several registry domains.

### 26 semantic tools

The selected surface keeps high-use intents easy to discover while the expert capability tool preserves long-tail coverage.

## Mutation boundary

All 26 tools are read-only. The API executor is read-only — no controller mutation endpoint is present in the source registry used here. `generate_site_config` does not touch the filesystem or call a Prisma mutation API either; it validates one site's device list against the `prisma_sdwan.sites` schema and returns the structured config plus formatted YAML text to the caller. Turning that into a real file, combining it with other sites, and applying it to the network is entirely up to whatever consumes this server — this keeps Ansible/change-control as the network mutation path, and keeps this server from holding any state of its own between calls.
