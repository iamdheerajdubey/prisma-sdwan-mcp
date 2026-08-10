## 1. Dependency and configuration groundwork

- [x] 1.1 Add `netmiko>=4.5,<5` to `pyproject.toml` dependencies and `requirements.txt`; confirm `pip install -e .` resolves on the build platform and note the added image size.
- [x] 1.2 Add ION credential accessors to `prisma_sdwan_mcp/config.py`: `get_ion_credentials()` returning username plus exactly one of password / private key / passphrase from `PRISMA_ION_USERNAME`, `PRISMA_ION_PASSWORD`, `PRISMA_ION_PRIVATE_KEY`, `PRISMA_ION_PRIVATE_KEY_PASSPHRASE`.
- [x] 1.3 Add CLI tuning accessors to `config.py`: `get_ion_ssh_port()` (default 22), `get_ion_probe_timeout()` (default 3s), `get_ion_connect_timeout()` (default 10s), `get_ion_read_timeout()` (default 300s), `get_ion_max_output_bytes()` (default 40960), `get_ion_max_commands()` (default 10) — each following the existing `_int_env` validation pattern.
- [x] 1.4 Add every new variable to `.env.example` with a comment stating that leaving them unset disables the CLI tool entirely.
- [x] 1.5 Add `ACTIVE_DIAGNOSTIC` annotation dict to `prisma_sdwan_mcp/mcp.py` alongside `READ_ONLY`: `readOnlyHint` false, `destructiveHint` false, `idempotentHint` false, `openWorldHint` true.

## 2. Port the command policy

- [x] 2.1 Copy `cli-mcp/prisma_sdwan_cli_mcp/policy.py` to `prisma_sdwan_mcp/cli/policy.py` near-verbatim; create `prisma_sdwan_mcp/cli/__init__.py`.
- [x] 2.2 Port `cli-mcp/tests/test_policy.py` to `tests/test_cli_policy.py`, adjusting imports only; confirm it passes unchanged.
- [x] 2.3 Add the batch-size limit from `get_ion_max_commands()` to `validate_batch`, rejecting an oversized batch with a structured reason before any per-command evaluation.
- [x] 2.4 Add tests asserting the refusal set explicitly: `debug reboot`, `debug shutdown`, `debug controller reachability`, `config`, `clear`, `file remove`, `curl`, `ssh`, `tcpdump`, `traceroute`, bare `dump`, bare `inspect`, and each shell-metacharacter form (`;`, `&`, backtick, `$(`, `>`, `<`, second `|`).

## 3. Port the SSH execution layer

- [x] 3.1 Copy `cli-mcp/prisma_sdwan_cli_mcp/executor.py` to `prisma_sdwan_mcp/cli/ssh.py`; keep the connection-factory injection point intact so tests stay device-free.
- [x] 3.2 Replace the module's own `get_max_output_bytes()` env read with the `config.py` accessor from task 1.3; keep the per-command cap semantics and the declared-truncation fields exactly as they are.
- [x] 3.3 Add `probe_reachable(host, port, timeout)` using `socket.create_connection`, called before the connection factory; on failure raise a distinct `IONUnreachableError`.
- [x] 3.4 Verify the connection-stage error classification still separates `host_key`, `authentication`, and `connection`, with `unreachable` now decided ahead of all three; add a test for each of the four.
- [x] 3.5 Assert in tests that no connection-stage failure triggers a retry with host-key checking relaxed, with a different credential, or against a different address.
- [x] 3.6 Port `cli-mcp/tests/test_executor.py` to `tests/test_cli_ssh.py`, adjusting imports and the config accessor; confirm the completion-detection, pagination, truncation, and credential-redaction tests all pass.

## 4. Device address resolution

