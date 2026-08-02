## ADDED Requirements

### Requirement: Every cap is classified

Every mechanism that limits how much data a response carries SHALL be declared in one
central registry, classified as exactly one of `env_tunable`, `paginated`, or `hard`
(a cap MAY be both `env_tunable` and `paginated`), and carry a stated recovery
mechanism or a stated reason for having none.

#### Scenario: Registry covers every cap
- **WHEN** the limits registry is compared against the constants that bound response
  size in api-mcp and cli-mcp
- **THEN** every such constant has a registry entry

#### Scenario: Unrecoverable caps state a reason
- **WHEN** a registry entry declares no recovery mechanism
- **THEN** it carries a non-empty `reason`

### Requirement: Every applied cap is signalled

When a response is limited by any cap, the response SHALL identify which cap fired,
in a machine-readable structured field. A cap SHALL NOT reduce returned data
silently, and SHALL NOT be discoverable only by parsing `summary`.

#### Scenario: Byte-budget truncation is signalled
- **WHEN** a collection exceeds the response byte budget
- **THEN** `truncated` is `true`, `total_count` exceeds `returned_count`, and
  `next_cursor` is present

#### Scenario: A non-budget cap is signalled structurally
- **WHEN** a response is limited by a cap other than the byte budget
- **THEN** the cap is named in a structured field
- **AND** the same conclusion is reachable with `summary` ignored entirely

#### Scenario: Top-talker ranking declares its size
- **WHEN** a flow digest returns a `top_talkers` ranking
- **THEN** the response states the ranking limit

#### Scenario: Truncated error text is declared
- **WHEN** a cli-mcp error message is clipped to the maximum error length
- **THEN** the result indicates the message was truncated

### Requirement: Byte-budget truncation is fully recoverable

A caller SHALL be able to retrieve a complete collection by repeatedly following
`next_cursor` until `truncated` is `false`. The byte budget SHALL be settable via
`PRISMA_MCP_MAX_RESPONSE_BYTES`.

#### Scenario: Cursor walk yields every record exactly once
- **WHEN** a collection is larger than the byte budget
- **AND** the caller follows `next_cursor` until `truncated` is `false`
- **THEN** the concatenated records equal the full collection, in order, with no
  duplicates and no gaps

#### Scenario: Malformed or out-of-range cursors are rejected
- **WHEN** a caller supplies a cursor that is not a cursor this server issued, or
  whose offset exceeds the collection size
- **THEN** the response is an error with code `invalid_cursor` and `retryable: false`
- **AND** no partial or silently-reset page is returned

### Requirement: Name resolution is not capped below the full match set

Name-resolution tools SHALL NOT truncate their candidate list below what byte-budget
pagination alone would return. A caller SHALL be able to reach every match by
following `next_cursor`.

#### Scenario: Matches beyond the former fixed cap are reachable
- **WHEN** a name matches more candidates than any fixed candidate cap
- **THEN** `total_count` equals the true match count
- **AND** following `next_cursor` returns every match

#### Scenario: Ambiguity is still reported
- **WHEN** more than one candidate matches
- **THEN** the response reports the match count and marks the result ambiguous
- **AND** no single candidate is auto-selected

### Requirement: Fan-out caps are resumable

A cap that exists to bound sequential upstream requests (an N+1 guard) SHALL remain
in force but SHALL be resumable: the caller SHALL be able to obtain the items beyond
the cap by continuing from where the previous call stopped. No item SHALL be
permanently unreachable.

#### Scenario: Leg resolution beyond the cap is reachable
- **WHEN** a site has more anynet legs than the leg-resolution cap
- **THEN** the response signals that the cap was applied
- **AND** the caller can issue a follow-up call that returns legs past the cap
- **AND** repeating this reaches every leg

#### Scenario: The fan-out bound still holds per call
- **WHEN** any single call resolves legs
- **THEN** it issues no more upstream leg-status requests than the cap allows

### Requirement: Sampled aggregates declare their completeness

An aggregate computed over a bounded sample SHALL state whether it covers the whole
requested window, the sample size, and the sample limit. An incomplete aggregate
SHALL NOT be presented as a total.

#### Scenario: A truncated flow digest is marked incomplete
- **WHEN** the flow fetch returns as many records as its sample limit allows
- **THEN** the response reports the aggregate as incomplete, with the sample size and
  sample limit
- **AND** it states that the counts and ranking cover only the sample

#### Scenario: A complete digest is marked complete
- **WHEN** the flow fetch returns fewer records than the sample limit
- **THEN** the response reports the aggregate as complete

### Requirement: Window ceilings are stated and bypassable

A relative lookback ceiling SHALL be rejected explicitly with `invalid_argument` when
exceeded, and SHALL be bypassable by supplying an explicit `start_time`/`end_time`
window. The absence of a relative ceiling on an explicit window SHALL be documented
as bounded only by controller retention.

#### Scenario: Excessive relative lookback is rejected
- **WHEN** `hours` exceeds the ceiling
- **THEN** the response is `invalid_argument` naming the ceiling

#### Scenario: An explicit window bypasses the relative ceiling
- **WHEN** `start_time` and `end_time` describe a window longer than the relative
  ceiling
- **THEN** the request is accepted
- **AND** the resolved window is echoed back in the response

### Requirement: Retry exhaustion is reported with its budget

When upstream retries are exhausted, the response SHALL report the attempt count, the
elapsed time, and the last upstream status code, so a caller can decide whether to
retry itself.

#### Scenario: Exhausted retries report their accounting
- **WHEN** an upstream call fails transiently on every attempt
- **THEN** the error carries the attempt count, elapsed seconds, and last status code
- **AND** `retryable` is `true`

### Requirement: CLI execution caps never masquerade as success

A cli-mcp command SHALL be reported with `status: "error"` when it hits a read
timeout, a pagination-page cap, or any other execution ceiling. Partial device output
SHALL NOT be returned as `status: "ok"`.

#### Scenario: Read timeout is an error, not truncated output
- **WHEN** a session stops responding and the read timeout elapses
- **THEN** that command's result has `status: "error"`

#### Scenario: Pagination cap is an error
- **WHEN** device output requires more pages than the pagination cap allows
- **THEN** that command's result has `status: "error"` naming the cap

#### Scenario: One failed command does not fail the batch
- **WHEN** one command in a batch errors and others succeed
- **THEN** each result carries its own status and the successful outputs are returned

### Requirement: Documented exceptions to signalling

Exemptions from the signalling requirement SHALL be enumerated here and nowhere else.
A cap MAY be exempt only where it applies inside a response whose entire declared
purpose is degradation, and where the truncated value is strictly more informative
than its absence.

#### Scenario: Identifier clipping inside an oversized-item response is exempt
- **WHEN** a single item exceeds the byte budget and only identifying fields are
  returned
- **THEN** identifying values clipped to their maximum length need not be separately
  flagged
- **AND** the response still carries the `item_too_large` error code
