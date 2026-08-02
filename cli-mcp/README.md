# Prisma SD-WAN ION CLI MCP

This sibling MCP server exposes one generic tool for read-only Palo Alto Prisma
SD-WAN ION CLI commands. It uses Netmiko over SSH and opens a fresh session for
each call. It does not use Ansible, local inventory, a vault, connection
pooling, or per-command typed tools.

Research sources and the verification limits for the ION CLI are recorded in
[RESEARCH.md](RESEARCH.md).

## Run the server

Install the runtime dependencies, then start the stdio server:

```powershell
python -m pip install -r requirements.txt
python prisma_sdwan_cli_mcp_server.py
```

The HTTP transports supported by the entrypoint are `stdio`, `sse`, and
`streamable-http`; use `--transport`, `--host`, and `--port` when needed.

## Tool contract

The only registered MCP tool is `run_commands`:

```json
{
	"host": "ion.example",
	"port": 22,
	"username": "readonly-user",
	"password": "supplied-for-this-call",
	"commands": [
		"dump interface status all",
		"inspect wanpaths all"
	]
}
```

Use exactly one of `password` or `private_key`. `private_key` is inline key
material supplied for the current call; the server does not read a key file.
An optional `private_key_passphrase` applies only to inline key material.
Credentials are passed to Netmiko for the session and never appear in a
response or a log message.

SSH host-key checking is strict (`ssh_strict=True`, `system_host_keys=True`):
the device's host key must already be present in the known_hosts file
(system default `~/.ssh/known_hosts`, or an alternate file passed via the
optional `known_hosts_file` argument) before the call is allowed to proceed.
An unknown or mismatched host key fails the call with `error.type ==
"host_key"` and no credentials are sent. Populate the known_hosts entry out
of band first (one interactive `ssh` login, or `ssh-keyscan`) — this MCP
intentionally does not auto-trust an unverified host key, since doing so
would let anyone on-path between this server and the device harvest
credentials by impersonating it.

Successful execution returns one independent result for every submitted
command. A device-side command error does not merge with another command.
Error detection only inspects the first line of a command's output (an ION
rejection is the immediate response to a bad command); a legitimate
multi-line dump/inspect result that merely contains a word like "Failed" on
an interior line is not reclassified as an error:

```json
{
	"status": "ok",
	"results": [
		{
			"command": "dump interface status all",
			"status": "ok",
			"output": "..."
		},
		{
			"command": "inspect wanpaths all",
			"status": "error",
			"error": "Invalid command ..."
		}
	]
}
```

Connection, authentication, and host-key failures are batch-level errors
(`error.type` is `"connection"`, `"authentication"`, or `"host_key"`) and
contain no executed command entries:

```json
{
	"status": "error",
	"error": {
		"type": "authentication",
		"message": "..."
	},
	"results": []
}
```

## Resource and prompt

Alongside the `run_commands` tool, the server exposes:

- **Resource** `prisma-cli://policy` — the enforced allow-list (allowed/denied
  command families, the output-filter grammar) as browsable JSON, generated
  from the same [policy.py](prisma_sdwan_cli_mcp/policy.py) constants the
  server actually enforces, so it can't drift from reality.
- **Prompt** `troubleshoot_ion(symptom_hint)` — a canned starting checklist
  (check the policy, confirm the host key is already trusted, call
  `run_commands`, read each result independently) rather than a tool call
  itself.

## Read-only enforcement

The policy gate runs before the Netmiko connection is opened. It validates the
whole command list and rejects the entire batch if any command is denied. A
denied batch contains one structured `denied` result per submitted command,
including the individual reason, and the backend is not invoked.

The allow policy is a positive, fail-closed whitelist in
[policy.py](prisma_sdwan_cli_mcp/policy.py), enforced at the **family** level
rather than as a per-subcommand list. Palo Alto's ION CLI reference already
classifies commands by family, not individually, so the policy trusts that
same boundary instead of duplicating it as an ever-growing list of exact
forms:

| ION command family | Policy | Evidence |
| --- | --- | --- |
| `dump` | Allowed for any subcommand/arguments matching the safe-argument character class, plus an optional single grep filter. | Palo Alto describes dump as displaying interface, device, and routing information, available to all user roles. |
| `inspect` | Allowed for any subcommand/arguments matching the safe-argument character class, plus an optional single grep filter. | Palo Alto describes inspect as displaying information, available to Read Only roles. |
| `clear` | Denied | Clears status. |
| `config` | Denied | Configures interfaces, devices, and routing. |
| `debug` | Denied | Includes disruptive operations such as reboot and shutdown. |
| `show`, `display`, `get`, and unknown roots | Denied | Not documented as ION command families in the current reference. |

A bare `dump` or `inspect` with no arguments is denied — at least one
trailing token is required, matching how every documented form is used.

The official ION reference documents one output-filter form, `COMMAND | grep
PATTERN`, with `grep` options `-i`, `-v`, `-w`, and `-F`. The policy allows at
most one such filter after a whitelisted command. The safe-argument character
class excludes newlines, semicolons, ampersands, backticks, dollar expansion,
redirection, and additional pipes — this is what actually prevents a
`dump`/`inspect` prefix from being turned into a command chain, independent
of which specific subcommand follows.

New `dump`/`inspect` subcommands the vendor documents in future ION releases
need no code change here — they're covered automatically by the family
match. Only touch `policy.py` if the family-level trust boundary itself needs
to change (e.g. a documented family is reclassified), and update
[RESEARCH.md](RESEARCH.md) plus `tests/test_policy.py` alongside it.

The current reference does not document ION pagination markers or terminal
length settings, and no lab device was available for this implementation. The
executor therefore handles common `--More--` and `(q)uit` prompts defensively
with bounded timing reads. Treat that behavior as an explicit verification gap
until a lab capture confirms the device prompt.

The official SSH documentation verifies username/password login. Inline key
material is also accepted because the caller contract allows password/key
credentials, but public-key acceptance must be confirmed for the target ION
deployment.

## Command selection ownership

This MCP does not decide which troubleshooting command is appropriate. The
calling agent's skill files are the authority for command selection and
ordering. Wire those skills in the agent or MCP host configuration that invokes
this server; do not add command-selection logic or per-command tools here.
