## Why

`D:\Prisma-MCP\webtester` is a 2,587-line local portal built against MCPv2's predecessor. Two facts decide what to do with it.

**It doesn't run.** Its gateway imports `prisma_sdwan_mcp.registry` — a module that existed in v1 and is `runtime` in MCPv2. Verified: `ModuleNotFoundError`. So "port it directly" was never actually on the table; something has to be rewritten either way.

**Its brain is the pattern this repo just deleted.** "Ask Network" is a keyword chain — *attention/problem/issue* → findings, *site/branch/health* → sites, *latency/loss/jitter* → telemetry, else substring search, else "I could not map that question to a supported network workflow." Behind it, `catalog.py` ranks the 27 tools with hand-written positive/negative word lists and `workflows.py` guesses tool arguments from parameter *names*. The `catalog-browse-not-search` change removed exactly this — substring-matching an operator's phrasing against tool prose fails silently, and the user cannot tell "unsupported" from "you phrased it wrong."

The deeper mismatch: MCPv2's 27 tools carry long operational docstrings written for a model to read. Webtester replaces the model with 40 lines of keyword rules. That is the ceiling on its question box, and polish does not raise it.

What webtester gets *right* is worth keeping: a coherent design system, a Preview mode that runs the whole UI off sample data with no tenant, an MCP tool explorer, and `normalizer.py`'s hard-won mapping of messy controller payloads into stable shapes.

So: keep the shell, delete the guessing layer, put a real model behind the question box, and add the two things a console can do that neither Palo Alto's UI nor a chat client can — show the actual call chain, and put the controller's answer next to the device's.

## What Changes

**New: `webui/` inside this repo**, sibling to `prisma_sdwan_mcp/`. One repo, one version, one test suite. The MCP server package itself is untouched.

- **The UI becomes a real MCP client.** Webtester imported the Python package and called `tool.fn(**args)` in-process — which is how it came to depend on `registry.client` and how it broke. The console speaks MCP over stdio to `prisma-sdwan-mcp` instead. Whatever works in the console works in Claude Desktop, and the reverse.
- **The question box runs a real tool-use loop.** Claude with the 27 tools, via the Anthropic SDK's MCP tool conversion helpers and tool runner. **BREAKING** relative to webtester: `catalog.py`'s `INTENT_RULES`, `workflows.py`'s `_build_args` parameter-name guessing, and the `ask()` keyword chain are deleted outright, not fixed.
- **Bring-your-own-key, memory only.** The user pastes an Anthropic API key in Administration; it lives in the running process and is never written to disk, never logged, never returned by any endpoint. `ANTHROPIC_API_KEY` from the environment is accepted as a fallback for local development. No key configured means the question box is disabled with a clear message — every other page still works.
- **New: call trace.** Every tool call the console makes — from a page or from the assistant — is rendered with its action, arguments, elapsed time, returned bytes, and whether the response truncated or paged. This is the thing a console can show that a chat client cannot.
- **New: two-lane device view.** Controller answer and device answer side by side, each labeled with its source, using the existing tools plus `run_commands`. Never presents a device answer as controller truth or the reverse.
- **Kept from webtester:** the app shell, design tokens and CSS, navigation, modals, toasts; Preview/demo mode; the Administration tool explorer; `normalizer.py`.
- **Dropped from webtester:** its standalone `server.py` entrypoint wiring, its in-process gateway, `catalog.py`, the intent/arg-guessing half of `workflows.py`, and the "customer-facing portal" framing — Palo Alto ships a controller UI with better dashboards, and competing on Overview/Sites/Telemetry pages is a race this loses.

**Dependencies stay optional.** The web layer keeps webtester's zero-dependency posture — Python's stdlib HTTP server and plain browser ES modules, no framework, no build step. The assistant needs `anthropic[mcp]`, added as an optional extra (`pip install -e ".[webui]"`), so the MCP server itself gains nothing.

## Capabilities

### New Capabilities
- `console-mcp-client`: How the console reaches Prisma SD-WAN — MCP protocol transport rather than in-process import, tool discovery, invocation and error surfacing, source attribution when controller and device answers appear together, and Preview mode's isolation from any live call.
- `console-assistant`: The question box — credential custody and fail-closed behavior, the model's tool-use loop, what it may and may not do on the user's behalf, refusal and failure handling, and secret hygiene across the transcript.
- `console-call-trace`: What the console makes observable about its own work — per-call action, arguments, timing, byte size, truncation and pagination state, and the assistant's full call chain.

### Modified Capabilities
<!-- None. `openspec/specs/` holds no baseline specs. -->

## Impact

**Code (new)**
- `webui/server.py` — stdlib HTTP server, static files, JSON API, no framework.
- `webui/app/mcp_client.py` — MCP stdio client session against `prisma-sdwan-mcp`; replaces `mcp_gateway.py`.
- `webui/app/assistant.py` — Claude tool-use loop over the MCP tool set; replaces `catalog.py` and the intent half of `workflows.py`.
- `webui/app/trace.py` — per-call record capture feeding the trace panel.
- `webui/app/normalizer.py`, `webui/app/demo.py` — ported from webtester.
- `webui/static/**` — shell, tokens, CSS, pages ported; `pages/ask.js` rewritten; `pages/trace.js` and the device lane new.
- `tests/test_webui_*.py` — assistant loop with a stubbed model, credential handling, trace records, MCP client error mapping.

**Code (modified)**
- `pyproject.toml` — optional `webui` extra; the base install is unchanged.

**Not affected**
- Every one of the 27 tools, the registry, the catalog, the resolver, the executors, the CLI lane. The console is a consumer; it changes nothing it consumes.
- The MCP server's dependency set, startup path, and transports.
- The mutation boundary. The console can call only what the tools expose, and all 27 are read-only or active-diagnostic.

**Security surface (new, and the reason several requirements below exist)**
- An Anthropic API key held in a local process.
- A model that decides which tools to call against a live tenant.
- Tenant data and device CLI output flowing into a third-party model.
- A local HTTP server, bound to loopback by default, with no authentication of its own.

**Docs**
- `README.md`, `docs/ARCHITECTURE.md` — the console as a second consumer alongside Claude Desktop.
- `webui/README.md` — running it, the key model, and the loopback-binding warning.
