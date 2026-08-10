## Why

`search_capabilities` matches an AI's query against a concatenated blob of human prose (`description`, `url_template`, `sdk_call`) using a single case-insensitive Python substring test. This is a human-text search primitive placed on an interface that only machines consume, and it fails on the queries an AI naturally produces:

| Query | Hits |
|---|---|
| `community` | 1 |
| `community list` | 1 |
| `bgp` | 21 |
| `bgp community` | **0** |
| `show me bgp peers` | **0** |

Multi-word queries fail because the needle must appear as one contiguous run of characters. The failure is silent and indistinguishable from "this capability does not exist," so the AI concludes the API is unsupported and stops — while `routing_bgp_ospf.routing_ipcommunitylists` sits in the catalog.

The catalog does not need to be searched. It is 316 fixed entries across 19 domains, largest domain 43 entries, and the complete listing is ~5,800 tokens. An AI can read the whole thing. Ranking, scoring, and fuzzy matching solve a scale problem this data does not have.

## What Changes

- **BREAKING**: Remove the `search` (free-text) and `detail` parameters from `search_capabilities`. Substring matching against descriptions is deleted, not fixed.
- **BREAKING**: Rename the tool `search_capabilities` → `list_capabilities`. The name is the instruction; "search" is what steers the model into the broken path.
- Add deterministic two-level browse:
  - `list_capabilities()` — returns all 19 domains with action counts and a machine-readable drill-in instruction.
  - `list_capabilities(domain=...)` — returns every action in that domain. No truncation: the largest domain is 43 entries, below the 100 cap.
- Every listed action always carries the fields required to execute it: `action_id`, `http_method`, `path_parameters` (with `required` flags), `body_schema`, `requires_live_test`. The current `detail="summary"` default strips `path_parameters`, forcing a second round trip before the AI can call `read_capability`.
- Keep `domain` and `method` filters. Both are exact-match against enumerated values — machine predicates, not text guessing.
- Remove `CapabilityCatalog.search()`'s haystack construction and substring branch; replace with exact filtering.

## Capabilities

### New Capabilities
- `capability-discovery`: How an AI enumerates and selects registry actions that no semantic tool covers — domain enumeration, action listing, guaranteed-complete results, and the execution contract handed to `read_capability`.

### Modified Capabilities
<!-- None. No specs exist in openspec/specs/ yet; capability-discovery is the first. -->

## Impact

**Code**
- `prisma_sdwan_mcp/tools/discovery.py` — `search_capabilities` replaced by `list_capabilities`; summary/full projection removed.
- `prisma_sdwan_mcp/catalog.py` — `search()` replaced by exact-filter listing; haystack join and substring test deleted.
- `prisma_sdwan_mcp/resources.py` — `prisma-v2://domains` becomes redundant with `list_capabilities()`; evaluate removal.

**Tool surface**
- Tool count stays 26. One tool renamed, none added or removed.
- `read_capability` is unchanged. Both safety gates (`MCP_EXPERT_TOOL_ENABLED`, `expert_blocked_by_default`) are unaffected.

**Docs**
- `docs/TOOL_CATALOG.md`, `docs/ARCHITECTURE.md`, `README.md` reference `search_capabilities` by name.

**Not affected**
- The 154 action_ids the 26 semantic tools call directly. This change only alters how the remaining 162 are discovered.
- Read-only posture. No mutation surface is introduced.
