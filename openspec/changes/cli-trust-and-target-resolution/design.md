## Context

### What cli-mcp is today

One tool. `run_commands(host, port, username, commands, password | private_key,
private_key_passphrase, known_hosts_file)` — server.py:86-95.

Three properties define its security posture:

1. **Deny-by-default command policy, validated before connecting.**
   `validate_batch(commands)` runs first (server.py:117-119); a denied batch returns
   without a socket ever opening. Only the `dump` and `inspect` *families* and the
   three exact diagnostic forms `ping` / `tcpping` / `dig` are permitted
   (policy.py:33-66). Family matching, not subcommand enumeration, is deliberate —
   the vendor already classifies at the family level (policy.py:1-18).
2. **Strict SSH host-key checking.** `ssh_strict=True` with
   `system_host_keys=True` unless `known_hosts_file` is given
   (executor.py:114-119). An unknown or mismatched host key aborts **before
   credentials are sent**, surfacing as `error.type: "host_key"`
   (executor.py:258-263).
3. **No stored state.** No credential, no inventory, no hostname. Secrets exist only
   as call arguments, are redacted from every error (executor.py:128-133), and the
   connection kwargs are cleared on exit (executor.py:297).

The tool annotations are honest about what this is: `readOnlyHint: False`, because
`ping`/`tcpping`/`dig` send real packets from the device (server.py:72-85).

### The proposal

`resolve_cli_target(element_id)` — the server holds `element_id → host/port/credential`
so callers need not know hostnames or secrets.

---

## Goals / Non-Goals

**Goals**
- Let callers address devices by `element_id`, the identifier the controller and
  api-mcp already use.
- Support multiple IONs per site, both ends of an AnyNetLink, and HA pairs.
- Do not turn cli-mcp into a credential vault.
- Keep cli-mcp deployable standalone by any consumer, with no assumption about which
  agent is calling it.

**Non-Goals**
- Server-held secrets. Rejected below.
- Any dependency on api-mcp or on the controller. cli-mcp must remain independently
  deployable.
- Widening the command allow-list. Target resolution is orthogonal to it.
- Deciding which commands to run. That is the caller's job, and cli-mcp's own prompt
  says so (server.py:209-212).

---

## Threat model

**Assets.** ION SSH credentials; the ability to execute commands on IONs; device
configuration and topology data readable via `dump`/`inspect`; the ability to
generate network traffic from a device via `ping`/`tcpping`/`dig`.

**Adversaries, in rough order of likelihood:**

| # | Adversary | Reachable today | Reachable with server-held secrets |
|---|---|---|---|
| A1 | A prompt-injected agent holding a legitimate MCP session — malicious content in device output, a controller alarm message, a ticket body | Only devices whose credentials the *operator* already supplied for that call | **Every ION in the map**, unauthenticated from the agent's side |
| A2 | A compromised or malicious MCP client on the same host | Whatever it can also steal from wherever the operator keeps secrets | Every ION, via an already-authorized local tool call |
| A3 | Someone with read access to the cli-mcp host's filesystem or process memory | Nothing at rest | The whole credential store |
| A4 | An on-path network attacker impersonating an ION | Blocked by strict host-key checking (executor.py:114-119) | Same — unchanged |
| A5 | An operator running an unsafe command by mistake or by instruction | Blocked by the allow-list (server.py:117-119) | Same — unchanged |

**The load-bearing observation: caller-supplied credentials are a per-call
authorization check.** Today, holding an MCP session to cli-mcp grants nothing. To
reach a device you must also possess that device's credential *at that moment*. A
prompt-injected agent (A1) that decides to enumerate every ION in the estate cannot,
because it does not have the secrets. The inconvenience of passing credentials every
call **is** the security property. A design that removes the inconvenience removes
the property with it.

**What changes if the server holds secrets.** Authorization collapses to "can you
open an MCP session". For a stdio-transport server that is "can you run a process on
this host"; for the HTTP/SSE transports the server also offers (server.py:219-226,
`--host 0.0.0.0` by default) it is "can you reach this port" — and cli-mcp has no
authentication layer of its own. Blast radius goes from one device to every device in
the map, and it does so for A1, A2, and A3 simultaneously.

