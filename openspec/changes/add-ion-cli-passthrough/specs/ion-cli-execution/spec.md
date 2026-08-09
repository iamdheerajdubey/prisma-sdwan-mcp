## ADDED Requirements

### Requirement: Devices are addressable by name

The system SHALL accept an element name as the device target and resolve it to an SSH address using the existing resolver and registry, so the AI never has to supply an IP address it would otherwise have to look up by hand.

An explicit `host` SHALL also be accepted, SHALL bypass resolution entirely, and SHALL take precedence over `element` when both are supplied. A caller-supplied address is authoritative: the system SHALL NOT refuse it, substitute it, or cross-check it against the controller.

Name resolution SHALL consider only interfaces whose `used_for` role is a management role, SHALL read each candidate's address from the interface's live status record rather than its configuration record, and SHALL require the interface to be operationally up.

#### Scenario: Element name resolves to an address

- **WHEN** `run_commands` is called with an element name that matches exactly one element with one candidate address
- **THEN** the command batch runs against that address
- **AND** the response reports the element, its element ID, and the address that was used

#### Scenario: Ambiguity returns candidates instead of a guess

- **WHEN** an element name matches multiple elements, or one element yields multiple candidate addresses
- **THEN** no connection is attempted
- **AND** the candidates are returned so the caller can disambiguate
- **AND** the behavior matches the resolver's existing contract that exact matches win and multiple matches are never silently narrowed

#### Scenario: Unresolvable name is a distinct error

- **WHEN** an element name matches nothing
- **THEN** a structured `resolution` error is returned
- **AND** it is distinguishable from a device that resolved but could not be reached

#### Scenario: Explicit host skips resolution

- **WHEN** `run_commands` is called with an explicit `host`
- **THEN** no resolver or registry call is made
- **AND** the address is used exactly as supplied

#### Scenario: Explicit host wins over a supplied element

- **WHEN** `run_commands` is called with both `host` and `element`
- **THEN** the call is not refused
- **AND** the supplied `host` is used without any resolution or cross-check
- **AND** the `element` appears only as a label on the response

#### Scenario: Neither host nor element is an input error

- **WHEN** `run_commands` is called with neither `host` nor `element`
- **THEN** an input error is returned naming both options

#### Scenario: A DHCP-assigned address resolves

- **WHEN** the selected management interface obtains its address by DHCP and therefore carries none in its configuration record
- **THEN** the live address from the interface status record is used
- **AND** the result is indistinguishable from a statically addressed interface

#### Scenario: A non-management interface is never a candidate

- **WHEN** an element has addressed interfaces serving WAN, HA, or service-link roles
- **THEN** none of them is offered as a candidate
- **AND** only interfaces in a management role are considered

#### Scenario: An operationally down interface is not a candidate

- **WHEN** a management interface is administratively enabled but operationally down
- **THEN** it is not selected
- **AND** it is reported among the rejected candidates with its operational state, so the reason is visible

#### Scenario: A tie in the preferred role does not fall through

- **WHEN** two live interfaces share the most-preferred management role
- **THEN** candidates are returned rather than a selection
- **AND** a less-preferred role is not silently used instead

### Requirement: Device credentials come from configuration and fail closed

The system SHALL read ION SSH credentials from environment configuration rather than requiring them as tool arguments, because a tool argument is visible to the model and is recorded in conversation transcripts.

Per-call credential arguments SHALL remain available as an explicit override. When no credential is available from either source, the system SHALL return a structured configuration error and SHALL NOT attempt a connection.

#### Scenario: Credentials are sourced from the environment

- **WHEN** ION credentials are configured in the environment and no credential argument is supplied
- **THEN** the connection uses the configured credential
- **AND** no credential value appears in the tool's arguments or in the returned response

#### Scenario: No credentials means no connection attempt

- **WHEN** no ION credential is configured and none is supplied per call
- **THEN** a structured `configuration` error is returned naming the missing setting
- **AND** no TCP connection, SSH handshake, or resolution call is attempted

#### Scenario: Exactly one credential type

- **WHEN** both a password and private key material are available from the same source, or neither is
- **THEN** an input error is returned describing the requirement for exactly one

#### Scenario: Credentials never appear in output

- **WHEN** any error occurs whose underlying message contains credential material
- **THEN** the credential value is replaced before the message is returned
- **AND** the response passes through the same recursive redaction applied to every other response

### Requirement: Host-key checking is strict

The system SHALL verify the device's SSH host key against a known_hosts file before sending credentials, and SHALL fail the call when the key is unknown or mismatched.

The system SHALL NOT auto-trust an unverified host key under any condition, including as a retry after failure.

#### Scenario: Unknown host key fails before credentials are sent

- **WHEN** the device's host key is absent from the known_hosts file
- **THEN** the call fails with error type `host_key`
- **AND** no credential is transmitted
- **AND** the message states that the entry must be populated out of band

#### Scenario: Mismatched host key fails

- **WHEN** the device presents a host key that differs from the stored entry
- **THEN** the call fails with error type `host_key`
- **AND** the call is not retried with checking relaxed

### Requirement: Unreachable devices fail fast and say so

