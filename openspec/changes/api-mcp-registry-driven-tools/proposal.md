## Why

api-mcp exposes 39 hand-written tool functions, each wrapping exactly one `prisma_sase` SDK call. Every new SDK call the fabric needs to expose requires a bespoke Python function — slow, and the gap is real: a source-verified catalog of 309 read-only SDK actions (203 GET across 18 domains, 106 POST across 15 domains) has just been curated (`mcp_GET_domain_registry.json`, `mcp_POST_domain_registry.json`) and only **17** of them are reachable through api-mcp today — the 39 tools make 26 distinct SDK calls, 17 of which the registries cover, leaving **291 curated actions unreachable**. Hand-writing those one function at a time repeats work the curation already did: verifying the SDK call, its parameters, and that it is safely read-only.

The POST half of that safety claim is no longer an assumption. All 106 POST actions were executed against the live tenant on 2026-08-05 with a control/treatment differential over 99 config collections: **106/106 succeeded, zero server-side state changes detected** (`verification/post-readonly-audit.md`). Registry structure, SDK resolvability, and coverage were measured at the same time (`verification/registry-facts.md`), and several assumptions in the first draft of this proposal did not survive — the corrections are folded in below.

## What Changes

- Add a **registry-driven dispatch layer**: for each of the **18** domains in the curated registries, one MCP tool takes an `action` parameter (validated against that domain's registry entries) and a params payload. The dispatcher resolves `action` → registry entry → the exact `prisma_sase` SDK method, called through the existing `PrismaSDWANClient` (so auth refresh, retry, and backoff are reused, not reimplemented).
  - 18, not 33: every one of the 15 POST domain names already exists in the GET registry. One tool per domain name carries both its GET and its POST actions. No action name collides inside a domain, so this needs no namespacing scheme.
- Dispatcher responses go through the **same envelope contract** every hand-built tool uses today (`formatting.py`'s `build_envelope`/`collection_response`/`single_response`, cursor pagination) — no second response shape. The envelope additionally carries the resolved `action`, so a consumer can tell one `sites_devices` result from another (additive, per the additive-only contract rule).
- **Move the two registry JSON files** from the repo root (currently untracked) into a checked-in, versioned location under `api-mcp/`, loaded and schema-validated at startup. The two files do **not** share a schema (the GET file has no `sdk_call` and no `input_parameters`; its `safety` block carries a fourth key), so the loader validates each against its own schema. The server refuses to expose any action whose `safety` block does not assert `read_only: true`, `destructive: false`, `verified_working: true` — the registry is trusted as *curated input*, not as an unchecked runtime authority.
- **Carry forward hand-won behavior** from the current tools into the registry-driven system rather than maintaining it twice: operational caveats (e.g. the HA-audit note on `get_elements`), custom field projections (`ELEMENT_KEEP_FIELDS`-style slimming), and cross-cutting response shaping (e.g. `get_app_defs`'s category histogram when called unfiltered) become per-action/per-domain overrides the generic dispatcher consults, keyed by the same `action` name.
- **The registries do not cover everything api-mcp does today.** Nine SDK calls that 11 of the 39 tools depend on appear in neither file — `element_status`, `vpnlinks_state`, `vpnlinks_status`, `events_query`, `monitor_flows`, `monitor_metrics`, `monitor_lqm_point_metrics`, `monitor_probe_point_metrics`, `topology`. Those are the metrics, flows, topology, events and link-status surface: the troubleshooting core. The tools built on them (`get_element_status`, `get_events`, `get_alarms`, `get_flows`, `get_link_metrics`, `get_probe_metrics`, `get_topology`, `get_site_paths`, `get_basenet_topology`, `get_vpnlink_status`, `get_vpnlink_state`, plus `resolve_path`) **stay hand-built and are not retired by this change.** A coverage test pins that set so a later registry pass cannot silently orphan them.
- **BREAKING**: tool names and signatures for domains fully absorbed into the dispatcher will change (e.g. `get_sites(site_id=...)` → a `sites_devices` domain tool with `action="sites"`). `webtester`'s gateway discovers tools dynamically via `mcp.list_tools()` and calls `tool.fn(**args)`, so nothing breaks at the call layer — but its *catalogue* does need a change (see Impact). `api-mcp/tests/test_tool_contract.py`'s `EXPECTED_SIGNATURES` asserts exact set equality and so must be updated in the same commit as the first tool registration, per `openspec/project.md`'s stated rule.

## Capabilities

### New Capabilities
- `registry-driven-tools`: how the curated GET/POST action registries become MCP tools — registry format (two shapes), startup validation, the safety gate, the domain-dispatch tool shape, `action`/params resolution to an SDK call, and how per-action overrides (guidance text, projection fields) attach.

### Modified Capabilities
- none — no capability in `openspec/specs/` is ratified yet (`response-contract-and-truncation-policy` is still an in-flight proposal, not yet applied). This change **consumes** that contract as a dependency but does not change its requirements; if it is applied first, the dispatcher requirements defer to it rather than restating it.

## Impact

**Code**
- `api-mcp/prisma_sdwan_mcp/registry.py` — currently near-empty; becomes home to the domain-dispatch tool registration plus the registry loader/validator.
- New module(s) for: registry loading + per-file schema validation, `action` → SDK-method resolution, per-action override lookup.
- `api-mcp/prisma_sdwan_mcp/tools/*.py` — existing hand-built tools are not deleted wholesale; the domains they cover become the dispatcher's override source, and the 11 registry-uncovered tools listed above remain as-is (see design.md for the per-domain disposition).
- `api-mcp/prisma_sdwan_mcp/resources.py`, `prompts.py` — need updates where the resources they delegate to (`get_sites`, `get_elements`, `get_topology`, `get_policy_sets`) change shape.
- `mcp_GET_domain_registry.json`, `mcp_POST_domain_registry.json` — move from repo root into `api-mcp/` (exact path in design.md), become tracked, versioned inputs. The GET file's `metadata.total_actions` says 202 (unique names) against 203 entries and is corrected in the move.

**Tests**
- `api-mcp/tests/test_tool_contract.py` — `EXPECTED_SIGNATURES` rewritten for the new tool set, deliberately, in the same commit as the first dispatcher registration (not deferred — the assert is exact set equality, so it fails the moment a tool is added alongside).
- New tests: per-file registry schema validation, startup exclusion of an unsafe or unresolvable entry, `action` resolution correctness per domain, override/registry sync, and the registry-coverage test pinning the 11 hand-built survivors.

**Consumers**
- `webtester` — **needs a small change**, contrary to this proposal's first draft. Its gateway is dynamic, but `app/mcp_gateway.py:76` derives a tool's category from `tool.fn.__module__` (18 dispatcher tools → one category) and `app/catalog.py` scores tools against hardcoded category names and `get_`/`list_`/`query_` name prefixes, dropping anything that scores ≤ 0 from its ranked pages. Measured detail in `verification/registry-facts.md`.

**Out of scope**
- `cli-mcp` is untouched by this change.
- Bringing the metrics/flows/topology/events surface into the registry format. That is a curation task, not a dispatcher task, and is the natural follow-up once the dispatcher is proven.
