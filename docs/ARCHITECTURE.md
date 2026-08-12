# MCP v2 Architecture

## Design rule

**The registry owns API facts. Semantic tools own operator meaning.**

A tool should not hard-code SDK endpoint details when the registry already knows them.

## Two lanes

There are exactly two ways out of this server, and they reach different things:

- the **API lane** reaches the **controller**, through the registry and the `prisma_sase` SDK — 26 of the 27 tools;
- the **CLI lane** reaches the **device itself**, over SSH — only `run_commands`.

They share the resolver and the response envelope. They share nothing else, and the difference is not cosmetic: one returns JSON the server can inspect key by key, the other returns a text blob the server can only pattern-match. Each lane is described below.

## The API lane

```text
AI
 |
 |  operator intent
 v
Semantic tool
 |
 +--> Resolver
 |      site name -> site ID
 |      element name -> element ID -> site ID
 |      policy name -> policy ID
 |
 +--> Workflow logic
 |      one intent may require several capabilities
 |
 v
CapabilityExecutor
 |
 +--> Registry lookup (catalog.py -- 316 actions)
 +--> required path validation
 +--> POST body schema-hint validation
 +--> SDK method binding
 +--> auth/retry client (client.py)
 |
 v
Prisma SASE SDK
 |
 |  JSON response
 v
safety.py    recursive redaction, by dict key
 |
 v
response.py  v2 envelope, cursor pagination, byte budget
```

## Main components

### `catalog.py`

Loads:

- `data/mcp_registry_get_post.json` — 308 generated read-only actions.
- `data/curated_capabilities.json` — 8 hand-curated actions absent from the generated registry.
- `data/registry_overrides.yaml` — human aliases and safety configuration.

It validates unique action IDs, supported methods, SDK call names, and path-parameter definitions.

Catalog discovery is enumeration, not search: the catalog is a fixed 316-entry list across 19 domains, largest domain 43 entries, well within a single response. `list_capabilities()` lists domains; `list_capabilities(domain=...)` lists every action in one, in full, every time. There is no free-text matching against descriptions — an AI's phrasing never has to guess a term that happens to appear in stored prose.

### `executor.py`

Generic API execution engine.

It does not know BGP, NAT, DNS, or Prisma Access semantics. It only knows how to execute an action contract from the registry safely.

SDK method signatures vary. The executor first uses Python signature names when available. If generated SDK wrappers are generic, it falls back to safe GET/POST positional patterns. All known registry actions are read-only.

### `resolver.py`

Converts human names into IDs. Exact IDs and exact names win over substring matches. More than one match produces candidates instead of a guess.

### `safety.py`

Runs on every registry response. It walks the structure and replaces the value of anything *named* like a secret — password, token, session ID, private key, passphrase, SNMP community. That is the right shape for the controller API, whose responses are JSON with meaningful key names, and it is the wrong shape for device CLI text; see `cli/redact.py`.

### `response.py`

Provides the stable v2 response contract, cursor pagination, byte-budget enforcement, and structured errors.

### `client.py`

Handles authentication end-to-end:

- lazy login;
- token lifetime handling;
- re-authentication on 401/403;
- bounded exponential backoff for 429 and 5xx;
- retry accounting.

## The CLI lane: ION over SSH

`run_commands` reaches the device itself, through a parallel path (`prisma_sdwan_mcp/cli/`) that shares the resolver but not the executor:

```text
AI
 |
 |  operator intent
 v
run_commands (tools/cli.py)
 |
 +--> cli/policy.py   -- deny-by-default allowlist, evaluated before anything else
 +--> config.py       -- ION credential/timeout accessors (server config only)
 +--> cli/address.py  -- element name -> live management address, via the
 |                        resolver + the registry (no hard-coded endpoints)
 +--> cli/ssh.py      -- TCP probe -> strict host-key check -> Netmiko session
 |                        -> per-command output cap
 +--> cli/redact.py   -- pattern redaction of the device's text output
 |
 v
safety.py    key-based redaction over the payload's own keys
 |
 v
response.py (single_json)
```

Order is load-bearing: policy validation, then credential availability, then address resolution, then the reachability probe, then the SSH session itself. A policy denial never reaches resolution; a missing credential never triggers a resolution call — see `docs/ION_CLI_RESEARCH.md` for the command-policy research this was built from.

Nothing here touches `executor.py`. Only `cli/address.py` calls back into the registry, through `tools/common.py`, so no endpoint path is hard-coded in this lane either. The response uses the same `response.py` envelope as every other tool; there is no second response contract.

### `cli/policy.py`

An allowlist, not a deny list. The vendor documents `dump` and `inspect` as display-only families, so those families are matched whole rather than enumerated subcommand by subcommand (an enumeration drifts). On top of that sit three exact forms — `ping`, `tcpping`, `dig` — matched as complete commands, so allowing them does not open the `debug` family they are documented under. An unmatched command is refused by construction, and one denied command rejects the whole batch before a connection is opened.

