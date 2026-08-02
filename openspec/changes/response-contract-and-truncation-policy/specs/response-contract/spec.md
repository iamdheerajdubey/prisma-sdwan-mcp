## ADDED Requirements

### Requirement: Frozen collection envelope

Every api-mcp tool returning a collection SHALL return a JSON object containing the
keys `tool`, `summary`, a typed collection key, `truncated`, `total_count`,
`returned_count`, and `retrieved_at`; plus `next_cursor` when and only when
`truncated` is `true`. These key names SHALL NOT be renamed or removed. Additional
keys MAY be added.

#### Scenario: Envelope carries the frozen key set
- **WHEN** any collection tool returns successfully
- **THEN** the parsed response contains `tool`, `summary`, its typed collection key,
  `truncated`, `total_count`, `returned_count`, and `retrieved_at`

#### Scenario: next_cursor appears exactly with truncation
- **WHEN** a response has `truncated: true`
- **THEN** `next_cursor` is present and decodes to an offset strictly greater than 0
- **WHEN** a response has `truncated: false`
- **THEN** `next_cursor` is absent

#### Scenario: The collection key is typed, not generic
- **WHEN** `get_sites` returns
- **THEN** the collection key is `sites`, not `data` or `items`

#### Scenario: retrieved_at is fixed-width UTC
- **WHEN** any successful response is returned
- **THEN** `retrieved_at` matches `YYYY-MM-DDTHH:MM:SSZ` and its length never varies

### Requirement: Single-record envelope

A tool returning exactly one record SHALL use the same envelope with
`truncated: false`, `total_count: 1`, `returned_count: 1`.

#### Scenario: Single response mirrors the collection envelope
- **WHEN** a single-record tool returns successfully
- **THEN** the response carries `tool`, `summary`, its typed key, `retrieved_at`,
  and `truncated: false`, `total_count: 1`, `returned_count: 1`

### Requirement: Summary states what was returned, never what it means

`summary` SHALL describe the retrieval — counts, scope, window, truncation. It SHALL
NOT contain a diagnosis, a hypothesis, a root cause, a confidence score, or a
recommended action.

#### Scenario: Summary reports facts only
- **WHEN** a tool returns records describing a degraded link
- **THEN** `summary` states the count and scope retrieved
- **AND** `summary` does not assert that anything is degraded, failing, or at fault

### Requirement: Consumers must not parse summary for machine state

Any condition a consumer must branch on SHALL be exposed as a structured field.
`summary` is a human-readable restatement and SHALL NOT be the sole carrier of any
machine-consumable fact.

#### Scenario: A cap is machine-detectable without string matching
- **WHEN** a response was limited by any cap
- **THEN** the cap is identifiable from structured fields alone, with `summary`
  ignored entirely

### Requirement: Projection is declared

When a tool applies a field projection, the response SHALL include
`projected_fields` listing every field the projection could emit, sorted. When no
projection is applied, `projected_fields` SHALL be absent.

#### Scenario: Projected responses declare their field set
- **WHEN** a tool applies a `*_KEEP_FIELDS` projection
- **THEN** `projected_fields` is present and sorted
- **AND** every key appearing on any returned item is either in `projected_fields`
  or is one of the preserved error keys `code`, `error`, `message`, `status_code`

#### Scenario: Unprojected responses omit the declaration
- **WHEN** a tool returns records without a projection
- **THEN** `projected_fields` is absent

### Requirement: Projection never discards upstream error information

Field projection SHALL preserve `code`, `error`, `message`, and `status_code` on any
record that carries them, whether or not those keys are in the projection's field
set.

#### Scenario: A per-record upstream error survives projection
- **WHEN** an upstream record contains `error` and `status_code` and the projection
  set excludes both
- **THEN** the projected record still contains `error` and `status_code`

### Requirement: Diagnostic endpoints SHALL NOT project

Tools whose records are evidence about an incident SHALL return every field the
controller sends, with no projection. Tools whose records are a catalogue being
browsed MAY project.

Diagnostic (no projection): events, alarms, flows, interface status, VPN link
status, BGP status.
Catalogue (projection permitted): sites, elements, machines, application
definitions, policy sets, security zones, path groups, service labels, WAN
networks.

Rationale, established by live capture on 2026-08-02: a projection is an editorial
judgement about which fields matter during an outage, made by a developer in
advance and invisible to the consumer. The flow projection dropped 44 of 80 real
fields, including `wan_path_change_reason` — the field stating why a flow moved
paths. Nobody judged it unimportant; nobody knew it existed.

An enumerated allow-list that happens to list every field known today is NOT
sufficient and SHALL NOT be treated as satisfying this requirement. It silently
drops whatever the vendor adds in a later release, reproducing the same defect
against a future field set. Absence of projection, not a complete projection, is
the requirement.

