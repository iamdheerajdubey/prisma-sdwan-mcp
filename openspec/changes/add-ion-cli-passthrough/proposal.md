## Why

MCPv2 can read everything the Prisma SD-WAN **controller** knows about a device — configuration, state, status, metrics — but nothing the **device itself** knows. When the controller says a WAN path is down, the next question is always on the ION: what does `dump interface status all` show, what does `inspect wanpaths` say, can it `ping` its gateway. Today that means a human SSHing in, which ends the AI-assisted troubleshooting session at exactly the point it becomes useful.

A working ION CLI passthrough MCP server already exists at `D:\Prisma-MCP\cli-mcp` (785 lines of code, 829 lines of tests): a deny-by-default command policy, a stateless Netmiko session per call, strict SSH host-key checking, per-command output caps, and credential redaction on error paths. It is sound and does not need rewriting. What it cannot do standalone is the one thing MCPv2 is built for: turn *"the Branch-42 ION"* into an address. Standalone, the caller must already know the device's IP — which is precisely the lookup the AI came here to avoid.

Folding it into MCPv2 rather than running it as a second server is what closes that gap: one server that resolves a site name to an element, an element to a reachable address, and then runs the approved command on it.

## What Changes

**New tool: `run_commands`** — tool count 26 → 27. Runs a batch of policy-approved ION CLI commands on one device over SSH and returns one independent result per command.

- **Command policy ported as-is.** Deny-by-default. The `dump` and `inspect` families (matched by root + safe-argument character class, plus at most one `| grep` filter), and three exact diagnostic forms: `ping <interface> <host> [args="-c 1..10"]`, `tcpping <interface> <host>:<port>`, `dig <interface> <dns-server> <hostname>`. Everything else — `debug`, `config`, `clear`, `file remove`, `curl`, `ssh`, `tcpdump`, `traceroute` — stays unmatched and therefore denied. The gate runs before any connection is opened; one denied command rejects the whole batch.
- **Device addressing by name, not IP.** `run_commands` accepts `element` (a name the existing resolver understands) *or* an explicit `host`. Name resolution reuses `ResourceResolver` and the registry's `sites_devices.interfaces` action to find candidate addresses. Consistent with the resolver's existing contract: an ambiguous result returns candidates, never a silent guess.
- **Device credentials move to the environment.** New `PRISMA_ION_USERNAME` / `PRISMA_ION_PASSWORD` / `PRISMA_ION_PRIVATE_KEY` / `PRISMA_ION_PRIVATE_KEY_PASSPHRASE`, read through `config.py` like every other MCPv2 secret. **BREAKING** relative to the standalone server, where the password was a `run_commands` argument: a tool argument is model-visible and lands in the conversation transcript, which is typically logged. Per-call credential arguments are retained only as an explicit override for callers that need them.
- **Smart fail-safe when the device is unreachable.** A distinct `unreachable` error type, decided by a short preflight TCP probe before Netmiko is invoked, so a deployment with no network path to branch management addresses fails in seconds with an actionable message naming the address and port tried — rather than stalling on a connect timeout or reporting a misleading authentication failure. Failure never degrades security posture: no host-key auto-trust, no credential-bearing retry, no fallback to a weaker check.
- **Missing device credentials fail closed at the tool boundary.** No credentials configured and none supplied per call means a structured configuration error and no connection attempt at all. A deployment that never sets the ION variables can never open an SSH session.
- **Responses join the existing envelope.** CLI results go through `response.py` and `safety.py` like every other MCPv2 response, so redaction and byte budgeting are not reimplemented in a second place.
- **The read-only boundary statement changes.** `ping`/`tcpping`/`dig` send real packets from the device. They modify nothing, but `run_commands` therefore declares `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: false` — the first tool in MCPv2 that is not `READ_ONLY`. The mutation boundary itself is unchanged: no controller write endpoint, no device configuration change, no server-side state.

**Deliberately excluded from the import:** the standalone `server.py`, `pytest.ini`, `requirements.txt` (merged into `pyproject.toml`), and the entire `capture/` directory — its `capture/config.py` holds a live ION host, username, and password in plain text. It was a one-off research harness; its findings are already written up in `RESEARCH.md`, which does move over.

## Capabilities

### New Capabilities
- `ion-cli-policy`: Which ION CLI commands may run and which are refused — the deny-by-default allowlist, family matching for `dump`/`inspect`, the three exact diagnostic forms, the single supported output filter, injection resistance, and batch rejection semantics.
- `ion-cli-execution`: How an approved batch actually reaches a device and comes back — device addressing by element name, credential sourcing and fail-closed behavior, SSH host-key strictness, the error taxonomy including unreachable, per-command completion and output caps, and per-command result independence.

### Modified Capabilities
<!-- None. `openspec/specs/` holds no baseline specs; nothing existing changes its requirements. -->

## Impact

**Code (new)**
- `prisma_sdwan_mcp/cli/policy.py` — ported from `cli-mcp/prisma_sdwan_cli_mcp/policy.py`, substantially unchanged.
- `prisma_sdwan_mcp/cli/ssh.py` — ported from `cli-mcp/prisma_sdwan_cli_mcp/executor.py`; renamed to avoid colliding with MCPv2's `executor.py`, which is the API capability executor and unrelated.
- `prisma_sdwan_mcp/cli/address.py` — element name → candidate SSH addresses, via the resolver and `sites_devices.interfaces`.
- `prisma_sdwan_mcp/tools/cli.py` — registers `run_commands` on the existing `mcp` singleton.
- `tests/test_cli_policy.py`, `tests/test_cli_ssh.py`, `tests/test_cli_tool.py` — ported from the standalone suite, which already injects a fake connection factory and needs no device.

**Code (modified)**
- `prisma_sdwan_mcp/server.py` — one import added to the tool-registration line.
- `prisma_sdwan_mcp/config.py` — ION credential and timeout accessors.
- `prisma_sdwan_mcp/mcp.py` — an `ACTIVE_DIAGNOSTIC` annotation set alongside `READ_ONLY`.

**Dependencies**
- Adds `netmiko>=4.5,<5`, which pulls `paramiko` and `cryptography`. First native-extension dependency in the project; grows the Docker image and adds a wheel-availability constraint on the build platform.

**Deployment**
- Introduces a second, entirely different network requirement: outbound SSH from wherever MCPv2 runs to each ION's management address, alongside the existing outbound HTTPS to the SASE API. A deployment that has one does not necessarily have the other. This is why `unreachable` is a first-class error type rather than a generic connection failure.

**Docs**
- `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/TOOL_CATALOG.md`, `README.md`, `.env.example` — tool count, the read-only statement, the new env vars, and the SSH network requirement.
- `docs/ION_CLI_RESEARCH.md` — `RESEARCH.md` carried over, including its stated verification gaps (ION pagination markers and public-key SSH acceptance are both unconfirmed against a real device).

**Not affected**
- All 26 existing tools, the registry, the catalog, the resolver's existing behavior, and the API executor. Nothing in the current call path changes.
- The mutation boundary. No controller write endpoint is reachable, no device configuration can be changed, and the server still holds no state between calls.