- [x] 4.1 Create `prisma_sdwan_mcp/cli/address.py` with `resolve_device_address(element, site)` built on `tools/common.py`'s `site_element()` and `execute()` — no hard-coded endpoint paths.
- [x] 4.2 Filter `sites_devices.interfaces` to management roles (`used_for` in `controller`, `lan`) and read each candidate's live address from `sites_devices.interfaces_status` (`ipv4_addresses`), requiring `operational_state == "up"`. *Revised from the original config-address approach after live validation — a DHCP interface carries no address in its config record, and `admin_up` filters nothing. See design.md decision 2 and LIVE_VALIDATION Step 7.*
- [x] 4.3 Prefer `controller` over `lan`; a tie inside the preferred role returns candidates rather than falling through to the next role. *`element_status.controller_connection_intf` was tried and rejected: it points at the DHCP public WAN port, not a management address.*
- [x] 4.4 When zero or still-multiple candidates remain, raise `ResolutionError` carrying the candidates so `common.handle_error` maps it to the existing `not_found` / `ambiguous_match` codes.
- [x] 4.5 Add `tests/test_cli_address.py` with a stubbed executor covering: single candidate, multiple candidates broken by `controller_connection_intf`, multiple candidates still ambiguous, and no candidates.

## 5. The `run_commands` tool

- [x] 5.1 Create `prisma_sdwan_mcp/tools/cli.py` registering `run_commands` on the `mcp` singleton with the `ACTIVE_DIAGNOSTIC` annotations and a full operational docstring in the existing house style.
- [x] 5.2 Accept `element` and/or `host`, optional `site`, and `commands`. An explicit `host` always wins and is never refused or cross-checked; `element` then only labels the response. An input error is returned only when neither is supplied. *Per-call credential overrides shipped and were later removed: two credential sources disagreed about what "not set" means, and a tool argument is model-visible. Configuration is now the only source.*
- [x] 5.3 Enforce call order strictly: policy validation → credential availability → address resolution → reachability probe → SSH session. Confirm by test that a policy denial reaches none of the later stages and that a missing credential performs no resolution call.
- [x] 5.4 Map failures onto `error_json` codes: `policy_denied`, `configuration_error`, `device_unreachable` (details carry the address and port tried, non-retryable), `host_key_unverified`, `device_authentication_failed`, `device_connection_failed`; resolution failures flow through `common.handle_error`. *`rate_limited` added after live validation — see 10.6.*
- [x] 5.5 Compute the effective per-command cap as `min(configured_cap, response_budget // len(commands))` with a floor, then return the batch via `single_json` so the oversized-object outline path is never reached.
- [x] 5.6 Route the assembled payload through `runtime.safety.redact` before returning, consistent with every other response path.
- [x] 5.7 Include the resolved element name, element ID, and address actually used in every successful response.
- [x] 5.8 Register the module in `prisma_sdwan_mcp/server.py`'s tool-registration import line.

## 6. Policy resource and prompt

- [x] 6.1 Port the `prisma-cli://policy` resource into `prisma_sdwan_mcp/resources.py`, generated from the same `policy.py` constants the validator evaluates.
- [x] 6.2 Add a test asserting the resource's advertised families and exact forms are derived from the validator's own constants, so published policy cannot drift from enforcement.
- [x] 6.3 Port the `troubleshoot_ion` prompt into `prisma_sdwan_mcp/prompts.py`, updated for name-based addressing, environment credentials, and the `device_unreachable` failure mode.

## 7. Tool-level tests

- [x] 7.1 Create `tests/test_cli_tool.py` covering: partial batch success with independent per-command results, batch-level errors returning an empty result list, first-line-only device error detection, and per-command truncation declaring both byte counts.
- [x] 7.2 Add a test asserting `run_commands` is advertised as not read-only and not idempotent, and that the total registered tool count is 27.
- [x] 7.3 Add a test asserting no credential value appears anywhere in a returned response, including on every error path.
- [x] 7.4 Run the full dependency-free suite (`PYTHONPATH=. pytest -q`) and confirm no existing test changed behavior.

## 8. Documentation