#### Scenario: A new upstream field reaches the consumer without a code change
- **WHEN** the controller begins returning a field on events, alarms, or flows that
  did not exist when the tool was written
- **THEN** the field appears in the tool's response
- **AND** no change to the server is required for it to do so

#### Scenario: Diagnostic tools declare no projection
- **WHEN** a diagnostic tool returns records
- **THEN** `projected_fields` is absent
- **AND** the record key set matches the upstream record key set

#### Scenario: Catalogue tools may still project
- **WHEN** a catalogue tool returns records
- **THEN** a projection MAY be applied
- **AND** if applied, `projected_fields` is present

### Requirement: Projections are verified against live controller responses

Each surviving `*_KEEP_FIELDS` set SHALL be validated against a captured real
controller response before it is treated as stable. Field names present in a set
but never returned upstream SHALL be removed or annotated as a documented alias.
Verification SHALL sample more than one record source: field presence varies per
record, so absence in a single capture proves nothing on its own.

#### Scenario: Aliased flow field pairs are resolved
- **WHEN** `FLOW_KEEP_FIELDS` is reviewed against a live flow record
- **THEN** for each of `source_ip`/`src_ip` and `destination_ip`/`dst_ip`, either both
  are confirmed to occur upstream or the unused name is removed
- **RESOLVED** 2026-08-02 by live capture: the controller emits `source_ip`,
  `destination_ip`, `source_port`, `destination_port`. The `src_ip`/`dst_ip`/
  `src_port`/`dst_port` names never occur and have been removed, along with
  `flow_id`, `id`, `site_id`, `bytes`, `packets`, `start_time`, `end_time`,
  `application`, `app_name`, and the `avg_jitter_c2s`/`avg_mos_c2s`/
  `avg_packet_loss_c2s` trio — flows carry no jitter, loss, or MOS at all.

### Requirement: Raw record access is opt-in per call

Raw data SHALL NOT be returned alongside projected data by default, because both
share one byte budget and doing so reduces the number of records any single response
can carry. A tool MAY instead accept `raw: bool = False` to return underlying records
instead of a derived or projected view.

#### Scenario: Default response is not raw
- **WHEN** a tool with a `raw` argument is called without it
- **THEN** the response is the projected or digest form

#### Scenario: Raw responses remain budgeted and paginated
- **WHEN** a tool is called with `raw=True`
- **THEN** the response still honours the byte budget and still reports `truncated`,
  `total_count`, and `returned_count`

### Requirement: Closed error-code set

An error response SHALL be a JSON object with `code`, `message`, `tool`, and
`retryable`, plus `status_code` when an HTTP status is known. `code` SHALL be one of:
`invalid_argument`, `invalid_limit`, `invalid_cursor`, `invalid_budget`,
`invalid_filename`, `not_found`, `schema_not_found`, `upstream_error`,
`internal_error`, `response_budget_exceeded`, `response_budget_too_small`,
`item_too_large`, `historical_data_unavailable`, `rate_limited`,
`unresolved_relationship`, `partial_response`.

#### Scenario: Every emitted code is in the closed set
- **WHEN** any tool returns an error
- **THEN** `code` is a member of the enumerated set

#### Scenario: Error responses carry the required fields
- **WHEN** any tool returns an error
- **THEN** `code`, `message`, `tool`, and `retryable` are all present

### Requirement: retryable has one meaning

`retryable: true` SHALL mean that the identical call, repeated later with no argument
change, may succeed. It SHALL be `false` for every `invalid_*` code and for
`not_found`, and `true` for `rate_limited`.

#### Scenario: Argument errors are never retryable
- **WHEN** an error carries a code beginning `invalid_`
- **THEN** `retryable` is `false`

#### Scenario: Rate limiting is always retryable
- **WHEN** the controller responds 429
- **THEN** `code` is `rate_limited` and `retryable` is `true`

#### Scenario: Upstream server errors are retryable
- **WHEN** the controller responds with a 5xx status
- **THEN** `retryable` is `true`

### Requirement: Partial success is declared, not hidden

A tool SHALL declare partial success: when it returns some data while one or more
sub-requests failed, it returns a success envelope containing an `error` object with
code `partial_response`, alongside per-part failure detail. It SHALL NOT silently
return only the successful subset.

#### Scenario: A failed policy family is reported
- **WHEN** `find_policy_set` queries four policy families and one endpoint fails
- **THEN** the envelope contains matches from the surviving families
- **AND** an `error` object with code `partial_response`
- **AND** per-family failure detail identifying which family failed and why

