## Context

api-mcp today: 39 MCP tools, each a hand-written Python function in `tools/{inventory,monitoring,network,policy,resolve,routing,config_gen}.py`, each calling exactly one `prisma_sase` SDK method through `PrismaSDWANClient.call_sdk`/`call_sdk_post` (`client.py`), each shaping its own response by hand-calling `formatting.py` primitives (`collection_response`, `single_response`, `build_envelope`, `project_items`). Between them they make 26 distinct SDK calls.

Two curated JSON files — `mcp_GET_domain_registry.json` (18 domains, **203** actions) and `mcp_POST_domain_registry.json` (15 domains, 106 actions) — now exist, source-verified against the real `prisma_sase` SDK, each action carrying its SDK method name, parameters, and a `safety` block. Both files' own metadata state the intended shape: one MCP tool per domain, an `action` parameter selecting the underlying call.

Everything asserted below about those files was measured, not assumed; the measurements and how to reproduce them are in `verification/registry-facts.md`, and the live read-only audit of the POST set is in `verification/post-readonly-audit.md`. The findings that shaped this design:

- **18 domains, not 33.** All 15 POST domain names already exist in the GET registry. No action name collides inside a domain.
- **The two files have different schemas.** GET has no `sdk_call` (its `name` *is* the SDK method — 203/203 resolve on `sdk.get`) and no `input_parameters` at all; its `safety` block carries a fourth key, `verified_using_a_real_chained_id`. POST has `sdk_call` (106/106 resolve on `sdk.post`), `input_parameters`, `api_version`, `category`.
- **Nine SDK calls used by 11 current tools are in neither registry** — the metrics, flows, topology, events and VPN-link-status surface. The dispatcher cannot serve them.
- **`input_parameters` is explicitly not exhaustive** (the registry says so in every entry's `note`), so it cannot be a closed allow-list.
- **`verified_working: true` is soft for GET**: 103 GET actions require a path parameter, but only 31 carry `verified_using_a_real_chained_id: true`.
- **The POST set is read-only in fact**, not just by assertion: 106/106 ran green against the live tenant with zero `_etag`/`_updated_on_utc` drift across 99 config collections, measured against a control window.

Not every one of the 39 current tools is a simple one-call wrapper:
- `tools/resolve.py` (`find_site`, `find_element`, `find_app`, …) fetches a full collection then does client-side fuzzy name matching — a search capability layered on top of a fetch, not a 1:1 SDK call.
- `tools/config_gen.py` (`generate_site_config`) builds and writes a config file against a JSON schema — not a read dispatch at all.
- `tools/monitoring.py` and parts of `tools/network.py` build time-windowed metric bodies (`formatting.monitor_body`, `monitor_metrics_body`) for endpoints the registry does not list.
- Most of `tools/inventory.py`, `tools/network.py`, `tools/policy.py`, `tools/routing.py` are close to 1:1 SDK wrappers, several with a hand-picked projection (`ELEMENT_KEEP_FIELDS`, `SITE_KEEP_FIELDS`, …) or a short operational caveat in the docstring.

`formatting.collection_response`/`single_response` already accept **any** SDK response shape plus an optional projection set — they do not assume which SDK call produced the data. A generic dispatcher can reuse them as-is; no new response-formatting code is needed, only a new way to reach the SDK call and look up which projection/guidance applies.

## Goals / Non-Goals

**Goals:**
- Expose the registry-covered surface (309 actions minus anything failing the safety gate) through 18 domain-dispatch tools, replacing tool-menu growth-by-hand-coding with growth-by-curating-the-registry.
- Preserve every piece of operational knowledge currently embedded in the 39 tools (caveats, projections, cross-cutting shaping) — attached to the dispatcher, not lost.
- Preserve every *capability*: no tool is retired unless the dispatcher can actually serve its SDK call.
- Keep exactly one path from "MCP tool call" to "formatted envelope" for any given data type, matching `openspec/project.md`'s existing rule.
- Make the registry a checked-in, schema-validated, fail-closed input: an entry not marked safe at load time is never callable.

**Non-Goals:**
- Not touching `cli-mcp` (separate trust boundary, separate change if ever needed).
- Not building per-action JSON Schema. **Resolved, not deferred**: `fastmcp==3.4.4` fixes a tool's `parameters` schema at registration and `list_tools()` returns it unchanged; MCP itself has no concept of a schema varying by an argument's value. The dispatcher ships a single `(action, params)` shape per domain plus registry-assembled docstrings, and that is the design.
- Not curating the metrics/flows/topology/events endpoints into the registry format. Follow-up change; until then those tools stay hand-built.
- Not migrating `find_*`, `resolve_path`, or `generate_site_config` into the generic dispatcher — they are genuinely not 1:1 SDK-call wrappers and stay hand-built, refactored only to call the dispatcher's internal fetch function instead of `registry.client.call_sdk` directly.

## Decisions

### 1. Registry storage: checked-in JSON under `api-mcp/`, validated with `jsonschema` (already a dependency)
Move `mcp_GET_domain_registry.json` / `mcp_POST_domain_registry.json` to `api-mcp/prisma_sdwan_mcp/registry_data/get_domain_registry.json` and `.../post_domain_registry.json`. Validate with `jsonschema`, already pinned in `requirements.txt` — no new dependency.

**Two schemas, not one.** The files genuinely differ (see Context). Write `get_registry.schema.json` and `post_registry.schema.json` sharing a common `$defs` for the parts that are identical (`domain`, `path_parameters`, the three required `safety` booleans). A single schema forced over both would have to make `sdk_call` and `input_parameters` optional, which would silently accept a POST entry missing its `sdk_call` — the one field the dispatcher cannot work without.

The loader counts actions itself and ignores `metadata.total_actions` (the GET file's says 202 against 203 actual). The move corrects the file; the loader does not depend on the correction.

**Alternative considered:** keep the JSON files at repo root or load them from an external path at deploy time. Rejected — the registry defines the tool surface; it must version with the code that dispatches against it, the same way `formatting.py` versions with its tests.

### 2. Startup safety gate: filter, don't crash — and match on required keys, not exact equality
At load, drop (with a logged warning) any action that fails either check:
- its `safety` block does not have `read_only: true`, `destructive: false`, `verified_working: true`;
- its SDK call (POST: `sdk_call`; GET: `name`) does not resolve to a real attribute on `sdk.post`/`sdk.get` at runtime — defends against registry/SDK version drift, e.g. after a `prisma_sase` upgrade.

The safety check tests **those three keys**, never exact object equality. The GET file's `safety` carries a fourth key (`verified_using_a_real_chained_id`); an exact-equality gate — which the first draft of this design and of spec.md both specified — would have excluded all 203 GET actions and shipped a server with no GET coverage at all.

Excluded actions are recorded and exposed via a `prisma://registry-audit` resource (what was loaded, what was dropped and why) rather than silently vanishing.

The audit resource also flags, without excluding, GET actions that require a path parameter but carry `verified_using_a_real_chained_id: false` — 72-ish entries whose `verified_working: true` was earned by a call that never supplied the ID the endpoint needs. They stay callable; the operator gets told which ones are untested.

**Alternative considered:** hard-fail server startup on any unsafe entry. Rejected as too brittle for a 309-action catalog maintained by hand — one bad entry from a future curation pass would take down the whole server instead of just that one action. Fail-closed per-action, not fail-closed per-server. (A file that fails *schema* validation is different: that blocks startup, because it means the loader cannot trust anything in it.)

### 3. Domain tool shape: `action` + `params` dict, one tool per domain — 18 of them
Each domain becomes one `@mcp.tool`: `def <domain>(action: str, params: dict | None = None, cursor: str | None = None, limit: int | None = None) -> str`. A domain tool carries **both** its GET and its POST actions; the registry entry records which, and the dispatcher routes to `sdk.get` or `sdk.post` accordingly. `action` is validated against that domain's loaded (post-safety-gate) action names; unknown actions return `structured_error("invalid_argument", ...)` listing valid actions.

Since no action name is duplicated across the GET and POST files within a domain, a flat action namespace per domain is unambiguous. A loader-time assertion enforces this rather than assuming it holds after the next curation pass.

**Alternative considered:** one MCP tool per action (309 tools). Rejected — recreates the "big menu" problem this change exists partly to fix, at ~8x today's scale, and contradicts both JSON files' own stated intent.

**Alternative considered:** separate GET and POST tools per domain (33 tools). Rejected — 15 of the 18 domain names exist in both files, so this needs a naming scheme (`sites_devices_get` / `sites_devices_query`) that pushes an implementation detail of the HTTP verb into the agent-facing surface, for no gain the agent can use.

**Alternative considered:** one single mega-tool for the whole server (`call(domain, action, params)`). Rejected — loses per-domain `readOnlyHint`/`openWorldHint` annotation granularity and makes every domain's docstring compete for space in one tool description.

Discoverability compensates for the collapsed schema: each domain tool's docstring is assembled at registration time from the registry — every callable `action` name, its description, required/optional params — so the agent reads one tool's docs to see the whole domain's action catalog.

### 4. Parameter validation: strict on path parameters, allow-listed on the query body
Two different rules, because the registry supports two different levels of confidence.

**Path parameters — strict.** The registry records them reliably, and the SDK method signature independently confirms them. A required path parameter that is missing, or a path parameter the action does not declare, is `invalid_argument` with no SDK call made.

**Query body — allow-listed, not registry-closed.** Every POST `input_parameters` entry says in its own `note` that it is "Not exhaustive" — the fields were harvested from `next_query` hints in observed responses, so a valid field is only listed if the controller happened to echo it. The GET file has no `input_parameters` at all. Rejecting any key the registry does not declare — as the first draft of spec.md required — would reject legitimate queries.

Instead the dispatcher validates the body against the union of: the action's declared `input_parameters`, plus the Prisma SD-WAN query grammar the SDK documents for every `/query` endpoint (`limit`, `dest_page`, `sort_params`, `sort_case_insensitive`, `getDeleted`, `total_count`, `aggregate`, `group_by`, `query_params`, `filter`, `retrieved_fields`, `next_query`). A key outside that union is `invalid_argument`. This still blocks a typo and still blocks anything shaped like a write payload; it does not block a valid filter the curation pass happened not to observe.

The exact grammar list is pinned in one constant with a comment pointing at the SDK docstring it came from, so it is reviewable in one place rather than inferred from behaviour.

### 5. Carrying forward hand-won knowledge: an override table, keyed by (domain, action)
A small `overrides.py` module holds a dict keyed by `(domain, action)` → optional `projection: set[str]`, `guidance: str`, `collection_key: str`, `summary: str`, and — only for the rare case that needs it — a full replacement handler. Migrating a current tool means writing its `(domain, action)` override entry rather than rewriting its logic:
- `get_elements`'s HA-audit caveat → `guidance` on `("sites_devices", "elements")`.
- `ELEMENT_KEEP_FIELDS`/`SITE_KEEP_FIELDS`/etc. → `projection` on the matching `(domain, action)`.
- `get_app_defs`'s "histogram when unfiltered" behavior → a full override handler (it changes response *shape* based on input, not just fields — the one clear case that needs a handler, not just metadata).

**Alternative considered:** encode guidance/projection directly inside the registry JSON files. Rejected for now — the registry is *curated input data*, periodically regenerated from SDK introspection; mixing hand-written prose and projections into it risks the next curation pass clobbering them. A separate, code-reviewed override module keeps curated data and hand-written judgment in different files with different change-review expectations.

### 6. The envelope's typed collection key, and naming the action
`FROZEN_ENVELOPE_KEYS` includes a `<typed_collection_key>` — `"sites"`, `"elements"`, and so on — that each hand tool picks by hand today. **The registry declares no such key.** The dispatcher resolves it as: the `collection_key` from the override table if one is declared, else the action name with a trailing `_query`/`_rquery` stripped, else `"items"`. Deriving it silently and inconsistently would put an unreviewable string into a frozen contract position, so the derivation is one function with one test.

The envelope's `tool` field would otherwise read `sites_devices` for all 15 of that domain's actions, leaving a consumer unable to tell one result from another. The dispatcher adds the resolved `action` to the envelope's `extra`. Additive, so it is safe under the additive-only response-contract rule.

### 7. Disposition of the current 39 tools
- **Registry-uncovered (11) — kept, untouched.** `get_element_status`, `get_events`, `get_alarms`, `get_flows`, `get_link_metrics`, `get_probe_metrics`, `get_topology`, `get_site_paths`, `get_basenet_topology`, `get_vpnlink_status`, `get_vpnlink_state`. Their SDK calls are in neither registry (see Context); the dispatcher cannot serve them. Retiring them would delete working troubleshooting capability. A test pins this list against the loaded registry so it shrinks only when curation actually covers a call.
- **Genuinely custom — kept.** `resolve.py`'s `find_*` and `resolve_path`, `config_gen.py`'s `generate_site_config`. Refactored to call the dispatcher's internal (non-MCP-exposed) fetch-and-format function instead of touching `registry.client.call_sdk` directly, so there is still exactly one path to any given SDK call.
- **Pass-through / enhanced (the remainder)** — e.g. `get_sites`, `get_machines`, `get_wan_interfaces`, `get_bgp_peers`: retired as standalone functions once the dispatcher plus an override entry covers them. `EXPECTED_SIGNATURES` drops these names and gains the domain-tool names.

Exact per-tool classification is an implementation-time audit (tasks.md 5.1), not decided line-by-line here.

## Risks / Trade-offs

- **[Risk] Collapsing named, individually-typed tools into 18 `(action, params)` dispatchers reduces per-argument type-checking an MCP client's UI could otherwise surface.** → Mitigation: registry-driven per-action parameter validation still runs server-side before dispatch (decision 4); rich per-domain docstrings substitute for per-tool schemas on the discovery side. Per-action schemas are not available at any price — see Non-Goals.
- **[Risk] The tool description for a domain like `sites_devices` (15 GET + 15 POST actions) becomes very large**, and every domain tool's description is sent to the agent on every `list_tools`. → Mitigation: the assembled docstring carries action name + one-line description + required params only; full parameter detail stays in `prisma://registry-audit`. Measure the total `list_tools` payload during implementation and treat a regression against today's 39 tools as a blocker.
- **[Risk — now largely discharged] A POST action's `read_only` classification could be wrong.** → All 106 were executed live against the tenant with a control/treatment `_etag` differential: zero writes detected (`verification/post-readonly-audit.md`). What remains uncovered: writes to objects with no `_etag` (a server-side saved search, an internal counter) — the controller audit log would be the detector, and it returns 403 for this service account. The startup safety gate stays a requirement because it defends future registry entries, which this one-time audit cannot.
- **[Risk] `verified_working: true` overstates confidence on GET.** 103 GET actions need a path parameter; only 31 were exercised with a real one. → Mitigation: the audit resource flags them (decision 2). They will fail at call time with an upstream error, which the existing structured-error path already handles — the cost is a wasted call, not a crash.
- **[Risk] `overrides.py` growing into a second registry that drifts from the JSON one.** → Mitigation: a test asserts every `(domain, action)` key in `overrides.py` still exists in the loaded registry.
- **[Trade-off] This is a breaking change to tool names/signatures**, and `webtester`'s catalogue heuristics need updating with it (proposal.md, Impact). Its gateway does not.

## Migration Plan

1. Add registry loader + two JSON Schemas + safety gate + `prisma://registry-audit` resource. **No tool registration yet** — verifiable in isolation, `test_tool_contract.py` untouched.
2. Build the generic dispatcher and register the 18 domain tools **alongside** the existing 39. `EXPECTED_SIGNATURES` must be updated in this same commit — the test asserts exact set equality (`test_tool_contract.py:59`), so it fails the instant a nineteenth name appears, not at step 4 as the first draft assumed.
3. Point `webtester` at the new domain tools; update its catalogue heuristics (category derivation, name-prefix scoring); compare output against the equivalent old tool for a sample of actions per domain.
4. Migrate `overrides.py` entries for every pass-through/enhanced tool; retire those tools; update `EXPECTED_SIGNATURES` again.
5. Refactor `resolve.py`/`config_gen.py` to call the dispatcher's internal function; confirm their tests still pass unchanged in behavior.
6. Remove the two root-level JSON files once `registry_data/` is the loaded source (`git mv`, not copy, so history follows).

**Rollback:** every step keeps the old tools working until step 4; rollback before step 4 is "stop, delete the new domain tools and revert `EXPECTED_SIGNATURES`." After step 4, rollback means restoring the retired functions from git history — acceptable given this is a pre-1.0 internal server with one consumer.

## Open Questions

Both of the original open questions are now answered; see `verification/`.

- ~~Does `fastmcp==3.4.4` support per-call dynamic JSON Schema?~~ **No**, and MCP has no such concept. Resolved in Non-Goals; no fast-follow to file.
- ~~Are all 106 POST actions side-effect-free?~~ **Yes, to the limit of what is observable from a read-only service account**: 106/106 green, zero `_etag`/`_updated_on_utc` drift across 99 collections against a control window. Audit log unavailable (403), so writes to non-`_etag` objects remain unprovable either way.

Still open:

- Should `overrides.py` guidance text be surfaced in every response (`extra` field), or only in the tool docstring (agent sees it once, not per-call, saving tokens)? Leaning docstring-only; confirm against how `get_elements`'s current HA caveat is actually consumed today.
- What is the total `list_tools` description payload for 18 registry-assembled docstrings versus today's 39 hand-written ones? **NEEDS MEASUREMENT** during step 2 — it is the main way this design could be worse than what it replaces.