- [x] 8.1 Copy `cli-mcp/RESEARCH.md` to `docs/ION_CLI_RESEARCH.md`, preserving its stated verification gaps (pagination marker, public-key authentication).
- [x] 8.2 Update `CLAUDE.md`: tool count 26 → 27, the "all tools are read-only" statement corrected to name `run_commands` as the active-diagnostic exception, and the mutation boundary restated as still intact.
- [x] 8.3 Update `docs/ARCHITECTURE.md` with the CLI path — policy gate, address resolution, reachability probe, SSH session — as a second lane alongside the registry executor.
- [x] 8.4 Update `docs/TOOL_CATALOG.md` with `run_commands`, its arguments, its error codes, and the explicit note that command selection belongs to the calling agent's skills, not this server.
- [x] 8.5 Update `README.md` with the SSH network prerequisite, the known_hosts requirement, the new environment variables, and the fail-closed behavior when they are unset.
- [x] 8.6 Confirm `capture/` was not copied and that no plaintext device credential exists anywhere in the repository.

## 9. Live validation

- [x] 9.1a Verify against the live tenant which address the controller API can produce for a named element. **Done 2026-08-09** — the `controller_connection_intf` heuristic was wrong and has been replaced by `used_for` role + interface status record; 14/15 sampled elements resolve to exactly one address. Recorded in `docs/LIVE_VALIDATION.md` Step 7.
- [x] 9.1b Verify that the resolved address is actually SSH-reachable from wherever MCPv2 runs. **Done 2026-08-10** — element AEDXB01-SDE01 resolved to 10.64.167.4 and SSH sessions succeeded from the Linux host. Resolution needed a fix first: the element had no `controller` interface and three live `lan` addresses, two of them RFC 6598 service-link space. See `docs/LIVE_VALIDATION.md`.
- [ ] 9.2 Verify the `--More--` pagination marker against real oversized `dump` output. **Still unexercised** — `dump interface status all` returned 11,568 bytes in one read with no pagination marker, so the paging loop has never run against a real device. A larger command is needed.
- [ ] 9.3 Verify whether the target ION deployment accepts public-key authentication. **Still untested** — all seven live runs used password authentication.
- [ ] 9.4 Verify that `device_unreachable` fires correctly and quickly from a host with no route to the device. **Not directly observed for the tool's own error path** — the probe's pre-flight socket check failed fast against an unroutable address, but `run_commands` itself was never driven at one.
- [x] 9.5 Record the outcomes in `docs/LIVE_VALIDATION.md`. **Done 2026-08-10** — seven probe runs against an ION 1200 (software 6.3.6-b9); the device's verbatim output from those runs is kept as `tests/fixtures/ion/direct_*.txt`.

## 10. Defects found only against real hardware

Each of these made `run_commands` unusable or silently wrong, and none was reachable by a unit test. All are fixed with regression tests using the captured bytes.

- [x] 10.1 A blank `ION_PRIVATE_KEY=` in the stock `.env` refused a valid password: `os.getenv` returns `''`, not `None`, and the "exactly one of password or key" check read blank as configured.
- [x] 10.2 A configured `known_hosts` file was never loaded — netmiko needs `alt_host_keys=True` beside `alt_key_file`, and only the latter was set, leaving no host keys loaded at all. Failed closed, so never a security hole.
- [x] 10.3 ANSI colour in the ION prompt made the completion pattern match the command echo, so the tool returned the caller's own command as the device's answer with `status: "ok"`.
- [x] 10.4 A rejected command was reported as successful: the ION echoes prompt and command twice before its error text.
- [x] 10.5 Name resolution could not pick between three live `lan` addresses; RFC 6598 (100.64.0.0/10) service-link addresses are now excluded.
- [x] 10.6 A device-side SSH rate limit was reported as a permanent failure. Measured: four consecutive sessions succeeded, the fifth was reset before the version string. Now `rate_limited`, and retryable.
- [x] 10.7 Regression coverage that needs no device: `tests/test_ion_replay.py` runs the captured device bytes in `tests/fixtures/ion/` through the real code path, as an ordinary part of the suite. Mutation-verified.
