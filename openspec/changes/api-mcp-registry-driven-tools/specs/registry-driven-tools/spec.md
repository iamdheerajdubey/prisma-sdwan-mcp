## ADDED Requirements

### Requirement: Registries are checked-in, versioned, and each validated against its own schema
The curated GET and POST action registries SHALL be stored as tracked files under `api-mcp/prisma_sdwan_mcp/registry_data/`, not as loose or untracked files. The two files do not share a shape — the GET registry declares no SDK-call field (its action `name` is the SDK method) and no query-body parameters, and its safety block carries an additional key — so each SHALL be validated at startup against a schema written for that file. A registry file that fails schema validation SHALL prevent the server from starting, with an error naming the file and the validation failure. The loader SHALL determine action counts by counting, not by reading the file's own `metadata`.

#### Scenario: Valid registry files load at startup
- **WHEN** the server starts with both registry files present and each valid against its own schema
- **THEN** the server starts successfully and every schema-valid domain is available for dispatch

#### Scenario: Malformed registry file blocks startup
- **WHEN** a registry file does not conform to its schema (e.g. a POST action missing its SDK-call field)
- **THEN** the server fails to start and logs which file and which schema constraint failed

#### Scenario: A GET action is not required to carry POST-only fields
- **WHEN** the GET registry is validated
- **THEN** the absence of an SDK-call field and of query-body parameter declarations is valid, and the action's `name` is used as the SDK method name

### Requirement: Unsafe or unresolvable actions are excluded, not exposed
An action SHALL only be exposed as callable if its safety block asserts `read_only: true`, `destructive: false`, and `verified_working: true`, AND its SDK call name resolves to a real attribute on the running `prisma_sase` SDK's `get`/`post` namespace. The safety check SHALL test for those three assertions and SHALL NOT require the safety block to contain exactly those keys — the GET registry carries an additional safety key, and an exact-match check would exclude every GET action. An action failing either check SHALL be excluded from that domain's callable action set and recorded as excluded, without stopping the server from starting.

#### Scenario: Action failing the safety assertions is excluded
- **WHEN** the registry contains an action whose `safety.destructive` is `true` or whose `safety.read_only` is absent
- **THEN** that action is not callable through any domain tool, and the exclusion is recorded

#### Scenario: Action carrying an extra safety key is still exposed
- **WHEN** an action's safety block asserts the three required values and also carries an additional informational key
- **THEN** that action is callable, and the additional key does not cause exclusion

#### Scenario: Action whose SDK method no longer exists is excluded
- **WHEN** an action's SDK call name has no matching attribute on the loaded `prisma_sase` SDK instance (e.g. after an SDK upgrade renamed or removed it)
- **THEN** that action is excluded from the callable set and recorded as excluded, rather than causing a runtime error on first call

### Requirement: Action names are unambiguous within a domain
Because a domain tool draws its actions from both registries, the loader SHALL verify at startup that no action name appears more than once within a single domain across the two files, and SHALL fail startup naming the collision if one is found.

#### Scenario: A duplicate action name within a domain fails startup
- **WHEN** the same action name appears in both registries under the same domain
- **THEN** startup fails with an error naming the domain and the duplicated action

### Requirement: Excluded, flagged, and loaded actions are inspectable
The server SHALL expose an MCP resource that reports, per domain: which actions loaded successfully and are callable, which were excluded and why, and which are callable but of reduced confidence — specifically GET actions that require a path parameter yet were never verified against a real identifier.

#### Scenario: Audit resource reflects current registry state
- **WHEN** a client reads the registry-audit resource
- **THEN** it receives, for every domain, the list of callable actions, the list of excluded actions each with an exclusion reason, and the list of callable-but-unverified actions

### Requirement: One MCP tool per domain, action-addressed, spanning both registries
Each domain name present in either registry SHALL be exposed as exactly one MCP tool, carrying that domain's GET and POST actions in a single flat action namespace. The tool SHALL take a required `action` argument identifying which underlying SDK call to invoke, an optional `params` argument carrying that action's arguments, and optional `cursor`/`limit` arguments for pagination. A domain SHALL NOT be split into separate GET and POST tools, and an individual action SHALL NOT become its own MCP tool.

#### Scenario: Calling a domain tool with a valid action
- **WHEN** a client calls a domain tool with `action` set to one of that domain's callable actions and valid `params`
- **THEN** the tool resolves the action to its registered SDK call, routes it to the GET or POST namespace according to the registry it came from, invokes it, and returns a formatted response

#### Scenario: Calling a domain tool with an unknown action
- **WHEN** a client calls a domain tool with an `action` value not present in that domain's callable action set
- **THEN** the tool returns a structured `invalid_argument` error listing the domain's valid action names, and no SDK call is made

### Requirement: Path parameters are validated strictly before dispatch
Before invoking the SDK, the domain tool SHALL verify that every path parameter the target action declares as required is present in `params`, and that `params` contains no path parameter the action does not declare.