**What does not change.** Host-key checking (A4) and the allow-list (A5) are
orthogonal to where credentials come from. They protect against a different class of
attack and stay exactly as they are under every option.

---

## Options

### (a) Keep caller-supplied credentials unchanged

- **Buys:** nothing new.
- **Costs:** the caller must know each device's hostname/IP, port, and username, and
  must map `element_id → host` itself. For a multi-ION site or both ends of an
  AnyNetLink, that mapping is exactly the kind of stateful lookup a consumer should
  not be reinventing — and every consumer reinvents it differently.
- **Security:** the current posture. No new attack surface.

### (b) Server resolves non-secret target data only  ← RECOMMENDED

The server maps `element_id → {host, port, username}` from an operator-provided JSON
file pointed to by an environment variable. **The secret is still supplied by the
caller on every call.**

- **Buys:** callers address devices by `element_id`. Multiple IONs per site, both
  ends of an AnyNetLink, and HA pairs are all just distinct map entries. Per-element
  `username` is supported (a per-element *credential* is not, and does not need to
  be: the caller supplies the matching secret).
- **Costs:** the server now holds a device inventory. That inventory is
  reconnaissance value — an attacker who reads it learns the estate's addressing.
  That is a real but far smaller loss than credentials, and it is information an
  operator's DNS, CMDB, and the controller itself already carry.
- **Security:** per-call authorization is **preserved intact**. A prompt-injected
  agent can enumerate hostnames it could not before; it still cannot log in to any of
  them. A1's blast radius is unchanged.
- **Standalone:** with no map configured, `resolve_cli_target` reports unconfigured
  and `run_commands` works exactly as today. A consumer that never sets the env var
  sees no behaviour change at all.

### (c) Full server-held credential store

Secret manager integration, audit logging, per-element authorization.

- **Buys:** callers need no secrets at all. Central rotation. Per-element policy.
- **Costs:** cli-mcp becomes a credential vault — a fundamentally different component
  with a fundamentally larger security budget. To be *safe* rather than merely
  functional it needs: a real secret backend (not a file), a caller-identity concept
  cli-mcp does not have and MCP does not provide, per-element authorization keyed to
  that identity, tamper-evident audit, secret rotation, and an answer for the
  HTTP/SSE transports it already exposes on `0.0.0.0` with no auth. Every one of
  those is a separate project.
- **Security:** without a caller-identity notion, "per-element authorization" is
  unimplementable — there is nobody to authorize. The MCP session is the only
  principal, and it is the same principal for every call. So option (c) in practice
  degrades to "any session reaches any device", i.e. the A1 worst case, while
  *appearing* to have authorization controls. That gap is the strongest argument
  against it.

---

## Decision

**Adopt (a): keep the current model unchanged.** The caller supplies host, port,
username, and the credential on every call. The server stores no target map and no
secret. Decided by the project owner on 2026-08-02, overriding this document's
earlier recommendation of (b).

Nothing is built. This change exists to record *why* nothing is built, so the
question is not reopened without the threat model in front of whoever reopens it.

**The property being preserved:** possession of a credential is a per-call
authorization check. Holding an MCP session to cli-mcp grants nothing on its own —
reaching a device also requires that device's secret, at that moment, from the
caller. An agent that has been prompt-injected cannot enumerate the estate, because
it does not have the secrets and the server cannot supply them.

**Why (b) was not taken despite being the safer half-step.** (b) would have removed
only hostname lookup, not credential handling — a modest convenience gain in
exchange for a new configuration file, a new tool, a new signature on
`run_commands`, and a new failure mode (a stale map pointing a command at the wrong
device). The owner's judgement is that supplying a host alongside a credential the
caller already has to supply is not the friction worth spending that on. Recorded
rather than re-argued.

**Why (c) remains rejected on technical grounds, not only risk appetite.** Option
(c)'s "per-element authorization" is **unimplementable here.** It requires a notion
of *who* is calling, and MCP gives this server exactly one principal — the session —
identical for every call. (c) therefore degrades in practice to "any session reaches
any device" while presenting the appearance of access control, which is worse than
having none, because it would be trusted. Compounding it, `main()` binds
`--host 0.0.0.0` by default for HTTP/SSE transport with no authentication layer
(server.py:226-232): survivable for a server holding no secrets, disqualifying for a
credential vault.

