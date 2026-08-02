## Context

`api-mcp` exposes ~39 read-only tools. Every one returns a **JSON string**, not a
dict. All collection responses funnel through `formatting.build_envelope`
(formatting.py:432-503); all single-record responses through
`formatting.single_response` (formatting.py:583-610); all errors through
`formatting.structured_error` / `error_json` (formatting.py:236-259).

The current collection envelope, from `formatting._envelope`
(formatting.py:356-387):

```json
{
  "tool": "get_sites",
  "summary": "Collection retrieved; 12 item(s) withheld; use next_cursor to continue",
  "sites": [ ... ],
  "truncated": true,
  "total_count": 40,
  "returned_count": 28,
  "retrieved_at": "2026-08-02T09:14:03Z",
  "next_cursor": "eyJ2IjoxLCJvZmZzZXQiOjI4fQ",
  "projected_fields": ["admin_state", "city", "..."]
}
```

Note `retrieved_at` (formatting.py:379, 604) and `projected_fields`
(formatting.py:542, 570) are **already present** — `_now_iso`
(formatting.py:14-16) deliberately uses a fixed-width format so the timestamp never
changes the envelope's byte size mid-packing.

The error envelope, from `structured_error` (formatting.py:236-250):

```json
{"code": "invalid_limit", "message": "limit must be at least 1", "tool": "get_events", "retryable": false, "status_code": 400}
```

Errors are a **different top-level shape** from success responses, not an `errors`
key inside one.

## Goals / Non-Goals

**Goals**
- Write down the contract consumers already depend on, so it can be changed
  deliberately rather than accidentally.
- Make every truncation both visible and (where possible) recoverable.
- Close the error-code set and give `retryable` a defined meaning.
- Define additive vs breaking, and a version consumers can detect.

**Non-Goals**
- Redesigning the envelope. See Decision 1.
- Removing byte budgeting. It is what keeps this server usable in a
  context-constrained client.
- Specifying *what* a consumer should conclude from any field. Tools return facts.
- Changing `webtester`. If a contract change requires touching
  `webtester/app/normalizer.py`, that is the signal it is a breaking change.

---

## Decision 1 — Keep the envelope; extend it additively

**Rejected alternative:** replace the envelope with
`{data, source, scope, warnings, errors}`.

**Rejected because** the cost is total and the benefit is nearly nil.

*Cost.* The rename touches all ~39 tools (every `collection_response` /
`single_response` / `build_envelope` call site), both api-mcp test suites, and
`webtester`. `webtester/app/normalizer.py:9-12` hunts for the payload list by
scanning a fixed key tuple that includes `"items"`, `"data"`, `"sites"`,
`"elements"`, `"events"` — a rename to `data` would *accidentally* keep working
there while silently changing which records `flatten_records` selects, because
`data` is second in `LIST_KEYS` and would shadow the typed key. That is worse than
an outright break: it is a break that passes smoke tests.

*Benefit.* Auditing the proposed keys against what exists:

| Proposed key | Already covered by | Verdict |
|---|---|---|
| `data` | the typed collection key (`sites`, `events`, `flows`, …) | rename only; the typed key is *more* informative |
| `source` | `tool` (formatting.py:374) | rename only |
| `scope` | per-tool `extra` — e.g. `window` (monitoring.py:787, 843), `site_present` (network.py:625) | already there, tool-shaped |
| `warnings` | `summary` text + boolean flags (`truncated`, `capped`, `digest_complete`) | present, but *unstructured* — see Decision 1b |
| `errors` | top-level error object, or `error` inside a partial envelope (formatting.py:385-386) | present |

The only content genuinely missing was a retrieval timestamp, and that has already
landed as `retrieved_at`.

**Decision.** The envelope keys `tool`, `summary`, `<collection_key>`, `truncated`,
`total_count`, `returned_count`, `retrieved_at`, and optional `next_cursor` are
**frozen**. New information is added as new keys, never by renaming an existing one.

