## Context

MCPv2 exposes Prisma SD-WAN as 27 tools whose docstrings are written for a model to read. Its consumers today are MCP hosts — Claude Desktop and friends. The server holds no state, all tools are read-only or active-diagnostic, and every response passes through one envelope and one redactor.

`D:\Prisma-MCP\webtester` is a 2,587-line local portal written against the v1 package: stdlib HTTP server, plain browser ES modules, no framework, no build step. Six pages, an Administration drawer with a tool explorer, and a Live/Preview toggle. It does not run against MCPv2 (`prisma_sdwan_mcp.registry` no longer exists), and its question box is a keyword chain over a hand-written intent table — the pattern `catalog-browse-not-search` removed from the server one layer down.

Constraints this design inherits:
- The MCP server package must not gain dependencies or startup requirements for the console's sake.
- No persistent storage. The server has none by design; a console that fronts it should not quietly acquire one.
- Every result the console shows came from a tool, and the tools already report their own truncation, paging, and fan-out state.

Two decisions were made by the user before design: **bring-your-own-key** for the model, and the console lives **inside this repo** at `webui/`.

## Goals / Non-Goals

**Goals:**
- One console that browses the tool surface, answers questions with a real model, and shows what it actually did.
- Speak MCP for real, so the console is a client like any other and cannot drift onto server internals.
- Keep the parts of webtester that took real work — the design system, Preview mode, the tool explorer, `normalizer.py`.
- Make the server's own limits visible: truncation, cursors, fan-out caps, byte budgets, elapsed time.
- Put the controller's answer and the device's answer in the same view, each labeled.
- Leave the MCP server's install, startup, and dependency set untouched.

**Non-Goals:**
- Competing with the Prisma SD-WAN controller UI on dashboards. It has better ones, and building worse ones is the surest way to waste this effort.
- A hosted or multi-tenant deployment. Loopback, single operator, one session.
- Authentication, RBAC, or audit logging of its own. It is a local tool; if it ever needs those, that is a different product.
- Any write path. The console can invoke only what the 27 tools expose.
- A build step, a framework, or a package manager for the front end.
- Persisting anything — no trace history, no cached results, no stored credentials.

## Decisions

### 1. `webui/` inside this repo, with the assistant behind an optional extra

`webui/` sits beside `prisma_sdwan_mcp/`. The base install is unchanged; `pip install -e ".[webui]"` adds `anthropic[mcp]` and the MCP client library.

*Why:* one repo, one version, one test suite, and the console can never drift out of sync with the tool surface it fronts. The optional extra is what protects the server: someone installing `prisma-sdwan-mcp` to run it under Claude Desktop gets exactly what they get today.

*Why not a separate repo:* full isolation, at the cost of two things to version and a guaranteed drift between the console's assumptions and the server's actual tools. The optional extra buys the isolation that matters — dependency isolation — without the drift.

*Front end stays as webtester built it:* stdlib HTTP server, plain ES modules, no framework, no build step. It works, it has no supply chain, and nothing about this change needs more.

### 2. The console is an MCP client over stdio

`webui/app/mcp_client.py` spawns `prisma-sdwan-mcp --transport stdio` and holds one session: `list_tools` for discovery, `call_tool` for everything else.

*Why:* webtester imported the package and called `tool.fn(**args)`. That is what let it reach `registry.client`, and that is what broke when `registry` became `runtime`. Speaking the protocol makes the console a consumer with no more access than Claude Desktop has — so a capability that works in one works in the other, and a server refactor that keeps the tool surface stable cannot break the console.

*Cost:* JSON serialization on every call, and a subprocess to manage. Both are noise next to a controller round trip.

*Why stdio rather than HTTP:* the server already supports it, it needs no port and no bind decision, and its lifetime is tied to the console process. HTTP transport remains available for anyone pointing the console at a server running elsewhere; nothing in the client is stdio-specific beyond how the session is opened.

### 3. All tool calls go through one wrapper, which is also where the trace is captured

