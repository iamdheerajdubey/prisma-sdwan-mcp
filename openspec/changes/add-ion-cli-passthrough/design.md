## Context

MCPv2 is a registry-first, read-only MCP server over the Prisma SD-WAN **controller API**. It authenticates once from environment credentials, holds no state between calls, and routes every response through a shared envelope (`response.py`) and a recursive secret redactor (`safety.py`). Its resolver turns operator-facing names into IDs and refuses to guess when a name is ambiguous.

A separate working server at `D:\Prisma-MCP\cli-mcp` talks to the **device** over SSH. It is small and sound: `policy.py` (159 lines) is a deny-by-default command allowlist, `executor.py` (359 lines) is a stateless Netmiko session with strict host-key checking and per-command output caps, `server.py` (267 lines) is a FastMCP entrypoint exposing a single `run_commands` tool. Its test suite (829 lines) already injects a fake connection factory, so it runs with no device present.

The two servers were written as siblings, and the CLI one is explicitly documented as not owning command selection — that is the calling agent's job. Its structural weakness is addressing: it requires the caller to already know the device's IP, which is exactly the lookup MCPv2 exists to perform.

Constraints this design has to respect:
- The architectural rule in `CLAUDE.md`: the registry owns API facts, tools own operator meaning. A tool must not hard-code SDK endpoint details the registry already knows.
- The mutation boundary: no controller write endpoint, no server-side persistent storage.
- The redaction rule: every response reaching the model passes through `safety.py`.
- MCPv2's current network requirement is outbound HTTPS to one cloud API endpoint. SSH to branch device management addresses is a materially different requirement that many deployments will not satisfy.

## Goals / Non-Goals

**Goals:**
- One MCP server exposing both controller reads and device CLI reads, with a single entrypoint, one test suite, and one response envelope.
- Address a device by the name the operator already uses, reusing the existing resolver rather than a parallel lookup path.
- Preserve the command policy's security properties exactly: deny-by-default, pre-connection validation, no shell chaining, strict host-key checking.
- Move device credentials out of the model's view.
- Fail fast, specifically, and safely when the device cannot be reached, so an unsupported deployment is diagnosed in seconds rather than misdiagnosed as an authentication or device problem.

**Non-Goals:**
- Command selection. Which `dump` subcommand answers a symptom stays the calling agent's job, driven by its skill files. No decision tree, no symptom→command mapping, no per-command typed tools.
- Parsing ION CLI output into structured records. Output is returned as text. ION CLI output is not consistently structured, and a parser would be a permanent maintenance liability against an undocumented format.
- Connection pooling, session reuse, an inventory file, a vault, or any device-state cache. The server stays stateless.
- Any device write. `config`, `clear`, and the `debug` family stay unmatched and therefore denied.
- Expanding the policy. The three active diagnostics are the ceiling for this change.

## Decisions

### 1. Fold into `prisma_sdwan_mcp` as a sub-package, not a nested second server

`prisma_sdwan_mcp/cli/{policy,ssh,address}.py` plus `tools/cli.py`, registering on the existing `mcp` singleton from `mcp.py`. The standalone `server.py`, `pytest.ini`, and `requirements.txt` are dropped.

*Why:* the imported code is three modules. Keeping it as a nested package means two entrypoints, two test configurations, and two response conventions inside one repo, permanently. More importantly, a nested standalone server cannot reach the resolver without importing across a boundary that was never designed for it — which forfeits the entire reason for merging.

*Alternative rejected — run both servers side by side:* zero merge work, and the AI host can mount both. But name resolution is then impossible: the AI would have to call MCPv2 to get an element, guess which returned field is an SSH address, and hand it to the other server. That guess is exactly what MCPv2's resolver contract forbids.

*Naming:* `executor.py` → `cli/ssh.py`. MCPv2 already has `executor.py` (the API capability executor). Two files named `executor.py` doing unrelated things in one package is a permanent reading tax.

### 2. Address resolution is candidate-producing, and explicit `host` always wins

**Revised after a live read against a real ion 5200. The original chain below was wrong; what replaced it is described first.**

Resolution order:
1. Explicit `host` — no lookup at all, and it wins outright when `element` is also supplied. A caller-supplied address is authoritative: the server does not refuse it, substitute it, or cross-check it. This is the escape hatch for out-of-band management networks the controller API does not know, and for an AI that already has the address in hand.
2. `element` name → `resolver.site_element()` (existing) → `site_id` + `element_id`.
3. `sites_devices.interfaces` for that element → keep only interfaces whose `used_for` is a management role, most-preferred first: `controller`, then `lan`.
4. For those few interfaces only, `sites_devices.interfaces_status` → take `ipv4_addresses`, requiring `operational_state == "up"`.
5. Exactly one live address in the most-preferred role wins. A tie inside that role returns candidates and does **not** fall through to the next role. No management role yielding an address returns the rejected interfaces with their operational state, so the reason is visible.

