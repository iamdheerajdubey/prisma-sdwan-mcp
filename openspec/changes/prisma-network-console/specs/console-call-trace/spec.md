## ADDED Requirements

### Requirement: Every tool call the console makes is recorded

The console SHALL record every MCP tool invocation it performs, whether initiated by a page or by the assistant, and SHALL make those records viewable.

The server already reports its own limits — page sizes, fan-out ceilings, byte budgets, truncation, cursors — inside responses nobody reads. A console that surfaces them is the one thing a console offers that a chat client cannot.

#### Scenario: A page call is recorded

- **WHEN** a page invokes a tool
- **THEN** a trace record is created for that invocation
- **AND** it is visible without re-running the call

#### Scenario: An assistant call is recorded identically

- **WHEN** the assistant invokes a tool during its loop
- **THEN** a trace record is created in the same form as a page-initiated call
- **AND** it is attributed to the question that caused it

#### Scenario: A failed call is recorded

- **WHEN** a tool call fails at any stage
- **THEN** a trace record is still created, carrying the failure
- **AND** failures are not omitted from the trace

### Requirement: A record carries what was asked and what came back

Each record SHALL carry the tool invoked, the arguments sent, the elapsed time, the size of the returned payload, and whether the call succeeded.

#### Scenario: Record contents

- **WHEN** a trace record is viewed
- **THEN** it shows the tool name, the arguments, the elapsed time, the returned byte size, and the outcome

#### Scenario: Arguments are shown as sent

- **WHEN** arguments are displayed
- **THEN** they are the values actually sent to the tool
- **AND** they are not re-derived or reformatted into something that was not sent

#### Scenario: No credential appears in a record

- **WHEN** an invocation carries a credential in any argument
- **THEN** the recorded arguments show it redacted
- **AND** the raw value is not stored in the record

### Requirement: Truncation and paging are visible

Where a response reports truncation, byte-budget compaction, fan-out capping, or a continuation cursor, the record SHALL surface that state rather than leaving it inside the payload.

A partial answer that looks complete is the failure mode this exists to prevent.

#### Scenario: A truncated response is flagged

- **WHEN** a response reports truncation
- **THEN** the record marks it truncated
- **AND** shows the returned size against the total where the response reports both

#### Scenario: More results available is visible

- **WHEN** a response carries a continuation cursor
- **THEN** the record indicates more results are available
- **AND** the user can see that what is displayed is one page

#### Scenario: A capped fan-out is visible

- **WHEN** a tool reports that it stopped short of a fan-out ceiling
- **THEN** the record shows that the result is partial and why

#### Scenario: A complete response is marked complete

- **WHEN** a response reports no truncation, no cursor, and no capping
- **THEN** the record shows it as complete
- **AND** completeness is stated, not merely implied by the absence of a warning

### Requirement: The trace reflects one session and outlives no session

The trace SHALL cover the current console session, SHALL be clearable on request, and SHALL NOT be written to persistent storage.

Records contain tenant data and device output. Keeping them beyond the session would give the console its own data store, which neither it nor the server it fronts is meant to have.

#### Scenario: The trace is not persisted

- **WHEN** the console process exits
- **THEN** no trace record remains on disk

#### Scenario: The trace can be cleared

- **WHEN** the user clears the trace
- **THEN** the existing records are discarded
- **AND** subsequent calls are recorded from empty

#### Scenario: The trace is bounded

- **WHEN** a long session produces more records than the retained ceiling
- **THEN** the oldest records are dropped
- **AND** the view indicates that earlier records were dropped rather than that none existed
