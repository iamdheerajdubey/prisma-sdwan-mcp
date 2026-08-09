## ADDED Requirements

### Requirement: The console reaches the server over MCP, not by importing it

The console SHALL communicate with `prisma-sdwan-mcp` as an MCP client over a supported transport, and SHALL NOT import the server package to call tool functions directly.

This is what keeps the console honest: a capability that works in the console works in any other MCP host, and the console cannot come to depend on internals the protocol does not expose.

#### Scenario: Tools are discovered through the protocol

- **WHEN** the console starts a session with the server
- **THEN** the available tools, their descriptions, and their input schemas come from the MCP tool listing
- **AND** no server-internal module, global, or attribute is read to obtain them

#### Scenario: No private state is reachable

- **WHEN** the console needs the server's connection or authentication state
- **THEN** it uses what the protocol exposes
- **AND** it does not read or assign server module globals

#### Scenario: Server-side renames do not break the console

- **WHEN** an internal module of the server package is renamed or moved without changing the tool surface
- **THEN** the console continues to work unchanged

### Requirement: Tool failures are surfaced, never swallowed

The console SHALL render a failed tool call as a visible failure carrying the server's own structured error, and SHALL NOT substitute an empty result, a cached result, or a generic message.

#### Scenario: A structured error reaches the user

- **WHEN** a tool returns a structured error
- **THEN** the console displays the error code and message as returned
- **AND** the failure is visually distinguishable from an empty successful result

#### Scenario: Ambiguity is presented as a choice

- **WHEN** a tool returns an ambiguous-match error carrying candidates
- **THEN** the candidates are shown so the user can choose
- **AND** the console does not select one on the user's behalf

#### Scenario: A transport failure is distinguishable from a tool failure

- **WHEN** the MCP session cannot be established or is lost
- **THEN** the console reports a connection-level failure naming that cause
- **AND** it is distinguishable from a tool that ran and returned an error

### Requirement: Every answer carries its source

The console SHALL label each displayed result with where it came from — the controller API or the device itself — and SHALL NOT merge the two into one undifferentiated view.

The controller's record of a device and the device's own report are different claims, and troubleshooting depends on seeing where they disagree.

#### Scenario: Controller and device answers appear side by side

- **WHEN** a view shows both a controller result and a device CLI result for the same subject
- **THEN** each is labeled with its source
- **AND** each is separately attributed to the tool and target that produced it

#### Scenario: A device answer is never presented as controller truth

- **WHEN** device CLI output is displayed
- **THEN** it is identified as the device's own report
- **AND** it is not merged into, or substituted for, a controller-sourced field

#### Scenario: A missing lane is stated, not hidden

- **WHEN** one of the two lanes is unavailable — no device credentials, an unreachable device, a failed call
- **THEN** the view says that lane is unavailable and why
- **AND** the remaining lane is still shown, not suppressed

### Requirement: Preview mode never touches a live tenant

The console SHALL provide a preview mode backed entirely by sample data, and while it is active SHALL make no MCP tool call, no controller request, and no device connection.

Preview exists so the interface can be demonstrated and worked on with no tenant and no risk; that guarantee is worthless if it is only usually true.

#### Scenario: No live call escapes preview mode

- **WHEN** preview mode is active and the user exercises any page
- **THEN** no MCP tool is invoked
- **AND** no network request leaves the console for the controller or a device

#### Scenario: Preview data is unmistakable

- **WHEN** preview mode is active
- **THEN** the interface indicates it continuously, not only at the moment of switching
- **AND** the sample data contains no real tenant identifiers or credentials

#### Scenario: Switching modes does not leak results

- **WHEN** the user switches between live and preview
- **THEN** results from the previous mode are cleared rather than left on screen under the new label
