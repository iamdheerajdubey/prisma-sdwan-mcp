## Why

`cli-mcp` today is **stateless and credential-free**. `run_commands`
(`cli-mcp/prisma_sdwan_cli_mcp/server.py:86-141`) takes `host`, `port`, `username`,
`commands`, and exactly one of `password` / `private_key` on **every call**. The
server stores no credential, holds no device inventory, and knows no hostname. It
reads no key files and no local inventory (`RESEARCH.md`, Authentication section).
Secrets live only in the arguments of one in-flight call: `execute_commands` binds
them to a local `secrets` tuple (executor.py:239), redacts them from every error
message (`_safe_error_message`, executor.py:128-133), and clears the connection
kwargs in a `finally` block (executor.py:297).

A proposed alternative — `resolve_cli_target(element_id)`, where the server holds an
`element_id → host/port/credential` mapping — would let callers address devices by
the same `element_id` the controller uses.

That is a real usability gain and a **security posture change**, not a refactor. It
converts cli-mcp from a component that *cannot* leak credentials into a credential
vault with network reach to every ION in the estate. That decision needs a threat
model, not a convenience argument.

## What Changes

This change records a **decision not to build**, with its threat model, so the
question is not reopened without it.

- **Adopt option (a): the current model is kept unchanged.** The caller supplies
  `host`, `port`, `username`, and exactly one of `password` / `private_key` on every
  call. The server stores no target map, no inventory, and no secret.
- **No `resolve_cli_target` tool.** No `element_id` parameter on `run_commands`. No
  mapping file, no new environment variable.
- **No code change to cli-mcp.** The current caller contract is already the decided
  contract.
- **Option (b) is documented and not adopted**; option (c) is documented and rejected
  on technical grounds — see `design.md`. Both are recorded so a future revisit
  starts from the analysis rather than from the convenience argument.
- **The allow-list gate stays first.** Command policy is validated before any
  connection (server.py:117-119). This ordering is the constraint any future revisit
  must preserve.

## Capabilities

### New Capabilities
- `cli-trust-model`: what cli-mcp is trusted to hold, what authorizes a call, and how
  secrets are handled.

### Modified Capabilities
None — no prior specs exist.

## Impact

**Code**
None. The decision is to keep the existing implementation.

**Tests**
None required by this change. The trust-model spec is written against behaviour
cli-mcp already has, so its scenarios are assertions about the current server.

**Deployment**
Unchanged. No new environment variable, no secret store, no controller coupling.

**Explicitly not in scope**
- Any server-held secret, and any server-held device inventory.
- Any `element_id`-based addressing for CLI calls.
- Any coupling to api-mcp.