*Why the address comes from the status record, not the config record:* an interface's configuration carries an address only when `ipv4_config.type` is `static`. A DHCP interface's config is literally `{"type": "dhcp"}` with no address anywhere. The status record carries `ipv4_addresses` for **both** kinds, and it is the live address rather than the intended one. Reading config would silently skip every DHCP interface.

*Why `used_for` rather than `admin_up`:* on the sampled device `admin_up` was true on nearly every interface including physically down ports, so it filtered nothing — 16 candidates, including service-link tunnel endpoints, an HA link, and duplicate WAN addresses. `used_for` cut that to 3, and preferring `controller` left exactly 1. Across a 15-element sample, 14 resolved to a single address; the one failure was an unprovisioned spare, which is the correct answer.

*Why step 4 is scoped to management roles:* status is a per-interface call. The sampled device has 33 interfaces; fetching status for all of them would be 33 calls per command batch. Filtering by role first makes it 2-3.

**Superseded original:** collect *configured* addresses from `admin_up` interfaces, then break ties using `element_status.controller_connection_intf`. Both halves failed against real data. `controller_connection_intf` pointed at the DHCP public WAN port the device happens to reach the cloud through — the one interface with no readable config address, and the wrong target for an SSH management session regardless. The tie-breaker therefore matched nothing and the call failed with a 16-way ambiguity.

*Alternative rejected — a static name→IP map in configuration:* works for out-of-band networks the API cannot see, but duplicates inventory the controller already owns and drifts. The explicit `host` argument covers the same case without introducing a second source of truth.

### 3. Reachability is decided by a stdlib TCP probe before Netmiko is invoked

`socket.create_connection((host, port), timeout=PROBE_TIMEOUT)` with a short default (3s), then close it. Success → proceed to the real SSH session. Failure → `device_unreachable`, naming the address and port tried and stating that this server may have no network path to the device.

*Why:* this is the "fail safely and smartly" requirement. Without it, a deployment with no route produces a 10-second Netmiko connect timeout whose exception text classifies as a generic connection failure — indistinguishable to the AI from a device problem, which sends it troubleshooting the wrong thing. The probe converts the single most likely deployment-level failure into a specific, actionable, fast answer.

*Why stdlib:* `socket` is already imported by everything underneath. Nothing needs to be added.

*Why `unreachable` is reported as non-retryable:* in its expected cause — no network path from this deployment to branch management addresses — retrying burns the probe timeout again and never succeeds. A caller that believes the failure was transient can still call again explicitly.

*Cost:* one extra TCP connection per call, negligible against an SSH handshake.

### 4. Credentials come from `config.py`, with per-call override retained

`PRISMA_ION_USERNAME`, `PRISMA_ION_PASSWORD`, `PRISMA_ION_PRIVATE_KEY`, `PRISMA_ION_PRIVATE_KEY_PASSPHRASE`, read through `config.py` alongside `PAN_CLIENT_ID` and friends. The per-call arguments survive as an explicit override.

*Why:* a tool argument is authored by the model and recorded in the conversation transcript, which is typically persisted and often shipped to a logging backend. Moving the device password to the environment removes it from that path entirely and matches how every other MCPv2 secret is handled. The standalone server's per-call model was defensible for a server with no configuration of its own; MCPv2 already has one.

*Why keep the override:* multi-tenant or per-engagement callers that genuinely hold different device credentials per call would otherwise be locked out, and removing it buys nothing — the environment path is used by default.

*Fail closed:* no credential from either source means a `configuration_error` and no resolution call, no probe, no connection. A deployment that never sets the ION variables cannot open an SSH session at all, which is the safe default for the many deployments that will never use this tool.

### 5. Errors join MCPv2's existing `structured_error` vocabulary

The standalone server returns its own `{"status", "error": {"type"}, "results"}` shape. Inside MCPv2 that becomes `error_json(...)` with codes: `policy_denied`, `configuration_error`, `device_unreachable`, `host_key_unverified`, `device_authentication_failed`, `device_connection_failed`, plus the existing `not_found` / `ambiguous_match` for resolution, which come free from `common.handle_error`.

Per-command results keep their own `status` / `output` / `error` / `truncated` fields *inside* the success payload. Those are data — a device rejecting one command is not a transport failure.

*Why:* one error vocabulary per server. An AI that has learned MCPv2's error shape should not have to learn a second one for one tool.

### 6. The response budget is divided across the batch, not applied after the fact

Batch size is capped (10 commands). The effective per-command output cap is `min(configured_cap, response_budget // len(commands))` with a floor.