**If this is ever revisited**, the load-bearing constraint is ordering: command
policy must be validated before any target resolution (server.py:117-119), so that a
denied batch never becomes an inventory oracle for an attacker holding neither valid
commands nor credentials.

### Audit logging

Every `resolve_cli_target` and every `run_commands` writes one structured log record
to the server's logger (stderr by default; the operator routes it):

- `event`: `cli.resolve` | `cli.execute`
- `element_id` (when given), `host`, `port`, `username`
- `commands`: the exact validated command strings
- `outcome`: `ok` | `denied` | `error`, with `error.type` on failure
  (`validation` / `policy` / `host_key` / `authentication` / `connection`)
- `duration_ms`

Rationale for what is *in*: without `host` and the commands, the log cannot answer
"what ran where", which is the only question an audit log exists to answer. The
commands are safe to log because they passed the allow-list — the allow-list's
argument patterns (`_SAFE_ARGUMENT`, policy.py:27) already exclude shell
metacharacters and quoting, and nothing caller-supplied is ever placed inside quotes
(policy.py:45-47).

### Secret redaction

- Secrets SHALL NOT appear in any log record, at any level, including exception
  tracebacks.
- The existing redaction in `_safe_error_message` (executor.py:128-133) — which
  replaces each secret with `[redacted]` before clipping — remains the single choke
  point for error text, and applies to audit records too.
- No response field returns a secret. `run_commands` returns only `status`, `error`,
  and per-command `command`/`status`/`output`/`error` (executor.py:264-284).
- A test asserts that a `run_commands` call with a distinctive sentinel password
  produces no log record and no response containing that sentinel.

### Interaction with the read-only allow-list

The allow-list is **independent of and prior to** target resolution. Resolving a
target does not widen what may run on it; there is no per-element policy override and
none is planned — a per-element allow-list would mean a device where more is
permitted, which is precisely the escalation path the deny-by-default design exists
to prevent.

One consequence worth stating plainly: `resolve_cli_target` makes it *easier* to
reach many devices in sequence. The allow-list bounds what each of those calls can
do, but it does not bound how many. Since `ping`/`tcpping`/`dig` generate real
traffic, a caller in a loop is a traffic generator. The mitigation is the audit log
(the behaviour is visible) plus the unchanged requirement that the caller hold a
credential for every device it touches — which is exactly the property option (b) was
chosen to keep.

---

## Risks / Trade-offs

- **The target map is reconnaissance value.** Accepted; it is strictly less valuable
  than credentials and largely duplicates data the operator already publishes in DNS
  and the controller.
- **Operators will be tempted to put passwords in the map.** Mitigated by rejecting
  secret-shaped keys at load with a loud error, not a warning. This is the main way
  option (b) degrades into an unaudited option (c), so the check is a requirement,
  not a nicety.
- **`element_id` semantics for HA pairs are unverified.** Whether each HA member has
  its own `element_id` with its own management address, or the pair shares one, is
  **NEEDS LIVE VERIFICATION**. Relatedly, whether the controller exposes *operational*
  HA role at all — `ELEMENT_KEEP_FIELDS` carries only `spoke_ha_config`
  (api-mcp formatting.py:31) and `get_elements`' docstring tells callers to infer the
  active member from configured priority values (api-mcp inventory.py:130-132), which
  is configuration, not state. If the map is keyed on `element_id` and an HA pair
  shares one, the map cannot express both members. **Verify before freezing the
  interface.**
- **Public-key authentication may not be permitted on every ION.** The vendor
  documents the password flow; `RESEARCH.md` flags key auth as a device/security-policy
  question to validate in the target lab. `element_id`-based targeting does not change
  this, but the map's `username` field is only useful if the deployment's auth method
  is known.
- **The HTTP/SSE transports have no authentication.** `main()` defaults to
  `--host 0.0.0.0` (server.py:226-232). Under option (b) this is survivable — an
  unauthenticated caller still needs device credentials. It would be disqualifying
  under option (c). If option (c) is ever revisited, this must be fixed first.
