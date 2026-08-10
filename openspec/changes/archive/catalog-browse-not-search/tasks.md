## 1. Catalog layer

- [x] 1.1 Add `CapabilityCatalog.list_actions(domain: str, method: str | None = None) -> list[dict]` returning `describe()` output for every action whose `domain` matches exactly, optionally filtered by exact `http_method`. No limit, no truncation, no text matching.
- [x] 1.2 Raise `RegistryError` from `list_actions` when `domain` is not a known domain identifier, so an unknown domain is distinguishable from an empty result.
- [x] 1.3 Delete `CapabilityCatalog.search()` including the `haystack` join over `action_id`/`domain`/`sdk_call`/`description`/`url_template`/`output_fields` and the `needle not in haystack` substring branch (catalog.py:172-202).
- [x] 1.4 Confirm `describe()` already returns the full execution contract (`action_id`, `http_method`, `path_parameters` with `required`, `body_schema`, `domain`, `description`, `source`, `requires_live_test`); add any missing field rather than reintroducing a projection mode.

## 2. Tool layer

- [x] 2.1 Replace `search_capabilities` with `list_capabilities(domain: Optional[str] = None, method: Optional[Literal["GET","POST"]] = None)` in `tools/discovery.py:121-161`. Drop the `search`, `detail`, and `limit` parameters, and write the docstring to describe enumeration only — it is transmitted to the AI as the tool description, so it must not advertise parameters or behavior the tool no longer has.
- [x] 2.2 Implement the no-argument branch: return every domain with `domain`, `title`, `description`, `action_count`, plus an explicit `next_call` field naming the exact follow-up invocation the AI should make.
- [x] 2.3 Implement the `domain` branch: return every action in that domain via `catalog.list_actions`, with `domain` and `action_count` echoed in `extra` so the caller can verify nothing was dropped.
- [x] 2.4 Map an unknown `domain` to a structured `invalid_argument` error listing valid domain identifiers.
- [x] 2.5 Update the `read_capability` docstring (discovery.py:174) to reference `list_capabilities` as the discovery step.
- [x] 2.6 Pass an explicit `limit` and `budget` to both `collection_json` calls so listings cannot be cut by `MCP_MAX_RESPONSE_BYTES` or `MCP_DEFAULT_PAGE_SIZE`. The tool exposes no cursor, so a truncated listing hides actions permanently instead of paginating them.

## 3. Redundant surface

- [x] 3.1 Remove the `prisma-v2://domains` MCP resource (resources.py:27-29) now that `list_capabilities()` returns the same data through a path every client supports.
- [x] 3.2 Verify no other tool, resource, or prompt calls `catalog.search()` before deleting it.

## 4. Tests

- [x] 4.1 Add `tests/test_capability_discovery.py`: `list_actions("routing_bgp_ospf")` returns exactly 20 actions and its length equals that domain's `action_count`.
- [x] 4.2 Assert every domain is fully listable — for each entry from `catalog.domains()`, `len(list_actions(domain)) == action_count`. This is the no-truncation guarantee.
- [x] 4.3 Assert every returned action carries `action_id`, `http_method`, `path_parameters`, and `body_schema` keys, so a listing is always execution-ready.
- [x] 4.4 Assert `list_actions` on an unknown domain raises `RegistryError` rather than returning `[]`.
- [x] 4.5 Assert `method="GET"` filtering returns only GET actions and that GET + POST counts sum to the domain's `action_count`.
- [x] 4.8 Assert the no-truncation guarantee at the **tool** layer, not just the catalog layer: with `MCP_MAX_RESPONSE_BYTES` lowered, every domain still returns its full `action_count` with `truncated == false` and no `next_cursor`. Tasks 4.1-4.5 exercise `catalog.list_actions()`, which sits below `collection_json` and cannot observe truncation.
- [x] 4.6 Update `tests/test_tool_surface_static.py:16` and `tests/test_registration_smoke.py:31` — count stays 26, but the expected name set changes from `search_capabilities` to `list_capabilities`.
- [x] 4.7 Run the full suite; `tests/test_action_references.py` must still pass since it validates hardcoded action_ids against the catalog and is unaffected by discovery changes.

## 5. Docs

- [x] 5.1 `docs/TOOL_CATALOG.md:10` — replace the row's "Search the full registry by human text/domain/method" with the browse description.
- [x] 5.2 `docs/TOOL_CATALOG.md:36` — update the "Why the expert tool exists" paragraph to describe enumeration rather than search.
- [x] 5.3 `README.md:28` — rename in the discovery tool list.
- [x] 5.4 `docs/LIVE_VALIDATION.md:174` — update the per-domain validation procedure to use `list_capabilities`.
- [x] 5.5 `docs/ARCHITECTURE.md` — record the design rule that catalog discovery is enumeration over a fixed 316-entry catalog, and that text matching is deliberately absent.

## 6. Verification

- [x] 6.1 Confirm the tool surface is still exactly 26 registered tools.
- [x] 6.2 Confirm `read_capability` behavior is unchanged, including the `MCP_EXPERT_TOOL_ENABLED` gate and the eight `expert_blocked_by_default` actions.
- [x] 6.3 Walk the spec's two-call path end to end: `list_capabilities()` → `list_capabilities(domain=...)` → `read_capability(...)` using only fields returned by the previous call.
- [x] 6.4 Grep the repo for `search_capabilities` and `catalog.search` and confirm zero remaining references outside `openspec/changes/`.
