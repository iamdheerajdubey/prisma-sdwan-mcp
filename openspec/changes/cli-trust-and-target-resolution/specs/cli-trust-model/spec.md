## ADDED Requirements

### Requirement: The server holds no secret

cli-mcp SHALL NOT store, cache, or read from disk any password, private key, or
passphrase. Every secret SHALL be supplied by the caller as an argument to the call
that uses it, and SHALL exist only for the duration of that call.

#### Scenario: No secret survives a call
- **WHEN** `run_commands` returns
- **THEN** no password, private key, or passphrase remains in server state, module
  globals, or the connection parameters

#### Scenario: Server cannot authenticate on its own
- **WHEN** `run_commands` is called with no `password` and no `private_key`
- **THEN** the call is rejected with a validation error
- **AND** no connection is attempted, regardless of any configured target mapping

### Requirement: Credential possession is the per-call authorization check

Holding an MCP session to cli-mcp SHALL NOT by itself grant the ability to execute
commands on any device. Reaching a device SHALL additionally require possession of a
credential accepted by that device.

#### Scenario: A session without credentials reaches nothing
- **WHEN** a caller holds an MCP session and knows a valid `element_id`
- **AND** supplies no credential
- **THEN** no device is reached

#### Scenario: Resolution grants no access
- **WHEN** `target resolution` succeeds for an element
- **THEN** the caller has gained connection parameters only
- **AND** has gained no ability to authenticate to that device

### Requirement: Command policy is evaluated before anything else

Command validation SHALL run before target resolution, before input validation, and
before any network connection. A denied batch SHALL NOT trigger a target lookup and
SHALL NOT open a socket.

#### Scenario: A denied batch performs no resolution
- **WHEN** `run_commands` is called with a disallowed command and an `element_id`
- **THEN** the response is a policy denial
- **AND** no target lookup occurs
- **AND** the response reveals no host, port, or username

#### Scenario: A denied batch opens no connection
- **WHEN** any command in the batch is denied
- **THEN** no SSH session is established
- **AND** every command in the batch is reported denied with a reason

### Requirement: The target never widens the allow-list

The set of permitted commands SHALL be identical for every device. There SHALL be no
per-element, per-site, or per-target policy override.

#### Scenario: Policy is target-independent
- **WHEN** the same command batch is submitted for two different elements
- **THEN** the policy decision is identical

### Requirement: Strict host-key checking is unconditional

SSH host-key verification SHALL remain strict regardless of how the target was
obtained. An unknown or mismatched host key SHALL abort the connection with
`error.type: "host_key"` before any credential is transmitted.

#### Scenario: Resolved targets are not implicitly trusted
- **WHEN** a target obtained via `target resolution` presents a host key absent from
  known_hosts
- **THEN** the call fails with `error.type: "host_key"`
- **AND** no credential is sent

### Requirement: Secrets are redacted everywhere

No secret supplied to cli-mcp SHALL appear in any response field, any log record at
any level, or any exception message or traceback the server emits.

#### Scenario: A sentinel secret never escapes
- **WHEN** `run_commands` is called with a distinctive sentinel password and the
  connection fails
- **THEN** neither the response nor any emitted log record contains the sentinel

#### Scenario: Error text is redacted before truncation
- **WHEN** an underlying library raises an error whose message embeds the credential
- **THEN** the reported message has the credential replaced with a redaction marker
- **AND** redaction happens before any length clipping

### Requirement: Every call is audited

cli-mcp SHALL emit one structured log record per `run_commands` and per
`target resolution` call, containing the event type, `element_id` when supplied,
`host`, `port`, `username`, the validated command strings, the outcome, the error
type on failure, and the duration.

#### Scenario: A successful execution is audited
- **WHEN** `run_commands` completes
- **THEN** one record is emitted with event `cli.execute`, the target, the commands,
  outcome `ok`, and a duration

#### Scenario: A denial is audited
- **WHEN** a batch is denied by policy
- **THEN** one record is emitted with outcome `denied` and the denial reason

#### Scenario: A resolution is audited
- **WHEN** `target resolution` is called
- **THEN** one record is emitted with event `cli.resolve` and the outcome

#### Scenario: Audit records carry no secrets
- **WHEN** any audit record is emitted
- **THEN** it contains no password, private key, or passphrase material

### Requirement: Timeouts and caps fail closed

An execution ceiling SHALL produce an error result, never a truncated output reported
as success.

#### Scenario: A wedged session errors
- **WHEN** a session stops responding and the read timeout elapses
- **THEN** that command's result has `status: "error"`
- **AND** no partial output is returned as `status: "ok"`