Pages and the assistant both call tools through `mcp_client.call_tool(...)`. That function writes the trace record: tool, arguments, elapsed, byte size, outcome, and the truncation/cursor/fan-out flags read out of the response envelope.

*Why here and not in the assistant:* a page call and an assistant call produce identical records because there is one code path, and there is no way to add a call site that escapes the trace. Capturing in the assistant loop would leave every page call invisible and quietly diverge.

### 4. The assistant is Claude Opus 5 driven by the SDK's tool runner over MCP-converted tools

`claude-opus-5`, adaptive thinking with `display: "summarized"`, `output_config.effort` starting at `xhigh`, streamed, `max_tokens` 64000. MCP tools are converted with the Anthropic SDK's MCP helpers and handed to `client.beta.messages.tool_runner`, which drives request → execute → loop.

*Why the tool runner rather than a hand-written loop:* it is a thin helper over the same endpoint, and its per-turn hook is exactly where the two things this design needs belong — recording the call chain, and gating an active diagnostic before it runs. Writing the loop by hand would buy nothing and cost the gate.

*Why summarized thinking:* on this model the default is omitted, which in a streaming UI reads as a long pause before anything appears. For a troubleshooting console the reasoning is part of the answer — the operator wants to see *why* it looked at the WAN path before the LAN.

*Why `xhigh` to start:* it is the documented starting point for agentic work. It is a starting point, not a setting — see Open Questions.

*Why not Managed Agents or the Claude Agent SDK:* both host things this does not need. Managed Agents would run the loop and a sandbox on Anthropic's side; the Agent SDK ships a filesystem/coding harness. The console already owns its compute and its tools; the tool runner is the piece it is missing.

### 5. Refusals are handled, with server-side fallback on by default

The loop checks `stop_reason` before reading content, and requests carry `fallbacks: "default"` under the server-side fallback beta.

*Why this is not boilerplate here:* network diagnostics is adjacent to the cyber category. A question about a device's reachability, a port scan-shaped `tcpping`, or a firewall path is plausible input for a safety classifier, and a refusal arrives as a normal 200 with an empty content array — code that reads `content[0]` breaks on it. `"default"` routes by refusal category rather than pinning a substitute model, so it survives model deprecations without a migration.

### 6. Bring-your-own-key, in memory, never through the environment

The key is POSTed from Administration, held in a module-level value in the console process, and passed explicitly to the Anthropic client constructor. `ANTHROPIC_API_KEY` is read as a fallback if already set.

*Why explicit rather than `os.environ[...] = key`:* webtester assigned credentials into `os.environ` at connect time. The console spawns the MCP server as a subprocess, and a subprocess inherits the parent environment — so writing the key there hands it to a process that has no use for it. Passing it to the constructor keeps it in one place.

*Fail closed:* no key means the question box is disabled with a message naming what to supply. Browsing, inspection, the tool explorer, and Preview all keep working. A console that half-works without a key is more useful than one that refuses to start.

*What this does not solve:* the key crosses loopback HTTP in plaintext on its way from the browser. See Risks.

### 7. Prompt caching on the stable prefix

The tool definitions and system prompt are byte-identical across questions in a session, so they carry a cache breakpoint; the question goes after it.

*Why it is worth doing here:* 27 tools with long operational docstrings is a large, entirely stable prefix, re-sent on every turn of every question — and a tool-use loop re-sends it on every iteration, not just once per question. The minimum cacheable prefix on this model is 512 tokens; the tool set clears that by a wide margin.

*What this constrains:* the tool list must be serialized deterministically and must not change mid-session, and nothing volatile — a timestamp, a session ID — may be interpolated ahead of the breakpoint.

### 8. Keep the shell, Preview, the explorer, and the normalizer; delete the guessing layer

Ported: the app shell, design tokens and CSS, navigation, modals, toasts, `demo.py`, the Administration tool explorer, `normalizer.py`.