#### Scenario: Missing a required path parameter
- **WHEN** a client calls an action whose registry entry declares a required path parameter, without supplying it in `params`
- **THEN** the tool returns a structured `invalid_argument` error naming the missing parameter, and no SDK call is made

#### Scenario: Supplying an undeclared path parameter
- **WHEN** a client supplies a path parameter the target action does not declare
- **THEN** the tool returns a structured `invalid_argument` error naming the unrecognized parameter, and no SDK call is made

### Requirement: Query-body fields are validated against an allow-list, not against the registry alone
The registry's declared query-body parameters are explicitly not exhaustive — they were harvested from observed responses — and the GET registry declares none at all. The domain tool SHALL therefore accept a query-body field if it is either declared by the target action OR a member of a pinned allow-list of the Prisma SD-WAN query grammar common to `/query` endpoints, and SHALL reject anything else with a structured error. The allow-list SHALL be defined in a single named constant.

#### Scenario: A valid query field the curation pass did not record is accepted
- **WHEN** a client supplies a query-body field that the target action's registry entry does not declare but that is a member of the pinned query grammar
- **THEN** the field is passed through to the SDK call rather than rejected

#### Scenario: A field outside both the entry and the grammar is rejected
- **WHEN** a client supplies a query-body field that is neither declared by the action nor a member of the pinned query grammar
- **THEN** the tool returns a structured `invalid_argument` error naming the unrecognized field, and no SDK call is made

### Requirement: Dispatcher responses conform to the existing envelope contract and name their action
Every response produced by a registry-driven domain tool SHALL be constructed through the same response-formatting functions used by hand-built tools (the shared envelope, cursor pagination, and structured-error construction), with no separate response shape for registry-driven dispatch. Because a domain tool's name identifies only the domain, the response SHALL additionally carry the resolved action name, added to the envelope's existing extension field so the change is additive.

#### Scenario: A collection-returning action is paginated like any hand-built tool
- **WHEN** a registry-driven action returns a list of records larger than one page
- **THEN** the response carries `truncated`, `total_count`, `returned_count`, and a `next_cursor` in the same shape a hand-built tool's collection response carries

#### Scenario: Two actions on the same domain tool are distinguishable
- **WHEN** two different actions on the same domain tool return collections
- **THEN** each response identifies which action produced it

#### Scenario: An upstream SDK error surfaces as a structured error
- **WHEN** the underlying SDK call fails (e.g. non-2xx status)
- **THEN** the domain tool returns a structured error using the existing closed error-code set, not a raw SDK exception or an ad hoc shape

### Requirement: The typed collection key is resolved deterministically
The response envelope's typed collection key is a frozen contract position, and the registry declares no such key. The dispatcher SHALL resolve it by a single documented rule — the override table's declared key if present, otherwise the action name with a trailing query suffix removed, otherwise a generic items key — implemented in one function with a test.

#### Scenario: An action without an override gets a derived key
- **WHEN** an action named with a trailing query suffix returns a collection and has no override-declared collection key
- **THEN** the envelope's typed collection key is the action name with that suffix removed

### Requirement: Per-action overrides attach curated knowledge without a second code path
The dispatcher SHALL consult an override table keyed by `(domain, action)` before formatting a response, applying any declared field projection and appending any declared guidance text, using the same formatting functions as the default path — an override SHALL NOT introduce a separate response-construction path.

#### Scenario: An action with a projection override returns only the projected fields
- **WHEN** a `(domain, action)` pair has a projection override declared
- **THEN** the response's collection items contain only the declared fields, and `projected_fields` is signalled in the response the same way a hand-built tool signals it

#### Scenario: An action with a guidance override surfaces that guidance
- **WHEN** a `(domain, action)` pair has guidance text declared
- **THEN** that guidance is present in the tool's documentation surfaced to the calling agent

### Requirement: Override entries stay in sync with the loaded registry
A test SHALL assert that every `(domain, action)` key present in the override table corresponds to an action that still exists and is still callable in the currently loaded registry.

#### Scenario: An override references a removed or excluded action
- **WHEN** the registry no longer contains an action (or it is now excluded by the safety gate) that an override table entry still references
- **THEN** the sync-check test fails, naming the orphaned override entry

### Requirement: Tools whose SDK call the registry does not cover are not retired
The registries do not cover every SDK call api-mcp exposes today — the metrics, flows, topology, events, and VPN-link-status calls are absent from both. A hand-built tool SHALL only be retired in favour of registry-driven dispatch if the loaded registry actually contains the SDK call it makes. A test SHALL pin the set of tools whose backing SDK calls are registry-uncovered, asserting those calls remain absent from the loaded registry, so the set shrinks only when curation deliberately covers a call.

#### Scenario: A registry-uncovered tool remains exposed
- **WHEN** the server loads with the current registries
- **THEN** every tool whose backing SDK call is absent from both registries is still registered and callable

#### Scenario: Curation covering a previously uncovered call is detected
- **WHEN** a registry pass adds an action for an SDK call that the pinned set records as uncovered
- **THEN** the coverage test fails, prompting a deliberate decision to migrate that tool rather than leaving the duplication in place