#### Scenario: A failed leg lookup is reported
- **WHEN** `get_basenet_topology` resolves legs and one `vpnlinks_status` call fails
- **THEN** the response contains the successfully resolved legs
- **AND** an `error` object with code `partial_response`

### Requirement: Missing historical data is distinguishable from no activity

A tool SHALL report `historical_data_unavailable` rather than an empty successful
collection when a time-windowed query returns nothing because the requested window
predates controller retention or is otherwise unavailable.

#### Scenario: An aged-out window is not reported as quiet
- **WHEN** a metrics or events window falls outside controller retention
- **THEN** the response carries code `historical_data_unavailable`
- **AND** it is not an empty collection with `total_count: 0`

### Requirement: Wrong-tenant identifiers are distinguishable from missing ones

A tool SHALL report the failure the controller reported. Where the controller does
not distinguish a foreign-tenant identifier from a nonexistent one, the tool SHALL
NOT invent the distinction.

Owner decision 2026-08-02: `tenant_or_region_mismatch` is **removed from the code
set**. Determining what a resolution failure means is the consuming agent's job;
MCP's job is to report what the controller said. A code the server cannot populate
from evidence would have to be guessed, which is the defect this contract exists to
prevent.

#### Scenario: A foreign-tenant ID is reported as the controller reported it
- **WHEN** a resource ID belonging to a different tenant is passed
- **AND** the controller does not distinguish it from a nonexistent ID
- **THEN** the tool returns `not_found`
- **AND** no tenant or region attribution is asserted

### Requirement: Unresolvable relationships are reported as facts

When a tool cannot resolve an identifier to a related object, it SHALL return an
explicit unresolved entry with a reason, or the `unresolved_relationship` code. It
SHALL NOT silently drop the identifier and SHALL NOT invent a relationship.

#### Scenario: An unmatched path is explicitly unresolved
- **WHEN** `resolve_path` is given a `path_id` matching no WAN interface, anynet
  link, or vpnlink leg
- **THEN** the response contains an entry with `resolved: false` and a reason
- **AND** no fabricated descriptor is returned

### Requirement: Additive changes do not break consumers

The following SHALL be non-breaking: adding an envelope key, a projection field, an
`extra` key, an optional tool argument with a backward-compatible default, a new
tool, or a new error code. Consumers SHALL treat unrecognised keys and unrecognised
error codes as opaque, falling back on `retryable` for retry decisions.

#### Scenario: An unknown envelope key is ignored
- **WHEN** a response contains a key a consumer does not recognise
- **THEN** the consumer processes the response normally

#### Scenario: An unknown error code degrades gracefully
- **WHEN** an error carries a code a consumer does not recognise
- **THEN** the consumer uses `retryable` to decide whether to retry

### Requirement: Breaking changes ship under a new tool name

A breaking change SHALL ship as a new tool name with the previous tool retained for
at least one release. Breaking means: renaming or removing a frozen envelope key,
renaming or removing a tool or argument, changing a field's type or units, narrowing
a projection, or redefining an existing error code. Existing tool names SHALL NOT
change behaviour incompatibly in place.

#### Scenario: A superseded tool remains callable
- **WHEN** a tool is superseded by an incompatible replacement
- **THEN** the original tool name remains registered and functional
- **AND** its description identifies the replacement

### Requirement: Contract version is discoverable

The server SHALL expose a `prisma://contract` resource reporting `contract_version`
(semver), the frozen envelope keys, the closed error-code set, and the limits table.
The version SHALL increment its minor component for additive changes and its major
component for breaking ones. The resource SHALL be generated from the same
definitions the server enforces.

#### Scenario: Contract resource is retrievable
- **WHEN** a client reads `prisma://contract`
- **THEN** it receives `contract_version`, the frozen envelope key list, the error
  code list, and the limits table

#### Scenario: Contract resource cannot drift from enforcement
- **WHEN** an error code is added to the enforced set
- **THEN** it appears in `prisma://contract` with no separate edit

### Requirement: Prompts and Resources do not constrain consumers

MCP Prompts SHALL be client-invoked and opt-in, and no tool result SHALL depend on
any prompt having been used. MCP Resources SHALL delegate to the same tool functions
and return the same envelope. No MCP **tool** SHALL return a diagnosis, hypothesis,
root cause, confidence score, or escalation recommendation.

#### Scenario: Tool results are prompt-independent
- **WHEN** a consumer calls tools without ever listing or invoking prompts
- **THEN** every tool returns its normal result

#### Scenario: Resources return the tool envelope
- **WHEN** a client reads `prisma://sites`
- **THEN** the payload is the same envelope `get_sites()` returns

#### Scenario: No tool returns a conclusion
- **WHEN** the registered tool set is inspected
- **THEN** no tool's response schema contains a diagnosis, root cause, confidence
  score, or recommended action field
