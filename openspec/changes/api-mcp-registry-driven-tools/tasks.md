## 0. Verification (done — evidence in `verification/`)

- [x] 0.1 Execute all 106 POST actions against the live tenant with a control/treatment `_etag` differential; confirm read-only — 106/106 green, 0 state changes (`verification/post-readonly-audit.md`)
- [x] 0.2 Measure registry structure, counts, SDK resolvability, and coverage against the current tools (`verification/registry-facts.md`)
- [x] 0.3 Answer design.md Open Question 1 — `fastmcp==3.4.4` has no per-action dynamic JSON Schema; the docstring approach is the design, not a placeholder

## 1. Registry as tracked, validated input

- [ ] 1.1 `git mv` `mcp_GET_domain_registry.json` → `api-mcp/prisma_sdwan_mcp/registry_data/get_domain_registry.json`, `mcp_POST_domain_registry.json` → `.../post_domain_registry.json`
- [ ] 1.2 Correct the GET file's `metadata.total_actions` in the same move — it says 202, which is the count of *unique* action names; there are 203 entries (`elementusers` is listed under two domains). The dispatcher registers entries, so 203 is the number that matters.
- [ ] 1.3 Write **two** JSON Schemas — `get_registry.schema.json`, `post_registry.schema.json` — sharing `$defs` for the common parts. The POST schema requires `sdk_call`; the GET schema must not (the GET file has none — its `name` is the SDK method). Neither may require `input_parameters` on GET, which has none.
- [ ] 1.4 Loader (`registry_loader.py`) validates each file against its own schema at import time using the pinned `jsonschema` dependency; counts actions itself rather than trusting `metadata.total_actions`
- [ ] 1.5 Loader raises with file name + failed constraint on schema violation (blocks server startup)
- [ ] 1.6 Safety-gate filtering: keep an action only if its `safety` block asserts `read_only: true`, `destructive: false`, `verified_working: true` — **testing those three keys, never exact object equality** (the GET file's `safety` carries a fourth key, `verified_using_a_real_chained_id`; exact equality excludes all 203 GET actions) — AND its SDK call resolves on the running SDK (`sdk_call` for POST, `name` for GET). Record every exclusion with a reason.
- [ ] 1.7 Loader asserts no action name appears twice within a domain across the two files (true today; the assertion is what keeps it true after the next curation pass)
- [ ] 1.8 Unit tests: each schema-valid file loads; a malformed file blocks startup with a clear error; an entry failing the safety keys is excluded not exposed; an entry with an unresolvable SDK call is excluded not exposed; a GET entry with its extra fourth safety key is **not** excluded; a duplicate action name within a domain fails loudly

## 2. Registry audit visibility

- [ ] 2.1 Add `prisma://registry-audit` MCP resource reporting, per domain: callable actions, excluded actions with reasons, and — flagged but still callable — GET actions that require a path parameter while carrying `verified_using_a_real_chained_id: false` (~72 entries whose `verified_working: true` was never exercised with a real ID)
- [ ] 2.2 Test: audit resource output matches a fixture registry with a mix of valid, excluded, and flagged-unverified entries

## 3. Generic domain dispatcher

- [ ] 3.1 Implement action → SDK-call resolution: given a domain and action, return the callable `sdk.get.<name>` or `sdk.post.<sdk_call>`, routing on which registry the entry came from
- [ ] 3.2 Implement path-parameter validation (strict): required path parameter missing, or a path parameter the action does not declare → `invalid_argument`, no SDK call made
- [ ] 3.3 Implement query-body validation (allow-listed, **not** registry-closed): accept the action's declared `input_parameters` plus the pinned Prisma SD-WAN query grammar (`limit`, `dest_page`, `sort_params`, `sort_case_insensitive`, `getDeleted`, `total_count`, `aggregate`, `group_by`, `query_params`, `filter`, `retrieved_fields`, `next_query`); anything else → `invalid_argument`. Registry `input_parameters` says "Not exhaustive" in every entry's own `note`, so it cannot be a closed allow-list. Pin the grammar in one constant with a comment naming the SDK docstring it came from.
- [ ] 3.4 Implement the typed collection key resolution: override table `collection_key` → else action name with trailing `_query`/`_rquery` stripped → else `"items"`. One function, one test — it lands in a `FROZEN_ENVELOPE_KEYS` position.
- [ ] 3.5 Implement the dispatch-and-format path: resolve action → validate params → call SDK via existing `PrismaSDWANClient` → route result through `formatting.collection_response`/`single_response`, adding the resolved `action` to the envelope `extra` so a consumer can tell one `sites_devices` result from another
- [ ] 3.6 Register one `@mcp.tool` per domain — **18 tools, not 33** (all 15 POST domain names already exist in the GET registry; one tool per domain carries both its GET and POST actions) — with `action`, `params`, `cursor`, `limit` arguments and mandatory `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint` annotations per `openspec/project.md`
- [ ] 3.7 Assemble each domain tool's docstring at registration time from the registry: callable action names, one-line descriptions, required params. Full parameter detail stays in `prisma://registry-audit`, not the docstring.
- [ ] 3.8 **Measure** the total `list_tools` description payload for the 18 registry-assembled docstrings against today's 39 hand-written ones; a regression is a blocker, not a note (design.md Open Question)
- [ ] 3.9 Tests: valid action + valid params dispatches and returns an enveloped response carrying the action; unknown action returns `invalid_argument` listing valid actions and makes no SDK call; missing required path param and undeclared path param both return `invalid_argument` and make no SDK call; a body key inside the query grammar but absent from `input_parameters` is **accepted**; a body key outside both is rejected; upstream SDK error surfaces as the existing structured error, not a raw exception

## 4. Overrides — carry forward hand-won knowledge

- [ ] 4.1 Add `overrides.py`: a table keyed by `(domain, action)` → optional `projection: set[str]`, `guidance: str`, `collection_key: str`, `summary: str`, optional full handler
- [ ] 4.2 Wire the dispatcher to consult `overrides.py` before formatting: apply projection and guidance through the same formatting functions, no second response path
- [ ] 4.3 Test: action with a projection override returns only projected fields and signals `projected_fields`; action with a guidance override surfaces that guidance in its documentation
- [ ] 4.4 Add the sync-check test: every `(domain, action)` key in `overrides.py` exists and is callable in the currently loaded registry; fails naming the orphaned entry if not

## 5. Audit and migrate the current 39 tools

- [ ] 5.1 Classify each of the 39 tools into: **registry-uncovered** (keep as-is), **genuinely custom** (keep, refactor), or **pass-through/enhanced** (replace with dispatcher + override) — record the classification as a table in this change's notes
- [ ] 5.2 Add the registry-coverage test pinning the 11 registry-uncovered tools — `get_element_status`, `get_events`, `get_alarms`, `get_flows`, `get_link_metrics`, `get_probe_metrics`, `get_topology`, `get_site_paths`, `get_basenet_topology`, `get_vpnlink_status`, `get_vpnlink_state` — and the 9 SDK calls behind them (`element_status`, `vpnlinks_state`, `vpnlinks_status`, `events_query`, `monitor_flows`, `monitor_metrics`, `monitor_lqm_point_metrics`, `monitor_probe_point_metrics`, `topology`). The test asserts each call is still absent from the loaded registry, so the list shrinks deliberately when curation covers a call — and fails loudly if someone retires a tool the dispatcher cannot serve.
- [ ] 5.3 For every pass-through/enhanced tool, add its `(domain, action)` override entry (`ELEMENT_KEEP_FIELDS`, `SITE_KEEP_FIELDS`, `MACHINE_KEEP_FIELDS`, `WAN_INTERFACE_KEEP_FIELDS`, the `get_elements` HA-audit guidance, the `get_app_defs` unfiltered-histogram handler, etc.)
- [ ] 5.4 Refactor `resolve.py` and `config_gen.py` to call the dispatcher's internal fetch-and-format function instead of `registry.client.call_sdk`/`call_sdk_post` directly; confirm existing behavior and tests are unchanged
- [ ] 5.5 Remove the now-redundant pass-through/enhanced tool functions from `tools/*.py` — **only** those whose SDK call the loaded registry actually covers
- [ ] 5.6 Update `resources.py`/`prompts.py` for any resource that delegated to a removed tool function (`prisma://sites`, `prisma://topology`, `prisma://policy-sets`, `prisma://site/{site_id}/elements`)

## 6. Contract and consumer verification

- [ ] 6.1 Update `EXPECTED_SIGNATURES` **in the same commit as the first dispatcher registration** (migration step 2), not at retirement time — `test_tool_contract.py:59` asserts exact set equality, so it fails the moment a nineteenth tool name appears. Update it again when tools are retired.
- [ ] 6.2 Update `webtester` for the new tool shape: `app/mcp_gateway.py:76` derives a tool's category from `tool.fn.__module__` (18 dispatcher tools would collapse into one category) and `app/catalog.py` scores against hardcoded category names (`:61`, `:88`) and `get_`/`list_`/`query_` name prefixes (`:92`), dropping anything scoring ≤ 0 from ranked pages (`:80`, `rank_tools`). The gateway itself is genuinely dynamic and needs nothing.
- [ ] 6.3 Run `webtester` against the new server; confirm tool discovery works and spot-check a sample of domains/actions through its UI
- [ ] 6.4 Full test suite (`api-mcp/tests/`) green; confirm envelope shape (`truncated`, `total_count`, `returned_count`, `next_cursor`, error codes) is consistent with the ratified/in-flight `response-contract-and-truncation-policy` spec

## 7. Cleanup

- [ ] 7.1 Confirm no loose registry JSON remains at repo root (fully moved via `git mv` in 1.1, not copied)
- [ ] 7.2 Update `api-mcp/README.md` and the root `README.md`'s tool-count/description table to reflect the new tool set and count
- [ ] 7.3 Open the follow-up change to curate the metrics/flows/topology/events surface (the 9 uncovered SDK calls) into the registry format, so 5.2's pinned list can shrink