Deleted: `catalog.py` in full, `workflows.py`'s `_build_args` and `ask()`, `mcp_gateway.py`, and webtester's standalone entrypoint wiring.

*Why the normalizer survives:* it encodes which controller fields mean "this is down", across payloads that disagree with each other. That is domain knowledge, not scaffolding, and re-deriving it would be a week of guessing.

*Why the intent layer does not:* it is the same substring-matching failure the server already removed, one floor up. Fixing it means rebuilding it, and the model replaces it outright.

*Why Preview survives:* demonstrating and styling the interface with no tenant and no risk is worth more than it costs, and it makes the whole front end testable without a controller.

## Risks / Trade-offs

**Tenant data leaves the machine** → questions and the tool results gathered to answer them go to a third-party model provider. This is inherent to the feature, not a bug in it, which is why disclosure-before-first-send is a spec requirement rather than a nicety. Operators who cannot send topology and device output offsite should not enable the assistant; the rest of the console works without it.

**The console has no authentication of its own** → anything that can reach its port can drive a live tenant through it, and read the trace. Mitigation is the bind: loopback by default, documented, with an explicit warning against binding it wider. This is a real ceiling on what the console is — a local operator tool, not a service.

**The key crosses loopback in plaintext** → the browser POSTs it over plain HTTP to `127.0.0.1`. On a single-user machine this is acceptable; on a shared or multi-user host it is not, because loopback is not private there. Documented as a prerequisite alongside the bind warning. Not solved by adding TLS to a localhost server — that trades a real problem for a certificate-management one.

**The model chooses which tools to call against a live tenant** → bounded three ways: it can invoke only the exposed set, the loop has an iteration ceiling, and an active diagnostic is surfaced before it runs rather than executed like a read. All 27 tools are non-destructive, so the worst case is wasted calls and packets, not damage.

**Beta SDK surfaces** → the tool runner, the MCP conversion helpers, and server-side fallbacks are all beta. Pin the SDK version, and treat an SDK bump as a change that needs its tests re-run rather than a routine upgrade.

**Blocking I/O in a stdlib threaded server** → one MCP session shared across request threads, and an assistant question that holds it for the length of a tool-use loop. For a single local operator this is invisible. If it ever isn't, the fix is a session per request, not a framework.

**Cost per question is the user's** → BYOK means the operator pays for `xhigh` on a large tool prefix. Prompt caching takes most of the repeated cost out; the effort sweep is what takes out the rest.

**The device lane may be inert** → the two-lane view depends on `run_commands`, whose SSH reachability from wherever the console runs is still unverified (`add-ion-cli-passthrough` task 9.1b). If the device is unreachable the lane reports that and the controller lane still works — but the flagship view is half a view until that question is answered.

**Scope creep back into dashboards** → the strongest pull on this change is to re-add the Overview/Sites/Telemetry pages verbatim because they already exist. They are the part with a better competitor. Ported pages should earn their place against the trace and device views, not ride along on being free.

## Migration Plan

Additive and self-contained. Nothing in `prisma_sdwan_mcp/` changes; the base install and every existing consumer behave exactly as today. `webui/` is inert unless the optional extra is installed and its server is started.

Rollback is deleting `webui/` and the extra.

## Open Questions

1. **What effort level does this actually need?** `xhigh` is the documented starting point for agentic work, not a measurement. Troubleshooting questions may resolve well at `medium` for a fraction of the cost and latency. Sweep once there is a question set to sweep against.
2. **Which ported pages survive?** Overview, Sites, Findings, Telemetry, and Resources were designed as a portal. Once the trace panel and the device lane exist, some of them may be redundant. Port them, then cut what the console does not need rather than deciding in the abstract.
3. **Is the device lane reachable from where the console runs?** Same open question as the CLI passthrough change, inherited. If not, the two-lane view degrades to one lane wherever it is deployed.
4. **Does the assistant need conversation memory?** The first cut answers one question at a time. Follow-ups ("and the other site?") are the obvious next ask, and they change the caching story — worth deciding deliberately rather than discovering.