**Decision 1b — structured warnings.** The one real gap: today a caller learns
about a cap by *string-matching the summary* ("returning the first 50 — refine your
search", resolve.py:66) or by knowing which per-tool boolean to look for
(`capped`, `leg_resolution_capped`, `digest_complete`). String-matching a
human-readable summary is not a contract. Add one additive key:

```json
"limits_applied": [
  {"limit": "find_cap", "kind": "hard", "value": 50, "recoverable": false,
   "reason": "candidate list is capped; refine the search term"}
]
```

Absent when no cap fired. `summary` keeps its prose for humans; `limits_applied` is
the machine-readable form. This is purely additive.

---

## Decision 2 — No blanket raw; opt-in `raw` per call

**Rejected alternative:** return `{normalized, raw, metadata}` on every response.

**The tension is arithmetic, not aesthetic.** `build_envelope` packs items into a
**fixed byte budget** by re-serializing the whole candidate envelope after each item
and stopping when it exceeds the budget (formatting.py:456-475). Bytes per item and
items per response are therefore in strict inverse proportion. Shipping the raw
record alongside the projected one roughly doubles-to-triples per-item size, so at
the default `PRISMA_MCP_MAX_RESPONSE_BYTES = 40960` (config.py:9) the same call
returns **a third to a half as many items and truncates far sooner**. "Expose
everything" and "return complete result sets" cannot both be maximized. A blanket
raw payload trades a complete answer for a more detailed fragment of one — the wrong
trade for an evidence platform, where a missing record is a missed incident and a
missing field is usually a field nobody needed.

**Decision.**
1. **Projections must be complete and correct** for their purpose (Decision 3).
   Getting the field-set right is the primary answer to "the data I need is missing".
2. **`raw: bool = False`** is added only to tools where the raw record demonstrably
   matters. `get_flows` already has it (monitoring.py:703, 755, 778-788) and is the
   precedent: `raw=False` returns a digest, `raw=True` returns projected individual
   records with `page`/`limit`. `get_link_metrics` has the same flag
   (monitoring.py:874, 886-888).
3. A `raw=True` response is **still budgeted and still paginated**. `raw` changes
   what is in an item, never whether the envelope obeys its budget.
4. Adding `raw` to a tool is additive (a new optional argument with a
   backward-compatible default) — but it changes that tool's entry in
   `test_tool_contract.py:EXPECTED_SIGNATURES`, which must be updated deliberately.

**Not decided here:** exactly which tools gain `raw`. That is per-tool and belongs
with the tool's own change.

---

## Decision 3 — Projection policy

Projections are the `*_KEEP_FIELDS` frozensets (formatting.py:19-173) applied by
`project_record` (formatting.py:284-295).

Two properties of the current implementation matter:

- `project_record` **preserves error keys unconditionally** — `code`, `error`,
  `message`, `status_code` survive projection even when absent from the field set
  (formatting.py:288-294). An upstream per-record error is never filtered away.
  Keep this.
- `_clean_response` drops `None` values and `_`-prefixed keys
  (formatting.py:176-186). So a field in the KEEP set that the controller returned
  as `null` is indistinguishable from one the controller never sent — and both are
  indistinguishable from one the projection excluded.

`projected_fields` (formatting.py:542, 570) already resolves the third case: a
consumer that sees `projected_fields` knows exactly which keys *could* have
appeared, so any key not in that list was filtered, and any key in that list but
absent from an item was null-or-missing upstream. The remaining null-vs-absent
ambiguity is left unresolved deliberately: distinguishing them costs a per-field
sentinel on every record — the same byte-budget tax as Decision 2 — to answer a
question no consumer has asked. Revisit if one does.

**Decision.**
1. A projection exists to keep a large collection inside the byte budget. A tool
   whose records are already small **should not have one** — `project_record`
   passes records through unchanged when `fields is None` (formatting.py:285-286),
   and `single_response` never projects at all (formatting.py:583-610), which is why
   `get_elements(element_id=...)` returns the full record while `get_elements()`
   returns projected ones (inventory.py:112-116).
2. A field belongs in a KEEP set if it is an **identifier**, a **state/health
   signal**, a **correlation key**, or a **join key to another tool**. The
   `EVENT_KEEP_FIELDS` comment (formatting.py:108) already names this rule for
   `code`: "the primary correlation key".
3. **Projections are verified against real controller responses, not guessed.** A
   field name that never appears upstream is dead weight that silently promises data
   the tool will never return. Verification means: capture a live response, diff its
   keys against the KEEP set, and record the diff. `FLOW_KEEP_FIELDS`
   (formatting.py:120-173) carries both `source_ip`/`src_ip` and
   `destination_ip`/`dst_ip`; `_flow_digest_response` reads `src_ip` first and falls
   back to `source_ip` (monitoring.py:813-814). One of each pair is dead. Which one
   is **NEEDS LIVE VERIFICATION**.
4. **Omission is signalled** by `projected_fields`, emitted whenever and only
   whenever a projection was applied (asserted by
   `test_projected_fields_reported_only_when_a_projection_is_applied`,
   test_formatting.py:103).
5. **A new controller field reaches consumers without a code change** through the
   `raw` escape hatch on tools that have one. Where no `raw` flag exists, a new
   upstream field requires a KEEP-set addition — which is additive and safe. This is
   the accepted cost of projecting at all.

---

## Decision 4 — Truncation and limits policy

Every cap is classified as exactly one of:

- **ENV-TUNABLE** — the deployer can change it via environment variable.
- **PAGINATED** — the caller can retrieve everything by repeating the call with a
  cursor/page argument.
- **HARD** — neither. The cap cannot be moved or paged past by the caller.

A cap may be both ENV-TUNABLE and PAGINATED (the byte budget is).

**Rule: every cap must be signalled in the response, and every HARD cap must carry a
documented reason for being unrecoverable.** A cap that silently drops data is a
defect regardless of classification.

### Inventory

| Cap | Location | Class | Signalled? | Recoverable? |
|---|---|---|---|---|
| `PRISMA_MCP_MAX_RESPONSE_BYTES` = 40960 | config.py:9, 24-32 | ENV-TUNABLE + PAGINATED | `truncated`, `total_count`, `returned_count`, `next_cursor` (formatting.py:367-387) | yes — `next_cursor` |
| `FIND_CAP` = 50 | resolve.py:9, 54-55 | HARD | `capped`, `match_count`, `refine_hint` (resolve.py:67-75) | **no** |
| `LEG_RESOLUTION_CAP` = 100 | network.py:18, 580-582 | HARD | `leg_resolution_capped` (network.py:628) | **no** |
| events/alarms `limit`, `last` ≤ 100 | monitoring.py:483, 553 | HARD | `summary` says "up to N" (monitoring.py:502, 572) | partly — windowable via `start_time`/`end_time` |
| `hours` ≤ 168 | monitoring.py:112-113 | HARD | rejected as `invalid_argument` | yes — explicit `start_time`/`end_time` bypasses it (monitoring.py:709-712) |
| flow digest over ≤ 1000 flows | monitoring.py:755 | HARD | `digest_complete`, `digest_sample_size`, `digest_sample_limit`, `digest_more_pages` (monitoring.py:836-852) | partly — `raw=True` + `page` |
| `top_talkers[:10]` | monitoring.py:828 | HARD | **not signalled** | no |
| identifying values → 128 chars | formatting.py:340-343, 337 | HARD | only inside an `item_too_large` error | no |
| `MAX_ATTEMPTS` = 3, `MAX_RETRY_WALL_SECONDS` = 8.0 | client.py:17-18, 151-177 | HARD | `retry_count`, `elapsed_seconds`, `status_code` in the error (client.py:163-176) | yes — caller retries |
| `DEFAULT_CONNECT_TIMEOUT` = 10.0 | cli-mcp executor.py:11 | HARD | `error.type: "connection"` | yes — caller retries |
| `DEFAULT_READ_TIMEOUT` = 300.0 | cli-mcp executor.py:18 | HARD | `status: "error"`, never a truncated success (executor.py:12-17) | yes — caller retries |
| `MAX_PAGINATION_PAGES` = 100 | cli-mcp executor.py:19, 188-190 | HARD | raises `IONCommandError` → per-command `status: "error"` | no |
| `MAX_ERROR_LENGTH` = 1000 | cli-mcp executor.py:20, 133 | HARD | **not signalled** | no |

### Required outcomes

**`FIND_CAP` → PAGINATED.** `_find_response` already accepts `cursor` and `limit`
and passes them to `build_envelope` (resolve.py:78-86), which paginates correctly.
The `matches[:FIND_CAP]` slice at resolve.py:55 happens *before* that and defeats it:
`total` is the true match count but `selected` is at most 50, so `build_envelope`'s
`next_cursor` can never walk past 50. The cap is redundant with byte budgeting —
`build_envelope` already stops when the bytes run out. Removing the slice is the fix.

**`LEG_RESOLUTION_CAP` → resumable.** This one is *not* redundant: it guards an N+1
of sequential HTTP calls — one `vpnlinks_status` GET per leg inside a nested loop
(network.py:584-586). Removing it would let one call fan out unboundedly. The cap
must stay; what must change is that it becomes **resumable** — the caller can obtain
legs beyond the first 100 by continuing from where the previous call stopped. Which
form that takes (a leg-offset argument, or a cursor that encodes the resolution
position) is an implementation choice; the requirement is that no leg is permanently
unreachable.

**`top_talkers[:10]` and `MAX_ERROR_LENGTH` → signalled.** Both currently drop data
with no indication. Both may remain HARD, but must say so:
`top_talkers_limit: 10` alongside the ranking, and `error_truncated: true` when
`_safe_error_message` clipped.

**Identifying-value 128-char truncation may remain unsignalled.** It applies only
inside `_oversized_item_response` (formatting.py:390-429), a last-resort path whose
entire contract is already "only identifying fields are returned" — a truncated
128-char identifier is strictly more information than the alternative, which is
nothing. Documented as an accepted exception.

### The verifiable form of this policy

The policy is a test, not a paragraph. A central declaration —

```python
LIMITS = {
    "response_bytes": Limit(kind="env_tunable_paginated", recovery="next_cursor"),
    "leg_resolution": Limit(kind="hard", recovery="resume_offset"),
    "top_talkers":    Limit(kind="hard", recovery=None, reason="ranking, not a collection"),
    ...
}
```

— lets one test assert that every entry is either recoverable or carries a `reason`,
and per-tool tests assert that a response which hit a cap names it in
`limits_applied`. Without a central declaration the policy is unenforceable and will
rot the first time someone adds a slice.

---

## Decision 5 — Closed error-code set

Codes in the source today: `invalid_argument` (44 sites), `invalid_limit` (9),
`upstream_error` (4), `invalid_cursor` (formatting.py:328), `invalid_budget`
(formatting.py:446), `internal_error` (formatting.py:264),
`response_budget_exceeded` (formatting.py:277), `response_budget_too_small`
(formatting.py:503), `item_too_large` (formatting.py:400), `not_found`
(network.py:420, 492), plus two config-gen-only codes `invalid_filename` and
`schema_not_found` (config_gen.py:84, 87).

`retryable` today is computed *purely* from HTTP status: `status_code == 429 or 500
<= status_code <= 599` (formatting.py:246). That is correct as far as it goes but
means a client-side `invalid_budget` and a genuine upstream 503 differ only by a
number the caller has to interpret.

**Decision.** `code` is drawn from a closed set (enumerated in
`specs/response-contract/spec.md`). `retryable` means exactly: *the identical call,
repeated later with no argument change, may succeed.* It is therefore
- always `false` for the `invalid_*` family and `not_found` — nothing changes by
  waiting;
- always `true` for `rate_limited`;
- status-derived for `upstream_error`, as today.

**New codes.** Each exists because a real situation is currently mislabelled:

| Code | Replaces | Why it is needed |
|---|---|---|
| `rate_limited` | `upstream_error` with `status_code: 429` | The one error whose correct handling (back off, retry) is unambiguous. `client.py:151` already special-cases 429 internally; the caller never learns it was rate limiting. |
| `historical_data_unavailable` | `upstream_error`, or an empty success | An empty metrics window because the controller has aged the data out is a *different fact* from "nothing happened". Today both look like an empty collection. |
| `unresolved_relationship` | a synthetic `resolved: false` record | `resolve_path` already returns `{"resolved": false, "reason": ...}` (resolve.py:668-675) — a fact-shaped non-answer. Promoting it to a code makes it uniform across tools. |
| `tenant_or_region_mismatch` | `upstream_error` 403/404 | The SDK derives the region at login and `PAN_REGION` is advisory only (client.py:32-37). An ID from the wrong tenant returns a bare 404 that reads as "does not exist". |
| `partial_response` | silent partial success | `find_policy_set` already collects `family_errors` and returns the surviving families (resolve.py:477-491); `get_basenet_topology` embeds per-leg errors in entries (network.py:588-594). Both are partial responses with no code saying so. |

`partial_response` occupies the existing `error` **inside** a success envelope
(formatting.py:385-386): the payload is real and usable, and the error qualifies it.
It is not a top-level error response.

---

## Decision 6 — Versioning and compatibility

**Additive (safe), no version bump:**
- a new top-level envelope key;
- a new field in a `*_KEEP_FIELDS` set;
- a new key inside `extra`;
- a new **optional** tool argument with a backward-compatible default;
- a new tool, resource, or prompt;
- a new error code (consumers must treat unknown codes as opaque — this is a
  requirement on consumers, stated in the spec).

**Breaking (version bump + migration):**
- renaming or removing any frozen envelope key;
- renaming or removing a tool or a tool argument;
- changing a field's type or units;
- narrowing a `*_KEEP_FIELDS` set (a consumer may be reading the removed field);
- making an optional argument required;
- changing what an existing error code means.

Note the asymmetry: *widening* a projection is additive, *narrowing* it is breaking.

**If a breaking change is ever unavoidable**, it ships as a **new tool name**
alongside the old one (`get_flows_v2`), with the old tool retained and its docstring
marking it superseded, for at least one release. Reason: MCP has no per-tool version
negotiation. A client discovers tools by name; a renamed field inside an existing
name is undetectable until it breaks at runtime, whereas a new name is discovered
correctly by every client automatically. There is no in-place breaking change.

**Version discovery.** A `prisma://contract` MCP resource
(`api-mcp/prisma_sdwan_mcp/resources.py`) reports `contract_version` (semver: minor
for additive, major for breaking), the frozen envelope keys, the closed error-code
set, and the limits table. A resource rather than an envelope key because it costs
zero bytes per response and it is exactly what MCP Resources are for — and
`resources.py` already establishes the pattern of delegating to the same code path
the tools use, so the document cannot drift from enforcement (the same trick
`cli-mcp`'s `prisma-cli://policy` resource uses, server.py:144-176).

**Prompts are not a boundary violation.** `api-mcp/prisma_sdwan_mcp/prompts.py` and
`cli-mcp`'s `troubleshoot_ion` (server.py:179-212) ship canned workflows. This is
legitimate: MCP Prompts are **client-invoked and opt-in**. A consumer that never
lists prompts is unaffected; a consumer that does gets a starting point it is free to
ignore. They constrain nothing and no tool result depends on them. Note that
`troubleshoot_ion` explicitly disclaims ownership of the reasoning: "Command
selection itself … is the calling agent's job … this server enforces safety, it does
not pick commands" (server.py:209-212).

A **tool** returning a diagnosis would be the violation — because a tool result is
not opt-in. It arrives in the consumer's context whether wanted or not, and a
consumer that disagrees with the conclusion has no way to get the underlying facts
without it. `summary` is the line: it may state *what was returned* ("12 item(s)
withheld", formatting.py:371), never *what it means* ("the WAN link is degraded").

---

## Risks / Trade-offs

- **`limits_applied` is a second way to say what booleans already say.** Accepted:
  the booleans stay (removing them is breaking), and the new key exists so consumers
  stop string-matching `summary`. It is duplication with a purpose and a deprecation
  path.
- **Removing `FIND_CAP` makes `find_*` responses cursor-walk longer lists.** That is
  the intended behaviour — `build_envelope` still bounds each page. The risk is a
  consumer that ignores `next_cursor` and now silently sees a *different* first page.
  Low: the first page's contents do not change, only what follows it.
- **Adding error codes changes what a consumer sees for an unchanged upstream
  condition.** A consumer branching on `code == "upstream_error"` will stop matching
  a 429. Mitigated by the requirement that consumers treat unknown codes as opaque
  and fall back on `retryable`.
- **`resolve_path` may not be answerable as specified.** It fetches
  `waninterfaces(site_id)` and the full anynet topology and matches `path_id`
  by string equality (resolve.py:600-666). Whether every `path_id` returned by
  `get_link_metrics` / `get_flows` is resolvable this way — and whether path-quality
  is **NEEDS LIVE VERIFICATION**. Path-quality / SLA thresholds are **out of scope**
  by owner decision 2026-08-02; a live capture on that date found no threshold field
  exposed anywhere, so no tool will be built to return one.
- **Operational HA role is NOT exposed — RESOLVED 2026-08-02 by live capture.**
  Findings, from a 49-element tenant with 21 two-element sites and 40 elements
  carrying `spoke_ha_config`:
  - Each HA member is a separate element with its own `element_id`. Members are
    linked by `spoke_ha_config.cluster_id`; the **top-level `cluster_id` is null on
    every element**, so it is the nested value that joins a pair.
  - Top-level `role` is `SPOKE` — device role, unrelated to HA.
  - `element_status` contains **no HA field of any kind**. The controller does not
    report which member is active.
  - `spoke_ha_config.priority` MUST NOT be used to infer the active member. Entries
    carry `track.interfaces[].reduce_priority`, which subtracts from priority at
    runtime when a tracked interface drops (observed values 8 and 150 — the latter
    large enough to invert a pair). The controller holds the base value; the device
    computes the effective one. Inferring from the base is therefore wrong precisely
    during the failure being investigated.
  - `get_elements`' docstring, which instructed callers to do exactly that, has been
    corrected.
  - Live active member is obtainable only from device CLI. Any future HA tool in
    api-mcp can report configuration and MUST label it as such.
  - **Open lead:** events carry `element_cluster_roles`, now retained. If it records
    HA role at event time it is the only API-side signal of operational role. Not yet
    inspected.