*Why:* `single_json` handles an oversized payload by replacing large values with an outline — which for CLI output means replacing the actual command output with a description of it. That is the wrong failure for this tool. Dividing the budget up front means the envelope never trips that path, and each command's truncation is declared explicitly with the byte counts, as the spec requires.

### 7. `run_commands` is the first tool that is not `READ_ONLY`

A new `ACTIVE_DIAGNOSTIC` annotation set in `mcp.py`: `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: false`, `openWorldHint: true`.

*Why:* `ping`/`tcpping`/`dig` send real packets from the device. Claiming `readOnlyHint` would tell clients they may auto-approve a call that generates network traffic, and two identical pings are two real probes, so `idempotentHint` is false too. Nothing here changes device or controller configuration, hence `destructiveHint` stays false.

*Alternative rejected — drop the three diagnostics to keep every tool `READ_ONLY`:* preserves a clean one-line claim in the docs at the cost of the only commands that can prove a path is broken from the device's own perspective. Honest annotations plus a corrected doc sentence is the better trade.

### 8. The imported tests come across; `capture/` does not

`tests/test_cli_policy.py`, `tests/test_cli_ssh.py`, `tests/test_cli_tool.py`, ported from the standalone suite. They inject a fake connection factory and need no device, so they run in the existing dependency-free core suite.

`capture/` is excluded outright: `capture/config.py` contains a live ION host, username, and password in plain text. It is gitignored in its own repository, but a directory copy is exactly how that protection is lost. It was a one-off research harness whose findings are already written up in `RESEARCH.md`, which does move to `docs/ION_CLI_RESEARCH.md`.

## Risks / Trade-offs

**The resolved address may not be SSH-reachable** → resolution now picks the interface the configuration marks as a management role and confirms it is operationally up, which is the strongest signal the controller exposes. It is still not proof that MCPv2's own host can route to that address — that is a network fact, not an API fact, and `device_unreachable` is what reports it. Explicit `host` bypasses resolution entirely and is documented as the fallback. Resolution never guesses between candidates.

**Key-based redaction does not see secrets inside CLI text** → `safety.py` redacts by dictionary key. Command output is one large string, so an SNMP community string or key material appearing in `dump` output passes through untouched. Mitigation is the operator's account: the policy permits only families the vendor documents as available to read-only roles, and deployments should use a read-only ION account. A line-level text scrubber is deliberately **not** built — a partial scrub of an undocumented output format would create false confidence in exactly the case where it fails.

**SSH is a new and much broader network requirement** → this is why `device_unreachable` is a first-class error with a message that names the deployment cause. Documented as a prerequisite in `README.md`; the fail-closed credential check means a deployment that does not configure ION credentials never attempts an SSH connection.

**`netmiko` brings `paramiko` and `cryptography`, the project's first native-extension dependency** → grows the Docker image and adds a wheel-availability constraint on the build platform. Accepted: SSH device access is the feature, and writing an SSH client is not on the table.

**Blocking SSH I/O inside an async MCP server** → a single `run_commands` call holds a connection for as long as the device takes, up to the 300s hang ceiling. Under stdio transport with one caller this is invisible; under HTTP transport with concurrent callers it occupies a worker. Not addressed in this change; if it becomes real, the fix is offloading the SSH call to a thread, not a connection pool.

**Two policies could drift** — the browsable policy resource and the enforcing validator → mitigated structurally by generating the resource from the same constants the validator evaluates, as the standalone server already does. Preserved on import, and asserted by a test.

**Ported code may quietly diverge from its origin** → the origin repository stays available; the port is deliberately near-verbatim for `policy.py` so a future diff is meaningful. Changes on import are confined to naming, credential sourcing, error shape, and the reachability probe.

## Migration Plan

No migration. This is additive: 26 tools become 27, nothing in the existing call path changes, and a deployment that sets no ION credentials behaves exactly as it does today.

Rollback is removing one import line from `server.py`, which unregisters the tool and leaves the rest of the server untouched.

## Open Questions

1. ~~**Which interface address is actually SSH-reachable?**~~ **Partially answered.** A live read against a real ion 5200 settled which address the API can produce: the `used_for` role plus the interface status record, as described in decision 2 — 14 of 15 sampled elements resolve to exactly one address. What remains open is whether MCPv2's host can actually *route* to those addresses (mostly RFC1918 management ranges); that is answered by a real SSH attempt, not by the API.
2. **Is the `--More--` pagination marker real for the target ION software version?** The origin `RESEARCH.md` flags this as an explicit verification gap. The `capture/` harness output in the origin repo suggests it is real; the paging code is defensive and bounded either way.
3. **Does the target ION deployment accept public-key SSH authentication?** The vendor documentation verifies username/password only. Key support is implemented but unverified.
4. **Where will MCPv2 actually run once this ships?** If it is containerized in a cloud environment with no path to branch management networks, this tool is inert there regardless of correctness — which is a deployment decision, not a code one.
