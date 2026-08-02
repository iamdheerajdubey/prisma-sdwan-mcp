## Why

Every consumer of api-mcp — a troubleshooting agent, a scripted client, the
`webtester` harness, two pytest suites — depends on the shape of what tools
return. That shape is currently *emergent*: it is whatever
`api-mcp/prisma_sdwan_mcp/formatting.py` happens to produce, and it is enforced
only by `api-mcp/tests/test_tool_contract.py` (which pins argument signatures, not
response bodies) and by scattered assertions in
`api-mcp/tests/test_formatting.py`.

Four consequences, all real today:

1. **Nobody can tell "the controller did not send this field" from "we filtered it
   out."** `formatting.project_record` (formatting.py:284-295) builds
   `{key: record.get(key) for key in fields}` and then `_clean_response`
   (formatting.py:176-186) drops every `None`. Both a missing upstream field and a
   deliberately-excluded one vanish identically.
2. **Caps are inconsistent about recoverability.** `PRISMA_MCP_MAX_RESPONSE_BYTES`
   truncation is signalled and resumable via `next_cursor`
   (formatting.py:367-387). `FIND_CAP = 50` (tools/resolve.py:9,54-55) is signalled
   (`capped: true`) but **not recoverable** — matches 51+ are unreachable by any
   argument the caller can pass. `LEG_RESOLUTION_CAP = 100`
   (tools/network.py:18,580-582) is the same. There is no rule saying which is
   acceptable.
3. **The error code set is undeclared and incomplete.** Twelve codes exist in the
   source; none is documented as a closed set, and categories the platform
   demonstrably needs (rate limiting, historical-data gaps, partial responses) are
   collapsed into `upstream_error`.
4. **There is no contract version.** A consumer cannot detect which shape it is
   talking to, so no compatible evolution path exists.

## What Changes

This change writes the contract down as testable requirements. It is
**specification-first**: most of the behaviour already exists and is being ratified;
a small number of additive fields are new.

- **Ratify the existing envelope** as the contract. Explicitly reject the proposed
  `{data, source, scope, warnings, errors}` rename.
- **Reject blanket `{normalized, raw, metadata}`**; specify an opt-in per-call
  `raw` flag on the few tools where the raw record matters, following the existing
  `get_flows(raw=...)` precedent (tools/monitoring.py:703, 755, 778-788).
- **Specify field-projection policy**: how projections are chosen, that they are
  verified against live controller responses rather than guessed, that omission is
  signalled via the already-emitted `projected_fields` key
  (formatting.py:542, 570), and that a new controller field reaches consumers
  without a code change via the `raw` escape hatch.
- **Classify every cap** as ENV-TUNABLE, HARD, or PAGINATED, and require that each
  is both *signalled* in the response and *recoverable* — or documented as
  unrecoverable with a stated reason.
- **Close the error-code set**, define `retryable` semantics, and add five missing
  categories: `historical_data_unavailable`, `rate_limited`,
  `unresolved_relationship`, `partial_response`.
- **Define additive vs breaking**, the (deliberately painful) path for shipping a
  breaking change, and a `contract_version` discovery mechanism.

## Capabilities

### New Capabilities
- `response-contract`: the envelope shape, projection policy, error model, and
  compatibility rules that every api-mcp tool response conforms to.
- `truncation-policy`: the classification, signalling, and recoverability rules
  every response-limiting cap in both servers must satisfy.

### Modified Capabilities
None — no prior specs exist.

## Impact

**Code**
- `api-mcp/prisma_sdwan_mcp/formatting.py` — envelope, projection, error
  construction. Additive fields only.
- `api-mcp/prisma_sdwan_mcp/tools/resolve.py` — `FIND_CAP` must become paginated or
  be documented unrecoverable.
- `api-mcp/prisma_sdwan_mcp/tools/network.py` — `LEG_RESOLUTION_CAP` must become
  resumable or documented unrecoverable.
- `api-mcp/prisma_sdwan_mcp/tools/monitoring.py` — flow-digest completeness
  signalling; `hours`/`limit`/`last` caps.
- `api-mcp/prisma_sdwan_mcp/client.py` — retry caps must surface as `rate_limited`
  where the status was 429.
- `cli-mcp/prisma_sdwan_cli_mcp/executor.py` — the CLI-side caps
  (`MAX_PAGINATION_PAGES`, `MAX_ERROR_LENGTH`, timeouts) fall under the same policy.

**Tests**
- `api-mcp/tests/test_formatting.py`, `api-mcp/tests/test_tool_contract.py` — new
  assertions per the spec's scenarios.

**Consumers**
- `webtester/app/normalizer.py` and `webtester/app/mcp_gateway.py` need **no
  change**. That is the point of the additive path.

**Concurrent work.** Several caps are being fixed right now by other agents
(`FIND_CAP` → cursor pagination, resumable leg resolution, flow-digest completeness
signalling, a cli-mcp output cap). This document is the policy those fixes must
conform to, not a competing implementation plan.