The system SHALL distinguish "no network path to this device" from every other failure, decided by a bounded TCP reachability probe before an SSH session is attempted, because MCPv2's existing deployments require only outbound HTTPS to the controller and may have no route to device management addresses at all.

The `unreachable` error SHALL name the address and port that were tried and SHALL state that the server may have no network path to the device.

#### Scenario: No route or filtered port fails as unreachable

- **WHEN** the TCP probe to the device's SSH port does not succeed within its bound
- **THEN** the call fails with error type `unreachable`
- **AND** the message names the address and port tried
- **AND** the failure is returned within the probe bound rather than waiting for an SSH connect timeout

#### Scenario: Unreachable is not reported as an authentication problem

- **WHEN** a device cannot be reached
- **THEN** the error type is `unreachable`
- **AND** it is not `authentication`, `host_key`, or a generic `connection` failure

#### Scenario: A reachable device that refuses the handshake is a connection error

- **WHEN** the TCP probe succeeds but the SSH handshake fails
- **THEN** the error type is `connection`
- **AND** it is distinguishable from `unreachable`

#### Scenario: Failure never weakens security posture

- **WHEN** any connection-stage failure occurs
- **THEN** no automatic retry is performed with host-key checking relaxed, with a different credential, or against a different address
- **AND** the caller receives the failure rather than a silently substituted result

### Requirement: Each command's result stands alone

The system SHALL return one independent result per submitted command, so that one command's failure does not invalidate or merge with another's output.

A device-side rejection SHALL be reported as that command's own error status while sibling commands retain their own status and output.

#### Scenario: Partial success is preserved

- **WHEN** a batch of three permitted commands runs and the device rejects the second
- **THEN** three results are returned
- **AND** the first and third carry their own output with status `ok`
- **AND** the second carries status `error` with the device's rejection text

#### Scenario: Device error detection reads only the first line

- **WHEN** a command's output is a legitimate multi-line result whose interior lines contain words such as "failed" or "invalid"
- **THEN** the result is not reclassified as an error
- **AND** only the first line of output is examined for a device rejection

#### Scenario: Batch-level failures carry no command results

- **WHEN** the failure is at the batch level — configuration, resolution, unreachable, host key, authentication, or connection
- **THEN** the response carries the batch error and an empty result list

### Requirement: Completion is decided by the device, not by a clock

The system SHALL read a command's output until the device signals it is ready for input again, so that command duration is irrelevant to correctness — an instant `dump` and a multi-second `ping` are both read to completion by the same rule.

A read ceiling SHALL exist solely to bound a session that has stopped responding, and reaching it SHALL be an error. A slow command SHALL NEVER be cut short and reported as success.

#### Scenario: A slow command is read to completion

- **WHEN** a command emits output over several seconds before the device returns its prompt
- **THEN** the complete output is returned with status `ok`
- **AND** the result is not truncated on account of elapsed time

#### Scenario: A wedged session fails rather than returning partial output

- **WHEN** the device stops responding and never returns its prompt
- **THEN** the read ceiling is reached and the command result has status `error`
- **AND** partial output is not presented as a successful result

#### Scenario: Paged output is read through

- **WHEN** the device pages its output with a pagination marker
- **THEN** paging continues to a bounded page limit until the prompt returns
- **AND** exceeding that limit is an error rather than a silent stop

### Requirement: Output caps are per command and always declared

The system SHALL cap each command's returned output independently, so one oversized command cannot starve its batch siblings, and SHALL never present truncated output as complete.

Every executed result SHALL carry an explicit truncation indicator. A truncated result SHALL additionally report the bytes returned and the bytes the device produced.

#### Scenario: Oversized output is truncated and declared

- **WHEN** a command produces output larger than the cap
- **THEN** the head of the output is returned with the truncation indicator set
- **AND** the result reports both the returned byte count and the total byte count
- **AND** the status remains `ok`, because the data is valid rather than failed

#### Scenario: The cap applies per command

- **WHEN** one command in a batch produces oversized output
- **THEN** the remaining commands in that batch return their own complete output
- **AND** their results are unaffected by the oversized sibling

#### Scenario: Truncation cuts cleanly

- **WHEN** output is truncated
- **THEN** the cut lands on a character boundary and does not split a multi-byte character
- **AND** a line boundary near the cap is preferred

#### Scenario: Complete output is marked complete

- **WHEN** a command's output is within the cap
- **THEN** the truncation indicator is false
- **AND** no byte-count fields are added

### Requirement: The tool declares that it is not read-only

The system SHALL advertise `run_commands` as non-read-only and non-idempotent, because the permitted diagnostics send real packets from the device, while continuing to advertise that it is non-destructive.

#### Scenario: Annotations reflect real behavior

- **WHEN** a client inspects the `run_commands` tool annotations
- **THEN** the tool is not marked read-only and not marked idempotent
- **AND** it is marked non-destructive

#### Scenario: The mutation boundary is unchanged

- **WHEN** any command permitted by the policy runs
- **THEN** no controller write endpoint is called
- **AND** no device configuration is modified
- **AND** the server retains no state between calls
