# Configuration

`.env.example` holds five settings because five is all the server reads.
Everything below already has a working default in `config.py` and only needs
setting if you have a specific reason.

Real environment variables always beat `.env`, so container secrets are never
overwritten by a checked-out file. `PRISMA_ENV_FILE` points the loader at a
different file when one host serves several configurations.

## Required

| Variable | What it is |
|---|---|
| `PAN_CLIENT_ID`, `PAN_CLIENT_SECRET`, `PAN_TSG_ID` | Prisma SASE API credentials. Everything except `run_commands` needs these. |
| `ION_USERNAME`, `ION_PASSWORD` | Device SSH login for `run_commands`. Blank disables device access: the tool fails closed before any network activity. |

`ION_PRIVATE_KEY` (inline PEM) and `ION_PRIVATE_KEY_PASSPHRASE` replace
`ION_PASSWORD`. Set a password **or** a key, never both.

Credentials are never accepted as tool arguments — an argument is visible to
the model and lands in the conversation transcript, which is usually logged.

## Defaults you can override

### Device SSH

| Variable | Default | Change it when |
|---|---|---|
| `ION_SSH_PORT` | `22` | the device listens elsewhere |
| `ION_PROBE_TIMEOUT` | `3` s | the reachability pre-check is too tight on a slow link |
| `ION_CONNECT_TIMEOUT` | `10` s | the SSH handshake needs longer |
| `ION_READ_TIMEOUT` | `300` s | a command legitimately runs longer than five minutes. This is a hang ceiling, not a pacing knob — completion is decided by the prompt returning. |
| `ION_MAX_OUTPUT_BYTES` | `40960` | a command's output must survive whole. Per command, so one large answer cannot starve the rest of its batch. |
| `ION_MAX_COMMANDS` | `10` | batches need to be longer |
| `ION_KNOWN_HOSTS` | `~/.ssh/known_hosts` | **usually.** There is no first-use trust, and a container or fresh server has no such file, so every connection fails until this points at a provisioned one. |

The longer `PRISMA_ION_*` spellings of all of these still work.

### Response guardrails

| Variable | Default | What it does |
|---|---|---|
| `MCP_MAX_RESPONSE_BYTES` | `40960` | Ceiling on one tool response, so a broad question cannot flood the model's context. |
| `MCP_DEFAULT_PAGE_SIZE` | `50` | Records per page when the caller does not say. |
| `MCP_MAX_PAGE_SIZE` | `200` | Largest page a caller may ask for. |
| `MCP_MAX_FANOUT` | `100` | Cap on how many sub-calls one semantic tool may make. |

### Registry access

| Variable | Default | What it does |
|---|---|---|
| `MCP_EXPERT_TOOL_ENABLED` | `true` | Keeps `read_capability` reachable, which is the escape hatch to all 316 registry actions. |
| `MCP_ALLOW_UNVERIFIED_COMPAT` | `false` | Allows curated actions still marked `requires_live_test` through the generic expert tool. Semantic tools expose them regardless. |
| `PAN_CONTROLLER` | `https://api.sase.paloaltonetworks.com` | Alternate controller endpoint. |

## Removed

`ION_IP` and `ION_ELEMENT` were read only by a diagnostic script that no longer
exists, and are gone from `.env.example`. Nothing reads them. A configuration
value that no code consults is worse than no value: it reads as a knob, and the
first person to set it will wonder why nothing happens.
