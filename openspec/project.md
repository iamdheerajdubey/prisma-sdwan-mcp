# Prisma-MCP — Project Conventions

## What this project is

An **independent, standalone evidence-access platform** for Palo Alto Prisma SD-WAN,
exposed over MCP. It must drop into *any* MCP client — a troubleshooting agent,
ChatGPT, Claude, an internal automation platform, a scripted consumer, a test
harness — and break none of them.

**The platform owns:** controller access, identifier resolution, normalization,
pagination, error reporting, credential protection, read-only enforcement, tool
schemas.

**The platform does not own:** troubleshooting workflows, hypotheses, diagnosis,
root-cause selection, confidence scoring, escalation decisions, or any consumer's
report format.

Tools return facts. The consumer reasons.

## Layout

| Path | What it is |
|---|---|
| `api-mcp/prisma_sdwan_mcp/` | Controller REST evidence server (~39 read-only tools) |
| `cli-mcp/prisma_sdwan_cli_mcp/` | Read-only ION device CLI over SSH |
| `webtester/` | A real consumer of api-mcp; constrains any contract change |

The two servers are **independent deployables**. Neither imports the other.
`cli-mcp` has no controller dependency and no `prisma_sase` import; that
independence is a deployment property, not an accident.

## Stack

- Python, `FastMCP` (`registry.mcp` in api-mcp, module-level `mcp` in cli-mcp).
- `prisma_sase` SDK for controller access (api-mcp only).
- `netmiko` / `paramiko` for SSH (cli-mcp only).
- `pytest`. Tests live in `api-mcp/tests/` and `cli-mcp/tests/`.
- Config from environment (`api-mcp/prisma_sdwan_mcp/config.py`, `python-dotenv`).

## Conventions

**Tools return a JSON string**, not a dict — every api-mcp tool returns
`str`. Serialization goes through `formatting.compact_json`.

**One envelope shape.** Collections go through `formatting.build_envelope`;
single records through `formatting.single_response`. Nothing hand-rolls a payload.

**Additive-only response contract.** Adding a key to the envelope or a field to a
projection is safe. Renaming or removing one is breaking. See
`openspec/changes/response-contract-and-truncation-policy/`.

**Errors are structured**, never prose: `formatting.structured_error` /
`error_json` produce `{code, message, tool, retryable, status_code?}` from a
closed code set.

**Read-only.** api-mcp calls only SDK `get`/`post`-query endpoints. cli-mcp
enforces a deny-by-default allow-list (`cli-mcp/prisma_sdwan_cli_mcp/policy.py`)
*before* any SSH session opens.

**Tool annotations are mandatory** on every `@mcp.tool` —
`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`. They are
honest: `run_commands` declares `readOnlyHint: False` because `ping`/`tcpping`/`dig`
emit real packets (`cli-mcp/prisma_sdwan_cli_mcp/server.py:72-85`).

**Resources and Prompts are legitimate.** MCP Resources
(`api-mcp/prisma_sdwan_mcp/resources.py`) are alternate read paths to the same
tool functions. MCP Prompts (`api-mcp/prisma_sdwan_mcp/prompts.py`) are
client-invoked and opt-in — they constrain no consumer. A *tool* that returned a
diagnosis would violate the boundary; a prompt does not.

**Contract tests are the gate.** `api-mcp/tests/test_tool_contract.py` pins every
tool name and argument signature; `cli-mcp/tests/test_tool_contract.py` does the
same for cli-mcp. A change that alters a signature must change that test in the
same commit, deliberately.

## Verification discipline

Where controller API behaviour is uncertain, say so in the spec and mark it
**NEEDS LIVE VERIFICATION** before the interface is frozen. Do not invent API
shapes; a guessed field name that ships becomes a contract.
