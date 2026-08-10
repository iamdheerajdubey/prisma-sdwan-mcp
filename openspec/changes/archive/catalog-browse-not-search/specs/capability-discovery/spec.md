## ADDED Requirements

### Requirement: Domain enumeration

The system SHALL expose every registry domain to the AI in a single call with no argument, so that discovering what exists never depends on the AI guessing a term.

`list_capabilities()` called with no arguments SHALL return every domain in the catalog, each with its `domain` identifier, `title`, `description`, and `action_count`.

#### Scenario: Listing all domains

- **WHEN** `list_capabilities()` is called with no arguments
- **THEN** the response contains one entry per catalog domain (19 at time of writing)
- **AND** each entry includes `domain`, `title`, `description`, and `action_count`
- **AND** the sum of all `action_count` values equals the total catalog action count

#### Scenario: Domain list is self-describing

- **WHEN** `list_capabilities()` returns the domain list
- **THEN** the response includes the exact next call required to list a domain's actions
- **AND** the AI can construct that call using only values present in the response

### Requirement: Complete action listing per domain

The system SHALL return every action in a requested domain without truncation, so an empty or short result always means the domain is small, never that results were cut.

#### Scenario: Listing a domain's actions

- **WHEN** `list_capabilities(domain="routing_bgp_ospf")` is called
- **THEN** all 20 actions in that domain are returned
- **AND** no action is omitted

#### Scenario: No domain exceeds the response cap

- **WHEN** any single domain is listed
- **THEN** the returned action count equals that domain's `action_count` from the domain listing
- **AND** the response is never silently truncated

#### Scenario: Completeness survives a reduced response budget

Catalog listings expose no cursor, so any action dropped by the shared response
budget is unreachable rather than paginated. Completeness therefore MUST NOT
depend on `MCP_MAX_RESPONSE_BYTES` or `MCP_DEFAULT_PAGE_SIZE`.

- **WHEN** `MCP_MAX_RESPONSE_BYTES` is lowered below a domain's serialized size
- **THEN** every action in that domain is still returned
- **AND** `truncated` is `false` and no `next_cursor` is present

#### Scenario: Unknown domain is an explicit error

- **WHEN** `list_capabilities(domain="not_a_domain")` is called
- **THEN** a structured error is returned naming the unknown domain
- **AND** the error is distinguishable from an empty result

### Requirement: Listings are execution-ready

The system SHALL include everything `read_capability` requires in every listed action, so selecting an action and executing it never requires an intermediate lookup call.

#### Scenario: Action entry carries its execution contract

- **WHEN** an action is returned by `list_capabilities`
- **THEN** the entry includes `action_id`, `http_method`, `path_parameters` with per-parameter `required` flags, `body_schema`, `domain`, `description`, `source`, and `requires_live_test`

#### Scenario: Discovery to execution in two calls

- **WHEN** the AI needs an action no semantic tool covers
- **THEN** `list_capabilities()` followed by `list_capabilities(domain=...)` yields a complete execution contract
- **AND** `read_capability` can be invoked next using only fields from that response

### Requirement: Filtering uses exact machine predicates

The system SHALL filter listings only by exact match against enumerated values, never by matching AI-supplied text against stored prose.

#### Scenario: Filtering by HTTP method

- **WHEN** `list_capabilities(domain="routing_bgp_ospf", method="GET")` is called
- **THEN** only actions whose `http_method` equals `GET` are returned

#### Scenario: Domain matching is exact

- **WHEN** a `domain` value is supplied
- **THEN** it is compared for exact equality against domain identifiers
- **AND** partial, prefix, or substring domain matches are not performed

## REMOVED Requirements

### Requirement: Free-text capability search

**Reason**: `search_capabilities(search=...)` joined `action_id`, `domain`, `sdk_call`, `description`, `url_template`, and `output_fields` into one lowercased string and tested whether the AI's query appeared inside it as a single contiguous substring. This is a human-text search primitive on an interface only machines consume, and it fails on ordinary AI phrasing: `"bgp community"` and `"show me bgp peers"` both return zero results while `routing_bgp_ospf.routing_ipcommunitylists` exists in the catalog. A zero-hit result is indistinguishable from "capability does not exist", so the AI abandons a supported request.

The catalog is 316 fixed entries totalling ~5,800 tokens across 19 domains, largest domain 43 entries. Enumeration is exhaustive and cheap; search solves a scale problem this data does not have.

**Migration**: Replace `search_capabilities(search="<text>")` with `list_capabilities()` to enumerate domains, then `list_capabilities(domain="<domain>")` to list that domain's actions. The AI selects from the returned list rather than guessing a matching term. The `domain` and `method` filters carry over unchanged.

### Requirement: Summary and full detail modes

**Reason**: The `detail` parameter defaulted to `"summary"`, which stripped `path_parameters` and `body_schema` from every result. The AI therefore received an `action_id` it could not execute and had to issue a second call with `detail="full"` before reaching `read_capability`. The omitted fields are small and always needed.

**Migration**: Remove the `detail` argument. All listings now return the full execution contract by default.