### `cli/address.py`

Element name -> site -> element -> interfaces -> one live management address. Shaped by live reads, not by the API schema:

- the *configured* address exists only on static interfaces, so the live `ipv4_addresses` from the interface status record is the only source read;
- `used_for` in (`controller`, `lan`) is what separates a management address from a public WAN port, an HA link, or a tunnel endpoint;
- `operational_state == "up"` is the liveness signal — `admin_up` is true on nearly everything, including physically dead ports;
- RFC 6598 shared address space (100.64.0.0/10) is excluded: Prisma uses that range for service-link and tunnel endpoints, so an address in it is internal plumbing rather than somewhere an operator can SSH to. On a live ion 1200 that exclusion is what turns three ambiguous candidates into the one address that answers.

It never guesses. More than one surviving candidate raises `ResolutionError` carrying the candidates, matching the resolver's ambiguity contract. An explicit `host` bypasses the module entirely.

### `cli/redact.py`

`safety.py` still runs on this lane's payload, and is structurally incapable of covering the part that matters — not by oversight. It redacts by dict key, while CLI output arrives as one text blob under the key `output`. `output` is not a sensitive name, so the recursive redactor descends to the string and hands it back untouched. A secret sitting in free text is not keyed on by anything; it has to be matched.

So this module does the other half: pattern-level redaction over the text itself — PEM private-key blocks, Unix password hashes, `keyword VALUE` assignments (SNMP community, RADIUS/TACACS key, password, PSK, bearer token), and credentials embedded in a URL. It runs after truncation and after error classification, so neither decision is made on rewritten text, and it reports whether it changed anything so a caller can tell "nothing was here" from "something was here and is hidden".

Both exist because the two lanes carry secrets in structurally different places. Neither is a proof: a redactor is a filter over what was anticipated, which is why the command policy is an allowlist.

### Error taxonomy

The SSH leg reports one of five failure types, mapped in `tools/cli.py` to response-envelope error codes:

| Type | Meaning |
|---|---|
| `unreachable` | the TCP probe never connected — wrong address, or nothing listening |
| `host_key` | unknown or mismatched host key; the session fails before credentials are sent |
| `authentication` | the device rejected the credentials |
| `rate_limited` | the device accepted the connection then reset it |
| `connection` | anything else that broke the session |

`rate_limited` is the one worth separating. A live ION resets roughly the fifth SSH session opened in quick succession, before sending its version string — and a session is opened per call, so an assistant answering a question about several sites hits it during ordinary use. Unlike every other failure here it clears on its own, so it is the only one reported as retryable; classing it as `connection` would tell the caller to stop when it should pause.

## Why 27 tools, not 19 or 316

### Not 316

316 tools would make model tool selection noisy and expose SDK vocabulary directly to AI.

### Not exactly 19 domains

Registry domains are useful for catalog organization, but they do not map cleanly to operator intent. Example: troubleshooting a VPN problem can require topology, WAN, events, and monitoring data across several registry domains.

### 27 semantic tools

The selected surface keeps high-use intents easy to discover while the expert capability tool preserves long-tail coverage.

## Mutation boundary

26 of the 27 tools are read-only. The API executor is read-only — no controller mutation endpoint is present in the source registry used here. `generate_site_config` does not touch the filesystem or call a Prisma mutation API either; it validates one site's device list against the `prisma_sdwan.sites` schema and returns the structured config plus formatted YAML text to the caller. Turning that into a real file, combining it with other sites, and applying it to the network is entirely up to whatever consumes this server — this keeps Ansible/change-control as the network mutation path, and keeps this server from holding any state of its own between calls.

`run_commands` is the exception to the *read-only claim*, not to the mutation boundary: it can send `ping`/`tcpping`/`dig` packets from the device, so it is annotated `ACTIVE_DIAGNOSTIC` rather than `READ_ONLY`. It still calls no controller write endpoint, changes no device configuration, and the server still holds no session or device state between calls — see the CLI lane above.

## Testing the CLI lane without a device

Everything in the CLI lane depends on how a real ION behaves, which is exactly what a unit test cannot invent. Captured device bytes close that gap:

- `tests/fixtures/ion/direct_*.txt` holds the device's verbatim output, captured during the live runs of 2026-08-10 against an ION 1200 running 6.3.6-b9 — the real ANSI escapes and the doubled command echo included.
- `tests/test_ion_replay.py` feeds those bytes back through the real code path (`_command_result`, `_completion_pattern`, `_normalise_prompt`) with no device attached. It runs in the ordinary suite, so a capture is a permanent regression fixture instead of a one-off observation.

The bug this pins is a race: `dump overview` returned 1627 bytes in one live run and 82 — its own command echo — in the next, from identical code, because a prompt-based read terminator can match the echo before the output arrives. Observing that once per lab round-trip was the slowest possible way to fix it; replay makes the losing case happen every time.
